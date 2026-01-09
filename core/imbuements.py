from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Dict, List, Tuple

import requests


# Fonte: TibiaWiki BR (JSON oficial mantido pela própria wiki)
# Ex.: https://www.tibiawiki.com.br/wiki/Tibia_Wiki:Imbuements/json
_IMBUEMENTS_JSON_PATH = "/index.php?title=Tibia_Wiki:Imbuements/json&action=raw"
_BASES = ("https://tibiawiki.com.br", "https://www.tibiawiki.com.br")

# Alguns sites bloqueiam o user-agent padrão do requests (python-requests/*) e retornam 403.
# Então usamos um UA de navegador e headers básicos.
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


@dataclass
class ImbuementEntry:
    # Nome curto (chave): Vampirism, Void, Strike, Scorch, etc.
    name: str
    # Texto completo por nível (descrição + itens necessários)
    basic: str
    intricate: str
    powerful: str


def _extract_json(text: str) -> Dict[str, Any]:
    """Tenta extrair JSON mesmo se vier com lixo antes/depois."""
    t = (text or "").strip()

    # remove BOM
    t = t.lstrip("\ufeff")

    if t.startswith("{") and t.endswith("}"):
        return json.loads(t)

    # Às vezes o wiki pode devolver HTML/preview; tenta extrair o maior bloco {...}
    m = re.search(r"(\{.*\})\s*$", t, flags=re.S)
    if m:
        return json.loads(m.group(1))

    raise ValueError("Resposta não parece conter JSON válido.")


def _format_level(level_obj: Dict[str, Any]) -> str:
    desc = (level_obj.get("description") or "").strip()
    items = level_obj.get("itens") or level_obj.get("items") or []
    if not isinstance(items, list):
        items = []

    if not items:
        return desc or "-"

    lines: List[str] = []
    for it in items:
        try:
            qty = it.get("quantity", "")
            nm = it.get("name", "")
            if qty and nm:
                lines.append(f"- {qty}x {nm}")
            elif nm:
                lines.append(f"- {nm}")
        except Exception:
            continue

    if lines:
        return f"{desc}\n\nItens:\n" + "\n".join(lines)
    return desc or "-"


def fetch_imbuements_table() -> Tuple[bool, List[ImbuementEntry] | str]:
    """Carrega todos os imbuements + itens diretamente do JSON do TibiaWiki BR.

    Retorna:
      (True, List[ImbuementEntry]) em caso de sucesso
      (False, mensagem) em caso de erro
    """
    try:
        s = requests.Session()
        s.headers.update(_HEADERS)

        last_err = None
        for base in _BASES:
            url = base + _IMBUEMENTS_JSON_PATH
            try:
                # dica: algumas WAFs liberam depois de visitar a home
                _ = s.get(base + "/", timeout=20)
                resp = s.get(url, timeout=20)
                if resp.status_code == 403:
                    # tenta uma segunda vez (às vezes libera após cookies)
                    resp = s.get(url, timeout=20)

                if resp.status_code >= 400:
                    last_err = f"{resp.status_code} Client Error"
                    continue

                data = _extract_json(resp.text)

                out: List[ImbuementEntry] = []
                for key, obj in (data or {}).items():
                    if not isinstance(obj, dict):
                        continue
                    level = obj.get("level") or {}
                    if not isinstance(level, dict):
                        level = {}

                    basic = _format_level(level.get("Basic") or {})
                    intricate = _format_level(level.get("Intricate") or {})
                    powerful = _format_level(level.get("Powerful") or {})

                    out.append(
                        ImbuementEntry(
                            name=str(key),
                            basic=basic,
                            intricate=intricate,
                            powerful=powerful,
                        )
                    )

                out.sort(key=lambda e: e.name.lower())
                if not out:
                    return False, "Não foi possível extrair imbuements do JSON."
                return True, out

            except Exception as e:
                last_err = str(e)
                continue

        return False, last_err or "Falha ao buscar dados do TibiaWiki."
    except Exception as e:
        return False, str(e)
