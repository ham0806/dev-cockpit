# サーバへの配置

Debian/Ubuntu系のLXCまたはVMへ、Dev Cockpitを常駐サービスとして配置する手順です。実際のサーバへSSH接続して操作するのではなく、必要なファイルをコピーしてサーバ側で実行します。

## 前提

- Debian/Ubuntu系のLXCまたはVM
- systemdが利用できる
- サーバへTailscaleをインストール済み、またはこれから導入する
- サーバ側にPython 3、Git、使用するAgent CLIを導入する
- Agentが操作するリポジトリをサーバ側へcloneする

最初にサーバ側で依存ツールを入れます。

```bash
sudo apt update
sudo apt install -y git python3 ca-certificates
```

Node.jsやCodex/Cursor CLIの導入方法は、それぞれの公式手順と利用契約に合わせてください。API keyや認証情報をGitリポジトリへ保存しないでください。

## ソースの配置

Dev Cockpitディレクトリだけをサーバへコピーするか、リポジトリをcloneします。Agentが操作するサンプルリポジトリを配置する場合は、例えば次のようにします。

```bash
sudo mkdir -p /srv/repos
sudo git clone <repository-url> /srv/repos/example-project
sudo chown -R "$USER:$USER" /srv/repos/example-project
```

`dev-cockpit` は `/srv/dev-cockpit` に配置します。すでにこのディレクトリへ移動している場合は、そのまま `deploy/install.sh` を実行できます。

```bash
cd /path/to/dev-cockpit
sudo bash deploy/install.sh
```

インストーラーは次を作成します。

- 実行ユーザー: `devcockpit`
- アプリ: `/srv/dev-cockpit`
- 設定: `/etc/dev-cockpit/config.json`
- 環境変数: `/etc/dev-cockpit/dev-cockpit.env`
- Job worktree: `/srv/dev-cockpit/runtime/jobs`
- systemd unit: `dev-cockpit.service`

## 設定

`/etc/dev-cockpit/config.json` の `projects[].repository` を、サーバ側の実際のclone先へ合わせます。公開用サンプルでは `/srv/repos/example-project` を使用しています。実環境固有のパスやprivate repository名は、Git管理対象外の `config.json` だけに設定してください。

`/etc/dev-cockpit/dev-cockpit.env` にtokenを設定します。

```bash
sudo python3 -c 'import secrets; print("DEV_COCKPIT_TOKEN=" + secrets.token_hex(32))' | sudo tee /etc/dev-cockpit/dev-cockpit.env >/dev/null
sudo chmod 600 /etc/dev-cockpit/dev-cockpit.env
```

Agent CLIの認証は、`devcockpit` ユーザーで確認します。rootユーザーで動作確認したCLI設定は、systemdの実行ユーザーからは見えないことがあります。

```bash
sudo -u devcockpit -H git -C /srv/repos/example-project status
sudo -u devcockpit -H codex --version
sudo -u devcockpit -H agent --version
```

利用しないAgentは `/etc/dev-cockpit/config.json` から削除してください。コマンドはshellではなくargvとして実行されます。

## 起動と確認

```bash
sudo systemctl start dev-cockpit.service
sudo systemctl status dev-cockpit.service
curl http://127.0.0.1:8787/api/health
sudo journalctl -u dev-cockpit.service -f
```

systemd unitは、アプリの書き込み先をJob runtimeとリポジトリに限定し、root権限ではAgentを実行しません。commitやpushはPWAからの明示操作です。

## Tailscale Serve

サーバ上でTailscaleへログインした後、Tailnet内限定でDev CockpitをHTTPS公開します。

```bash
sudo tailscale up
sudo tailscale serve --bg http://127.0.0.1:8787
sudo tailscale serve status
```

表示された `https://<server>.<tailnet>.ts.net/` を、Tailscaleへログイン済みの端末から開きます。外部インターネットへ一般公開する `tailscale funnel` は、commit/push操作を含む本アプリでは使わないでください。

停止する場合:

```bash
sudo tailscale serve reset
sudo systemctl disable --now dev-cockpit.service
```

## 重要な運用上の注意

- 別マシンの作業ツリーをネットワーク共有でマウントして直接操作せず、リポジトリをサーバ側へcloneする
- Agent用のGit credentialやAPI keyは、専用ユーザーの環境・秘密管理へ置く
- TailscaleのGrant/ACLは、自分のユーザーまたは許可した端末からこのサーバへの必要なポートだけ許可する
- サーバをスナップショットまたはバックアップする。Job worktreeは再生成可能だが、設定と認証情報は別途保全する
- 実IP、Tailnet名、内部ホスト名、private repository名を公開リポジトリの設定例へ書かない
