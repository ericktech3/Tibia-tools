[app]
title = Tibia Tools
package.name = tibiatools
package.domain = org.erick
source.dir = .
source.include_exts = py,kv,json,txt,png,ico,md

version = 0.2.0

requirements = python3,kivy,requests,certifi,pyjnius,plyer
android.accept_sdk_license = True

android.logcat_filters = *:S python:D
android.permissions = INTERNET,FOREGROUND_SERVICE,POST_NOTIFICATIONS,RECEIVE_BOOT_COMPLETED

services = watcher:service/main.py

android.api = 33
android.minapi = 24
android.archs = arm64-v8a

[buildozer]
log_level = 2
warn_on_root = 1
