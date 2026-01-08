import re
import requests
from bs4 import BeautifulSoup


def fetch_exevopan_bosses(world: str):
    """Busca lista de bosses do ExevoPan para um world.

    Retorna uma lista de dicts: {"boss": str, "chance": str, "status": str}
    """
    world = (world or "").strip()
    if not world:
        return []

    url = f"https://www.exevopan.com/bosses/{world}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Android) TibiaTools/1.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        r = requests.get(url, headers=headers, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text("\n")
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

        out = []
        for idx, ln in enumerate(lines):
            if ln.startswith("#### "):
                boss = ln[5:].strip()

                # pega a próxima linha útil como "status"
                status_line = ""
                j = idx + 1
                while j < len(lines):
                    nxt = lines[j]
                    if nxt and not nxt.startswith("#### "):
                        status_line = nxt.strip()
                        break
                    j += 1

                chance = ""
                status = ""
                if status_line:
                    if "%" in status_line:
                        chance = status_line
                    elif status_line.lower().startswith("no chance"):
                        # Ex.: "No chance Expected in: 8 days"
                        m = re.match(r"(?i)no chance\s*(.*)$", status_line)
                        chance = "No chance"
                        status = (m.group(1).strip() if m else "")
                    else:
                        # "Unknown" ou "Expected in: ..."
                        chance = status_line

                out.append({"boss": boss, "chance": chance, "status": status})

        return out
    except Exception:
        return []
