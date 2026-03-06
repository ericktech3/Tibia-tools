import tempfile
import unittest
from pathlib import Path

from core.storage import safe_read_json, safe_write_json


class StorageTests(unittest.TestCase):
    def test_safe_write_and_read_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'nested' / 'data.json'
            self.assertTrue(safe_write_json(str(path), {'ok': True}))
            self.assertEqual(safe_read_json(str(path), default={}), {'ok': True})

    def test_safe_read_invalid_json_returns_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'broken.json'
            path.write_text('{oops', encoding='utf-8')
            self.assertEqual(safe_read_json(str(path), default=[]), [])


if __name__ == '__main__':
    unittest.main()
