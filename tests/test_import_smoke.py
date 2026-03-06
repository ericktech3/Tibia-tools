import importlib
import unittest


class ImportSmokeTests(unittest.TestCase):
    def test_import_core_and_integrations_modules(self):
        modules = [
            "core.state",
            "core.storage",
            "integrations.tibiadata",
            "integrations.exevopan",
            "integrations.tibia_com",
            "integrations.github_releases",
            "repositories.favorites_repo",
            "services.error_reporting",
            "services.release_service",
            "features.settings.controller",
            "service.main",
            "ui.kv_loader",
        ]
        for name in modules:
            with self.subTest(module=name):
                self.assertIsNotNone(importlib.import_module(name))


if __name__ == "__main__":
    unittest.main()
