import os
import hashlib
import requests


def _cache_sprite(url: str, cache_dir: str, prefix: str) -> str:
    """Baixa um sprite remoto e salva localmente.

    - Retorna caminho local (preferencialmente PNG).
    - Em caso de falha, retorna string vazia (pra UI esconder o widget).
    """
    if not url:
        return ""

    try:
        os.makedirs(cache_dir, exist_ok=True)
    except Exception:
        return ""

    # nome determinístico por URL
    h = hashlib.md5(url.encode("utf-8")).hexdigest()  # nosec (somente cache)
    base = os.path.join(cache_dir, f"{prefix}_{h}")

    # detecta extensão
    clean = url.split("?")[0]
    ext = os.path.splitext(clean)[1].lower() or ".img"
    raw_path = base + ext
    png_path = base + ".png"

    # se já temos png cacheado, usa
    if os.path.exists(png_path) and os.path.getsize(png_path) > 0:
        return png_path
    # se existe o original, tenta usar (pode ser png/jpg)
    if os.path.exists(raw_path) and os.path.getsize(raw_path) > 0 and ext in (".png", ".jpg", ".jpeg", ".webp"):
        return raw_path

    # baixa
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        with open(raw_path, "wb") as f:
            f.write(r.content)
    except Exception:
        return ""

    # Se for GIF (comum nos sprites do tibia.com), converte pra PNG
    if ext == ".gif":
        try:
            from PIL import Image as PILImage  # pillow

            with PILImage.open(raw_path) as im:
                try:
                    im.seek(0)
                except Exception:
                    pass
                im = im.convert("RGBA")
                im.save(png_path, format="PNG")
            # remove o gif cru pra economizar espaço
            try:
                os.remove(raw_path)
            except Exception:
                pass
            return png_path if os.path.exists(png_path) else ""
        except Exception:
            # se não conseguir converter, devolve vazio pra não mostrar placeholder quebrado
            return ""

    # outros formatos: tenta usar o raw
    if os.path.exists(raw_path) and os.path.getsize(raw_path) > 0:
        return raw_path
    return ""

def fetch_boosted():
    """Retorna boosted creature e boosted boss usando TibiaData v4.

    Além dos nomes, tenta retornar também os sprites (image_url) quando disponíveis.
    """
    try:
        c = requests.get("https://api.tibiadata.com/v4/creatures", timeout=10).json()
        b = requests.get("https://api.tibiadata.com/v4/boostablebosses", timeout=10).json()

        c_boosted = ((c.get("creatures") or {}).get("boosted") or {})
        b_boosted = ((b.get("boostable_bosses") or {}).get("boosted") or {})

        creature = c_boosted.get("name", "N/A")
        boss = b_boosted.get("name", "N/A")

        creature_image_url = c_boosted.get("image_url") or ""
        boss_image_url = b_boosted.get("image_url") or ""

        # cache local (evita placeholder quebrado no AsyncImage, especialmente pra GIF)
        # No Android, precisa ser um diretório gravável (user_data_dir).
        try:
            from kivy.app import App

            app = App.get_running_app()
            if app and getattr(app, "user_data_dir", None):
                base_dir = os.path.join(app.user_data_dir, "sprite_cache")
            else:
                base_dir = os.path.join(os.getcwd(), ".sprite_cache")
        except Exception:
            base_dir = os.path.join(os.getcwd(), ".sprite_cache")
        creature_image = _cache_sprite(creature_image_url, base_dir, "creature")
        boss_image = _cache_sprite(boss_image_url, base_dir, "boss")

        return {
            "creature": creature,
            "boss": boss,
            "creature_image": creature_image,
            "boss_image": boss_image,
        }
    except Exception:
        return None
