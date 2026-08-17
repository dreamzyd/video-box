#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v docker >/dev/null 2>&1; then
  echo "错误：未找到 docker。请先安装 Docker Engine。" >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "错误：未找到 Docker Compose plugin（docker compose）。" >&2
  exit 1
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "已从 .env.example 生成 .env。"
fi
chmod 600 .env 2>/dev/null || true

random_hex() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  else
    od -An -N32 -tx1 /dev/urandom | tr -d ' \n'
  fi
}

random_password() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 18 | tr -d '/+=' | cut -c1-20
  else
    od -An -N18 -tx1 /dev/urandom | tr -d ' \n' | cut -c1-20
  fi
}

get_env() {
  grep -E "^$1=" .env 2>/dev/null | tail -n1 | cut -d= -f2- || true
}

set_env() {
  local key="$1" value="$2"
  if grep -qE "^${key}=" .env; then
    sed -i "s#^${key}=.*#${key}=${value}#" .env
  else
    printf '\n%s=%s\n' "$key" "$value" >> .env
  fi
}

# 从旧版本升级时 .env 可能没有 BIND_ADDRESS；1.1.1 默认仅监听本机。
if [ -z "$(get_env BIND_ADDRESS)" ]; then
  set_env BIND_ADDRESS "127.0.0.1"
fi

app_secret="$(get_env APP_SECRET)"
if [ -z "$app_secret" ] || [ "$app_secret" = "please-change-this-secret" ] || [ "$app_secret" = "change-me-now" ]; then
  set_env APP_SECRET "$(random_hex)"
  echo "已自动生成 APP_SECRET。"
fi

app_password="$(get_env APP_PASSWORD)"
legacy_admin_password="$(get_env ADMIN_PASSWORD)"
generated_password="false"
if [ -z "$app_password" ]; then
  if [ -n "$legacy_admin_password" ] && [ "$legacy_admin_password" != "please-change-this-admin-password" ]; then
    app_password="$legacy_admin_password"
    set_env APP_PASSWORD "$app_password"
    echo "已将旧 ADMIN_PASSWORD 迁移为 APP_PASSWORD。"
  else
    app_password="$(random_password)"
    set_env APP_PASSWORD "$app_password"
    generated_password="true"
  fi
fi

mkdir -p data/db data/uploads data/media data/logs

echo "检查 Compose 配置…"
docker compose config >/dev/null

echo "构建并启动 Video Box 1.1.1…"
docker compose up -d --build
docker compose ps

bind_address="$(get_env BIND_ADDRESS)"
bind_address="${bind_address:-127.0.0.1}"
port="$(get_env VIDEO_PORT)"
port="${port:-8080}"

echo
if [ "$generated_password" = "true" ]; then
  echo "============================================"
  echo "首次生成的登录口令：$app_password"
  echo "请保存好；上传和管理使用此口令。"
  echo "公开视频观看不需要口令。"
  echo "============================================"
  echo
fi

if [ "$bind_address" = "127.0.0.1" ] || [ "$bind_address" = "localhost" ]; then
  echo "当前安全默认模式：仅监听服务器本机 ${bind_address}:${port}"
  echo "服务器本机地址：http://127.0.0.1:${port}/"
  echo
  echo "远程访问推荐二选一："
  echo "  1) SSH 隧道：ssh -L ${port}:127.0.0.1:${port} <user>@<server>"
  echo "     然后本机打开：http://127.0.0.1:${port}/"
  echo "  2) 宿主机 Nginx/Caddy 反代到：http://127.0.0.1:${port}"
  echo
  echo "如确实需要直接开放端口，在 .env 设置 BIND_ADDRESS=0.0.0.0 后执行 docker compose up -d。"
else
  echo "当前监听：${bind_address}:${port}"
  echo "登录/上传：http://<服务器IP>:${port}/"
  echo "管理中心：http://<服务器IP>:${port}/admin"
fi

echo "公开视频路径：/v/<资源ID>；公开文档路径：/r/<资源ID>（均无需登录；仍受暂停/恢复控制）"
