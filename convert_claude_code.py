#!/usr/bin/env python3
"""Claude Code（このCLI）のセッション記録を Obsidian用Markdownに変換する。
対象: AI_EXPORT_CLAUDE_PROJECTS で指定したディレクトリの **/*.jsonl。
      未指定時は ~/.claude/projects。
手動エクスポート不要・ローカル完結。

使い方:
    python3 convert_claude_code.py          # 全セッションを変換（既存はスキップ）
    python3 convert_claude_code.py --dry     # 変換せず件数だけ表示
"""
import os, re, sys, glob, json
from datetime import datetime, timezone, timedelta
from common import out_path, already_exists, existing_note_paths, write_note, fold

# 入力範囲を利用者が指定する。複数指定はOSのパス区切りを使う。
PROJECT_ROOTS = [
    os.path.expanduser(p) for p in os.environ.get(
        "AI_EXPORT_CLAUDE_PROJECTS", "~/.claude/projects"
    ).split(os.pathsep) if p
]
JST = timezone(timedelta(hours=9))

# /model 等のローカルコマンド実行やシステム注入のタグ。タイトル・本文から除去する。
_CMD_TAG_RE = re.compile(
    r"<(local-command-caveat|local-command-stdout|local-command-stderr|"
    r"command-name|command-message|command-args|command-contents|system-reminder)>"
    r".*?</\1>",
    re.S,
)

def clean_user_text(s):
    """ユーザー発話からコマンド実行・システム注入タグを取り除く。"""
    return _CMD_TAG_RE.sub("", s or "").strip()

_NOTE_PATHS = None
def note_paths():
    """既存ノートの sid→パス対応（1回だけ走査してキャッシュ）。"""
    global _NOTE_PATHS
    if _NOTE_PATHS is None:
        _NOTE_PATHS = existing_note_paths()
    return _NOTE_PATHS

def note_msg_count(path):
    """既存ノートのフロントマター messages: を読む。無ければ -1。"""
    try:
        with open(path, encoding="utf-8") as f:
            head = f.read(2000)
        m = re.search(r"^messages: *(\d+)", head, re.M)
        return int(m.group(1)) if m else -1
    except Exception:
        return -1

def parse_ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(JST)
    except Exception:
        return None

def render_content(content, is_user=False):
    """message.content（str か block list）をMarkdownにする。思考/ツールは折りたたむ。"""
    if isinstance(content, str):
        return (clean_user_text(content) if is_user else content.strip()), []
    if not isinstance(content, list):
        return "", []
    texts, folds = [], []
    for b in content:
        if not isinstance(b, dict):
            continue
        t = b.get("type")
        if t == "text":
            txt = b.get("text", "").strip()
            if is_user:
                txt = clean_user_text(txt)
            if txt:
                texts.append(txt)
        elif t == "thinking":
            th = b.get("thinking", "").strip()
            if th:
                folds.append(fold("🧠 思考 (thinking)", th))
        elif t == "tool_use":
            name = b.get("name", "tool")
            inp = json.dumps(b.get("input", {}), ensure_ascii=False, indent=2)
            folds.append(fold(f"🛠️ ツール呼び出し: {name}", f"```json\n{inp}\n```"))
        elif t == "tool_result":
            c = b.get("content", "")
            if isinstance(c, list):
                c = "\n".join(x.get("text", "") for x in c if isinstance(x, dict))
            folds.append(fold("📤 ツール結果 (tool_result)", f"```\n{str(c)[:4000]}\n```"))
    return "\n\n".join(t for t in texts if t), folds

def convert_one(path, dry=False):
    rows = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    sid = None
    title = None
    msgs = []
    timestamps = []
    for o in rows:
        sid = sid or o.get("sessionId")
        if o.get("type") == "ai-title" and o.get("aiTitle"):
            title = o["aiTitle"]
        if o.get("type") in ("user", "assistant"):
            msg = o.get("message", {})
            if not isinstance(msg, dict):
                continue
            ts = parse_ts(o.get("timestamp", ""))
            if ts:
                timestamps.append(ts)
            msgs.append((o["type"], msg.get("content")))
    # 実質的な会話が無いものはスキップ
    real = [m for m in msgs if m[0] in ("user", "assistant")]
    if not real or not timestamps:
        return None
    sid = sid or os.path.splitext(os.path.basename(path))[0]
    # 既存ノートがあっても、会話が伸びている／caveatタイトルのままなら更新する
    update_target = None
    if already_exists(sid):
        old = note_paths().get(sid) or note_paths().get(sid[:8])
        old_base = os.path.basename(old) if old else ""
        # この変換器が生成したノート（[cc]_入り）のみ更新対象。旧形式エクスポートは触らない
        if old and "[cc]_" in old_base and (
            len(real) > note_msg_count(old) or "local-command-caveat" in old_base
        ):
            update_target = old
        else:
            return "skip"
    dt = min(timestamps)
    if not title:
        # 最初の実質的なユーザー発話をタイトルに（コマンド実行・システム注入は除外）
        for typ, c in msgs:
            if typ == "user":
                s = c if isinstance(c, str) else ""
                if not s and isinstance(c, list):
                    s = " ".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
                s = clean_user_text(s)
                if s:
                    title = s[:40]
                    break
        title = title or "(無題)"
    proj_raw = os.path.basename(os.path.dirname(path))
    project = proj_raw.replace("-Users-hara-", "").replace("-", "/").strip("/") or "ホーム"
    # 本文
    blocks = []
    for typ, content in msgs:
        text, folds = render_content(content, is_user=(typ == "user"))
        if not text and not folds:
            continue
        head = "## 🧑 あなた" if typ == "user" else "## 🤖 Claude Code"
        blocks.append(head + "\n\n" + text + ("\n\n" + "\n".join(folds) if folds else ""))
    body = "\n\n---\n\n".join(blocks)
    fields = [
        ("created", dt.strftime("%Y-%m-%d")),
        ("source", f"Claude Code（{project}）"),
        ("messages", len(real)),
        ("id", sid),
    ]
    p = out_path(dt, "cc", title, sid)
    if not dry:
        write_note(p, title, fields, body)
        # タイトル改善などでファイル名が変わった場合、旧ノートを削除（実質リネーム）
        if update_target and os.path.abspath(update_target) != os.path.abspath(p):
            try:
                os.remove(update_target)
            except OSError:
                pass
    return "update" if update_target else p

def quick_scan(path):
    """jsonl を軽く走査して (sessionId, user/assistantメッセージ数) を返す。"""
    sid = None
    n = 0
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        sid = sid or o.get("sessionId")
        if o.get("type") in ("user", "assistant"):
            n += 1
    return (sid or os.path.basename(path)), n

def best_files():
    """同一sessionIdが複数jsonlに分かれている場合、最もメッセージ数が多いものだけ採用。"""
    best = {}
    for root in PROJECT_ROOTS:
        for f in glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True):
            sid, n = quick_scan(f)
            if sid not in best or n > best[sid][1]:
                best[sid] = (f, n)
    return sorted(v[0] for v in best.values())

def main():
    dry = "--dry" in sys.argv
    files = best_files()
    made = updated = skipped = empty = 0
    for f in files:
        r = convert_one(f, dry=dry)
        if r == "skip":
            skipped += 1
        elif r == "update":
            updated += 1
        elif r:
            made += 1
        else:
            empty += 1
    label = "変換予定" if dry else "新規変換"
    print(f"対象jsonl: {len(files)} / {label}: {made} / 更新: {updated} / 既存スキップ: {skipped} / 空・対象外: {empty}")

if __name__ == "__main__":
    main()
