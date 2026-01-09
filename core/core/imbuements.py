# -*- coding: utf-8 -*-
"""Imbuements (TibiaWiki BR)

A TibiaWiki BR pode retornar 403 para scraping de páginas HTML (/wiki/...).
Para evitar isso, este módulo tenta primeiro ler um JSON mantido na própria wiki:
  Tibia_Wiki:Imbuements/json (via action=raw)

Se o endpoint raw falhar, tenta rotas alternativas via MediaWiki API.
O módulo é escrito para ser compatível com versões mais antigas de Python no Android
(evita sintaxe 3.10+ como Union com '|').
"""

import json
import re


# Mantemos uma classe simples (sem dataclass) para máxima compatibilidade.
class ImbuementEntry(object):
    def __init__(self, name, basic, intricate, powerful):
        self.name = name
        self.basic = basic
        self.intricate = intricate
        self.powerful = powerful


# Preferência: TibiaWiki BR
_BASES = (
    "https://tibiawiki.com.br",
    "https://www.tibiawiki.com.br",
)

# Página que contém o JSON (mantida pela própria wiki)
_RAW_PATH = "/index.php?title=Tibia_Wiki:Imbuements/json&action=raw"

# Fallbacks via API MediaWiki (às vezes passam onde /wiki/ bloqueia)
_API_QUERY_PATH = (
    "/api.php?action=query&format=json&prop=revisions&rvprop=content&titles="
    "Tibia_Wiki:Imbuements/json&formatversion=2"
)
_API_PARSE_PATH = (
    "/api.php?action=parse&format=json&page=Tibia_Wiki:Imbuements/json&prop=wikitext&formatversion=2"
)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 13; Mobile) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


def _strip_bom(s):
    return s.lstrip("\ufeff") if s else s


def _extract_json_text(s):
    """Extrai o maior bloco JSON possível de uma string."""
    s = (_strip_bom(s) or "").strip()
    if not s:
        raise ValueError("Resposta vazia.")
    if s.startswith("{") and s.endswith("}"):
        return s

    # Remove tags <pre> se vier de algum proxy/preview
    s2 = re.sub(r"</?pre[^>]*>", "", s, flags=re.I).strip()
    if s2.startswith("{") and s2.endswith("}"):
        return s2

    # Procura o maior bloco {...}
    m = re.search(r"(\{.*\})", s2, flags=re.S)
    if m:
        return m.group(1).strip()
    raise ValueError("Não foi possível localizar JSON na resposta.")


def _parse_imbuements_json(data):
    """Converte o JSON (dict) em lista de ImbuementEntry."""
    if not isinstance(data, dict):
        raise ValueError("JSON inesperado: esperado objeto/dict.")

    out = []
    for key, obj in data.items():
        if not isinstance(obj, dict):
            continue

        lvl = obj.get("level") or obj.get("levels") or {}
        if not isinstance(lvl, dict):
            lvl = {}

        basic = _format_level(lvl.get("Basic") or {})
        intricate = _format_level(lvl.get("Intricate") or {})
        powerful = _format_level(lvl.get("Powerful") or {})

        out.append(ImbuementEntry(str(key), basic, intricate, powerful))

    out.sort(key=lambda e: e.name.lower())
    return out


def _format_level(level_obj):
    """Monta texto de um nível: descrição + itens."""
    if not isinstance(level_obj, dict):
        return "-"

    desc = (level_obj.get("description") or "").strip()

    items = level_obj.get("itens")
    if items is None:
        items = level_obj.get("items")
    if not isinstance(items, list):
        items = []

    lines = []
    for it in items:
        if not isinstance(it, dict):
            continue
        qty = it.get("quantity") or it.get("qty") or ""
        nm = it.get("name") or ""
        try:
            qty = str(qty).strip()
        except Exception:
            qty = ""
        try:
            nm = str(nm).strip()
        except Exception:
            nm = ""
        if not nm:
            continue
        if qty:
            lines.append("- %sx %s" % (qty, nm))
        else:
            lines.append("- %s" % nm)

    if lines:
        if desc:
            return desc + "\n\nItens:\n" + "\n".join(lines)
        return "Itens:\n" + "\n".join(lines)

    return desc or "-"


