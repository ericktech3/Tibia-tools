# Tibia Tools (Android)

App de utilidades para **Tibia** feito em **Kivy + KivyMD**, pensado para rodar no Android e ser fácil de compilar via **GitHub Actions**.

> Projeto não-oficial / sem afiliação com CipSoft, Tibia.com, TibiaWiki ou ExevoPan.

---

## 📱 Funcionalidades

### 🔎 Busca de personagem
- Consulta dados do personagem via **TibiaData API**
- Exibe status **ONLINE/OFFLINE** de forma mais confiável (quando possível) usando a lista de players online do **world**
- Mostra **Outros personagens visíveis na conta** (se o dono do personagem permitir no Tibia.com)
  - Toque em um nome para buscar automaticamente

### ⭐ Favoritos + Monitor em segundo plano
- Adicione personagens aos favoritos
- **Monitoramento em segundo plano** (Foreground Service com notificação fixa — exigência do Android)
- Notificações quando:
  - personagem fica online/offline
  - mudanças relevantes detectadas (dependendo das opções)
- Intervalo configurável (padrão recomendado: **30s**)


### 📈 XP / Histórico (quando disponível)
- Exibe informações de XP/histórico quando a fonte estiver acessível
- Se a fonte de histórico estiver bloqueada/indisponível (anti-bot), o app não trava: apenas não preenche os dados extras
---

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

## 📲 Instalação (usuário final)

- Baixe o APK (quando publicado) e instale no Android.
- No Android 13+ (API 33+), conceda permissão de **Notificações** para o monitor funcionar bem.

> Dica: se seu Android for agressivo com bateria (Xiaomi/Realme/Samsung), desative otimizações de bateria para o app para evitar que o sistema mate o serviço.

---

## ⚙️ Configurações importantes

Dentro do app (Configurações):
- ✅ **Monitorar favoritos**: mantém o serviço rodando em segundo plano
- ✅ **Iniciar automaticamente ao ligar** *(se habilitado no projeto)*: reinicia o serviço após reboot (depende do receiver)
- ⏱️ **Intervalo de verificação**: recomendado **30s** para “offline há X” ficar bem preciso

### Sobre “Offline há X”
O tempo “Offline há X” é calculado com base no instante em que o **monitor detecta a transição ONLINE → OFFLINE** (mais fiel ao logout real), e não por “Last Login”.

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
