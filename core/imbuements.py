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
    try:
        url = "https://www.tibiawiki.com.br/wiki/Imbuements"
        headers = {"User-Agent": "Mozilla/5.0 (Android) TibiaTools/1.0", "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"}
        html = requests.get(url, headers=headers, timeout=15).text
        soup = BeautifulSoup(html, "html.parser")

        tables = soup.find_all("table")
        target = None
        for t in tables:
            head = t.get_text(" ", strip=True).lower()
            if "basic" in head and "intricate" in head and "powerful" in head:
                target = t
                break
        if not target:
            return False, "Tabela não encontrada."

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
            if name:
                out.append(ImbuementEntry(name, basic, intricate, powerful))

        return True, out
    except Exception as e:
        return False, str(e)
