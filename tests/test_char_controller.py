import sys
import types
import unittest
from types import SimpleNamespace


def _install_kivy_stubs():
    kivy = sys.modules.get("kivy") or types.ModuleType("kivy")
    kivy.__path__ = []
    kivy_clock = types.ModuleType("kivy.clock")
    kivy_clock.Clock = SimpleNamespace(schedule_once=lambda fn, dt=0: fn(0))
    kivy_metrics = types.ModuleType("kivy.metrics")
    kivy_metrics.dp = lambda value: value

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
            "kivymd": kivymd,
            "kivymd.uix": kivymd_uix,
            "kivymd.uix.list": kivymd_list,
            "kivymd.uix.menu": kivymd_menu,
        }
    )


_install_kivy_stubs()

from features.char.controller import CharControllerMixin


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
    def __init__(self, text=""):
        self.text = text
        self.focus = False


class DummyCharApp(CharControllerMixin):
    def __init__(self):
        self.char_field = _CharField()
        self.home = SimpleNamespace(ids=_Ids(char_name=self.char_field))
        self.root = _Root(self.home)
        self.search_calls = 0
        self.prefs = {}
        self.favorites = ["Knight One", "mage two"]

    def search_character(self, *args, **kwargs):
        self.search_calls += 1

    def _prefs_get(self, key, default=None):
        return self.prefs.get(key, default)

    def _prefs_set(self, key, value):
        self.prefs[key] = value

    def toast(self, message: str):
        self.last_toast = message


class CharControllerTests(unittest.TestCase):
    def test_clear_char_search_resets_text_and_focuses(self):
        app = DummyCharApp()
        app.char_field.text = "Eternal Oblivion"
        app.clear_char_search()
        self.assertEqual(app.char_field.text, "")
        self.assertTrue(app.char_field.focus)

    def test_open_char_from_account_list_populates_field_and_searches(self):
        app = DummyCharApp()
        app.open_char_from_account_list("Sorcerer X")
        self.assertEqual(app.char_field.text, "Sorcerer X")
        self.assertFalse(app.char_field.focus)
        self.assertEqual(app.search_calls, 1)

    def test_get_and_add_char_history_normalize_values(self):
        app = DummyCharApp()
        app.prefs["char_history"] = [" Alpha ", "", None, 123]
        self.assertEqual(app._get_char_history(), ["Alpha", "123"])
        app._add_to_char_history("alpha")
        self.assertEqual(app.prefs["char_history"][0], "alpha")
        self.assertEqual(len(app.prefs["char_history"]), 2)

    def test_shorten_death_reason_compacts_killers(self):
        app = DummyCharApp()
        reason = "Slain at Level 100 by Dragon, Demon and Hero."
        self.assertEqual(app._shorten_death_reason(reason), "Slain by Dragon +2")

    def test_safe_helpers(self):
        app = DummyCharApp()
        self.assertIsNotNone(app._safe_parse_iso_datetime("2026-03-06T10:00:00"))
        self.assertIsNone(app._safe_parse_iso_datetime("not-a-date"))
        self.assertEqual(app._safe_int("42"), 42)
        self.assertIsNone(app._safe_int("NaN"))
        self.assertEqual(app._favorite_names_set(), {"knight one", "mage two"})


if __name__ == "__main__":
    unittest.main()
