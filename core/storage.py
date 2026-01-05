import os
import json

def get_data_dir():
    try:
        from android.storage import app_storage_path
        return app_storage_path()
    except Exception:
        return os.path.join(os.path.dirname(__file__), "..", "data")

def safe_read_json(path, default=None):
    try:
        if not os.path.exists(path):
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def safe_write_json(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
