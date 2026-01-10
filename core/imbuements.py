# -*- coding: utf-8 -*-
"""
Imbuements (TibiaWiki BR)

⚠️ Importante: este módulo PRECISA ser importável no Android.
Por isso:
- não usa sintaxe nova (PEP604 |, list[str], etc.)
- não faz requests no import (rede só dentro das funções)
- expõe ImbuementEntry + fetch_imbuements_table + fetch_imbuement_details

Fonte preferencial:
- JSON oficial da TibiaWiki BR: Tibia_Wiki:Imbuements/json (action=raw)

Melhoria (offline-first):
- salva o JSON em cache persistente (app_storage_path) após baixar
- se a rede falhar, usa o cache salvo para evitar que a aba quebre
"""

import json
import os
import re
import time
from typing import Any, Dict, List, Optional

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

# Cache simples em memória (evita baixar 2x na mesma sessão)
_CACHE_DATA = None  # type: Optional[Dict[str, Any]]

# Cache persistente (arquivo)
_CACHE_FILENAME = "imbuements_cache.json"
# TTL longo para reduzir chance de erro de rede. Se quiser, pode baixar de novo após esse tempo.
_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 dias


# Import local (com fallback) para não quebrar em ambientes diferentes
try:
    from .storage import get_data_dir, safe_read_json, safe_write_json
