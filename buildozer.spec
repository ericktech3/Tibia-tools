[app]

# (str) Title of your application
title = Tibia Tools

# (str) Package name
presplash.filename = assets/presplash.png
android.presplash_color = #000000
icon.filename = assets/icon.png
package.name = tibiatools

# (str) Package domain (needed for android/ios packaging)
package.domain = org.erick

# (str) Source code where the main.py live
source.dir = .

# Background service (monitor favorites)
services = favwatch:service/main.py

# (list) Source files to include (let empty to include all the files)
source.include_exts = py,kv,png,jpg,jpeg,txt,json,ttf,atlas,ico

# (str) Application versioning (method 1)
version = 0.1.0

# (list) Application requirements
# ✅ trava o KivyMD na versão compatível com MDBottomNavigation etc.
requirements = python3,kivy,kivymd==1.2.0,requests,urllib3,idna,charset-normalizer,chardet,certifi,beautifulsoup4,soupsieve,typing_extensions,pillow

# (str) Supported orientation (one of landscape, portrait or all)
orientation = portrait

# (str) Fullscreen mode (0 = not fullscreen)
fullscreen = 0


# --- ANDROID ---
android.api = 33
android.minapi = 24
android.activity_attributes = android:windowSoftInputMode="adjustResize"
android.ndk = 25b
android.archs = arm64-v8a,armeabi-v7a

# Permissões mínimas (INTERNET é essencial se você busca dados online)
android.permissions = INTERNET,POST_NOTIFICATIONS,FOREGROUND_SERVICE,WAKE_LOCK
android.foreground_service_type = dataSync

# ✅ evita prompt interativo de licença no GitHub Actions
android.accept_sdk_license = True
