"""LRH 手机集群控制 APP 入口（Kivy）
运行（电脑调试）：python main.py
打包 APK：./build_apk.bat（WSL2）或 GitHub Actions（见 .github/workflows）
"""
import os
import sys

# 电脑调试：Kivy 窗口按 16:9（1280x720 逻辑 → 高分屏 ×缩放后仍 16:9）。
# 必须在 import 手机 App（触发 kivy 初始化）之前设置 Config，窗口才按此比例创建；
# 手机真机不设（Android 全屏由系统管理）。
try:
    from kivy.config import Config
    from kivy.utils import platform
    if platform != 'android':
        Config.set('graphics', 'width', '1280')
        Config.set('graphics', 'height', '720')
except Exception:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from swarm_mobile.app import main as app_main

if __name__ == '__main__':
    app_main()