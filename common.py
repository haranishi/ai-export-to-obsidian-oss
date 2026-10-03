"""共通ユーティリティ：AI会話をObsidian用Markdownに変換する際の共通処理。"""
import os, re, json, functools, traceback

# ===== 設定 =====
VAULT = os.path.expanduser(os.environ.get("AI_EXPORT_VAULT", ""))
if not VAULT or not os.path.isabs(VAULT):
    raise ValueError("AI_EXPORT_VAULT must be an explicit absolute output directory")
# 出力先は必ず利用者が指定する。私用Vaultや同期先を既定値にしない。
OUTPUT_BASE = os.path.join(VAULT, os.environ.get("AI_EXPORT_FOLDER", "ai-exports"))
# ================

def safe_filename(s, maxlen=60):
    """ファイル名に使えない文字を除去し、長すぎる場合は切り詰める。"""
    s = (s or "").strip() or "(無題)"
    s = re.sub(r'[/\\:*?"<>|\n\r\t]', " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:maxlen].strip()

def out_path(dt, source_tag, title, sid):
    """出力フォルダ/<年>/<日付>_<時刻>_[source]_<タイトル>__<sid8>.md を返す。"""
    year = dt.strftime("%Y")
    d = os.path.join(OUTPUT_BASE, year)
    os.makedirs(d, exist_ok=True)
    name = f"{dt.strftime('%Y-%m-%d_%H%M')}_[{source_tag}]_{safe_filename(title)}__{sid[:8]}.md"
    return os.path.join(d, name)

# メタ行に埋め込まれた会話/セッションIDを拾う（旧形式 "- ID: `uuid`" も含む）
# フロントマターの `id:` と、旧形式の本文メタ `- ID:` / `- 会話ID:` / `- セッションID:` の両対応
_ID_RE = re.compile(
    r"^id: *`?([0-9A-Za-z][0-9A-Za-z\-]{6,})`?\s*$"
    r"|^- (?:ID|会話ID|セッションID): `([0-9A-Za-z][0-9A-Za-z\-]{6,})`",
    re.M,
)

@functools.lru_cache(maxsize=1)
def known_ids():
    """出力先の既存ノートを走査し、埋め込まれた会話IDの集合（フルと先頭8文字）を返す。
    これにより、ファイル名形式が違っても（旧エクスポートの456件など）会話IDで重複判定できる。"""
    ids = set()
    if not os.path.isdir(OUTPUT_BASE):
        return ids
    for root, _dirs, files in os.walk(OUTPUT_BASE):
        for fn in files:
            if not fn.endswith(".md"):
                continue
            try:
                with open(os.path.join(root, fn), encoding="utf-8") as f:
                    head = f.read(2000)  # IDは先頭メタ部にあるので頭だけ読む
            except Exception:
                continue
            for g1, g2 in _ID_RE.findall(head):
                m = g1 or g2
                if m:
                    ids.add(m)
                    ids.add(m[:8])
            # 新形式ファイル名末尾の __ID8 も拾う
            if "__" in fn:
                ids.add(fn.rsplit("__", 1)[1][:8])
    return ids

def already_exists(sid):
    """sid（会話/セッションID）が既存ノートに存在するか（形式不問・冪等性のため）。"""
    if not sid:
        return False
    ids = known_ids()
    return sid in ids or sid[:8] in ids

def existing_note_paths():
    """既存ノートの会話ID（フル/先頭8文字）からファイルパスへの対応を返す。"""
    paths = {}
    if not os.path.isdir(OUTPUT_BASE):
        return paths
    for root, _dirs, files in os.walk(OUTPUT_BASE):
        for fn in files:
            if not fn.endswith(".md"):
                continue
            path = os.path.join(root, fn)
            ids = set()
            try:
                with open(path, encoding="utf-8") as f:
                    head = f.read(2000)
            except Exception:
                continue
            for g1, g2 in _ID_RE.findall(head):
                sid = g1 or g2
                if sid:
                    ids.add(sid)
                    ids.add(sid[:8])
            if "__" in fn:
                ids.add(fn.rsplit("__", 1)[1][:8])
            for sid in ids:
                paths.setdefault(sid, path)
    return paths

def note_text(title, fields, body):
    """ObsidianノートのMarkdown文字列を組み立てる。"""
    parts = ["---", "tags:", "  - diary"]
    for k, v in fields:
        if v is None or v == "":
            continue
        parts.append(f"{k}: {v}")
    parts += ["---", "", f"# {title}", "", body.rstrip(), ""]
    return "\n".join(parts)

def preserve_manual_fields(path, fields):
    """既存ノートの topic:/status:（tag_topics.py や手動で付与した値）を保持して
    fields にマージする。会話が伸びて再変換されても分類が消えないようにするため。
    source 行の直後に差し込む（無ければ末尾）。既に fields に同キーがあれば触らない。"""
    keep = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                head = f.read(1500)
        except Exception:
            head = ""
        m = re.match(r"---\n(.*?)\n---", head, re.S)
        if m:
            for ln in m.group(1).split("\n"):
                for k in ("topic", "status"):
                    if ln.startswith(k + ":"):
                        keep[k] = ln.split(":", 1)[1].strip()
    if not keep:
        return fields
    have = {k for k, _ in fields}
    to_add = [(k, keep[k]) for k in ("topic", "status") if k in keep and k not in have]
    if not to_add:
        return fields
    out, inserted = [], False
    for k, v in fields:
        out.append((k, v))
        if k == "source" and not inserted:
            out.extend(to_add)
            inserted = True
    if not inserted:
        out.extend(to_add)
    return out


def postprocess_note(path):
    """拡張用フック。OSS版には私用の分類・ハンドオフ処理を含めない。"""
    return None

def write_note(path, title, fields, body):
    """テンプレ準拠（フロントマター付き #diary）のMarkdownを書き出す。
    fields: フロントマターに入れる順序付き (key, value) のリスト（created/source/messages/id など）。
    既存ノートに topic:/status: があれば保持する（再変換で分類が消えないように）。"""
    fields = preserve_manual_fields(path, fields)
    with open(path, "w", encoding="utf-8") as f:
        f.write(note_text(title, fields, body))
    postprocess_note(path)

def fold(summary, content):
    """<details> で折りたたむ（思考・ツール呼び出し等の全文保持用）。"""
    return f"<details>\n<summary>{summary}</summary>\n\n{content}\n\n</details>\n"
