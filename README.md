# Tibia Tools (Android) - Utilities + Foreground Monitor (Kivy)

Inclui:
- Favoritos (até 10) + monitor por Foreground Service (notifica mesmo com app fechado)
- Aba Utilidades:
  1) Calculadora de Blessings (custos configuráveis)
  2) Onde está o Rashid + contagem do Server Save (10:00 CET/CEST)
  3) Calculadora de Stamina (offline para 39:00 / 42:00 / meta)

## Build (WSL2/Ubuntu)
```bash
sudo apt update
sudo apt install -y python3 python3-pip git zip unzip openjdk-17-jdk \
  build-essential autoconf automake libtool pkg-config \
  libssl-dev libffi-dev libltdl-dev \
  libncurses5-dev libncursesw5-dev zlib1g-dev \
  libbz2-dev libreadline-dev libsqlite3-dev
python3 -m pip install --upgrade pip
python3 -m pip install buildozer cython==0.29.36
buildozer -v android debug
```

## Observações importantes (Android)
- “Menor delay possível” em background = **Foreground Service** (ícone fixo na notificação).
- Se o usuário desativar notificações/otimização de bateria, o Android pode limitar.
- Os custos de blessings mudam ao longo do tempo; por isso, a calculadora permite editar os valores base/incremento.
