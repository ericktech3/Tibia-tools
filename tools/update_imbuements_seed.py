# -*- coding: utf-8 -*-
"""
Atualiza o snapshot embutido no APK:
  core/data/imbuements_seed.json

Uso (local):
  python tools/update_imbuements_seed.py

Uso (GitHub Actions):
  Este script é chamado por .github/workflows/update_imbuements_seed.yml
"""

import json
import re
from pathlib import Path

import requests


URL_RAW = "https://tibiawiki.com.br/index.php?title=Tibia_Wiki:Imbuements/json&action=raw"
URL_HTML = "https://www.tibiawiki.com.br/wiki/Tibia_Wiki:Imbuements/json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}


def normalize_payload_to_dict(payload: str) -> dict:
    t = (payload or "").strip().lstrip("\ufeff")
    if t.startswith("{"):
        return json.loads(t)

    m = re.search(r"<pre[^>]*>(.*?)</pre>", t, flags=re.I | re.S)
    if not m:
        raise ValueError("Não achei <pre> com JSON.")
    inner = m.group(1).replace("&quot;", '"').replace("&amp;", "&").strip()
    return json.loads(inner)


def download() -> dict:
    s = requests.Session()
    s.headers.update(HEADERS)

    # 1) tenta action=raw
    try:
        r = s.get(URL_RAW, timeout=30)
        if r.status_code == 200:
            obj = normalize_payload_to_dict(r.text)
            if isinstance(obj, dict) and obj:
                return obj
    except Exception:
        pass

    # 2) fallback: HTML
    r2 = s.get(URL_HTML, timeout=30)
    r2.raise_for_status()
    obj = normalize_payload_to_dict(r2.text)
    if not isinstance(obj, dict) or not obj:
        raise ValueError("JSON não está no formato esperado.")
    return obj


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    out = repo_root / "core" / "data" / "imbuements_seed.json"
    out.parent.mkdir(parents=True, exist_ok=True)

    obj = download()
    out.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("OK - seed atualizado:", out)


if __name__ == "__main__":
    main()
