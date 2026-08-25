#!/usr/bin/env bash
# LRH手机集群控制 - 一键推送 GitHub 出 APK（给 AI 调用，无阻塞）
# 用法：
#   ./一键推送GitHub出APK.sh https://github.com/你的用户/仓库.git
# 或：LRH_REPO=... ./一键推送GitHub出APK.sh
# 或：在目录里写一行 repo_url.txt
set -e
cd "$(dirname "$0")"

if ! command -v git >/dev/null 2>&1; then
  echo "[错误] 未找到 git。请先安装 Git for Windows: https://git-scm.com/download/win" >&2
  exit 1
fi

REPO="${1:-${LRH_REPO:-}}"
if [ -z "$REPO" ] && [ -f repo_url.txt ]; then
  REPO="$(grep -vE '^\s*(#|$)' repo_url.txt | head -n1 | tr -d '\r')"
fi
if [ -z "$REPO" ]; then
  echo "[错误] 没拿到仓库地址，请用：参数1 / LRH_REPO 环境变量 / repo_url.txt" >&2
  exit 1
fi

echo "[1/5] 初始化本地仓库..."
[ -d .git ] || git init -q

git config user.name >/dev/null 2>&1 || git config user.name "LRH Bot"
git config user.email >/dev/null 2>&1 || git config user.email "lrh-bot@local"

echo "[2/5] 加入并提交..."
git add -A
git commit -m "LRH mobile swarm console v1.0" -q 2>/dev/null || echo "（无新改动可提交，继续）"
git branch -M main
git remote remove origin 2>/dev/null || true
git remote add origin "$REPO"

echo "[3/5] 推送到 GitHub: $REPO"
git push -u origin main

echo
echo "[4/5] 推送成功！"
echo "[5/5] 去仓库 Actions 选项卡等 LRH集群控制-apk 工件（首次 5~15 分钟）。"
