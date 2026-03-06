from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path
from types import TracebackType
from typing import Optional

CRASH_FILE_NAME = "tibia_tools_crash.log"


def _try_android_app_storage() -> str | None:
    try:
        from android.storage import app_storage_path  # type: ignore
    except ImportError:
        return None
    except Exception:
        return None

    try:
        path = app_storage_path()
    except Exception:
        return None

    if not path:
        return None
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        return None
    return str(path)


def _try_running_app_data_dir() -> str | None:
    try:
        from kivy.app import App  # type: ignore
    except ImportError:
        return None
    except Exception:
        return None

    try:
        app = App.get_running_app()
    except Exception:
        return None

    data_dir = getattr(app, "user_data_dir", None) if app else None
    if not data_dir:
        return None
    try:
        os.makedirs(str(data_dir), exist_ok=True)
    except OSError:
        return None
    return str(data_dir)


def get_writable_dir() -> str:
    for candidate in (_try_android_app_storage(), _try_running_app_data_dir()):
        if candidate:
            return candidate
    return os.getcwd()


def get_crash_file_path(filename: str = CRASH_FILE_NAME) -> str:
    return str(Path(get_writable_dir()) / filename)


def write_crash_log(text: str, *, filename: str = CRASH_FILE_NAME) -> None:
    if text is None:
        return
    try:
        crash_file = Path(get_crash_file_path(filename))
        crash_file.parent.mkdir(parents=True, exist_ok=True)
        payload = text if text.endswith("\n") else f"{text}\n"
        with crash_file.open("a", encoding="utf-8") as handle:
            handle.write(payload)
    except OSError:
        pass


def log_current_exception(*, prefix: str | None = None, filename: str = CRASH_FILE_NAME) -> None:
    text = traceback.format_exc()
    if prefix:
        text = f"{prefix}\n{text}"
    write_crash_log(text, filename=filename)


def install_excepthook(target_sys=None) -> None:
    module_sys = target_sys or sys
    default_hook = getattr(module_sys, "__excepthook__", None)

    def _hook(exc_type: type[BaseException], exc: BaseException, tb: Optional[TracebackType]) -> None:
        write_crash_log("".join(traceback.format_exception(exc_type, exc, tb)))
        if callable(default_hook):
            default_hook(exc_type, exc, tb)

    module_sys.excepthook = _hook
