#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "このスクリプトはrootで実行してください。" >&2
  exit 1
fi

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${APP_DIR:-/srv/dev-cockpit}"
CONFIG_DIR="${CONFIG_DIR:-/etc/dev-cockpit}"
REPOSITORY_DIR="${REPOSITORY_DIR:-/srv/repos/example-project}"
SERVICE_USER="${SERVICE_USER:-devcockpit}"

if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "${APP_DIR}" --shell /usr/sbin/nologin "${SERVICE_USER}"
fi

install -d -m 0755 "${APP_DIR}" "${APP_DIR}/runtime/jobs" "${CONFIG_DIR}" "$(dirname "${REPOSITORY_DIR}")"
if [[ "${SOURCE_DIR}" != "${APP_DIR}" ]]; then
  cp -a "${SOURCE_DIR}/." "${APP_DIR}/"
fi
install -m 0644 "${SOURCE_DIR}/config.linux.example.json" "${CONFIG_DIR}/config.example.json"
install -m 0644 "${SOURCE_DIR}/deploy/dev-cockpit.service" /etc/systemd/system/dev-cockpit.service
if [[ ! -f "${CONFIG_DIR}/config.json" ]]; then
  cp "${SOURCE_DIR}/config.linux.example.json" "${CONFIG_DIR}/config.json"
fi
if [[ ! -f "${CONFIG_DIR}/dev-cockpit.env" ]]; then
  install -m 0600 "${SOURCE_DIR}/deploy/dev-cockpit.env.example" "${CONFIG_DIR}/dev-cockpit.env"
  echo "${CONFIG_DIR}/dev-cockpit.env にDEV_COCKPIT_TOKENを設定してください。"
fi

chown -R root:root "${APP_DIR}"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${APP_DIR}/runtime" "${CONFIG_DIR}"
chmod 0750 "${APP_DIR}/runtime" "${APP_DIR}/runtime/jobs"
systemctl daemon-reload
systemctl enable dev-cockpit.service

cat <<EOF
インストール完了。

次に確認・編集するファイル:
  ${CONFIG_DIR}/config.json
  ${CONFIG_DIR}/dev-cockpit.env

リポジトリを ${REPOSITORY_DIR} にcloneした後、起動:
  systemctl start dev-cockpit.service
  systemctl status dev-cockpit.service
EOF
