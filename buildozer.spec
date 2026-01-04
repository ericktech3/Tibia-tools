[app]
title = Tibia Tools
package.name = tibiatools
package.domain = org.erick
source.dir = .
source.include_exts = py,kv,json,txt,png,ico,md

version = 0.2.0

requirements = python3,kivy,requests,certifi,pyjnius,plyer

android.logcat_filters = *:S python:D

android.permissions = INTERNET,FOREGROUND_SERVICE,POST_NOTIFICATIONS,RECEIVE_BOOT_COMPLETED

# ✅ aceita licença do Android SDK automaticamente no CI
android.accept_sdk_license = True

# ✅ service (confere se sua pasta é "service/" minúscula e tem main.py)
services = watcher:service/main.py:foreground:sticky

android.api = 33
android.minapi = 24

# ✅ para seu S25 Ultra (arm64)
android.archs = arm64-v8a

[buildozer]
log_level = 2
warn_on_root = 1
