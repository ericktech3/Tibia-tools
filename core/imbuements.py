# -*- coding: utf-8 -*-
"""
Imbuements (TibiaWiki BR) — modo robusto + cache offline

Motivação:
- O TibiaWiki pode retornar 403 para requisições "de app" (requests/urllib).
- Para evitar quebrar a aba, usamos:
  1) cache local (user_data_dir) -> funciona offline depois do 1º sucesso
  2) múltiplas URLs (HTML com <pre> e action=raw)
  3) fallback via r.jina.ai (proxy de leitura) quando o TibiaWiki bloquear

Fonte base do dataset (quando acessível):
- https://www.tibiawiki.com.br/wiki/Tibia_Wiki:Imbuements/json
"""

from __future__ import annotations

import json
import os
import re
import html as _html
from typing import Any, Dict, List, Tuple

import requests


# Preferimos a página /wiki (HTML com <pre>), pois action=raw costuma dar 403 em alguns ambientes.
_TIBIAWIKI_JSON_PAGE = "https://www.tibiawiki.com.br/wiki/Tibia_Wiki%3AImbuements/json"
_TIBIAWIKI_JSON_RAW = "https://www.tibiawiki.com.br/index.php?title=Tibia_Wiki:Imbuements/json&action=raw"

# Fallback "reader/proxy" (r.jina.ai) — evita muitos bloqueios de WAF/UA.
# Ex.: https://r.jina.ai/https://example.com
def _jina(url: str) -> str:
    return "https://r.jina.ai/" + url.lstrip("/")


TRY_URLS = [
    _TIBIAWIKI_JSON_PAGE,
    _TIBIAWIKI_JSON_RAW,
    _jina(_TIBIAWIKI_JSON_PAGE),
    _jina(_TIBIAWIKI_JSON_RAW),
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 12; Mobile) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Mobile Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.tibiawiki.com.br/",
    "Connection": "keep-alive",
}

_CACHE_FILENAME = "imbuements_cache_tibiawiki.json"


def _cache_path() -> str | None:
    """
    Retorna um caminho gravável (Android/Desktop) para cache do JSON.
    """
    try:
        from kivy.app import App  # import lazy (evita crash no import do módulo)
        app = App.get_running_app()
        if app and getattr(app, "user_data_dir", None):
            return os.path.join(app.user_data_dir, _CACHE_FILENAME)
    except Exception:
        pass
    return None


def _read_cache() -> Dict[str, Any] | None:
    path = _cache_path()
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data:
            return data
    except Exception:
        return None
    return None


def _write_cache(data: Dict[str, Any]) -> None:
    path = _cache_path()
    if not path:
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        # cache é best-effort; nunca pode quebrar a tela
        pass


def _extract_json_blob(text: str) -> str:
    """
    Extrai um blob JSON do texto:
    - raw JSON
    - HTML com <pre>...JSON...</pre>
    - texto do r.jina.ai (normalmente inclui o JSON inteiro)
    """
    if not text:
        raise ValueError("Resposta vazia")

    s = text.strip()

    # Caso 1: já é JSON puro
    if s.startswith("{") and s.rstrip().endswith("}"):
        return s

    # Caso 2: HTML com <pre>
    m = re.search(r"<pre[^>]*>(.*?)</pre>", text, flags=re.IGNORECASE | re.DOTALL)
    if m:
        blob = _html.unescape(m.group(1)).strip()
        if blob.startswith("{") and blob.rstrip().endswith("}"):
            return blob

    # Caso 3: fallback — pega do primeiro { até o último }
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last != -1 and last > first:
        blob = text[first:last + 1].strip()
        return blob

    raise ValueError("Não foi possível localizar JSON na resposta")


def _fetch_remote_json(timeout: int = 25) -> Dict[str, Any]:
    """
    Baixa o JSON (dict) do TibiaWiki, tentando múltiplas URLs.
    """
    session = requests.Session()
    session.headers.update(_HEADERS)

    last_err: Exception | None = None
    for url in TRY_URLS:
        try:
            resp = session.get(url, timeout=timeout)
            # Alguns proxies retornam 200 com texto de erro; ainda assim tentamos parsear
            resp.raise_for_status()
            blob = _extract_json_blob(resp.text)
            data = json.loads(blob)
            if isinstance(data, dict) and data:
                return data
            last_err = ValueError(f"JSON inválido em {url}")
        except Exception as e:
            last_err = e
            continue

    raise last_err or RuntimeError("Falha ao buscar Imbuements")


