[app]

# (str) Title of your application
title = Tibia Tools

# (str) Package name
# Splash screen (pre-splash)
#
# If the app is crashing immediately on some Android 14/15 devices with:
#   FORTIFY: pthread_mutex_lock called on a destroyed mutex
# and the crash thread name is `hwuiTask0/1` (Android UI renderer),
# a common workaround is to DISABLE the pre-splash (it uses HWUI to render).
#
# Try one of these options:
#   (A) disable the pre-splash entirely (comment the two lines below)
#   (B) replace assets/presplash.png with a small 512x512 power-of-two image
#       (Buildozer recommends power-of-two sizes for pre-splash images)
#
# android.presplash_color = #000000
icon.filename = assets/icon.png
presplash.color = #222222
presplash.filename = %(source.dir)s/assets/presplash.png
package.name = tibiatools

# (str) Package domain (needed for android/ios packaging)
package.domain = org.erick

# (str) Source code where the main.py live
source.dir = .

# Background service (monitor favorites)
# Roda como serviço em primeiro plano (foreground) para enviar notificações
# mesmo com o app fechado.
services = favwatch:service/main.py

# (list) Source files to include (let empty to include all the files)
source.include_exts = py,kv,png,jpg,jpeg,txt,json,ttf,atlas,ico

# (str) Application versioning (method 1)
version = 0.1.0

# (list) Application requirements
# ✅ trava o KivyMD na versão compatível com MDBottomNavigation etc.
# ✅ fixa versões estáveis pra evitar quebra no GitHub Actions/p4a
#    (no log: Kivy 2.3.0 falhou ao compilar no armeabi-v7a por falta dos .c gerados)
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

# Use a newer python-for-android (p4a) checkout when building.
# This can help with device/OS-specific native crashes on newer Android versions.
# If it causes build issues in your environment, remove these 2 lines.
p4a.branch = master
# p4a.commit = <optional specific commit SHA>

# Permissões mínimas (INTERNET é essencial se você busca dados online)
android.permissions = INTERNET, POST_NOTIFICATIONS, FOREGROUND_SERVICE, WAKE_LOCK
# Tipo de foreground service (ajuda em Androids mais novos/OEMs). Como o serviço
# faz polling de rede, dataSync é o mais apropriado.
android.foreground_service_type = dataSync

# ✅ evita prompt interativo de licença no GitHub Actions
android.accept_sdk_license = True