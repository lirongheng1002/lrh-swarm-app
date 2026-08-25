# LRH 手机集群控制（Kivy Android APP）

手机端集群控制 APP，与桌面端 **LRH集群控制 v2.0** 共用同一套 MAVLink 核心
（`swarm_mobile/core/` 原样复用桌面控制台的 mavlink_bus / commands / vehicles /
missions / formation / config），4G 通过阿里云服务器中继直连每架机
（15551~15560，每机一条 TCP）。

功能：连接飞机 · 卫星数 · 单机/全队起降 · 单机/全队解锁上锁 · 模式切换 ·
自动执行任务 · 队形编队（6 预设+间距）· 任务航点设置/下载/上传 · 投弹指令（184）。

## 目录

```
swarm-mobile/
├── main.py                     # 入口（python main.py 电脑调试）
├── swarm_mobile/
│   ├── app.py                  # Kivy 全中文手机界面
│   ├── fleet.py                # 手机端控制逻辑（薄调度核心）
│   ├── core/                   # 复用核心（纯 Python，与桌面控制台一致）
├── config.yaml                 # 默认配置（打进 APK，可在手机内改写并保存）
├── smoke_mobile.py             # 核心冒烟（连 mock_relay 自动验证）
├── ui_smoke.py                 # UI 冒烟（Kivy 窗口自动开合）
├── buildozer.spec              # APK 打包配置
├── build_apk.bat / build_apk.sh# 一键打包（WSL2 / Linux）
├── .github/workflows/build-apk.yml  # GitHub Actions 云端打包
└── 手机集群控制APP使用说明.md
```

## 运行与验证

```bash
pip install -r requirements.txt
python smoke_mobile.py    # 核心链路冒烟（自动连 mock_relay）
python ui_smoke.py        # 界面冒烟（窗口 2 秒自动关闭）
python main.py            # 电脑上以手机尺寸窗口调试
```

## 打包 APK

- 方式 1（领导选定的方案）：**推到 GitHub → Actions 自动出 APK**（免本机安装）；
- 方式 2：WSL2 + Ubuntu 后双击 `build_apk.bat`。

### 推送到 GitHub 的具体操作

**情况 A：装 Git（推荐）**
1. 下载安装 Git for Windows：<https://git-scm.com/download/win>（一路默认即可）；
2. 在 `swarm-mobile` 目录打开命令行，执行：
   ```
   git init
   git add .
   git commit -m "LRH手机集群控制 v1.0"
   git branch -M main
   git remote add origin <你的GitHub新仓库地址>
   git push -u origin main
   ```
   （GitHub 上先新建一个**空仓库**，不要勾选生成 README。）
3. 推送后仓库 Actions 自动打包（首次约 5~15 分钟，会缓存 SDK 避免下次重下），
   完成后在 Actions 页面下载 `LRH集群控制-apk` 工件里的 `.apk` 传到手机安装。

**情况 B：不装 Git · 网页上传**
1. GitHub 新建空仓库；
2. 仓库页点「Add file → Upload files」，把整个 `swarm-mobile` 目录的文件拖进去上传
   （`fonts/NotoSansSC-VF.ttf` 16.9MB 单文件可传；上传后 Actions 同样自动打包）；
3. 若文件太多，可先用压缩软件把整个目录压成 zip，上传后在 Actions 页下载工件。

> 中文显示：已内置 Noto Sans SC 开源字体（`fonts/`），Android 上全中文界面正常显示，无需额外处理。