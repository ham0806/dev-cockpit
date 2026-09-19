# Dev Cockpit

タブレットや別端末のSafari/PWAから、開発マシン上のCodex / Cursor / Devin CLIへ指示を送り、Job単位のGit worktreeと差分を確認するための薄い開発コンソールです。

## MVPの範囲

- Projectの許可リストから対象リポジトリを選択
- Codex / Cursor / Devin CLIをJob単位のGit worktreeで起動
- Job ID、状態、stdoutログ、変更ファイル、Git diffを確認
- 差分中のMarkdownをSource / Renderedで確認
- 同じworktreeへ修正指示を送信
- `Approve / commit` と `Push` をUI上の明示操作として分離
- 通常は `127.0.0.1` にbindし、Tailscale経由で使う場合だけ設定でlisten先を変更

## 起動

```powershell
Set-Location C:\dev\dev-cockpit
Copy-Item .\config.example.json .\config.json
python .\server.py --config .\config.json
```

`config.example.json` は公開可能なサンプル値だけを含みます。実際に使うリポジトリのパスは、Git管理対象外の `config.json` に設定してください。

Proxmox上のDebian/Ubuntu LXCや自宅サーバへsystemdで常駐させる場合は、[deploy/README.md](deploy/README.md)を参照してください。Linux用設定例、systemd unit、Tailscale Serveの手順を含みます。

ブラウザで `http://127.0.0.1:8787/` を開きます。Tailscale内の別端末から接続する場合は、`config.json` の `host` を `0.0.0.0` などPCのlisten設定へ変更し、必ずファイアウォールをTailnet内に限定してください。インターネットへ直接公開する設定はサポートしません。

認証を追加する場合は、サーバー起動前に環境変数を設定します。トークンはファイルやリポジトリへ保存しません。

```powershell
$env:DEV_COCKPIT_TOKEN = 'ローカルで生成した十分に長い値'
python .\server.py --config .\config.json
```

同じPWAをブラウザで開いた場合は、画面右上のAPI token欄へ入力するとブラウザ内のlocalStorageへ保存され、以後のAPIリクエストに `Authorization: Bearer ...` が付与されます。

## Agentコマンドの設定

`config.json` のコマンドはshellを経由せず、argvとして実行します。次のプレースホルダーを使えます。

- `{prompt}`: ユーザーの指示
- `{worktree}`: Job専用worktreeの絶対パス
- `{project}`: Project ID
- `{job_id}`: Job ID

Codex CLIやCursor Agent CLIのインストール場所・利用可能な引数は環境ごとに異なるため、`config.example.json` をコピーした後に手元のCLI仕様へ合わせてください。シークレットやAPI keyをコマンド・設定ファイルへ直接書かないでください。

## Auto routing（Jev + Devin SWE-2）

`config.json` の `routing.enabled` を `true` にすると、UIに `Auto (Jev)` が追加されます。Autoではタスク本文をJevへ渡し、設定済みAgentから実行先を選びます。Agentを明示選択した場合はルーターを通りません。

サンプル設定では次の役割分担にしています。

- `devin-swe2`: 通常の実装、バグ修正、テスト、定型的なリファクタの第一候補
- `codex-luna`: README、誤字、整形などのごく軽い変更
- `codex-sol`: 複雑なデバッグ、複数コンポーネント、移行や設計
- `codex-astra`: 高リスク、高曖昧性、大きなblast radiusを伴う例外的なタスクだけ

Astraが選ばれても `architecture_impact` / `ambiguity` / `blast_radius` の最大スコアが `astra_min_score` 未満ならSolへ落とします。Jevがタイムアウト・未設定・APIエラーになった場合もJobを失敗させず、ローカルのヒューリスティックへフォールバックします。ヒューリスティックからAstraを自動選択することはありません。

### Jevのセットアップ

Node.jsを用意し、リポジトリ直下で次を実行します。

```powershell
npm install --prefix tools
$env:AI_GATEWAY_API_KEY = 'Vercel AI GatewayのAPI key'
```

`tools/jev-route.mjs` は AI SDK 7 の `experimental_evaluate` と `typesafe-ai/jev` を使用します。API keyは `config.json` に書かず環境変数だけで渡してください。Auto routingでは `zeroDataRetention` を要求します。

Devin側はサンプルで `devin --model swe --permission-mode accept-edits --respect-workspace-trust false -p {prompt}` を使います。`swe` はSWEファミリの最新モデルを指す短縮名です。利用可能モデルは `devin models list` で確認できます。

### Routing履歴

`runtime/router.jsonl` に時刻、選択Agent、confidence、risk scoreを1行JSONで記録します。プロンプト本文は保存せず、SHA-256と文字数だけを保存します。将来、実タスクの成功率から閾値を調整するためのデータとして利用できます。

## 安全策

- プロジェクトは設定ファイルに列挙したGitリポジトリだけを対象にします。
- Agentコマンドはshell文字列として解釈しません。
- Jobごとに `runtime/jobs/<job-id>/worktree` を作ります。通常のworking treeへ直接書き込みません。
- commit、push、worktree破棄はAPI/UIの別操作です。Agent完了だけでは実行しません。
- `DEV_COCKPIT_TOKEN` を設定すると全APIにBearer認証を要求します。
- `Discard worktree` はworktreeとJob履歴を削除する不可逆操作です。
- `config.json`、runtime data、credential類はGitへ追加しません。

## テスト

外部AgentやGitHubへ接続せず、コアの入力検証とJob履歴の永続化を検証します。

```powershell
python -m unittest discover -s tests -v
```

## 公開前の確認

private repository から公開する場合は、現在のファイルだけでなくGit履歴も確認してください。過去コミットに個人情報や実環境のパスが含まれる場合は、履歴を書き換えるか、サニタイズ済みの内容から新しい履歴を作成してから公開します。詳細は [PUBLICATION.md](PUBLICATION.md) を参照してください。

## 今後の拡張

Tailscale Serveの具体的な適用、code-server / tmuxのフォールバック、Wake-on-LAN、Cursor Web連携、Markdown差分のより高度なレンダリングはMVPの後続作業です。
