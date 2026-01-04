[app]
title = Tibia Tools
package.name = tibiatools
package.domain = org.erick

source.dir = .
source.include_exts = py,kv,json,txt,png,jpg,jpeg,ico,md

version = 0.2.0

requirements = python3,kivy,requests,certifi,pyjnius,plyer

# logs úteis pra debug no Android
android.logcat_filters = *:S python:D

# permissões
android.permissions = INTERNET,FOREGROUND_SERVICE,POST_NOTIFICATIONS,RECEIVE_BOOT_COMPLETED

# service (se você realmente usa)
services = watcher:service/main.py

# APIs
android.api = 33
android.minapi = 24
android.archs = arm64-v8a,armeabi-v7a

# ✅ FORÇA VERTICAL
orientation = portrait

# ✅ Forçar buildozer usar o SDK do GitHub runner (evita SDK interno quebrado)
android.sdk_path = /usr/local/lib/android/sdk

[buildozer]
log_level = 2
warn_on_root = 1
