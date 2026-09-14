# Public release checklist

このリポジトリを公開する前に、現在のファイルだけでなく Git 履歴全体を確認してください。

## 公開対象から除外するもの

- API key、token、password、秘密鍵、credential file
- 個人のメールアドレス、OSユーザー名、端末名
- 実在するローカルパス、private repository名
- LAN / VPN / Tailnet の実IPアドレス、内部ホスト名、実ドメイン
- `config.json`、runtime data、ログ、ローカル環境変数ファイル

## 確認手順

1. `config.example.json` と `config.linux.example.json` がサンプル値だけで構成されていることを確認する。
2. `.gitignore` にローカル設定、環境変数、runtime data が含まれていることを確認する。
3. Secret scanning または gitleaks 等で公開対象を検査する。
4. Git履歴を検索し、現在は削除済みの個人情報や実環境値が残っていないか確認する。
5. 過去コミットに公開したくない値が含まれる場合は、履歴を書き換えるか、サニタイズ済みの内容から新しい履歴を作成する。
6. 新しい公開用履歴を作る場合は、GitHubのnoreplyメールなど公開して問題ないauthor情報を使用する。

最新コミットから値を削除しただけでは、過去コミットから復元できる場合があります。private repository を public に切り替える前に、履歴まで含めて公開可能であることを確認してください。
