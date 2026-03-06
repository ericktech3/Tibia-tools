# -*- coding: utf-8 -*-
"""
Imbuements (TibiaWiki BR) — modo offline (seed embutido)

Motivação:
- A TibiaWiki frequentemente retorna 403 para requisições "automatizadas" (app/requests),
  quebrando a aba de Imbuements.
- Para distribuir o APK pra guild sem ninguém ter que "importar arquivo", este módulo
  carrega um snapshot (seed) EMBUTIDO no app: core/data/imbuements_seed.json.

Ordem de carregamento:
1) Cache local (salvo no storage do app)  -> mais rápido/offline
2) Seed embutido no APK                  -> funciona mesmo no 1º uso sem internet
3) (Opcional) Internet (se allow_net=True)

Este módulo expõe:
- ImbuementEntry
- fetch_imbuements_table()
- fetch_imbuement_details(key_or_name)
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

# URLs (só usados se allow_net=True)
_URL_RAW = "https://tibiawiki.com.br/index.php?title=Tibia_Wiki:Imbuements/json&action=raw"
_URL_HTML = "https://www.tibiawiki.com.br/wiki/Tibia_Wiki:Imbuements/json"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 13; Mobile) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Mobile Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

# Cache em memória (evita I/O repetido)
_MEM_CACHE: Optional[Dict[str, Any]] = None


class ImbuementEntry(object):
    def __init__(self, name: str, page: str = "", basic: str = "", intricate: str = "", powerful: str = ""):
        self.name = name
        self.page = page  # chave do JSON (ex.: Vampirism, Void, Strike...)
        self.basic = basic
        self.intricate = intricate
        self.powerful = powerful


def _seed_path() -> str:
    return os.path.join(os.path.dirname(__file__), "data", "imbuements_seed.json")


def _cache_path() -> str:
    # Reusa helper do projeto (Android: app_storage_path)
    try:
        from core.storage import get_data_dir  # type: ignore
        base = get_data_dir()
    except Exception:
        base = os.path.join(os.path.expanduser("~"), ".tibia-tools")

    try:
        os.makedirs(base, exist_ok=True)
    except Exception:
        pass

    return os.path.join(base, "imbuements_cache.json")


def _safe_read_json_file(path: str) -> Optional[Dict[str, Any]]:
    try:
        if not path or (not os.path.exists(path)):
            return None
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _safe_write_json_file(path: str, obj: Dict[str, Any]) -> None:
    try:
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _normalize_payload_to_dict(payload: str) -> Dict[str, Any]:
    t = (payload or "").strip()
    t = t.lstrip("\ufeff")
    if t.startswith("{"):
        return json.loads(t)

    # tenta extrair JSON dentro de <pre>...</pre>
    try:
        import re
        m = re.search(r"<pre[^>]*>(.*?)</pre>", t, flags=re.I | re.S)
        if m:
            inner = m.group(1)
            # desescapa alguns casos comuns
            inner = inner.replace("&quot;", '"').replace("&amp;", "&").strip()
            return json.loads(inner)
    except Exception:
        pass

    raise ValueError("Payload não é JSON válido.")


def _download_latest() -> Dict[str, Any]:
    """
    Baixa os dados da TibiaWiki.
    Tenta primeiro action=raw; se falhar (403/HTML), cai pro HTML e extrai o <pre>.
    """
    import requests  # import local
    sess = requests.Session()
    sess.headers.update(_HEADERS)

    # 1) raw
    try:
        r = sess.get(_URL_RAW, timeout=25)
        if r.status_code == 200:
            obj = _normalize_payload_to_dict(r.text)
            if isinstance(obj, dict) and obj:
                return obj
    except Exception:
        pass

    # 2) html
    r2 = sess.get(_URL_HTML, timeout=25)
    r2.raise_for_status()
    # extrai <pre> com regex (evita depender de bs4 no Android)
    import re
    m = re.search(r"<pre[^>]*>(.*?)</pre>", r2.text, flags=re.I | re.S)
    if not m:
        raise ValueError("Não encontrei bloco <pre> com o JSON na página.")
    inner = m.group(1)
    inner = inner.replace("&quot;", '"').replace("&amp;", "&").strip()
    obj = json.loads(inner)
    if not isinstance(obj, dict) or not obj:
        raise ValueError("JSON baixado não está no formato esperado.")
    return obj


def _load_imbuements_json(allow_net: bool = False) -> Tuple[bool, Any]:
    """
    Retorna (ok, data_or_error)
    """
    global _MEM_CACHE
    if _MEM_CACHE is not None:
        return True, _MEM_CACHE

    # 1) cache local
    cache = _safe_read_json_file(_cache_path())
    if cache:
        _MEM_CACHE = cache
        return True, cache

    # 2) seed embutido
    seed = _safe_read_json_file(_seed_path())
    if seed:
        _MEM_CACHE = seed
        # grava pro cache pra acelerar nas próximas
        _safe_write_json_file(_cache_path(), seed)
        return True, seed

    # 3) internet (opcional)
    if allow_net:
        try:
            latest = _download_latest()
            _MEM_CACHE = latest
            _safe_write_json_file(_cache_path(), latest)
            return True, latest
        except Exception as e:
            return False, str(e)

    return False, "Sem dados: seed não encontrado e cache vazio."


def _format_items(items: Any) -> List[str]:
    out: List[str] = []
    if isinstance(items, list):
        for it in items:
            if isinstance(it, dict):
                nm = (it.get("name") or it.get("nome") or it.get("item") or "").strip()
                qty = it.get("quantity") or it.get("quantidade") or it.get("qtd") or ""
                qty_s = str(qty).strip() if qty is not None else ""
                if nm and qty_s and qty_s != "0":
                    out.append("%sx %s" % (qty_s, nm))
                elif nm:
                    out.append(nm)
            elif isinstance(it, str):
                s = it.strip()
                if s:
                    out.append(s)
    return out


def fetch_imbuements_table(allow_net: bool = False):
    """
    Retorna (ok, List[ImbuementEntry] | erro_str)
    Por padrão NÃO acessa a internet (evita 403 no Android).
    """
    ok, data = _load_imbuements_json(allow_net=allow_net)
    if not ok:
        return False, data

    if not isinstance(data, dict):
        return False, "Dados inválidos."

    entries: List[ImbuementEntry] = []
    for key, val in data.items():
        if not isinstance(val, dict):
            continue
        display = (val.get("name") or key or "").strip()
        level = val.get("level") or {}
        basic = ""
        intr = ""
        powr = ""
        if isinstance(level, dict):
            b = level.get("Basic") or level.get("basic") or {}
            i = level.get("Intricate") or level.get("intricate") or {}
            p = level.get("Powerful") or level.get("powerful") or {}
            if isinstance(b, dict):
                basic = (b.get("description") or b.get("desc") or "").strip()
            if isinstance(i, dict):
                intr = (i.get("description") or i.get("desc") or "").strip()
            if isinstance(p, dict):
                powr = (p.get("description") or p.get("desc") or "").strip()

        entries.append(ImbuementEntry(display, page=str(key), basic=basic, intricate=intr, powerful=powr))

    entries.sort(key=lambda e: (e.name or "").lower())
    return True, entries


def fetch_imbuement_details(title_or_page: str, allow_net: bool = False):
    """
    Retorna (ok, dict | erro_str)
    Formato esperado pelo main.py:
      {
        "basic": {"effect": "...", "items": ["25x X", ...]},
        "intricate": {...},
        "powerful": {...}
      }
    """
    ok, data = _load_imbuements_json(allow_net=allow_net)
    if not ok:
        return False, data

    if not isinstance(data, dict):
        return False, "Dados inválidos."

    key = (title_or_page or "").strip()
    if not key:
        return False, "Imbuement inválido."

    picked = None  # type: Optional[Dict[str, Any]]

    # tenta por chave exata
    if key in data and isinstance(data.get(key), dict):
        picked = data.get(key)

    # tenta por nome (case-insensitive)
    if picked is None:
        lk = key.lower()
        for k, v in data.items():
            if isinstance(v, dict):
                nm = (v.get("name") or "").strip()
                if nm and nm.lower() == lk:
                    picked = v
                    break

    if picked is None:
        return False, "Não encontrei detalhes para: %s" % key

    level = picked.get("level") or {}
    if not isinstance(level, dict):
        return False, "Formato inválido (level)."

    def tier_obj(level_key: str) -> Dict[str, Any]:
        t = level.get(level_key) or level.get(level_key.lower()) or {}
        if not isinstance(t, dict):
            t = {}
        effect = (t.get("description") or t.get("desc") or "").strip()
        items = _format_items(t.get("itens") or t.get("items") or t.get("itens ") or [])
        return {"effect": effect, "items": items}

    details = {
        "basic": tier_obj("Basic"),
        "intricate": tier_obj("Intricate"),
        "powerful": tier_obj("Powerful"),
    }
    return True, details
