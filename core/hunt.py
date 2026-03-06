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

        # opcionais
        xp_gain = re.search(r"XP Gain:\s*([\d\.,]+)", txt, flags=re.I)
        raw_xp = re.search(r"Raw XP Gain:\s*([\d\.,]+)", txt, flags=re.I)
        # Session Time: 01:23h (Tibia)
        sess_time = re.search(r"Session\s*Time:\s*(\d{1,2})\s*:\s*(\d{2})\s*h", txt, flags=re.I)
        # Alguns clientes usam 'Session duration'
        if not sess_time:
            sess_time = re.search(r"Session\s*(?:duration|time)\s*:\s*(\d{1,2})\s*:\s*(\d{2})", txt, flags=re.I)

        if not loot or not sup or not bal:
            return HuntResult(False, "Texto inválido. Copie o Session Data do Tibia.")

        loot_v = _num(loot.group(1))
        sup_v = _num(sup.group(1))
        bal_v = _num(bal.group(1).replace(" ", ""))

        lines = [
            f"Loot: {loot_v:,} gp",
            f"Supplies: {sup_v:,} gp",
            f"Balance: {bal_v:,} gp",
        ]

        # métricas por hora
        minutes = None
        if sess_time:
            try:
                h = int(sess_time.group(1))
                m = int(sess_time.group(2))
                minutes = max(1, h * 60 + m)
                lines.append(f"Session Time: {h:02d}:{m:02d}h")
            except Exception:
                minutes = None

        def per_hour(val: int) -> str:
            if not minutes:
                return ""
            v = int(round(val * 60.0 / minutes))
            return f"{v:,} /h".replace(",", ".")

        if minutes:
            lines.append(f"Profit/h: {per_hour(bal_v)}")

        if xp_gain:
            try:
                xp = _num(xp_gain.group(1))
                lines.append(f"XP Gain: {xp:,}".replace(",", "."))
                if minutes:
                    lines.append(f"XP/h: {per_hour(xp)}")
            except Exception:
                pass

        if raw_xp:
            try:
                rxp = _num(raw_xp.group(1))
                lines.append(f"Raw XP Gain: {rxp:,}".replace(",", "."))
            except Exception:
                pass

        pretty = "\n".join(lines).replace(",", ".") + "\n"

        return HuntResult(True, pretty=pretty)
    except Exception as e:
        return HuntResult(False, f"Erro: {e}")
