[app]
title = Tibia Tools
package.name = tibiatools
package.domain = org.erick

source.dir = .
source.include_exts = py,kv,json,txt,png,jpg,jpeg,ttf,ico,md,ini
# Se você tiver pastas específicas, pode reforçar:
# source.include_patterns = assets/*,core/*,ui/*,service/*

version = 0.2.0

requirements = python3,kivy,requests,certifi,plyer

# VERTICAL
orientation = portrait

# Android
android.api = 33
android.minapi = 24
android.ndk_api = 24

android.archs = arm64-v8a, armeabi-v7a

android.permissions = INTERNET,FOREGROUND_SERVICE,POST_NOTIFICATIONS,RECEIVE_BOOT_COMPLETED

# Serviço
services = watcher:service/main.py

# AndroidX
android.enable_androidx = True

# Logcat útil pra debug
android.logcat_filters = *:S python:D

# NÃO use develop aqui, a menos que você saiba que quer API 36 e NDK 29.
# p4a.branch = develop   <-- REMOVA se existir
# p4a.branch = master    <-- opcional (padrão costuma ser master/estável)

[buildozer]
log_level = 2
warn_on_root = 1
