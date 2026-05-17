#!/usr/bin/env bash
#
# Transcriber 緊急回滾腳本。
#
# 使用方式（在 EC2 Web Server 上）：
#   sudo transcriber-rollback              # 列出可用版本
#   sudo transcriber-rollback <sha>        # 回到指定 sha
#   sudo transcriber-rollback --prev       # 回到前一個版本（自動找）
#
# 釋出檔位置：/opt/transcriber/releases/<component>-<sha>.tar.gz
# 當前版本：  /opt/transcriber/releases/CURRENT  （deploy 寫入）
#
set -euo pipefail

RELEASES_DIR=/opt/transcriber/releases
CURRENT_FILE=${RELEASES_DIR}/CURRENT
APP_DIR=/opt/transcriber
WEB_ROOT=/var/www/transcriber
ADMIN_ROOT=/var/www/admin

if [[ $EUID -ne 0 ]]; then
  echo "❌ 必須用 sudo 執行：sudo $(basename "$0") $*" >&2
  exit 1
fi

list_releases() {
  echo "📦 可用 backend 版本（新→舊）："
  ls -1t "${RELEASES_DIR}"/backend-*.tar.gz 2>/dev/null \
    | sed -E 's|.*/backend-(.*)\.tar\.gz|  - \1|' || echo "  （無）"
  if [[ -f $CURRENT_FILE ]]; then
    echo "🎯 目前版本：$(cat "$CURRENT_FILE")"
  fi
}

find_previous_sha() {
  local current
  current=$(cat "$CURRENT_FILE" 2>/dev/null || echo "")
  ls -1t "${RELEASES_DIR}"/backend-*.tar.gz 2>/dev/null \
    | sed -E 's|.*/backend-(.*)\.tar\.gz|\1|' \
    | grep -v "^${current}$" \
    | head -1
}

ROLLBACK_SHA=""
case "${1:-}" in
  "")
    list_releases
    exit 0
    ;;
  --prev)
    ROLLBACK_SHA=$(find_previous_sha)
    if [[ -z $ROLLBACK_SHA ]]; then
      echo "❌ 找不到前一個版本" >&2
      exit 1
    fi
    echo "🔙 回滾到前一版：${ROLLBACK_SHA}"
    ;;
  --help|-h)
    head -10 "$0" | sed 's/^# //;s/^#//'
    exit 0
    ;;
  *)
    ROLLBACK_SHA=$1
    ;;
esac

# 驗證三個元件都有對應釋出檔
for prefix in backend frontend admin-frontend; do
  if [[ ! -f ${RELEASES_DIR}/${prefix}-${ROLLBACK_SHA}.tar.gz ]]; then
    echo "❌ 缺少 ${prefix}-${ROLLBACK_SHA}.tar.gz" >&2
    exit 1
  fi
done

echo "⏪ 正在回滾到 ${ROLLBACK_SHA}..."

# Backend
cd "$APP_DIR"
tar -xzf "${RELEASES_DIR}/backend-${ROLLBACK_SHA}.tar.gz"
cp "${APP_DIR}/deploy/nginx-ec2.conf" /etc/nginx/conf.d/transcriber.conf
rm -f /etc/nginx/conf.d/default.conf
nginx -t && systemctl reload nginx
systemctl restart transcriber
echo "✅ Backend 已回滾"

# Frontend
tmp_dir=$(mktemp -d)
tar -xzf "${RELEASES_DIR}/frontend-${ROLLBACK_SHA}.tar.gz" -C "$tmp_dir"
mkdir -p "$WEB_ROOT"
# 第一次部署時 web root 可能不存在，用 find 清較安全（rm -rf empty/* 會 set -e 退出）
find "$WEB_ROOT" -mindepth 1 -delete 2>/dev/null || true
cp -r "${tmp_dir}/dist/"* "${WEB_ROOT}/"
chown -R nginx:nginx "$WEB_ROOT"
rm -rf "$tmp_dir"
echo "✅ Frontend 已回滾"

# Admin
tmp_dir=$(mktemp -d)
tar -xzf "${RELEASES_DIR}/admin-frontend-${ROLLBACK_SHA}.tar.gz" -C "$tmp_dir"
mkdir -p "$ADMIN_ROOT"
find "$ADMIN_ROOT" -mindepth 1 -delete 2>/dev/null || true
cp -r "${tmp_dir}/dist/"* "${ADMIN_ROOT}/"
chown -R nginx:nginx "$ADMIN_ROOT"
rm -rf "$tmp_dir"
echo "✅ Admin frontend 已回滾"

# 更新 CURRENT 標記
echo "${ROLLBACK_SHA}" > "$CURRENT_FILE"

# 健康檢查
sleep 3
if curl -fsS https://soundlite.app/health > /dev/null; then
  echo "✅ 回滾成功，健康檢查通過：${ROLLBACK_SHA}"
else
  echo "⚠️  回滾完成但 /health 沒回 200，請手動檢查 systemctl status transcriber"
  exit 2
fi
