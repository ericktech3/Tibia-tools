from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup


@dataclass
class ImbuementEntry:
    name: str
    basic: str
    intricate: str
    powerful: str


def fetch_imbuements_table():
    """Busca e parseia a tabela de Imbuements.

    Fonte principal: tibiawiki.com.br
    Fallback: tibia.fandom.com (caso a primeira falhe / mude layout).
    """
    url = "https://www.tibiawiki.com.br/wiki/Imbuements"
    alt_url = "https://tibia.fandom.com/wiki/Imbuements"
    headers = {
        "User-Agent": "Mozilla/5.0 (Android) TibiaTools/1.0",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=20)
        html = resp.text or ""
        if resp.status_code >= 400 or len(html) < 2000:
            html = requests.get(alt_url, headers=headers, timeout=20).text or ""

        soup = BeautifulSoup(html, "html.parser")

        def is_target_table(t) -> bool:
            header = " ".join(
                [th.get_text(" ", strip=True) for th in t.find_all("th")[:10]]
            ).lower()
            if "basic" in header and "intricate" in header and "powerful" in header:
                return True
            txt = t.get_text(" ", strip=True).lower()
            return ("basic" in txt and "intricate" in txt and "powerful" in txt)

        target = None
        for t in soup.find_all("table"):
            if is_target_table(t):
                target = t
                break

        if not target:
            return False, "Tabela de imbuements não encontrada."

        out = []
        rows = target.find_all("tr")
        for r in rows[1:]:
            cols = r.find_all(["td", "th"])
            if len(cols) < 4:
                continue
            name = cols[0].get_text(" ", strip=True)
            basic = cols[1].get_text(" ", strip=True)
            intricate = cols[2].get_text(" ", strip=True)
            powerful = cols[3].get_text(" ", strip=True)

            if not name:
                continue
            # ignora cabeçalhos repetidos
            if name.strip().lower() in {"imbuement", "name", "imbuements"}:
                continue

            out.append(ImbuementEntry(name, basic, intricate, powerful))

        if not out:
            return False, "Não foi possível extrair linhas da tabela."
        return True, out
    except Exception as e:
        return False, str(e)
