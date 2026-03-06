import types
import unittest
from unittest.mock import patch

from features.settings.controller import SettingsControllerMixin


class _Ids(dict):
    __getattr__ = dict.__getitem__


class _DummyField:
    def __init__(self, text='', active=False):
        self.text = text
        self.active = active


class _DummyScreen:
    def __init__(self):
        self.ids = _Ids(
            set_theme_light=_DummyField(active=False),
            set_notify_boosted=_DummyField(active=True),
            set_notify_boss_high=_DummyField(active=True),
            set_repo_url=_DummyField(text='https://github.com/openai/example-repo'),
            set_status=_DummyField(text=''),
            set_bg_monitor=_DummyField(active=True),
            set_bg_notify_online=_DummyField(active=True),
            set_bg_notify_level=_DummyField(active=True),
            set_bg_notify_death=_DummyField(active=True),
            set_bg_interval=_DummyField(text='30'),
            set_bg_autostart=_DummyField(active=True),
        )


class _DummyRoot:
    def __init__(self, screen):
        self._screen = screen

    def get_screen(self, name):
        if name != 'settings':
            raise KeyError(name)
        return self._screen


class DummySettingsApp(SettingsControllerMixin):
    def __init__(self):
        self.screen = _DummyScreen()
        self.root = _DummyRoot(self.screen)
        self.theme_cls = types.SimpleNamespace(theme_style='Dark')
        self.data_dir = '.'
        self.prefs = {
            'theme_style': 'Dark',
            'notify_boosted': True,
            'notify_boss_high': True,
            'repo_url': 'https://github.com/openai/example-repo',
            'last_release': 'v1.0.0',
        }
        self.toast_messages = []
        self.dialogs = []
        self.cache_cleared = False
        self.bg_synced = False

    def _prefs_get(self, key, default=None):
        return self.prefs.get(key, default)

    def _prefs_set(self, key, value):
        self.prefs[key] = value

    def _show_text_dialog(self, title, text):
        self.dialogs.append((title, text))

    def toast(self, message):
        self.toast_messages.append(message)

    def _cache_clear(self):
        self.cache_cleared = True

    def _sync_bg_monitor_state_from_ui(self):
        self.bg_synced = True


class SettingsControllerTests(unittest.TestCase):
    def test_settings_open_releases(self):
        app = DummySettingsApp()
        with patch('features.settings.controller.webbrowser.open') as mock_open:
            app.settings_open_releases()
        mock_open.assert_called_once_with('https://github.com/openai/example-repo/releases')

    def test_updates_done_with_new_release(self):
        app = DummySettingsApp()
        with patch('features.settings.controller.webbrowser.open') as mock_open:
            app._updates_done('v1.1.0', 'https://github.com/openai/example-repo/releases/tag/v1.1.0', 'v1.0.0')
        self.assertEqual(app.screen.ids.set_status.text, 'Nova versão: v1.1.0')
        self.assertTrue(app.dialogs)
        mock_open.assert_called_once()

    def test_settings_save_updates_prefs_and_ui(self):
        app = DummySettingsApp()
        app.screen.ids.set_theme_light.active = True
        app.screen.ids.set_repo_url.text = 'https://github.com/openai/new-repo'
        app.settings_save()
        self.assertEqual(app.prefs['theme_style'], 'Light')
        self.assertEqual(app.theme_cls.theme_style, 'Light')
        self.assertTrue(app.bg_synced)
        self.assertIn('Configurações salvas.', app.toast_messages)

    def test_settings_clear_cache(self):
        app = DummySettingsApp()
        app.settings_clear_cache()
        self.assertTrue(app.cache_cleared)
        self.assertEqual(app.screen.ids.set_status.text, 'Cache limpo.')


if __name__ == '__main__':
    unittest.main()
