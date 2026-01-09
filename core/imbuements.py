# -*- coding: utf-8 -*-
"""
Imbuements (TibiaWiki BR)

Este módulo usa a página JSON mantida na TibiaWiki (MediaWiki), evitando scraping de HTML
(que frequentemente retorna 403). Ele expõe duas funções usadas pelo app:

- fetch_imbuements_table() -> (ok, list[dict])
- fetch_imbuement_details(title_or_page) -> (ok, dict)

Compatível com Python 3.10 (p4a).
"""

import json
import re
from typing import Any, Dict, List, Tuple, Optional

BASE_URL = "https://www.tibiawiki.com.br"
JSON_TITLE = "Tibia_Wiki:Imbuements/json"

_HEADERS = {
    # Um UA de navegador reduz chances de 403/WAF.
    "User-Agent": "Mozilla/5.0 (Linux; Android 13; Mobile) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.tibiawiki.com.br/",
    "Connection": "keep-alive",
}

_DB_CACHE: Optional[Dict[str, Any]] = None
_DB_ERROR: Optional[str] = None


def _http_get(url: str, params: Optional[Dict[str, str]] = None) -> str:
    # Import local para evitar falha de import caso requests não esteja disponível em algum build.
    import requests  # type: ignore

    resp = requests.get(url, params=params, headers=_HEADERS, timeout=25)
    resp.raise_for_status()
    # A TibiaWiki geralmente usa UTF-8
    resp.encoding = resp.encoding or "utf-8"
    return resp.text


def _extract_json_from_html(html: str) -> str:
    """
    Fallback: extrai o JSON de uma página HTML (normalmente dentro de <pre>).
    """
    m = re.search(r"<pre[^>]*>(.*?)</pre>", html, flags=re.I | re.S)
    payload = m.group(1) if m else html

    # Remover tags residuais e des-escapar entidades mais comuns.
    payload = re.sub(r"<[^>]+>", "", payload)
    payload = payload.replace("&quot;", '"').replace("&#34;", '"')
    payload = payload.replace("&amp;", "&").replace("&#38;", "&")
    payload = payload.replace("&#039;", "'").replace("&lt;", "<").replace("&gt;", ">")

    payload = payload.strip()
    # Recortar do primeiro { ao último } para evitar lixo.
    a = payload.find("{")
    b = payload.rfind("}")
    if a != -1 and b != -1 and b > a:
        payload = payload[a:b + 1]
    return payload


def _load_db() -> Tuple[bool, Any]:
    """
    Carrega e cacheia o banco JSON de imbuements.

    Retorna:
      (True, dict) em caso de sucesso
      (False, str) em caso de erro
    """
    global _DB_CACHE, _DB_ERROR

    if _DB_CACHE is not None:
        return True, _DB_CACHE
    if _DB_ERROR is not None:
        return False, _DB_ERROR

    e1 = e2 = e3 = None

    # 1) MediaWiki API (preferido)
    try:
        api_text = _http_get(
            f"{BASE_URL}/api.php",
            params={
                "action": "query",
                "prop": "revisions",
                "titles": JSON_TITLE,
                "rvprop": "content",
                "rvslots": "main",
                "format": "json",
                "formatversion": "2",
            },
        )
        api_json = json.loads(api_text)
        page = (api_json.get("query", {}).get("pages") or [{}])[0]
        rev = (page.get("revisions") or [{}])[0]
        slots = rev.get("slots") or {}
        content = (slots.get("main") or {}).get("content") or ""
        db = json.loads(content)
        if isinstance(db, dict) and db:
            _DB_CACHE = db
            return True, db
        raise ValueError("Conteúdo JSON vazio/inesperado (API).")
    except Exception as ex:
        e1 = ex

    # 2) action=raw (alternativa)
    try:
        raw_text = _http_get(
            f"{BASE_URL}/index.php",
            params={"title": JSON_TITLE, "action": "raw"},
        )
        db = json.loads(raw_text)
        if isinstance(db, dict) and db:
            _DB_CACHE = db
            return True, db
        raise ValueError("Conteúdo JSON vazio/inesperado (raw).")
    except Exception as ex:
        e2 = ex

    # 3) Página HTML + extração (último recurso)
    try:
        html = _http_get(f"{BASE_URL}/wiki/{JSON_TITLE}")
        json_text = _extract_json_from_html(html)
        db = json.loads(json_text)
        if isinstance(db, dict) and db:
            _DB_CACHE = db
            return True, db
        raise ValueError("Conteúdo JSON vazio/inesperado (html).")
    except Exception as ex:
        e3 = ex

    _DB_ERROR = (
        "Não foi possível carregar os Imbuements da TibiaWiki.\n"
        f"1) API: {e1}\n"
        f"2) RAW: {e2}\n"
        f"3) HTML: {e3}"
    )
    return False, _DB_ERROR


def fetch_imbuements_table() -> Tuple[bool, Any]:
    """
    Retorna a lista principal para a aba:
      ok=True  -> lista de dicts com pelo menos {"title": <nome>}
      ok=False -> mensagem de erro (str)
    """
    ok, db = _load_db()
    if not ok:
        return False, db

    entries: List[Dict[str, Any]] = []
    for title, info in db.items():
        if not isinstance(title, str):
            continue
        if not isinstance(info, dict):
            info = {}
        entries.append(
            {
                "title": title,
                "name": info.get("name", ""),
                "gold_token": bool(info.get("gold_token", False)),
            }
        )

    entries.sort(key=lambda x: x.get("title", "").lower())
    return True, entries


def _find_entry(db: Dict[str, Any], key: str) -> Optional[Dict[str, Any]]:
    if key in db and isinstance(db[key], dict):
        return db[key]
    # fallback case-insensitive
    lk = key.lower()
    for k, v in db.items():
        if isinstance(k, str) and k.lower() == lk and isinstance(v, dict):
            return v
    return None


def fetch_imbuement_details(title_or_page: str) -> Tuple[bool, Any]:
    """
    Retorna detalhes para o popup (Basic/Intricate/Powerful).

    Saída esperada pelo main.py:
      ok=True -> dict {
        "basic": {"effect": str, "items": [str, ...]},
        "intricate": {...},
        "powerful": {...},
      }
    """
    ok, db = _load_db()
    if not ok:
        return False, db

    key = (title_or_page or "").replace("_", " ").strip()
    if not key:
        return False, "Imbuement inválido."

    entry = _find_entry(db, key)
    if not entry:
        return False, f"Imbuement não encontrado: {key}"

    def parse_tier(tier_label: str) -> Dict[str, Any]:
        tier = entry.get(tier_label) or {}
        if not isinstance(tier, dict):
            tier = {}

        effect = (tier.get("description") or tier.get("effect") or "").strip()

        items_out: List[str] = []
        raw_items = tier.get("itens") or tier.get("items") or []
        if isinstance(raw_items, list):
            for it in raw_items:
                if isinstance(it, dict):
                    nm = (it.get("name") or it.get("nome") or "").strip()
                    qty = it.get("quantity")
                    if qty is None:
                        qty = it.get("quantidade")
                    if qty is None:
                        qty = it.get("amount")
                    if nm and qty is not None and str(qty).strip() != "":
                        items_out.append(f"{nm} x{qty}")
                    elif nm:
                        items_out.append(nm)
                elif isinstance(it, str):
                    s = it.strip()
                    if s:
                        items_out.append(s)

        return {"effect": effect, "items": items_out}

    details = {
        "basic": parse_tier("Basic"),
        "intricate": parse_tier("Intricate"),
        "powerful": parse_tier("Powerful"),
    }
    return True, details
