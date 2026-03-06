import unittest

from service.main import import_core_modules


class ServiceImportTests(unittest.TestCase):
    def test_service_imports_current_modules(self):
        state_mod, tibia_mod, prefix = import_core_modules()
        self.assertEqual(prefix, 'integrations')
        self.assertTrue(hasattr(state_mod, 'load_state'))
        self.assertTrue(hasattr(tibia_mod, 'fetch_character_world'))
        self.assertTrue(hasattr(tibia_mod, 'fetch_world_online_players'))


if __name__ == '__main__':
    unittest.main()
