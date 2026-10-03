#!/usr/bin/env python3
"""claude.ai（ウェブ版Claude）の全データエクスポートを Obsidian用Markdown に変換する。

事前準備（手動・半自動の「定期エクスポート」部分）:
  1. claude.ai → 設定 → プライバシー → 「データをエクスポート」
  2. しばらくするとメールでダウンロードリンクが届く → zip を解凍
  3. 中の conversations.json のパスを引数に渡す

使い方:
    python3 convert_claude_ai.py /path/to/conversations.json
"""
import os, sys, json
from datetime import datetime, timezone, timedelta
from common import out_path, already_exists, write_note, fold

JST = timezone(timedelta(hours=9))

def parse_ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(JST)
    except Exception:
        try:
            return datetime.fromtimestamp(float(s), JST)
        except Exception:
            return None

def text_of(msg):
    """claude.ai のメッセージから本文テキストを取り出す。"""
    if isinstance(msg.get("text"), str) and msg["text"].strip():
        return msg["text"].strip()
    parts = []
    for c in msg.get("content", []) or []:
        if isinstance(c, dict):
            if c.get("type") == "text":
                parts.append(c.get("text", ""))
            elif "text" in c:
                parts.append(c["text"])
    return "\n\n".join(p for p in parts if p).strip()

def convert(json_path):
    data = json.load(open(json_path, encoding="utf-8"))
    convs = data if isinstance(data, list) else data.get("conversations", [])
    made = skipped = empty = 0
    for conv in convs:
        sid = str(conv.get("uuid") or conv.get("id") or "")
        title = conv.get("name") or conv.get("title") or "(無題)"
        msgs = conv.get("chat_messages") or conv.get("messages") or []
        dt = parse_ts(conv.get("created_at")) or (parse_ts(msgs[0].get("created_at")) if msgs else None)
        rendered = []
        for m in msgs:
            role = m.get("sender") or m.get("role") or ""
            who = "## 🧑 あなた" if role in ("human", "user") else "## 🤖 Claude"
            t = text_of(m)
            if t:
                rendered.append(f"{who}\n\n{t}")
        if not rendered or not dt:
            empty += 1
            continue
        if not sid:
            sid = f"{dt.strftime('%Y%m%d%H%M')}{abs(hash(title))%10000:04d}"
        if already_exists(sid):
            skipped += 1
            continue
        fields = [
            ("created", dt.strftime("%Y-%m-%d")),
            ("source", "Claude（claude.ai ウェブ）"),
            ("messages", len(rendered)),
            ("id", sid),
        ]
        body = "\n\n---\n\n".join(rendered)
        write_note(out_path(dt, "claude", title, sid), title, fields, body)
        made += 1
    print(f"会話数: {len(convs)} / 新規変換: {made} / 既存スキップ: {skipped} / 空: {empty}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使い方: python3 convert_claude_ai.py /path/to/conversations.json")
        sys.exit(1)
    convert(sys.argv[1])
