#!/usr/bin/env bash
# Linux / WSL 内一键打包 APK（需 python3 + buildozer 依赖；首次运行会下载 SDK/NDK）
set -e
cd "$(dirname "$0")"

echo '== 1/3 安装 buildozer（若已装会跳过） =='
command -v buildozer >/dev/null 2>&1 || pip3 install --user buildozer cython

export PATH="$HOME/.local/bin:$PATH"
command -v java >/dev/null 2>&1 || { echo '错误：未安装 Java（JDK 17），请先 apt install openjdk-17-jdk'; exit 1; }

echo '== 2/3 打包 APK（首次下载 Android SDK/NDK 需数分钟~几十分钟） =='
buildozer android debug

echo '== 3/3 完成 =='
ls -lh bin/*.apk 2>/dev/null | tail -1