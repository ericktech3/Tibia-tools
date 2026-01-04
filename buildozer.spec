[app]
title = Tibia Tools
package.name = tibiatools
package.domain = org.erick

source.dir = .
source.include_exts = py,kv,json,txt,md,png,jpg,jpeg,atlas,ttf,otf,ico

version = 0.2.0

; NÃO coloque "python3" aqui
requirements = kivy,requests,certifi,plyer

; Vertical
orientation = portrait

android.permissions = INTERNET,FOREGROUND_SERVICE,POST_NOTIFICATIONS,RECEIVE_BOOT_COMPLETED

android.api = 33
android.minapi = 24
android.archs = arm64-v8a,armeabi-v7a
android.enable_androidx = True

; Se você tiver o service:
services = watcher:service/main.py

[buildozer]
log_level = 2
warn_on_root = 1
