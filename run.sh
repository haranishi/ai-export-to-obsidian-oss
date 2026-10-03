#!/bin/bash
# AI会話をまとめてObsidianに変換する。
# 使い方:
#   ./run.sh                                  … Claude Code のみ
#   ./run.sh <claude.ai.json> <chatgpt.json>  … 引数の json も取り込む（順不同・任意）
set -e
cd "$(dirname "$0")"

if [ -d "${AI_EXPORT_CODEX_ROOT:-$HOME/.codex}/sessions" ]; then
  echo "▶ Codex（指定したローカル記録）"
  python3 convert_codex.py
fi

echo "▶ Claude Code（ローカルセッション）"
python3 convert_claude_code.py

for arg in "$@"; do
  if grep -qi "chatgpt\|mapping" "$arg" 2>/dev/null; then
    echo "▶ ChatGPT: $arg"
    python3 convert_chatgpt.py "$arg"
  else
    echo "▶ claude.ai: $arg"
    python3 convert_claude_ai.py "$arg"
  fi
done

echo "完了。AI_EXPORT_VAULT 内の出力フォルダを確認してください。"
