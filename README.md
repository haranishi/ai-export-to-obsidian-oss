# AI会話エクスポート → Obsidian — OSS版

自分で取得した ChatGPT / Claude のエクスポートと、ローカルCLIのセッションをMarkdownへ変換するPythonツールです。外部APIを呼ぶ機能はありません。

現行の処理・更新/削除・データ境界: [設計記録](docs/current-design.md)。

## 設定と変換

Python 3 と、書き込み専用に用意したVaultまたはテスト用フォルダを使います。実行前に入力と出力のバックアップを取ってください。

```sh
export AI_EXPORT_VAULT="/absolute/path/to/test-vault"
python3 convert_chatgpt.py /path/to/conversations.json
python3 convert_claude_ai.py /path/to/claude-conversations.json
```

出力は既定で `ai-exports/<年>/` に保存します。`AI_EXPORT_FOLDER` で保存フォルダ名を変更できます。

## ローカルCLIの記録

```sh
# 読み取り対象を自分のセッションディレクトリに限定します。
export AI_EXPORT_CODEX_ROOT="/absolute/path/to/codex-data"
python3 convert_codex.py
export AI_EXPORT_CLAUDE_PROJECTS="/absolute/path/to/claude/projects"
python3 convert_claude_code.py --dry
python3 convert_claude_code.py
```

未指定時の入力は標準の `~/.codex` と `~/.claude/projects` です。複数のClaude入力先はOSのパス区切り文字で指定します。
会社・顧客・他人の会話を処理する場合は、そのデータを扱う権限と保存先の条件を先に確認してください。

## 秘密情報と公開範囲

変換結果には会話・ツールの出力・認証情報が含まれる可能性があります。Markdownを公開リポジトリへ保存しないでください。
`python3 scan_secrets.py /path/to/output` は簡易検査で、すべての秘密情報や個人情報を検出するものではありません。

このOSS版には会話データ、実運用の出力先、自動実行設定、Git自動同期、私用の分類・ハンドオフ処理を含めていません。既存の運用環境は変更していません。
自作ソースは [MIT](LICENSE) です。ChatGPT / Claude / Codex / Obsidian の公式製品ではありません。
