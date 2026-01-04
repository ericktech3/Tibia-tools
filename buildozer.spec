[app]
title = Tibia Tools
package.name = tibiatools
package.domain = org.erick

source.dir = .
source.include_exts = py,kv,json,txt,png,jpg,jpeg,ico,md

version = 0.2.0

requirements = python3,kivy,requests,certifi,pyjnius,plyer

# Vertical (portrait)
orientation = portrait

# Android config
android.api = 33
android.minapi = 24
android.ndk_api = 24
android.archs = arm64-v8a,armeabi-v7a

# FIX do teu erro: aceita licença automaticamente
android.accept_sdk_license = True

# Evita build-tools 36.x aleatório (e o prompt de licença)
android.build_tools_version = 33.0.2

# Permissões
android.permissions = INTERNET,FOREGROUND_SERVICE,POST_NOTIFICATIONS,RECEIVE_BOOT_COMPLETED,WAKE_LOCK

# Logs (útil p/ quando “abre e fecha”)
android.logcat_filters = *:S python:D

# Service (ajuste o caminho conforme a pasta REAL no repo)
# Se sua pasta for "service/", use:
services = watcher:service/main.py


[buildozer]
log_level = 2
warn_on_root = 1
