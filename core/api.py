"""HTTP helpers + aliases de compatibilidade.

Este módulo existe para evitar que mudanças de nome quebrem o app no Android.
A UI (main.py) usa principalmente:
- fetch_character_tibiadata  -> JSON completo da TibiaData v4
- fetch_worlds_tibiadata     -> JSON completo da lista de mundos

Também expomos:
- fetch_character_snapshot   -> snapshot leve (para service/monitor)
- is_character_online_tibiadata -> fallback para status Online/Offline via /v4/world/{world}
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import re
import time
import html as _html
from urllib.parse import quote, quote_plus

import requests
from bs4 import BeautifulSoup


# TibiaData v4
WORLDS_URL = "https://api.tibiadata.com/v4/worlds"
CHAR_URL = "https://api.tibiadata.com/v4/character/{name}"
WORLD_URL = "https://api.tibiadata.com/v4/world/{world}"

# GuildStats (fansite) – usado apenas para complementar informações (ex: xp lost em mortes)
GUILDSTATS_DEATHS_URL = "https://guildstats.eu/character?nick={name}&tab=5"

# GuildStats (fansite) – histórico de experiência (tab=9)
GUILDSTATS_EXP_URL = "https://guildstats.eu/character?nick={name}&tab=9"

# Tibia.com (oficial) – fallback extra para detectar ONLINE
# Preferimos a página do personagem (não é paginada como a lista do world).
TIBIA_CHAR_URL = "https://www.tibia.com/community/?subtopic=characters&name={name}"

# Alguns sites (principalmente fansites) podem bloquear user-agent genérico.
# Usamos um UA de navegador comum para reduzir falsos negativos.
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 13; Mobile) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Mobile Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
}


def _get_json(url: str, timeout: int) -> Dict[str, Any]:
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=timeout, headers=UA)
            # Alguns endpoints podem devolver 5xx temporariamente
            if int(getattr(r, "status_code", 0) or 0) >= 500:
                raise requests.HTTPError(f"HTTP {r.status_code}", response=r)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_exc = e
            if attempt < 2:
                time.sleep(0.6 * (2 ** attempt))
            continue
    if last_exc:
        raise last_exc
    return {}


def _get_text(url: str, timeout: int, headers: Optional[dict] = None) -> str:
    """GET com retry básico (evita falhas temporárias)"""
    hdr = headers or UA
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=timeout, headers=hdr)
            if int(getattr(r, "status_code", 0) or 0) >= 500:
                raise requests.HTTPError(f"HTTP {r.status_code}", response=r)
            if r.status_code != 200:
                return ""
            return r.text or ""
        except Exception as e:
            last_exc = e
            if attempt < 2:
                time.sleep(0.6 * (2 ** attempt))
            continue
    _ = last_exc
    return ""


def fetch_worlds_tibiadata(timeout: int = 12) -> Dict[str, Any]:
    """JSON completo do endpoint /v4/worlds."""
    return _get_json(WORLDS_URL, timeout)


# Compat: alguns lugares antigos chamavam fetch_worlds()
def fetch_worlds(timeout: int = 12) -> List[str]:
    """Lista simples de nomes de worlds (compat)."""
    data = fetch_worlds_tibiadata(timeout=timeout)
    worlds = data.get("worlds", {}).get("regular_worlds", []) or []
    out: List[str] = []
    for w in worlds:
        if isinstance(w, dict) and w.get("name"):
            out.append(str(w["name"]))
    return out


def fetch_character_tibiadata(name: str, timeout: int = 12) -> Dict[str, Any]:
    """JSON completo do endpoint /v4/character/{name}."""
    safe_name = quote(name)
    return _get_json(CHAR_URL.format(name=safe_name), timeout)


def fetch_character_snapshot(name: str, timeout: int = 12) -> Dict[str, Any]:
    """Snapshot leve (compat).

    Mantemos a assinatura para evitar quebrar código antigo. Hoje, retorna um
    subconjunto do /v4/character.
    """
    data = fetch_character_tibiadata(name=name, timeout=timeout)
    ch = (
        data.get("character", {})
        .get("character", {})
        or {}
    )
    return {
        "name": ch.get("name"),
        "world": ch.get("world"),
        "level": ch.get("level"),
        "vocation": ch.get("vocation"),
        "status": ch.get("status"),
        "url": f"https://www.tibia.com/community/?subtopic=characters&name={quote(name)}",
    }


def is_character_online_tibiadata(name: str, world: Optional[str] = None, timeout: int = 12) -> Optional[bool]:
    """
    Retorna:
      - True  -> online
      - False -> offline
      - None  -> falha (para permitir fallback em outro método)

    Se world não for informado, usa o endpoint do personagem (que já traz status).
    """
    try:
        # Sem world: endpoint do personagem (melhor para Favoritos)
        if not world:
            data = fetch_character_tibiadata(name, timeout=timeout)
            status = None
            if isinstance(data, dict):
                char_block = data.get("character")
                if isinstance(char_block, dict):
                    inner = char_block.get("character") if isinstance(char_block.get("character"), dict) else char_block
                    if isinstance(inner, dict):
                        status = inner.get("status") or inner.get("state") or inner.get("online_status")
            if isinstance(status, str):
                st = status.strip().lower()
                if st == "online":
                    return True
                if st == "offline":
                    return False
            # Sem status: assume offline (sem "desconhecido" na UI)
            return False

        # Com world: checa lista de online players do mundo
        safe_world = quote(str(world).strip())
        url = f"https://api.tibiadata.com/v4/world/{safe_world}"
        data = _get_json(url, timeout=timeout)

        world_block = (data or {}).get("world", {}) if isinstance(data, dict) else {}
        players = None
        if isinstance(world_block, dict):
            players = world_block.get("online_players") or world_block.get("players_online") or world_block.get("players")
            if isinstance(players, dict):
                players = players.get("online_players") or players.get("players") or players.get("data")
        if not players or not isinstance(players, list):
            return False

        target = name.strip().lower()
        for p in players:
            if isinstance(p, dict):
                pname = p.get("name") or p.get("player_name")
            else:
                pname = p
            if isinstance(pname, str) and pname.strip().lower() == target:
                return True
        return False
    except Exception:
        return None

def is_character_online_tibia_com(name: str, world: str, timeout: int = 12, *, light_only: bool = False) -> Optional[bool]:
    """Fallback extra usando o site oficial (tibia.com) para checar se o char está online.

    Importante: NÃO usamos a página do world porque é paginada (pode dar falso OFFLINE).

    Retorna:
    - True/False se conseguimos checar
    - None se houve erro/parsing falhou
    """
    _ = world  # mantemos o parâmetro por compatibilidade
    try:
        safe_name = quote_plus(str(name))
        url = TIBIA_CHAR_URL.format(name=safe_name)
        html = _get_text(url, timeout=timeout, headers=UA)
        if not html:
            return None
        # Fast path: tenta achar o Status via regex (evita BeautifulSoup e reduz uso de CPU/GIL no Android)
        try:
            m = re.search(r"status:</td>\s*<td[^>]*>\s*(online|offline)\s*<", html, flags=re.I)
            if m:
                return m.group(1).strip().lower() == "online"
        except Exception:
            pass

        if light_only:
            return None

        soup = BeautifulSoup(html, "html.parser")
        # A página do char tem uma tabela com linhas "Label" / "Value".
        for tr in soup.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 2:
                continue
            k = (tds[0].get_text(" ", strip=True) or "").strip().rstrip(":").strip().lower()
            if k != "status":
                continue
            v = (tds[1].get_text(" ", strip=True) or "").strip().lower()
            if "online" in v:
                return True
            if "offline" in v:
                return False
            return None

        return None
    except Exception:
        return None


def fetch_guildstats_deaths_xp(name: str, timeout: int = 12, *, light_only: bool = False) -> List[str]:
    """Retorna a lista de 'Exp lost' (strings) do GuildStats, em ordem (mais recente primeiro).

    Observação: é um complemento (fansite). Se falhar, devolve lista vazia.
    """
    try:
        # Em query-string, preferimos + para espaços.
        safe = quote_plus(name)
        base_url = GUILDSTATS_DEATHS_URL.format(name=safe)

        def fetch_html(u: str) -> str:
            try:
                return _get_text(u, timeout=timeout, headers=UA)
            except Exception:
                return ""

        # Alguns ambientes/rotas podem variar por linguagem; tentamos algumas opções.
        html = ""
        for u in (base_url, base_url + "&lang=pt", base_url + "&lang=en"):
            html = fetch_html(u)
            if html:
                break
        if not html:
            return []

        # Alguns chars não têm a lista atualizada (GuildStats mostra uma mensagem e não renderiza tabela).
        if "death list is not updated" in html.lower():
            return []

        # Fast path: tenta extrair a coluna "Exp lost" via regex (sem BeautifulSoup) — bem mais leve no Android
        try:
            low = html.lower()
            if "exp lost" in low:
                pos = low.find("exp lost")
                table_start = low.rfind("<table", 0, pos)
                table_end = low.find("</table>", pos)
                chunk = ""
                if table_start != -1 and table_end != -1 and table_end > table_start:
                    chunk = html[table_start:table_end]
                else:
                    chunk = html[pos:pos + 20000]  # limite defensivo

                vals: List[str] = []
                for m1 in re.finditer(r"<td[^>]*>\s*(-\s*[\d\.,]+)\s*</td>", chunk, flags=re.I):
                    raw = (m1.group(1) or "").strip()
                    digits = re.findall(r"\d+", raw)
                    if not digits:
                        continue
                    num = int("".join(digits))
                    if num < 10_000:
                        continue
                    vals.append(f"-{num:,}")
                if vals:
                    return vals
        except Exception:
            pass

        if light_only:
            return []

        soup = BeautifulSoup(html, "html.parser")

        def norm(s: str) -> str:
            return re.sub(r"\s+", " ", (s or "").strip()).lower()

        # Procurar a tabela correta de forma robusta:
        # - achar uma linha de header (<tr> com <th>) que tenha uma coluna contendo "Exp lost"
        # - capturar o índice dessa coluna
        best = None  # (table, exp_idx, score)
        for table in soup.find_all("table"):
            header_tr = None
            for tr in table.find_all("tr"):
                ths = tr.find_all("th")
                if ths:
                    header_tr = tr
                    break
            if not header_tr:
                continue

            headers = [norm(th.get_text(" ", strip=True)) for th in header_tr.find_all("th")]
            if not headers:
                continue

            exp_idx = None
            for i, h in enumerate(headers):
                if "exp" in h and "lost" in h:
                    exp_idx = i
                    break
            if exp_idx is None:
                continue

            # heurística extra: a tabela de mortes também tem "lvl" e/ou "morto"/"killed"/"when"
            score = 0
            joined = " ".join(headers)
            if "lvl" in joined or "level" in joined:
                score += 1
            if "quando" in joined or "when" in joined:
                score += 1
            if "morto" in joined or "killed" in joined:
                score += 1

            if best is None or score > best[2]:
                best = (table, exp_idx, score)

        if not best:
            return []

        table, exp_idx, _score = best

        out: List[str] = []
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if not tds:
                continue
            if exp_idx >= len(tds):
                continue
            xp = tds[exp_idx].get_text(" ", strip=True)
            xp = re.sub(r"\s+", " ", xp).strip()
            # filtra linhas que não parecem valor (cabeçalhos/colunas vazias)
            if not xp:
                continue
            out.append(xp)

        # Normalmente a primeira linha é a mais recente; mantemos a ordem.
        return out
    except Exception:
        return []


def fetch_guildstats_exp_changes(name: str, timeout: int = 12, *, light_only: bool = False) -> List[Dict[str, Any]]:
    """Retorna o histórico (diário) de experiência do GuildStats (tab=9).

    Saída (ordem conforme a tabela):
      [{"date": "YYYY-MM-DD", "exp_change": "+33,820,426", "exp_change_int": 33820426}, ...]

    Observação: é um complemento (fansite). Se falhar, devolve lista vazia.
    """
    try:
        # O GuildStats é um fansite e pode variar o HTML (às vezes sem <th> no cabeçalho).
        # Aqui tentamos ser tolerantes: buscamos a tabela "Date / Exp change" por padrão de linhas,
        # não apenas por texto do cabeçalho.

        # Alguns chars só respondem bem com %20 (quote) em vez de + (quote_plus).
        enc_quote = quote(name, safe="")
        enc_plus = quote_plus(name)

        url_variants = [
            GUILDSTATS_EXP_URL.format(name=enc_quote),
            GUILDSTATS_EXP_URL.format(name=enc_plus),
        ]

        # headers um pouco mais "browser-like" para reduzir bloqueios.
        headers = dict(UA)
        headers.update({
            "Referer": "https://guildstats.eu/",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        })

        def fetch_html(u: str) -> str:
            try:
                txt = _get_text(u, timeout=timeout, headers=headers)
                if not txt:
                    return ""
                # Detecta páginas de bloqueio/anti-bot (para não tentar parsear "lixo").
                low = txt.lower()
                block_markers = (
                    'checking your browser',
                    'just a moment',
                    'cf-browser-verification',
                    'attention required',
                    'verify you are human',
                    'enable javascript',
                )
                if any(m in low for m in block_markers):
                    return ''
                return txt
            except Exception:
                return ""

        html = ""
        # Tenta sem idioma e com pt/en (algumas páginas mudam layout/texto com lang)
        for base_url in url_variants:
            for u in (base_url, base_url + "&lang=pt", base_url + "&lang=en"):
                html = fetch_html(u)
                if html:
                    break
            if html:
                break

        if not html:
            return []

        # Fast path: tenta extrair a tabela via regex (sem BeautifulSoup) — bem mais leve no Android
        # (robusto: não assume que Date/Exp são sempre as colunas 0/1)
        try:
            def _parse_exp_to_int_fast(s: str) -> Optional[int]:
                txt = (s or "").strip()
                if not txt:
                    return None
                t = txt.replace(" ", " ")
                m0 = re.search(r"([+-])?\s*(\d[\d\s,\.]*)", t)
                if not m0:
                    return None
                sign_ch = m0.group(1)
                digits = re.findall(r"\d+", m0.group(2) or "")
                if not digits:
                    return None
                num = int("".join(digits))
                return -num if sign_ch == "-" else num

            # Datas: ISO (YYYY-MM-DD) e DMY (DD.MM.YYYY / DD/MM/YYYY / DD-MM-YYYY)
            iso_re = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
            dmy_re = re.compile(r"\b(\d{2})[./-](\d{2})[./-](\d{4})\b")

            def _extract_date_iso(s: str) -> Optional[str]:
                txt = (s or "").strip()
                m = iso_re.search(txt)
                if m:
                    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
                m = dmy_re.search(txt)
                if m:
                    dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
                    return f"{yyyy}-{mm}-{dd}"
                return None

            def _strip_tags(s: str) -> str:
                t = s or ""
                # remove blocos grandes que só atrapalham
                t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", t)
                t = re.sub(r"(?is)<[^>]+>", " ", t)
                try:
                    t = _html.unescape(t)
                except Exception:
                    pass
                t = t.replace(" ", " ")
                t = re.sub(r"\s+", " ", t).strip()
                return t

            def _parse_rows(fragment: str) -> List[Dict[str, Any]]:
                rows: List[Dict[str, Any]] = []
                seen_dates = set()

                for mtr in re.finditer(r"(?is)<tr[^>]*>.*?</tr>", fragment or ""):
                    tr_html = mtr.group(0) or ""
                    tds = re.findall(r"(?is)<td[^>]*>.*?</td>", tr_html)
                    if len(tds) < 2:
                        continue

                    cells = [_strip_tags(td) for td in tds]

                    date_iso = None
                    for c in cells:
                        date_iso = _extract_date_iso(c)
                        if date_iso:
                            break

                    if not date_iso or date_iso in seen_dates:
                        continue

                    candidates = []
                    for c in cells:
                        exp_int = _parse_exp_to_int_fast(c)
                        if exp_int is None:
                            continue
                        # evita pegar colunas pequenas (lvl/rank)
                        if abs(int(exp_int)) not in (0,) and abs(int(exp_int)) < 10_000:
                            continue
                        has_sign = bool(re.search(r"^\s*[+-]", c))
                        candidates.append((1 if has_sign else 0, abs(int(exp_int)), c, int(exp_int)))

                    if not candidates:
                        continue

                    # Escolha do "Exp change":
                    # 1) se houver valor com +/-, ele quase sempre é o delta
                    # 2) se não houver, mas houver 0, preferimos 0 (evita pegar "Total experience")
                    # 3) senão, pega o menor valor absoluto (delta costuma ser menor que o total)
                    signed = [x for x in candidates if x[0] == 1]
                    if signed:
                        best = max(signed, key=lambda x: x[1])
                    else:
                        zeros = [x for x in candidates if x[3] == 0]
                        if zeros:
                            best = zeros[0]
                        else:
                            best = min(candidates, key=lambda x: x[1])

                    _sgn, _abs, exp_txt, exp_int = best
                    seen_dates.add(date_iso)
                    rows.append({
                        'date': date_iso,
                        'exp_change': exp_txt,
                        'exp_change_int': int(exp_int),
                    })

                return rows

            def _extract_best_table_fragment(html_full: str) -> str:
                best = ""
                best_score = 0
                for mt in re.finditer(r"(?is)<table[^>]*>.*?</table>", html_full or ""):
                    chunk = mt.group(0) or ""
                    score = len(iso_re.findall(chunk)) + len(dmy_re.findall(chunk))
                    if score > best_score:
                        best_score = score
                        best = chunk
                return best if best_score >= 3 else ""

            fast_rows = _parse_rows(html)
            if len(fast_rows) < 3:
                frag = _extract_best_table_fragment(html)
                if frag:
                    alt = _parse_rows(frag)
                    if len(alt) > len(fast_rows):
                        fast_rows = alt

            if len(fast_rows) >= 3:
                return fast_rows
            if light_only and fast_rows:
                return fast_rows
        except Exception:
            pass

        if light_only:
            return []

        soup = BeautifulSoup(html, "html.parser")

        def parse_exp_to_int(s: str) -> Optional[int]:
            # exemplos: "+33,820,426" | "-55,947,218" | "0" | "+200,710,181 👍"
            txt = (s or "").strip()
            if not txt:
                return None
            # Normaliza NBSP e tenta achar um número.
            t = txt.replace("\u00a0", " ")
            # pega primeiro bloco numérico e sinal se existir no começo
            m = re.search(r"([+-])?\s*(\d[\d\s,\.]*)", t)
            if not m:
                return None
            sign_ch = m.group(1)
            digits = re.findall(r"\d+", m.group(2) or "")
            if not digits:
                return None
            num = int("".join(digits))
            return -num if sign_ch == "-" else num

        date_re = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")

        # Tenta um parsing simples (col0=data, col1=exp_change) percorrendo todos os <tr>.
        # Isso cobre variações em que a tabela não tem <th> ou muda de classe/estrutura.
        fast_rows: List[Dict[str, Any]] = []
        seen_dates = set()
        for tr in soup.find_all('tr'):
            tds = tr.find_all('td')
            if len(tds) < 2:
                continue
            dtext = re.sub(r'\s+', ' ', (tds[0].get_text(' ', strip=True) or '')).strip()
            mdate = date_re.search(dtext)
            if not mdate:
                continue
            date_iso = mdate.group(1)
            etext = re.sub(r'\s+', ' ', (tds[1].get_text(' ', strip=True) or '')).strip()
            exp_int = parse_exp_to_int(etext)
            if exp_int is None:
                continue
            # evita pegar colunas pequenas (rank/lvl) por engano
            if abs(int(exp_int)) not in (0,) and abs(int(exp_int)) < 10_000:
                continue
            if date_iso in seen_dates:
                continue
            seen_dates.add(date_iso)
            fast_rows.append({
                'date': date_iso,
                'exp_change': etext,
                'exp_change_int': int(exp_int),
            })

        if len(fast_rows) >= 3:
            return fast_rows

        # Heurística robusta: escolhe a tabela em que muitas linhas possuem uma data ISO
        # e alguma coluna com valores grandes e frequentemente prefixados com +/-. 
        best = None  # (table, date_idx, exp_idx, score)

        for table in soup.find_all("table"):
            rows = []
            max_cols = 0
            for tr in table.find_all("tr"):
                cells = tr.find_all(["td", "th"])
                if not cells:
                    continue
                row = [re.sub(r"\s+", " ", (c.get_text(" ", strip=True) or "")).strip() for c in cells]
                if not row:
                    continue
                rows.append(row)
                max_cols = max(max_cols, len(row))

            if not rows or max_cols < 2:
                continue

            # normaliza linhas para mesmo tamanho
            norm_rows = [r + [""] * (max_cols - len(r)) for r in rows]

            # conta datas por coluna
            date_counts = [0] * max_cols
            for r in norm_rows:
                for ci, v in enumerate(r):
                    if date_re.search(v or ""):
                        date_counts[ci] += 1

            date_idx = max(range(max_cols), key=lambda i: date_counts[i])
            # Alguns chars podem ter poucos registros (tracking recente).
            if date_counts[date_idx] < 3:
                continue

            # pontua colunas de EXP
            col_scores = []
            for ci in range(max_cols):
                if ci == date_idx:
                    col_scores.append((-1, ci))
                    continue
                exp_count = 0
                plusminus = 0
                abs_sum = 0
                max_abs = 0
                zero_count = 0
                for r in norm_rows:
                    if not date_re.search(r[date_idx] or ""):
                        continue
                    v = (r[ci] or "").strip()
                    if not v:
                        continue
                    exp_int = parse_exp_to_int(v)
                    if exp_int is None:
                        continue
                    exp_count += 1
                    ai = abs(int(exp_int))
                    abs_sum += ai
                    max_abs = max(max_abs, ai)
                    if int(exp_int) == 0:
                        zero_count += 1
                    if v.lstrip().startswith(("+", "-")):
                        plusminus += 1

                if exp_count < 3:
                    col_scores.append((-1, ci))
                    continue

                avg_abs = abs_sum / float(exp_count) if exp_count else 0.0

                # Evita confundir com colunas pequenas (lvl/rank) — normalmente exp change tem valores grandes,
                # mas também pode ter muitos "0". A coluna "Experience" (total) tem valores enormes e SEM +/-. 
                if plusminus > 0:
                    if avg_abs < 10_000:
                        col_scores.append((-1, ci))
                        continue
                    # score: +/− domina completamente (senão a coluna "Experience" ganha pelo tamanho).
                    score = (plusminus * 1_000_000) + (exp_count * 1000) + min(avg_abs, 1_000_000_000) / 1_000_000_000
                else:
                    # Sem sinais: aceitaremos apenas se os valores não forem absurdamente grandes
                    # (para não pegar a coluna "Experience"). Também damos bônus se for muito "0".
                    if max_abs > 5_000_000:
                        col_scores.append((-1, ci))
                        continue
                    zero_ratio = (zero_count / float(exp_count)) if exp_count else 0.0
                    score = (exp_count * 1000) + (zero_ratio * 500) + (5_000_000 - max_abs) / 10_000
                col_scores.append((score, ci))

            best_col = max(col_scores, key=lambda x: x[0])
            if best_col[0] < 0:
                continue
            exp_idx = best_col[1]

            table_score = date_counts[date_idx] + best_col[0]
            if best is None or table_score > best[3]:
                best = (table, date_idx, exp_idx, table_score)

        if not best:
            return []

        table, date_idx, exp_idx, _score = best

        out: List[Dict[str, Any]] = []
        for tr in table.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if not cells:
                continue
            vals = [re.sub(r"\s+", " ", (c.get_text(" ", strip=True) or "")).strip() for c in cells]
            if date_idx >= len(vals) or exp_idx >= len(vals):
                continue

            date_txt = vals[date_idx]
            exp_txt = vals[exp_idx]
            if not date_txt or not exp_txt:
                continue

            m = date_re.search(date_txt)
            if not m:
                continue
            date_iso = m.group(1)

            exp_int = parse_exp_to_int(exp_txt)
            if exp_int is None:
                continue

            out.append({
                "date": date_iso,
                "exp_change": exp_txt,
                "exp_change_int": int(exp_int),
            })

        return out
    except Exception:
        return []


__all__ = [
    "fetch_worlds",
    "fetch_worlds_tibiadata",
    "fetch_character_snapshot",
    "fetch_character_tibiadata",
    "is_character_online_tibiadata",
    "is_character_online_tibia_com",
    "fetch_guildstats_deaths_xp",
    "fetch_guildstats_exp_changes",
]
