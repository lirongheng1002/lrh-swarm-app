@echo off
chcp 65001 >nul
setlocal
title LRH手机集群控制 - 一键推送 GitHub 出 APK
cd /d "%~dp0"

echo ================================================================
echo   LRH 手机集群控制 —— 一键推送 GitHub，云端自动打包 APK
echo ================================================================
echo.

where git >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 git。请先安装 Git for Windows:
    echo         https://git-scm.com/download/win
    pause
    exit /b 1
)

REM -------- 解析仓库地址（优先级：参数1 ^> 环境变量 LRH_REPO ^> repo_url.txt） --------
set "REPO="
if not "%~1"=="" set "REPO=%~1"
if "%REPO%"=="" if not "%LRH_REPO%"=="" set "REPO=%LRH_REPO%"
if "%REPO%"=="" if exist "repo_url.txt" (
    for /f "usebackq tokens=* delims=" %%r in ("repo_url.txt") do (
        if not "%%r"=="" if not "%%r:~0,1%"=="#" set "REPO=%%r"
    )
)
if "%REPO%"=="" (
    echo [错误] 没拿到仓库地址，请用任一方式提供:
    echo   1^) 把 URL 写到本目录 repo_url.txt（一行）
    echo   2^) 设置环境变量 LRH_REPO
    echo   3^) 传参:   %~nx0 https://github.com/你的用户/仓库.git
    pause
    exit /b 1
)

REM -------- git 初始化 / 提交 --------
echo [1/5] 检查/初始化本地仓库...
if not exist .git git init >nul

REM 若未配置 user/email，给个保守默认（不会影响推送，只让 commit 不被拒）
git config user.name >nul 2>nul
if errorlevel 1 git config user.name "LRH Bot"
git config user.email >nul 2>nul
if errorlevel 1 git config user.email "lrh-bot@local"

echo [2/5] 加入全部文件...
git add -A
git commit -m "LRH mobile swarm console v1.0" 2>nul
if errorlevel 1 echo （无新改动可提交，继续）
git branch -M main
git remote remove origin 2>nul
git remote add origin "%REPO%"

echo [3/5] 推送到 GitHub（首次会弹浏览器登录窗口，按提示完成）...
git push -u origin main
if errorlevel 1 (
    echo.
    echo [错误] 推送失败。可能原因：
    echo   - 仓库地址不对（应为 .git 结尾的 URL）
    echo   - 未登录 GitHub（弹的浏览器没完成授权）
    echo   - 仓库非空（GitHub 端要先建空仓库、不要勾 README）
    pause
    exit /b 1
)

echo.
echo [4/5] 推送成功！
echo.
echo [5/5] GitHub Actions 已经自动开始 build-apk 工作流：
echo   仓库页 -^> 上方 Actions 选项卡 -^> 几分钟后产出 LRH集群控制-apk 工件
echo.
echo   完成后把 .apk 传到手机安装（首次安装允许"未知来源"）。
echo.
pause
endlocal
