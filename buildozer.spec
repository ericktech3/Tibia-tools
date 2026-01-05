[app]
title = Tibia Tools
package.name = tibiatools
package.domain = org.erick

source.dir = .
source.include_exts = py,kv,png,jpg,jpeg,txt,json,ttf,atlas

version = 0.1.0

requirements = python3,kivy,kivymd,certifi,requests,beautifulsoup4

orientation = portrait

# Android
android.permissions = INTERNET
android.api = 33
android.minapi = 21
android.ndk = 25b
android.archs = arm64-v8a,armeabi-v7a

# evita prompt de licença no CI (importante!)
android.accept_sdk_license = True

# (opcional) melhora logs em debug
log_level = 2
