import json, re, requests

def fetch_exevopan_bosses(world: str):
    url = f"https://www.exevopan.com/bosses/{world}"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        html = requests.get(url, headers=headers, timeout=15).text
        m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
        if not m:
            return []
        data = json.loads(m.group(1))

        best = []
        def walk(obj):
            nonlocal best
            if isinstance(obj, dict):
                for k,v in obj.items():
                    if isinstance(v, list) and v and all(isinstance(x, dict) for x in v[:5]):
                        keys = set().union(*(x.keys() for x in v[:5]))
                        if ("boss" in keys or "bossName" in keys or "name" in keys) and ("chance" in keys or "status" in keys):
                            if len(v) > len(best):
                                best = v
                    walk(v)
            elif isinstance(obj, list):
                for it in obj:
                    walk(it)

        walk(data)

        out = []
        for it in best:
            name = it.get("boss") or it.get("bossName") or it.get("name")
            chance = it.get("chance") or it.get("chanceText")
            status = it.get("status") or it.get("state")
            out.append({"boss": name, "chance": str(chance), "status": str(status)})
        return out
    except Exception:
        return []
