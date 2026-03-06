import tempfile
import threading
import unittest
from pathlib import Path

from services.persistence import PersistenceService


class _FakeApp:
    def __init__(self, base_dir: str):
        self.prefs_path = str(Path(base_dir) / 'prefs.json')
        self.cache_path = str(Path(base_dir) / 'cache.json')
        self.prefs = {}
        self.cache = {}
        self._prefs_lock = threading.Lock()
        self._cache_lock = threading.Lock()
        self._prefs_dirty = False
        self._cache_dirty = False
        self._disk_event = threading.Event()
        self._disk_stop = threading.Event()


class PersistenceServiceTests(unittest.TestCase):
    def test_prefs_set_and_flush_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _FakeApp(tmp)
            service = PersistenceService(app)

            service.prefs_set('theme', 'dark')
            service.cache_set('fav_status:erick', 'online')
            service.flush_prefs_to_disk(force=True)
            service.flush_cache_to_disk(force=True)

            self.assertFalse(app._prefs_dirty)
            self.assertFalse(app._cache_dirty)
            self.assertIn('theme', Path(app.prefs_path).read_text(encoding='utf-8'))
            self.assertIn('fav_status:erick', Path(app.cache_path).read_text(encoding='utf-8'))

    def test_cache_get_respects_ttl(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = _FakeApp(tmp)
            service = PersistenceService(app)
            service.cache_set('boosted', {'name': 'Dragon'})
            self.assertEqual(service.cache_get('boosted', ttl_seconds=60), {'name': 'Dragon'})
            self.assertIsNone(service.cache_get('boosted', ttl_seconds=-1))


if __name__ == '__main__':
    unittest.main()
