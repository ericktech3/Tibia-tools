import unittest

from core.hunt import parse_hunt_session_text


class HuntTests(unittest.TestCase):
    def test_parse_hunt_session_text(self):
        text = """Loot: 1,234,567
Supplies: 234,567
Balance: 1,000,000
XP Gain: 3,600,000
Raw XP Gain: 2,000,000
Session Time: 01:30h"""
        result = parse_hunt_session_text(text)
        self.assertTrue(result.ok)
        self.assertIn("Profit/h", result.pretty)
        self.assertIn("XP/h", result.pretty)
        self.assertIn("1.000.000 gp", result.pretty)

    def test_invalid_hunt_text(self):
        result = parse_hunt_session_text("nada util aqui")
        self.assertFalse(result.ok)


if __name__ == "__main__":
    unittest.main()
