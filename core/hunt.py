from dataclasses import dataclass
import re

@dataclass
class HuntResult:
    ok: bool
    error: str = ""
    pretty: str = ""

def _num(s):
    s = s.replace(".", "").replace(",", "")
    return int(s)

def parse_hunt_session_text(txt: str) -> HuntResult:
    try:
        loot = re.search(r"Loot:\s*([\d\.,]+)", txt)
        sup = re.search(r"Supplies:\s*([\d\.,]+)", txt)
        bal = re.search(r"Balance:\s*([-]?\s*[\d\.,]+)", txt)

        if not loot or not sup or not bal:
            return HuntResult(False, "Texto inválido. Copie o Session Data do Tibia.")

        loot_v = _num(loot.group(1))
        sup_v = _num(sup.group(1))
        bal_v = _num(bal.group(1).replace(" ", ""))

        pretty = (
            f"Loot: {loot_v:,} gp\n"
            f"Supplies: {sup_v:,} gp\n"
            f"Balance: {bal_v:,} gp\n"
        ).replace(",", ".")

        return HuntResult(True, pretty=pretty)
    except Exception as e:
        return HuntResult(False, f"Erro: {e}")
