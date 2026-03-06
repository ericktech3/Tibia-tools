from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def get_data_dir() -> str:
    try:
        from android.storage import app_storage_path  # type: ignore
        path = app_storage_path()
        if path:
            return str(path)
    except ImportError:
        pass
    except Exception:
        pass
    return str(Path(__file__).resolve().parent.parent / 'data')


def safe_read_json(path: str, default: Any = None):
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            return json.load(handle)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError:
        return default
    except OSError:
        return default


def safe_write_json(path: str, data: Any) -> bool:
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + '.tmp')
        with tmp.open('w', encoding='utf-8') as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, target)
        return True
    except OSError:
        return False
