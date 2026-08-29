[app]
# 手机集群控制 APP（Kivy / Android）
title = LRH集群控制
package.name = lrhswarm
package.domain = org.lrh

source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,yaml,txt,md,ttf,otf,ttc
source.include_patterns =

version = 1.2.3

# Python-for-android 依赖（pymavlink/pyyaml p4a 均有 recipe）
requirements = python3,kivy,pymavlink,pyyaml
# 固定 p4a 到与 buildozer 1.5.0 同期（v2023.09.16：--dir 参数仍在、NDK 25b 匹配；新版 tag 已移除 --dir）
p4a.branch = v2023.09.16

orientation = portrait
fullscreen = 0

# ---- Android ----
android.permissions = INTERNET,ACCESS_NETWORK_STATE,ACCESS_WIFI_STATE
android.api = 34
android.minapi = 21
android.ndk = 25b
android.archs = arm64-v8a
android.allow_backup = True
# 必须 True：buildozer 据此传 --private（False 会传旧式 --dir，p4a 一律不认）
android.private_storage = True
android.enable_androidx = True
android.accept_sdk_license = True
# 应用图标：用桌面 LRH_icon（512x512 PNG，放项目根）
android.icon = LRH_icon.png
android.add_src =
android.add_aars =
android.add_jars =
android.gradle_dependencies =
android.manifest_placeholders =

# ---- iOS(暂不支持) / 其他 ----
ios.package_name = org.lrh.lrhswarm
ios.bundle_name = LRH集群控制

[buildozer]
log_level = 2
warn_on_root = 1