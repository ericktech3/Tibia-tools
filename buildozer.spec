[app]
title = Tibia Tools
package.name = tibiatools
package.domain = org.erick

source.dir = .
source.include_exts = py,kv,json,txt,png,jpg,jpeg,ico,md

version = 0.2.0

requirements = python3,kivy,requests,certifi,plyer

# Permissões
android.permissions = INTERNET,FOREGROUND_SERVICE,POST_NOTIFICATIONS,RECEIVE_BOOT_COMPLETED

# Build Android
android.api = 33
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a,armeabi-v7a

# FIX: não deixar o p4a puxar build-tools “do nada” (36.x etc)
android.build_tools_version = 33.0.2

# AndroidX (recomendado)
android.enable_androidx = True

# Orientação
orientation = portrait

# Service (se você usa watcher em background)
services = watcher:service/main.py

# Logs do Python no logcat
android.logcat_filters = *:S python:V

[buildozer]
log_level = 2
warn_on_root = 1