def fetch_imbuements_table(force_refresh: bool = False) -> Tuple[bool, List[Dict[str, Any]]]:
    """
    Retorna (ok, lista_de_imbuements).
    A lista é normalizada para consumo da tela.

    - Se existir cache e force_refresh=False, usa o cache (offline).
    - Se cache não existir (ou force_refresh=True), tenta baixar e salva no cache.
    - Se falhar o download mas existir cache, usa cache.
    """
    # 1) cache primeiro (offline)
    if not force_refresh:
        cached = _read_cache()
        if cached:
            try:
                return True, _normalize_imbuements(cached)
            except Exception:
                # cache corrompido -> ignora e tenta rede
                pass

    # 2) rede
    try:
        raw = _fetch_remote_json()
        _write_cache(raw)
        return True, _normalize_imbuements(raw)
    except Exception as e:
        # 3) fallback: se cache existir, usa mesmo assim
        cached = _read_cache()
        if cached:
            try:
                return True, _normalize_imbuements(cached)
            except Exception:
                pass
        return False, [{"name": f"Erro: {str(e)}"}]


def _normalize_imbuements(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Converte o JSON do TibiaWiki para a estrutura usada no app.
    """
    entries: List[Dict[str, Any]] = []

    for key, info in raw.items():
        if not isinstance(info, dict):
            continue

        name = info.get("name") or key

        # description costuma ter "Basic: X\nIntricate: Y\nPowerful: Z"
        desc = info.get("description") or ""
        basic, intricate, powerful = _extract_tiers_from_description(desc)

        items = info.get("items") or {}
        # items pode vir em formatos diferentes; tentamos padronizar
        items_norm = _normalize_items(items)

        entries.append({
            "name": name,
            "basic": basic,
            "intricate": intricate,
            "powerful": powerful,
            "items": items_norm,
            "source": "TibiaWiki",
        })

    # ordena alfabeticamente
    entries.sort(key=lambda x: x.get("name", "").lower())
    return entries


def _extract_tiers_from_description(desc: str) -> Tuple[str, str, str]:
    basic = intricate = powerful = ""
    if not desc:
        return basic, intricate, powerful

    # tolera "Basic", "Intricate", "Powerful" com/sem dois pontos
    def _find(label: str) -> str:
        m = re.search(rf"{label}\s*:?\s*([^\n\r<]+)", desc, flags=re.IGNORECASE)
        return (m.group(1).strip() if m else "")

    basic = _find("Basic")
    intricate = _find("Intricate")
    powerful = _find("Powerful")
    return basic, intricate, powerful


def _normalize_items(items: Any) -> Dict[str, List[Dict[str, Any]]]:
    """
    Esperado pela UI: {"basic":[{"name":..,"qty":..},...], "intricate":[...], "powerful":[...]}
    """
    out: Dict[str, List[Dict[str, Any]]] = {"basic": [], "intricate": [], "powerful": []}

    if not items:
        return out

    # Caso 1: já vem no formato certo
    if isinstance(items, dict) and any(k in items for k in ("basic", "intricate", "powerful")):
        for tier in ("basic", "intricate", "powerful"):
            tier_items = items.get(tier) or []
            out[tier] = _as_item_list(tier_items)
        return out

    # Caso 2: vem como lista única ou dict "tier -> string"
    if isinstance(items, dict):
        # Ex: {"Basic":"25x ...", ...}
        for k, v in items.items():
            tier = k.strip().lower()
            if tier.startswith("basic"):
                out["basic"] = _as_item_list(v)
            elif tier.startswith("intricate"):
                out["intricate"] = _as_item_list(v)
            elif tier.startswith("powerful"):
                out["powerful"] = _as_item_list(v)
        return out

    # Caso 3: qualquer outra coisa -> tenta transformar
    out["basic"] = _as_item_list(items)
    return out


def _as_item_list(value: Any) -> List[Dict[str, Any]]:
    """
    Converte vários formatos em lista de {"name","qty"}.
    """
    if value is None:
        return []

    # já é lista de dicts
    if isinstance(value, list):
        out = []
        for it in value:
            if isinstance(it, dict):
                nm = it.get("name") or it.get("item") or it.get("title") or ""
                qty = it.get("qty") or it.get("amount") or it.get("count") or ""
                out.append({"name": str(nm), "qty": str(qty)})
            elif isinstance(it, str):
                out.append({"name": it, "qty": ""})
        return out

    # string grande -> tenta quebrar por linhas / vírgula
    if isinstance(value, str):
        txt = value.strip()
        if not txt:
            return []
        parts = re.split(r"[\n\r]+|,\s*", txt)
        parts = [p.strip() for p in parts if p.strip()]
        out = []
        for p in parts:
            # tenta capturar "25x Item"
            m = re.match(r"(\d+)\s*[x×]\s*(.+)", p, flags=re.IGNORECASE)
            if m:
                out.append({"name": m.group(2).strip(), "qty": m.group(1)})
            else:
                out.append({"name": p, "qty": ""})
        return out

    # número etc.
    return [{"name": str(value), "qty": ""}]