except Exception:
    def get_data_dir():
        return os.path.join(os.path.dirname(__file__), "..", "data")

    def safe_read_json(path, default=None):
        try:
            if not os.path.exists(path):
                return default
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default

    def safe_write_json(path, data):
        try:
            d = os.path.dirname(path)
            if d:
                os.makedirs(d, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


class ImbuementEntry(object):
    def __init__(self, name, page="", basic="", intricate="", powerful=""):
        self.name = name
        self.page = page
        self.basic = basic
        self.intricate = intricate
        self.powerful = powerful


def _extract_json(payload_text):
    t = (payload_text or "").strip()
    t = t.lstrip("﻿")  # remove BOM

    # Caso venha JSON puro
    if t.startswith("{") and t.endswith("}"):
        return json.loads(t)

    # Caso venha HTML com JSON dentro de <pre> ... </pre>
    m = re.search(r"<pre[^>]*>(.*?)</pre>", t, flags=re.I | re.S)
    if m:
        inner = m.group(1).strip().lstrip("﻿")
        return json.loads(inner)

    # Último recurso: tenta pegar o maior bloco {...}
    m = re.search(r"(\{.*\})\s*$", t, flags=re.S)
    if m:
        return json.loads(m.group(1))

    raise ValueError("Resposta não contém JSON válido.")


def _normalize_key(s):
    s = (s or "").strip()
    s = s.replace(" ", " ")
    s = re.sub(r"\s+", " ", s)
    return s.lower()


def _cache_path():
    try:
        base = get_data_dir()
    except Exception:
        base = os.path.join(os.path.dirname(__file__), "..", "data")
    return os.path.join(base, _CACHE_FILENAME)


def _read_persisted_cache():
    """Retorna (data_dict, age_seconds) ou (None, None)."""
    path = _cache_path()
    blob = safe_read_json(path, default=None)

    if not isinstance(blob, dict):
        return None, None

    # Formato novo (wrapper)
    if isinstance(blob.get("data"), dict):
        data = blob.get("data")
        fetched_at = blob.get("fetched_at")
        age = None
        if fetched_at is not None:
            try:
                age = time.time() - float(fetched_at)
            except Exception:
                age = None
        return data, age

    # Formato antigo: era o dict direto
    return blob, None


def _read_seed_cache():
    """Opcional: um snapshot empacotado junto do app."""
    seed_path = os.path.join(os.path.dirname(__file__), "data", "imbuements_seed.json")
    blob = safe_read_json(seed_path, default=None)
    if isinstance(blob, dict) and blob:
        # pode estar no formato wrapper também
        if isinstance(blob.get("data"), dict):
            return blob.get("data")
        return blob
    return None


def _write_persisted_cache(data):
    if not isinstance(data, dict) or not data:
        return
    payload = {"fetched_at": time.time(), "data": data}
    safe_write_json(_cache_path(), payload)


def _tier_payload(tier_obj):
    """Normaliza um tier em um dict com (effect:str, items:list[str])."""
    if not isinstance(tier_obj, dict):
        return {"effect": "-", "items": []}

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

    out_items = []  # type: List[str]
    if isinstance(items, list):
        for it in items:
            if isinstance(it, dict):
                nm = (it.get("name") or it.get("nome") or it.get("item") or "").strip()
                qty = it.get("quantity") or it.get("quantidade") or it.get("qtd") or ""
                qty = str(qty).strip()
                if nm and qty and qty != "0":
                    out_items.append("%sx %s" % (qty, nm))
                elif nm:
                    out_items.append(nm)
            elif isinstance(it, str):
                s = it.strip()
                if s:
                    out_items.append(s)

    return {"effect": effect or "-", "items": out_items}


def _tier_text(tier_obj):
    """Formato pronto (multilinha), útil para exibir em lista."""
    t = _tier_payload(tier_obj)
    effect = (t.get("effect") or "").strip()
    items = t.get("items") or []
    lines = []
    if effect and effect != "-":
        lines.append(effect)
    for it in items:
        lines.append("- %s" % it)
    return "\n".join(lines).strip() or "-"


def _load_json():
    """Retorna (ok, dict) ou (False, mensagem)."""
    global _CACHE_DATA

    if _CACHE_DATA is not None:
        return True, _CACHE_DATA

    # 1) tenta cache persistente primeiro (offline-first)
    cached, age = _read_persisted_cache()
    cached_ok = isinstance(cached, dict) and bool(cached)

    if cached_ok:
        _CACHE_DATA = cached
        return True, cached
    # 1.1) tenta snapshot empacotado (se existir)
    seed = _read_seed_cache()
    if not cached_ok and isinstance(seed, dict) and seed:
        _CACHE_DATA = seed
        return True, seed

    # 2) tenta baixar (e salvar)
    try:
        import requests  # import local para não quebrar o app no boot
    except Exception as e:
        # se tinha cache velho, usa ele mesmo assim
        if cached_ok:
            _CACHE_DATA = cached
            return True, cached
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
            if not isinstance(data, dict) or not data:
                last_err = "JSON inválido (não é objeto)."
                continue

            _CACHE_DATA = data
            _write_persisted_cache(data)
            return True, data
        except Exception as e:
            last_err = str(e)
            continue

    # 3) fallback final: cache velho (se existia)
    if cached_ok:
        _CACHE_DATA = cached
        return True, cached

    return False, (last_err or "Falha ao carregar JSON do TibiaWiki.")


def fetch_imbuements_table():
    """
    Retorna (ok, lista_de_ImbuementEntry) ou (False, mensagem).
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

        # alguns JSONs podem trazer um campo de página
        page = (
            obj.get("page")
            or obj.get("title")
            or obj.get("pagina")
            or obj.get("Página")
            or ""
        )
        page = str(page).strip()
        if not page:
            page = str(name)

        basic = _tier_text(level.get("Basic") or level.get("basic") or {})
        intricate = _tier_text(level.get("Intricate") or level.get("intricate") or {})
        powerful = _tier_text(level.get("Powerful") or level.get("powerful") or {})

        out.append(ImbuementEntry(str(name), page, basic, intricate, powerful))

    out.sort(key=lambda e: (e.name or "").lower())
    if not out:
        return False, "Não foi possível extrair a lista de imbuements."
    return True, out


def fetch_imbuement_details(title_or_page):
    """
    Devolve (ok, dict com basic/intricate/powerful) onde cada tier é:
      {"effect": str, "items": [str, ...]}

    Obs: o argumento pode ser o nome (chave) ou o título/página.
    """
    ok, data = _load_json()
    if not ok:
        return False, data

    target = _normalize_key(title_or_page)

    picked = None
    # tenta achar por chave direta (case-insensitive)
    for name, obj in data.items():
        if _normalize_key(str(name)) == target:
            picked = obj
            break

    # tenta achar pelo campo de página (se existir)
    if picked is None:
        for _name, obj in data.items():
            if not isinstance(obj, dict):
                continue
            page = obj.get("page") or obj.get("title") or obj.get("pagina") or ""
            if page and _normalize_key(str(page)) == target:
                picked = obj
                break

    if not isinstance(picked, dict):
        return False, "Imbuement não encontrado: %s" % title_or_page

    level = picked.get("level")
    if not isinstance(level, dict):
        level = {}

    details = {
        "basic": _tier_payload(level.get("Basic") or level.get("basic") or {}),
        "intricate": _tier_payload(level.get("Intricate") or level.get("intricate") or {}),
        "powerful": _tier_payload(level.get("Powerful") or level.get("powerful") or {}),
    }
    return True, details
