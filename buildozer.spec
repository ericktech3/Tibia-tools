[app]
title = Tibia Tools
package.name = tibiatools
package.domain = org.erick

source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,json,txt,ttf,otf,db

version = 0.2.0

requirements = python3,kivy,requests,certifi,plyer

orientation = portrait
fullscreen = 0

# Se você usa service no projeto, descomente e ajuste:
# services = Watcher:service/main.py:foreground

[buildozer]
log_level = 2
warn_on_root = 1

[android]
android.api = 33
android.minapi = 24
android.ndk_api = 24

android.archs = arm64-v8a,armeabi-v7a

android.permissions = INTERNET

# MUITO IMPORTANTE no GitHub Actions:
android.sdk_path = /home/runner/android-sdk
android.skip_update = True
android.accept_sdk_license = True

# AndroidX (se você estiver usando libs que exigem)
android.enable_androidx = True
