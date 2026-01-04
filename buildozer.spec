[app]
title = Tibia Tools
package.name = tibiatools
package.domain = org.erick
source.dir = .
source.include_exts = py,kv,json,txt,png,ico,md

version = 0.2.0

requirements = python3,kivy,requests,certifi,pyjnius,plyer

# Android
android.api = 33
android.minapi = 24

# S25 Ultra -> arm64
android.archs = arm64-v8a

# Tela
orientation = portrait

# Logs
android.logcat_filters = *:S python:D

# Permissões
android.permissions = INTERNET,FOREGROUND_SERVICE,POST_NOTIFICATIONS,RECEIVE_BOOT_COMPLETED

# Aceitar licenças no CI
android.accept_sdk_license = True

# Service de monitoramento (pasta "service/" minúscula)
services = watcher:service/main.py:foreground:sticky

[buildozer]
log_level = 2
warn_on_root = 1
