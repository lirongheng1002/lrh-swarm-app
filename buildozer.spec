[app]
# 手机集群控制 APP（Kivy / Android）
title = LRH集群控制
package.name = lrhswarm
package.domain = org.lrh

source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,yaml,txt,md,ttf,otf,ttc
source.include_patterns =

version = 1.0.0

# Python-for-android 依赖（pymavlink/pyyaml p4a 均有 recipe）
requirements = python3,kivy,pymavlink,pyyaml

orientation = portrait
fullscreen = 0

# ---- Android ----
android.permissions = INTERNET,ACCESS_NETWORK_STATE,ACCESS_WIFI_STATE
android.api = 34
android.minapi = 21
android.ndk = 25b
android.archs = arm64-v8a,armeabi-v7a
android.allow_backup = True
android.private_storage = False
android.enable_androidx = True
android.add_src =
android.add_aars =
android.add_jars =
android.gradle_dependencies =
android.manifest_placeholders =
android.signing = debug

# ---- iOS(暂不支持) / 其他 ----
ios.package_name = org.lrh.lrhswarm
ios.bundle_name = LRH集群控制

[buildozer]
log_level = 2
warn_on_root = 1