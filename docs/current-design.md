# 現行設計: AI会話を利用者指定のMarkdown保存先へ変換する

2026-10-30時点の公開trackedコードに基づく。操作と入力の条件は[README](../README.md)を引き継ぐ。今回確認したのはソースと文書だけで、変換器のimport/実行、個人ログ・会話・Vault・settings・生成ノートの読取は行っていない。

## 要件と処理範囲

- 利用者自身が用意したWeb版エクスポートまたは指定CLI記録を、1会話/セッション単位のMarkdownへ変換する。外部APIや会話取得機能は持たない。
- 出力先は`AI_EXPORT_VAULT`に絶対パスを明示する。入力と出力は別の領域として扱い、利用者がバックアップを用意する。
- 原文に秘密・個人情報が含まれる前提を保ち、変換結果を公開用の匿名化データとは扱わない。
- 方式ごとの重複スキップ/更新条件を保つ。すべてを追記専用または完全バックアップと見なさない。

## 構成と入力契約

| 入口 | 取り出す内容と更新方針 |
| --- | --- |
| [convert_chatgpt.py](../convert_chatgpt.py) | 引数のJSON配列または`conversations`配下。mapping内のuser/assistant文字列を時刻順に並べる。現在の分岐1本を選ぶ処理ではない。既存IDはスキップ。 |
| [convert_claude_ai.py](../convert_claude_ai.py) | 引数のJSONの会話/メッセージを読み、文字列本文とtext blockをMarkdown化。既存IDはスキップ。 |
| [convert_claude_code.py](../convert_claude_code.py) | 指定rootを再帰走査し、同sessionIdのJSONLではメッセージ数が最多のファイルを採用。思考/ツールはdetailsに畳み、tool_resultは最大4,000文字。 |
| [convert_codex.py](../convert_codex.py) | 指定rootのsessionsとsession_indexを参照。session_metaとevent_msgのuser_message/agent_messageを採用し、他のイベントは変換対象外。途中の不正JSON行はスキップ。 |
| [common.py](../common.py) | 出力先、命名、ID探索、frontmatter、既存topic/statusの保持と通常のノート書込。製品外の分類用hookはno-op。 |
| [run.sh](../run.sh) | Codex rootにsessionsがあれば変換し、Claude Codeを実行。その後、引数ファイルの文字列検査でChatGPT/Claudeへ振り分ける。バックグラウンド常駐やGit同期の登録はしない。 |

CLI入力rootは`AI_EXPORT_CODEX_ROOT`と`AI_EXPORT_CLAUDE_PROJECTS`で指定する。未指定の場合は既存CLIの標準保存先を使うので、検証時は必ず合成入力rootを指定する。Claude側の複数rootはOSのパス区切り文字で分ける。
`run.sh`の振り分けはJSON schema検証ではない。新しいエクスポート形式は各変換器へ明示的に渡して確認する。

## 出力・重複・更新の境界

出力は`AI_EXPORT_FOLDER`（既定`ai-exports`）の年フォルダ配下で、JST日時・sourceタグ・整形したタイトル・IDをファイル名に使う。frontmatterはcreated/source/messages/id等とdiaryタグ、本文は話者ごとのMarkdown。入力原本を削除する処理はない。

- Web版2変換器とClaude CodeのID判定は[common.py](../common.py)の既存ノート先頭とファイル名を調べ、完全IDと先頭8文字を使う。prefix衝突や無IDの代用IDにより、厳密な重複防止を保証しない。Web版の無ID fallbackにはPythonのhashが入り、実行間の同一IDも保証しない。
- Claude Codeは、既存の`[cc]_`ノートでメッセージ増加または旧コマンド由来タイトルを検出した場合だけ更新する。新しい名前へ書き込んだ後、名前が変わった旧ノートを削除することがある。
- Codexは完全session IDを使い、旧8文字の候補は本文IDで再照合。同IDの通常変換ではsessions内で発話数最多の記録を選ぶ。既存内容が同じなら書かず、変化時は`.tmp`へ書いて`os.replace`する。
- CodexのCLIは`fcntl`の排他lockを使う。ほかの変換器には同じ書込lock/atomic置換はない。CodexのコードはPOSIXの`fcntl`を前提とする。
- 更新で保持する手動項目はtopic/statusのみ。本文を手で編集しても、更新時に原文から置き換わる可能性がある。

## dry-runとhookの扱い

Claude CodeとCodexには`--dry`があり、会話本文の書込/旧ノート削除を抑える。ただし命名処理で年フォルダを作り、Codex CLIはlockファイルを開くため、完全な読み取り専用ではない。Web版2変換器と`run.sh`にはdry-run入口がない。

Codexの`--latest`は更新日時が新しい入力、`--session`は明示ファイルを選ぶ。`--hook`はstdinのJSONを読み、transcript_pathの実体がsessions配下なら採用し、不採用ならsession_idのglob検索へfallbackする。fallback候補やCLI明示ファイルに同じrealpath閉じ込めを課す処理はない。hook経路の重複候補再走査は省略し、例外時はローカルerror logへ記録して`{}`を返す。hookコードの存在と、利用者のCLIへ自動実行設定が登録済みであることは別であり、このrepoは登録しない。

## 権限・保存・秘密情報

このツールにはアプリ独自の認証/権限分離はなく、実行したOSユーザーの権限でファイルを読む/書く。`AI_EXPORT_VAULT`の絶対パス検査は出力sandboxではない。`AI_EXPORT_FOLDER`の結合、symlink、入力IDを含む全パスの閉じ込めを包括的に検証する実装はないため、入力と設定を信頼できる範囲に限定する。
会話・プロジェクト情報・ツール内容をMarkdownへ保存し、暗号化、秘密の自動除去、HTMLの安全化は行わない。一般ノートの書込はatomicではなく、途中中断時の復旧を保証しない。
[scan_secrets.py](../scan_secrets.py)は別途指定rootを走査し、代表的な鍵/トークン形式の種類と相対位置を報告する簡易検査。変換器から自動実行されず、検出時の値の除去やコミット操作も行わない。検出0でも公開可能という保証にはならない。

## 変更時に必要な合成検証

- 空の専用出力先と、各形式の小さな合成JSON/JSONLを使い、JST時刻・source/ID・発話の選択と順序・tool_resultの切り詰めを確認する。
- 同IDの再変換、先頭8文字衝突、同IDの親/子入力、Codexの旧IDノートを用意し、スキップ/最多発話選択/更新の対象を検査する。
- Claude Codeのタイトル変更による旧ファイル削除、topic/statusの保持、Codexの同一内容無変更とatomic置換を確認する。
- dry時に本文が変わらないことと、許されるdir/lockの副作用を分けて検査する。hookは許可root内/外の合成パスで境界を確認する。
- scannerは明らかな合成の検出/非検出例だけで検証し、実鍵をfixtureへ置かない。
- 現在この公開repoに自動テスト構成はない。今回は上記検証を実行しておらず、ソース対応と相対参照の確認のみ。実入力の互換性や安全な出力復旧は未検証として残す。
