# -*- coding: utf-8 -*-
"""
Imbuements (TibiaWiki BR)

⚠️ Importante: este módulo PRECISA ser importável no Android.
Por isso:
- não usa sintaxe nova (PEP604 |, list[str], etc.)
- não faz requests no import (rede só dentro das funções)
- expõe ImbuementEntry + fetch_imbuements_table (como o main.py espera)

Fonte preferencial:
- JSON oficial da TibiaWiki BR: Tibia_Wiki:Imbuements/json (action=raw)
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple

# Endpoints (tenta com e sem www)
_IMBUEMENTS_JSON_URLS = [
    "https://www.tibiawiki.com.br/index.php?title=Tibia_Wiki:Imbuements/json&action=raw",
    "https://tibiawiki.com.br/index.php?title=Tibia_Wiki:Imbuements/json&action=raw",
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 13; Mobile) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Mobile Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

# Cache simples em memória (evita baixar 2x)
_CACHE_DATA = None  # type: Optional[Dict[str, Any]]


class ImbuementEntry(object):
    def __init__(self, name, basic="", intricate="", powerful=""):
        self.name = name
        self.basic = basic
        self.intricate = intricate
        self.powerful = powerful


def _extract_json(payload_text):
    t = (payload_text or "").strip()
    t = t.lstrip("\ufeff")  # remove BOM

    # Caso venha JSON puro
    if t.startswith("{") and t.endswith("}"):
        return json.loads(t)

    # Caso venha HTML com JSON dentro de <pre> ... </pre>
    m = re.search(r"<pre[^>]*>(.*?)</pre>", t, flags=re.I | re.S)
    if m:
        inner = m.group(1).strip().lstrip("\ufeff")
        return json.loads(inner)

    # Último recurso: tenta pegar o maior bloco {...}
    m = re.search(r"(\{.*\})\s*$", t, flags=re.S)
    if m:
        return json.loads(m.group(1))

    raise ValueError("Resposta não contém JSON válido.")


def _tier_text(tier_obj):
    if not isinstance(tier_obj, dict):
        return "-"

    # Variações possíveis de campo
    effect = (
        tier_obj.get("effect")
        or tier_obj.get("description")
        or tier_obj.get("Efeito")
        or tier_obj.get("Descrição")
        or ""
    )
    effect = (effect or "").strip()

    items = tier_obj.get("items")
    if items is None:
        items = tier_obj.get("itens")
    if items is None:
        items = tier_obj.get("Itens")
    if items is None:
        items = []

    lines = []  # type: List[str]
    if isinstance(items, list):
        for it in items:
            if isinstance(it, dict):
                nm = (it.get("name") or it.get("nome") or it.get("item") or "").strip()
                qty = it.get("quantity") or it.get("quantidade") or it.get("qtd") or ""
                qty = str(qty).strip()
                if nm and qty and qty != "0":
                    lines.append("- %sx %s" % (qty, nm))
                elif nm:
                    lines.append("- %s" % nm)
            elif isinstance(it, str):
                s = it.strip()
                if s:
                    lines.append("- %s" % s)

    if lines:
        if effect:
            return effect + "\n" + "\n".join(lines)
        return "\n".join(lines)

    return effect or "-"


def _normalize_key(s):
    s = (s or "").strip()
    s = s.replace("\u00a0", " ")
    s = re.sub(r"\s+", " ", s)
    return s.lower()


def _load_json():
    global _CACHE_DATA

    if _CACHE_DATA is not None:
        return True, _CACHE_DATA

    try:
        import requests  # import local para não quebrar o app no boot
    except Exception as e:
        return False, "requests não disponível: %s" % e

    last_err = None
    sess = requests.Session()
    sess.headers.update(_HEADERS)

    # “aquecimento” (às vezes libera WAF/cookies)
    try:
        sess.get("https://www.tibiawiki.com.br/", timeout=10)
    except Exception:
        pass

    for url in _IMBUEMENTS_JSON_URLS:
        try:
            r = sess.get(url, timeout=20)
            if r.status_code == 403:
                # tenta mais uma vez (cookies)
                r = sess.get(url, timeout=20)

            if r.status_code >= 400:
                last_err = "%s Client Error: %s" % (r.status_code, url)
                continue

            data = _extract_json(r.text)
            if not isinstance(data, dict):
                last_err = "JSON inválido (não é objeto)."
                continue

            _CACHE_DATA = data
            return True, data
        except Exception as e:
            last_err = str(e)
            continue

    return False, (last_err or "Falha ao carregar JSON do TibiaWiki.")


def fetch_imbuements_table():
    """
    Retorna (ok, lista_de_ImbuementEntry) ou (False, mensagem).
    A lista vem completa (ex.: ~24).
    """
    ok, data = _load_json()
    if not ok:
        return False, data

    out = []  # type: List[ImbuementEntry]
    for name, obj in data.items():
        if not isinstance(obj, dict):
            continue

        level = obj.get("level")
        if not isinstance(level, dict):
            level = {}

        basic = _tier_text(level.get("Basic") or level.get("basic") or {})
        intricate = _tier_text(level.get("Intricate") or level.get("intricate") or {})
        powerful = _tier_text(level.get("Powerful") or level.get("powerful") or {})

        out.append(ImbuementEntry(str(name), basic, intricate, powerful))

    out.sort(key=lambda e: (e.name or "").lower())
    if not out:
        return False, "Não foi possível extrair a lista de imbuements."
    return True, out


def fetch_imbuement_details(title_or_page):
    """
    Mantido por compatibilidade: devolve (ok, dict com basic/intricate/powerful)
    """
    ok, data = _load_json()
    if not ok:
        return False, data

    target = _normalize_key(title_or_page)

    # tenta achar por chave direta (case-insensitive)
    picked = None
    for name, obj in data.items():
        if _normalize_key(str(name)) == target:
            picked = obj
            break

    if not isinstance(picked, dict):
        return False, "Imbuement não encontrado: %s" % title_or_page

    level = picked.get("level")
    if not isinstance(level, dict):
        level = {}

    details = {
        "basic": _tier_text(level.get("Basic") or level.get("basic") or {}),
        "intricate": _tier_text(level.get("Intricate") or level.get("intricate") or {}),
        "powerful": _tier_text(level.get("Powerful") or level.get("powerful") or {}),
    }
    return True, details