def _try_fetch_json_from_raw(session, base):
    url = base + _RAW_PATH
    r = session.get(url, timeout=20, allow_redirects=True)
    if r.status_code >= 400:
        raise Exception("%s %s" % (r.status_code, r.reason))
    txt = _extract_json_text(r.text)
    return json.loads(txt)


def _try_fetch_json_from_api_query(session, base):
    url = base + _API_QUERY_PATH
    r = session.get(url, timeout=20, allow_redirects=True)
    if r.status_code >= 400:
        raise Exception("%s %s" % (r.status_code, r.reason))
    j = r.json()

    # Formatos possíveis:
    # formatversion=2 => query.pages[0].revisions[0].content
    try:
        pages = j.get("query", {}).get("pages", [])
        if pages and isinstance(pages, list):
            revs = pages[0].get("revisions", [])
            if revs and isinstance(revs, list):
                content = revs[0].get("content")
                if content:
                    txt = _extract_json_text(content)
                    return json.loads(txt)
    except Exception:
        pass

    # Formato legado: query.pages.{id}.revisions[0]['*']
    try:
        pages = j.get("query", {}).get("pages", {})
        if isinstance(pages, dict):
            for _, page in pages.items():
                revs = page.get("revisions", [])
                if revs:
                    content = revs[0].get("*")
                    if content:
                        txt = _extract_json_text(content)
                        return json.loads(txt)
    except Exception:
        pass

    raise ValueError("Resposta API query não contém conteúdo esperado.")


def _try_fetch_json_from_api_parse(session, base):
    url = base + _API_PARSE_PATH
    r = session.get(url, timeout=20, allow_redirects=True)
    if r.status_code >= 400:
        raise Exception("%s %s" % (r.status_code, r.reason))
    j = r.json()

    # parse.wikitext pode vir como string ou dict com '*'
    wt = None
    try:
        wt = j.get("parse", {}).get("wikitext")
        if isinstance(wt, dict):
            wt = wt.get("*")
    except Exception:
        wt = None

    if not wt:
        raise ValueError("Resposta API parse sem wikitext.")
    txt = _extract_json_text(wt)
    return json.loads(txt)


def fetch_imbuements_table():
    """Retorna (ok, dados_ou_erro).

    ok=True  => dados_ou_erro é list[ImbuementEntry]
    ok=False => dados_ou_erro é string (mensagem)
    """
    # Import lazy para evitar quebrar o app no start se faltar algum módulo no Android
    try:
        import requests  # pylint: disable=import-error
    except Exception as e:
        return False, "Falha ao importar requests: %s" % e

    try:
        session = requests.Session()
        session.headers.update(_HEADERS)

        last_err = None
        for base in _BASES:
            try:
                # pega cookies básicos
                try:
                    session.get(base + "/", timeout=10)
                except Exception:
                    pass

                # 1) action=raw (preferido)
                try:
                    data = _try_fetch_json_from_raw(session, base)
                    entries = _parse_imbuements_json(data)
                    if entries:
                        return True, entries
                except Exception as e:
                    last_err = str(e)

                # 2) API query
                try:
                    data = _try_fetch_json_from_api_query(session, base)
                    entries = _parse_imbuements_json(data)
                    if entries:
                        return True, entries
                except Exception as e:
                    last_err = str(e)

                # 3) API parse
                try:
                    data = _try_fetch_json_from_api_parse(session, base)
                    entries = _parse_imbuements_json(data)
                    if entries:
                        return True, entries
                except Exception as e:
                    last_err = str(e)

            except Exception as e:
                last_err = str(e)

        return False, last_err or "Não foi possível buscar dados do TibiaWiki BR (bloqueado/403?)."
    except Exception as e:
        return False, str(e)
