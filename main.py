"""LRH 手机集群控制 APP 入口（Kivy）
运行（电脑调试）：python main.py
打包 APK：./build_apk.bat（WSL2）或 GitHub Actions（见 .github/workflows）
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from swarm_mobile.app import main as app_main

if __name__ == '__main__':
    app_main()