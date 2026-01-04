[app]
title = Tibia Tools
package.name = tibiatools
package.domain = org.erick
source.dir = .
source.include_exts = py,kv,json,png,jpg,ttf

version = 0.2.0
requirements = python3,kivy,requests,pillow,certifi

orientation = portrait
fullscreen = 1

android.permissions = INTERNET,ACCESS_NETWORK_STATE,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE
android.api = 34
android.minapi = 21
android.archs = arm64-v8a,armeabi-v7a

# MUITO IMPORTANTE no CI: força o Buildozer a usar o SDK do runner
android.sdk_path = /usr/local/lib/android/sdk

# Opcional, mas ajuda a não “interagir” com licença no CI
android.accept_sdk_license = True
android.skip_update = True

[buildozer]
log_level = 2
warn_on_root = 1
