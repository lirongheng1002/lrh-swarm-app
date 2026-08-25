@echo off
chcp 65001 >nul
setlocal
title LRH 手机集群控制 - APK 打包
cd /d "%~dp0"

echo ================================================
echo  LRH 手机集群控制 APK 一键打包（WSL2 方式）
echo  没有 WSL 发行版？改用 GitHub Actions 云端打包：
echo    .\..\push 到 GitHub 后自动出 APK（见 .github/workflows）
echo ================================================

echo [1/3] 检查 WSL Ubuntu 发行版...
wsl -l -v 2>nul | findstr /i "/Ubuntu" >nul 2>&1
if errorlevel 1 (
  echo.
  echo  [提示] 未找到 WSL Ubuntu。两种处理方式：
  echo   方式1（推荐）: 安装 WSL+Ubuntu 后重跑本脚本：
  echo       wsl --install -d Ubuntu
  echo   方式2（免安装）: 把本项目推到 GitHub，用云端 Actions 自动打包。
  pause
  exit /b 1
)

echo [2/3] 在 WSL 内执行 build_apk.sh（首次需下载 SDK/NDK，较慢）...
set "APP_DIR=%CD:\=/%"
wsl -d Ubuntu -- bash -lc "cd '%APP_DIR%' && ./build_apk.sh"
if errorlevel 1 (
  echo 打包失败，请查看上面 WSL 输出。
  pause
  exit /b 1
)

echo [3/3] 完成！APK 在 bin 目录：
dir /b bin\*.apk 2>nul
pause