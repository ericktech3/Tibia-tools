[app]
title = Tibia Tools
package.name = tibiatools
package.domain = org.erick
version = 0.2.0

source.dir = .
source.include_exts = py,kv,png,jpg,jpeg,webp,json,txt,ttf,otf,atlas

# Ajuste seus requirements conforme o seu projeto real
requirements = python3,kivy,requests,certifi,urllib3,idna,chardet

# VERTICAL (portrait)
orientation = portrait
fullscreen = 0

# Permissões
android.permissions = INTERNET,FOREGROUND_SERVICE,POST_NOTIFICATIONS,RECEIVE_BOOT_COMPLETED

# Android config
android.api = 33
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a,armeabi-v7a
android.enable_androidx = True

# Service (se você realmente usa)
services = watcher:service/main.py

# Logs úteis para debug
android.logcat_filters = *:S python:V kivy:V

[buildozer]
log_level = 2
warn_on_root = 1
