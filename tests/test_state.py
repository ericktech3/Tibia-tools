import tempfile
import unittest

from core import state


class StateTests(unittest.TestCase):
    def test_add_and_remove_favorite(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok, msg, favs = state.add_favorite(tmp, "Erick")
            self.assertTrue(ok)
            self.assertIn("Erick", favs)

            st = state.load_state(tmp)
            self.assertEqual(st["favorites"], ["Erick"])

            ok, msg, favs = state.remove_favorite(tmp, "Erick")
            self.assertTrue(ok)
            self.assertEqual(favs, [])
            st = state.load_state(tmp)
            self.assertEqual(st["favorites"], [])

    def test_load_state_migrates_plain_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = state.state_path(tmp)
            with open(path, "w", encoding="utf-8") as f:
                f.write('["A", "B"]')
            st = state.load_state(tmp)
            self.assertEqual(st["favorites"], ["A", "B"])
            self.assertIn("interval_seconds", st)


if __name__ == "__main__":
    unittest.main()
