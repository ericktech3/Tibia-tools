import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch


def _install_kivy_stubs():
    kivy = sys.modules.get("kivy") or types.ModuleType("kivy")
    kivy.__path__ = []
    kivy_clock = types.ModuleType("kivy.clock")
    kivy_clock.Clock = SimpleNamespace(schedule_once=lambda fn, dt=0: fn(0))
    kivy_metrics = types.ModuleType("kivy.metrics")
    kivy_metrics.dp = lambda value: value
    kivy_core = sys.modules.get("kivy.core") or types.ModuleType("kivy.core")
    kivy_core.__path__ = []
    kivy_clipboard = types.ModuleType("kivy.core.clipboard")
    kivy_clipboard.Clipboard = SimpleNamespace(copy=lambda value: None)

    class _ListItem:
        def __init__(self, text="", secondary_text=""):
            self.text = text
            self.secondary_text = secondary_text
            self.secondary_theme_text_color = None
            self.secondary_text_color = None
            self.children = []
            self._bindings = {}

        def add_widget(self, widget):
            self.children.append(widget)

        def bind(self, **kwargs):
            self._bindings.update(kwargs)

    class _IconLeftWidget:
        def __init__(self, icon=""):
            self.icon = icon

    kivymd = types.ModuleType("kivymd")
    kivymd_uix = types.ModuleType("kivymd.uix")
    kivymd_list = types.ModuleType("kivymd.uix.list")
    kivymd_list.OneLineIconListItem = _ListItem
    kivymd_list.TwoLineIconListItem = _ListItem
    kivymd_list.IconLeftWidget = _IconLeftWidget
    kivymd_menu = types.ModuleType("kivymd.uix.menu")

    class _Menu:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.opened = False

        def open(self):
            self.opened = True

        def dismiss(self):
            self.opened = False

    kivymd_menu.MDDropdownMenu = _Menu

    sys.modules.update(
        {
            "kivy": kivy,
            "kivy.clock": kivy_clock,
            "kivy.metrics": kivy_metrics,
            "kivy.core": kivy_core,
            "kivy.core.clipboard": kivy_clipboard,
            "kivymd": kivymd,
            "kivymd.uix": kivymd_uix,
            "kivymd.uix.list": kivymd_list,
            "kivymd.uix.menu": kivymd_menu,
        }
    )


_install_kivy_stubs()

from features.favorites.controller import FavoritesControllerMixin


class _Ids(dict):
    __getattr__ = dict.__getitem__


class _Root:
    def __init__(self, home):
        self._home = home

    def get_screen(self, name):
        if name != "home":
            raise KeyError(name)
        return self._home


class _CharField:
    def __init__(self):
        self.text = ""


class _Nav:
    def __init__(self):
        self.switched = None

    def switch_tab(self, name):
        self.switched = name


class DummyFavoritesApp(FavoritesControllerMixin):
    def __init__(self):
        self.home = SimpleNamespace(ids=_Ids(char_name=_CharField(), bottom_nav=_Nav(), fav_list=SimpleNamespace()))
        self.root = _Root(self.home)
        self.favorites = ["Knight One", "Mage Two"]
        self.cache = {}
        self._fav_status_cache = {}
        self._fav_world_cache = {}
        self._fav_items = {}
        self.saved = 0
        self.refreshed = 0
        self.service_sync = 0
        self.toasts = []
        self.search_calls = 0

    def toast(self, message: str):
        self.toasts.append(message)

    def _cache_get(self, key, ttl_seconds=None):
        return self.cache.get(key)

    def _cache_set(self, key, value):
        self.cache[key] = value

    def save_favorites(self):
        self.saved += 1

    def refresh_favorites_list(self, *args, **kwargs):
        self.refreshed += 1

    def _maybe_start_fav_monitor_service(self):
        self.service_sync += 1

    def search_character(self, *args, **kwargs):
        self.search_calls += 1

    def _set_cached_last_seen_online_iso(self, name, value):
        self.cache[f"seen:{name.lower()}"] = value

    def _set_cached_offline_since_iso(self, name, value):
        self.cache[f"off:{name.lower()}"] = value

    def _get_cached_last_seen_online_iso(self, name):
        return self.cache.get(f"seen:{name.lower()}")

    def _get_cached_offline_since_iso(self, name):
        return self.cache.get(f"off:{name.lower()}")

    def _format_ago_short(self, dt):
        return "há pouco"


class FavoritesControllerTests(unittest.TestCase):
    def test_status_presentation_uses_offline_duration(self):
        app = DummyFavoritesApp()
        label, color = app._fav_status_presentation("offline", offline_since_iso="2026-03-06T10:00:00")
        self.assertEqual(label, "Offline • há pouco")
        self.assertEqual(color, (0.95, 0.3, 0.3, 1))

    @patch("features.favorites.controller.webbrowser.open")
    def test_open_fav_on_site_quotes_name(self, mock_open):
        app = DummyFavoritesApp()
        app._open_fav_on_site("Knight One")
        mock_open.assert_called_once()
        self.assertIn("Knight+One", mock_open.call_args.args[0])

    @patch("features.favorites.controller.Clipboard.copy")
    def test_copy_fav_name_calls_clipboard_and_toast(self, mock_copy):
        app = DummyFavoritesApp()
        app._copy_fav_name("Knight One")
        mock_copy.assert_called_once_with("Knight One")
        self.assertEqual(app.toasts[-1], "Nome copiado.")

    def test_remove_favorite_is_case_insensitive_and_refreshes(self):
        app = DummyFavoritesApp()
        app._remove_favorite("knight one")
        self.assertEqual(app.favorites, ["Mage Two"])
        self.assertEqual(app.saved, 1)
        self.assertEqual(app.service_sync, 1)
        self.assertEqual(app.refreshed, 1)
        self.assertEqual(app.toasts[-1], "Removido dos favoritos.")

    def test_open_fav_in_app_switches_tab_and_searches(self):
        app = DummyFavoritesApp()
        app._open_fav_in_app("Knight One")
        self.assertEqual(app.home.ids.bottom_nav.switched, "tab_char")
        self.assertEqual(app.home.ids.char_name.text, "Knight One")
        self.assertEqual(app.search_calls, 1)


if __name__ == "__main__":
    unittest.main()
