import unittest

from ui.kv_loader import FALLBACK_KV, KV_PARTS, get_combined_kv_text


class KvLoaderTests(unittest.TestCase):
    def test_combined_kv_contains_root_content(self):
        text = get_combined_kv_text()
        self.assertIn('RootSM:', text)
        self.assertIn('BossFavoritesScreen:', text)

    def test_fallback_stays_as_emergency_copy(self):
        self.assertIn('RootSM:', FALLBACK_KV)
        self.assertGreaterEqual(len(KV_PARTS), 5)


if __name__ == '__main__':
    unittest.main()
