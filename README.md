# Tibia Tools (Android)

App de utilidades para **Tibia** feito em **Kivy + KivyMD**, pensado para rodar no Android e ser fácil de compilar via **GitHub Actions**.

> Projeto não-oficial / sem afiliação com CipSoft, Tibia.com, TibiaWiki ou ExevoPan.

---

## 📱 Funcionalidades

### Aba **Char**
- **Busca de personagem** (nome) usando **TibiaData v4**
  - mostra informações principais do personagem na tela (ex.: world, vocation, level e status quando disponível).
- **Abrir no Tibia.com** (link direto do personagem).
- **Favoritar** o personagem (para aparecer na aba Favoritos).
- **Calculadora de Shared XP**
  - informa o range de level que pode fazer party share (⌈2/3⌉ até ⌊3/2⌋ do seu level).

### Aba **Favoritos**
- Lista dos personagens favoritados.
- Ao tocar em um favorito:
  - **ABRIR** no Tibia.com
  - **REMOVER** da lista

### Aba **Mais**

#### 🗡️ Bosses (ExevoPan)
- Seleção de **World** + botão **Buscar Bosses**.
- Mostra a lista de bosses e a chance/indicador retornado pelo ExevoPan.
- Ao tocar no nome do boss:
  - aparece um **diálogo de confirmação** perguntando se você quer abrir a página do boss
  - ao confirmar, abre a página no **TibiaWiki (BR)** no navegador.

#### ⭐ Boosted
- Mostra:
  - **Boosted Creature**
  - **Boosted Boss**
- Botão **refresh** para atualizar (fonte: TibiaData v4).

#### 🏋️ Treino (Exercise)
Calculadora para treino com **exercise weapons**:
- Escolha do **tipo de skill** (melee / distance / shielding / magic / fist)
- Escolha da **vocation**
- Escolha da **arma de treino** (Standard / Enhanced / Lasting)
- Informa estimativas de:
  - charges/quantidade necessária
  - custo aproximado em gp
  - resumo do resultado

> As fórmulas são aproximações usadas por calculadoras populares (dummy / exercise). Use como referência.

#### ⚡ Imbuements (offline)
- Lista e busca de **Imbuements** (ex.: Vampirism, Strike…).
- Toque em um imbuement para ver detalhes por tier:
  - **Basic / Intricate / Powerful**
  - efeito + itens necessários
- **Offline-first** (sem 403):
  - os dados vêm de um **seed embutido no APK**: `core/data/imbuements_seed.json`
  - na primeira execução, o app salva um **cache local** e passa a usar ele.

**Atualizar o seed (para quem mantém o repo):**
- Script: `tools/update_imbuements_seed.py`
- Ele baixa/atualiza o `core/data/imbuements_seed.json` antes de compilar uma nova versão.

#### ⏳ Stamina
Calculadora de stamina offline:
- Você informa:
  - **stamina atual** (hh:mm)
  - **stamina desejada** (hh:mm)
- O app calcula:
  - **quanto tempo ficar offline**
  - **em qual horário** você atinge a stamina alvo (considerando que você desloga “agora”)

Regras consideradas:
- Regeneração começa **após 10 min offline**
- Até **39:00**: +1 min stamina a cada **3 min offline**
- De **39:00 → 42:00**: +1 min stamina a cada **6 min offline**

#### 📊 Hunt Analyzer
- Cole o texto da sessão (Hunt Session) e o app extrai e formata:
  - **Loot**
  - **Supplies**
  - **Balance**

---

## 🧩 Estrutura do projeto

- `main.py` — UI + navegação + handlers
- `tibia_tools.kv` — layout KivyMD
- `core/` — lógica por módulo (bosses, boosted, imbuements, stamina, training, hunt…)
- `assets/` — ícone e presplash
- `.github/workflows/android.yml` — build do APK via GitHub Actions
- `buildozer.spec` — configuração do Buildozer

---

## 🛠️ Build pelo GitHub (recomendado)

O workflow **Build Android APK (Kivy/Buildozer)** roda:
- automaticamente em push na branch `main`
- manualmente em **Actions → Run workflow**

Ele gera o APK como **artifact** do workflow.

---

## 🧪 Build local (Linux / WSL2)

Pré-requisitos (exemplo):
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

---

## 🎨 Presplash / Ícone

- Ícone: `assets/icon.png`
- Presplash: `assets/presplash.png`

No `buildozer.spec`:
```ini
icon.filename = assets/icon.png
presplash.filename = assets/presplash.png
android.presplash_color = #000000
```

---

## ⚠️ Observações
- Para buscar dados online (char/boosted/bosses), o app precisa de **INTERNET**.
- Imbuements foi desenhado para funcionar **offline** (seed embutido + cache).
- Sem licença definida no momento (uso pessoal/guild). Se quiser, você pode adicionar uma licença (ex.: MIT).

---

## 👤 Créditos
- **Erick Bandeira (Monk Curandeiro)** — idealização, especificação, testes e manutenção do projeto para uso na guild.

## 📌 Fontes de dados
- TibiaData API (personagem/boosted)
- ExevoPan (lista de bosses por world)
- TibiaWiki (páginas de bosses + referência de imbuements)
