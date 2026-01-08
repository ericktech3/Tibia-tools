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
    """Extrai tabela de imbuements do TibiaWiki.

    Retorna (ok, data_ou_erro)
    """
    url = "https://www.tibiawiki.com.br/wiki/Imbuements"
    headers = {
        "User-Agent": "Mozilla/5.0 (Android) TibiaTools/1.0",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    }
    try:
        r = requests.get(url, headers=headers, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        target = None
        for t in soup.find_all("table"):
            heads = [th.get_text(" ", strip=True).lower() for th in t.find_all("th")]
            if not heads:
                continue
            has_basic = any("basic" in h or "básic" in h for h in heads)
            has_intr = any("intricate" in h or "intric" in h for h in heads)
            has_pow = any("powerful" in h or "power" in h for h in heads)
            if has_basic and has_intr and has_pow:
                target = t
                break

        if target is None:
            return False, "Tabela de imbuements não encontrada (página mudou ou bloqueada)."

        out = []
        rows = target.find_all("tr")
        for row in rows[1:]:
            cols = row.find_all(["td", "th"])
            if len(cols) < 4:
                continue
            name = cols[0].get_text(" ", strip=True)
            basic = cols[1].get_text(" ", strip=True)
            intricate = cols[2].get_text(" ", strip=True)
            powerful = cols[3].get_text(" ", strip=True)
            if name:
                out.append(ImbuementEntry(name, basic, intricate, powerful))

        if not out:
            return False, "Tabela carregou, mas não consegui extrair linhas (layout mudou)."

        return True, out
    except Exception as e:
        return False, str(e)
