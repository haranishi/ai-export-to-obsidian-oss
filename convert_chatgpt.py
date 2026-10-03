#!/usr/bin/env python3
"""ChatGPT の全データエクスポートを Obsidian用Markdown に変換する。

事前準備（手動・半自動の「定期エクスポート」部分）:
  1. ChatGPT → 設定 → データコントロール → 「データをエクスポート」
  2. メールでダウンロードリンクが届く → zip を解凍
  3. 中の conversations.json のパスを引数に渡す

使い方:
    python3 convert_chatgpt.py /path/to/conversations.json
"""
import os, sys, json
from datetime import datetime, timezone, timedelta
from common import out_path, already_exists, write_note

JST = timezone(timedelta(hours=9))

def ts(v):
    try:
        return datetime.fromtimestamp(float(v), JST)
    except Exception:
        return None

def linearize(mapping):
    """ChatGPT export の mapping(ツリー) を作成時刻順の発話列に変換する。"""
    nodes = []
    for nid, node in mapping.items():
        msg = node.get("message")
        if not msg:
            continue
        role = (msg.get("author") or {}).get("role")
        if role not in ("user", "assistant"):
            continue
        parts = (msg.get("content") or {}).get("parts") or []
        text = "\n\n".join(p for p in parts if isinstance(p, str) and p.strip())
        if not text.strip():
            continue
        nodes.append((msg.get("create_time") or 0, role, text.strip()))
    nodes.sort(key=lambda x: x[0])
    return nodes

def convert(json_path):
    data = json.load(open(json_path, encoding="utf-8"))
    convs = data if isinstance(data, list) else data.get("conversations", [])
    made = skipped = empty = 0
    for conv in convs:
        title = conv.get("title") or "(無題)"
        sid = str(conv.get("conversation_id") or conv.get("id") or "")
        nodes = linearize(conv.get("mapping", {}))
        if not nodes:
            empty += 1
            continue
        dt = ts(conv.get("create_time")) or ts(nodes[0][0])
        if not dt:
            empty += 1
            continue
        if not sid:
            sid = f"{dt.strftime('%Y%m%d%H%M')}{abs(hash(title))%10000:04d}"
        if already_exists(sid):
            skipped += 1
            continue
        rendered = []
        for _t, role, text in nodes:
            who = "## 🧑 あなた" if role == "user" else "## 🤖 ChatGPT"
            rendered.append(f"{who}\n\n{text}")
        fields = [
            ("created", dt.strftime("%Y-%m-%d")),
            ("source", "ChatGPT"),
            ("messages", len(rendered)),
            ("id", sid),
        ]
        write_note(out_path(dt, "gpt", title, sid), title, fields, "\n\n---\n\n".join(rendered))
        made += 1
    print(f"会話数: {len(convs)} / 新規変換: {made} / 既存スキップ: {skipped} / 空: {empty}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使い方: python3 convert_chatgpt.py /path/to/conversations.json")
        sys.exit(1)
    convert(sys.argv[1])
