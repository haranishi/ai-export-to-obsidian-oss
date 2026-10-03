#!/usr/bin/env python3
"""Codexのローカルセッションを、1セッションにつき1つのMarkdownへ同期する。"""
import argparse
import fcntl
import glob
import json
import os
import re
import sys
import traceback
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from common import (
    OUTPUT_BASE,
    note_text,
    postprocess_note,
    preserve_manual_fields,
    safe_filename,
)

CODEX_INPUT_ROOT = os.path.expanduser(os.environ.get("AI_EXPORT_CODEX_ROOT", "~/.codex"))
SESSIONS = os.path.join(CODEX_INPUT_ROOT, "sessions")
SESSION_INDEX = os.path.join(CODEX_INPUT_ROOT, "session_index.jsonl")
LOCK_PATH = os.path.join(os.path.dirname(__file__), ".codex-export.lock")
ERROR_LOG = os.path.join(os.path.dirname(__file__), "codex_autosave.log")
JST = timezone(timedelta(hours=9))


def parse_ts(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(JST)
    except Exception:
        return None


def load_titles():
    titles = {}
    if not os.path.isfile(SESSION_INDEX):
        return titles
    with open(SESSION_INDEX, encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except Exception:
                continue
            sid = row.get("id")
            title = row.get("thread_name")
            if sid and title:
                titles[sid] = title
    return titles


def codex_note_paths():
    """CodexノートのセッションID→パスを、本文を開かずに構築する。

    Stopフックは30秒以内に完了する必要がある。iCloud上の全ノート本文を読むと
    未ダウンロードファイルの取得待ちになるため、ファイル名末尾のIDだけを使う。
    旧形式の8文字と、衝突を防ぐ新形式の完全IDの両方を扱う。
    """
    paths = {}
    if not os.path.isdir(OUTPUT_BASE):
        return paths
    for root, _dirs, files in os.walk(OUTPUT_BASE):
        for filename in files:
            match = re.search(r"__([0-9A-Za-z-]{8,36})\.md$", filename)
            if not match:
                continue
            suffix_id = match.group(1)
            path = os.path.join(root, filename)
            if len(suffix_id) == 36:
                paths.setdefault(suffix_id, path)
            else:
                # iCloud/APFSが長い日本語名を短縮した旧ノートも、本文IDで照合する。
                paths.setdefault(suffix_id[:8], []).append(path)
    return paths


def note_session_id(path):
    """旧8文字ファイル名の候補が同じ会話か、先頭メタだけで確認する。"""
    try:
        with open(path, encoding="utf-8") as f:
            head = f.read(1500)
    except Exception:
        return None
    match = re.search(r"^id: *`?([0-9A-Za-z-]+)`?\s*$", head, re.M)
    return match.group(1) if match else None


def unique_out_path(created, title, sid):
    """ファイル名上限内で、完全IDが必ず残る出力先を返す。"""
    directory = os.path.join(OUTPUT_BASE, created.strftime("%Y"))
    os.makedirs(directory, exist_ok=True)
    prefix = f"{created.strftime('%Y-%m-%d_%H%M')}_[codex]_"
    suffix = f"__{sid}.md"
    title = safe_filename(title, maxlen=60)
    # macOS/iCloudは日本語をNFDに正規化するため、文字数ではなく正規化後の
    # UTF-8バイト数で余裕を持って240バイト以内に収める。
    while title and len(unicodedata.normalize("NFD", prefix + title + suffix).encode()) > 240:
        title = title[:-1].rstrip()
    return os.path.join(directory, prefix + (title or "(無題)") + suffix)


def title_from_prompt(text):
    marker = "## My request for Codex:"
    if marker in text:
        text = text.split(marker, 1)[1]
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        if line.startswith(("# Context from", "## Active file:", "## Open tabs:")):
            continue
        return safe_filename(line.lstrip("#>❯ ").strip(), maxlen=60)
    return "(無題)"


def project_label(cwd):
    if not cwd:
        return "不明"
    home = os.path.expanduser("~")
    if cwd == home:
        return "~"
    try:
        if os.path.commonpath([home, cwd]) == home:
            return os.path.relpath(cwd, home)
    except ValueError:
        pass
    return cwd


def parse_session(path, titles):
    meta = {}
    messages = []
    session_ts = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except Exception:
                # 稼働中セッションの末尾が書き込み途中でも、完成済みの行は保存する。
                continue
            ts = parse_ts(row.get("timestamp", ""))
            if row.get("type") == "session_meta":
                meta = row.get("payload") or {}
                session_ts = ts or session_ts
                continue
            if row.get("type") != "event_msg":
                continue
            payload = row.get("payload") or {}
            event_type = payload.get("type")
            if event_type not in ("user_message", "agent_message"):
                continue
            text = payload.get("message")
            if not isinstance(text, str) or not text.strip():
                continue
            messages.append(
                {
                    "role": "user" if event_type == "user_message" else "assistant",
                    "phase": payload.get("phase"),
                    "text": text.strip(),
                    "timestamp": ts,
                }
            )

    if not messages:
        return None
    filename = os.path.basename(path)
    match = re.search(
        r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
        filename,
        re.I,
    )
    sid = meta.get("id") or (match.group(1) if match else filename.removesuffix(".jsonl"))
    timestamps = [m["timestamp"] for m in messages if m["timestamp"]]
    created = min(timestamps) if timestamps else session_ts or datetime.now(JST)
    updated = max(timestamps) if timestamps else created
    first_user = next((m["text"] for m in messages if m["role"] == "user"), "")
    title = titles.get(sid) or title_from_prompt(first_user)
    return {
        "id": sid,
        "title": title,
        "cwd": meta.get("cwd"),
        "created": created,
        "updated": updated,
        "messages": messages,
    }


def render_body(messages):
    blocks = []
    for message in messages:
        if message["role"] == "user":
            heading = "## 🧑 あなた"
        elif message.get("phase") == "commentary":
            heading = "## 🤖 Codex（進捗）"
        else:
            heading = "## 🤖 Codex"
        text = message["text"].replace("\r\n", "\n").replace("\r", "\n")
        blocks.append(f"{heading}\n\n{text}")
    return "\n\n---\n\n".join(blocks)


def convert_one(path, titles, note_paths, dry=False):
    session = parse_session(path, titles)
    if not session:
        return "empty", None

    sid = session["id"]
    fields = [
        ("created", session["created"].strftime("%Y-%m-%d")),
        ("updated", session["updated"].strftime("%Y-%m-%d %H:%M")),
        ("source", f"Codex（{project_label(session['cwd'])}）"),
        ("save_unit", "session"),
        ("messages", len(session["messages"])),
        ("id", sid),
    ]
    # セッションIDを固定キーにし、同じセッションの各ターンは同じノートへ上書きする。
    existing = note_paths.get(sid)
    if not existing:
        for legacy_candidate in note_paths.get(sid[:8], []):
            if note_session_id(legacy_candidate) == sid:
                existing = legacy_candidate
                break
    path_out = existing or unique_out_path(session["created"], session["title"], sid)
    # tag_topics.py や手動操作で付けた分類を、ターン更新時にも保持する。
    fields = preserve_manual_fields(path_out, fields)
    body = render_body(session["messages"])
    content = note_text(session["title"], fields, body)

    old = None
    if existing and os.path.isfile(existing):
        with open(existing, encoding="utf-8") as f:
            old = f.read()
    # 派生処理が末尾改行だけを正規化する場合は、同一内容として扱う。
    if old == content or (old is not None and old.rstrip("\n") == content.rstrip("\n")):
        return "unchanged", path_out
    if not dry:
        os.makedirs(os.path.dirname(path_out), exist_ok=True)
        tmp = f"{path_out}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path_out)
        postprocess_note(path_out)
        note_paths[sid] = path_out
        note_paths.setdefault(sid[:8], []).append(path_out)
    return ("updated" if existing else "new"), path_out


def all_session_files():
    return sorted(glob.glob(os.path.join(SESSIONS, "**", "*.jsonl"), recursive=True))


def latest_session_file():
    """最後に更新されたCodexセッションを返す（常駐監視の軽量実行用）。"""
    paths = all_session_files()
    return max(paths, key=os.path.getmtime) if paths else None


def find_session(session_id):
    if not session_id:
        return None
    matches = glob.glob(
        os.path.join(SESSIONS, "**", f"*{session_id}*.jsonl"), recursive=True
    )
    return matches[-1] if matches else None


def valid_transcript_path(path):
    if not path or not os.path.isfile(path):
        return None
    real_sessions = os.path.realpath(SESSIONS) + os.sep
    real_path = os.path.realpath(path)
    return real_path if real_path.startswith(real_sessions) else None


@contextmanager
def export_lock():
    with open(LOCK_PATH, "w", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def best_files(paths, titles):
    """渡されたファイルが属する会話ごとに、最も発話数の多いファイルだけを返す。

    Codexのサブエージェントは親と同じ ``session_meta.id`` を持つため、素直に
    全ファイルを変換すると、数発話しかないサブエージェント記録が親の会話ノートを
    上書きして本文が消える（2026-07-29に7件の実被害を確認）。
    convert_claude_code.py の best_files と同じ「発話数が最大のものを採用」方針。
    """
    sid_of = {}
    best = {}
    for path in all_session_files():
        session = parse_session(path, titles)
        if not session:
            continue
        sid = session["id"]
        sid_of[os.path.realpath(path)] = sid
        count = len(session["messages"])
        if sid not in best or count > best[sid][1]:
            best[sid] = (path, count)
    selected = []
    seen = set()
    for path in paths:
        sid = sid_of.get(os.path.realpath(path))
        if sid is None:
            selected.append(path)  # sessions配下以外を明示指定された場合はそのまま
            continue
        if sid in seen:
            continue
        seen.add(sid)
        selected.append(best[sid][0])
    return selected


def run(paths, dry=False, quiet=False, resolve_duplicates=True):
    titles = load_titles()
    if resolve_duplicates:
        paths = best_files(paths, titles)
    note_paths = codex_note_paths()
    counts = {"new": 0, "updated": 0, "unchanged": 0, "empty": 0, "error": 0}
    for path in paths:
        try:
            status, _ = convert_one(path, titles, note_paths, dry=dry)
            counts[status] += 1
        except Exception:
            counts["error"] += 1
            if not quiet:
                traceback.print_exc()
    if not quiet:
        label = "変換予定" if dry else "同期"
        print(
            f"対象jsonl: {len(paths)} / {label}: 新規 {counts['new']}・更新 {counts['updated']}"
            f" / 変更なし {counts['unchanged']} / 空 {counts['empty']} / エラー {counts['error']}"
        )
    return counts


def log_hook_error():
    with open(ERROR_LOG, "a", encoding="utf-8") as f:
        f.write(f"===== {datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')} hook error =====\n")
        traceback.print_exc(file=f)
        f.write("\n")


def run_hook():
    try:
        payload = json.load(sys.stdin)
        path = valid_transcript_path(payload.get("transcript_path"))
        path = path or find_session(payload.get("session_id"))
        if path:
            with export_lock():
                # Stop が渡した親スレッドの transcript_path は変換対象そのもの。
                # 全履歴を再走査しないことで、ターン終了時の即時保存を軽く保つ。
                run([path], quiet=True, resolve_duplicates=False)
    except Exception:
        log_hook_error()
    # Stopフックは終了コード0の場合、stdoutにJSONを要求する。
    sys.stdout.write("{}\n")
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--hook", action="store_true")
    parser.add_argument("--latest", action="store_true")
    parser.add_argument("--session")
    args = parser.parse_args()

    if args.hook:
        return run_hook()
    if args.session:
        paths = [args.session]
    elif args.latest:
        latest = latest_session_file()
        paths = [latest] if latest else []
    else:
        paths = all_session_files()
    with export_lock():
        counts = run(paths, dry=args.dry, quiet=args.quiet)
    return 1 if counts["error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
