import unittest

from core.stamina import BONUS_START_MIN, compute_offline_regen, format_hm, parse_hm_text


class StaminaTests(unittest.TestCase):
    def test_parse_and_format(self):
        total = parse_hm_text("38", "30")
        self.assertEqual(total, 38 * 60 + 30)
        self.assertEqual(format_hm(total), "38:30")

    def test_offline_regen_crossing_green_zone(self):
        current = 38 * 60 + 30
        target = BONUS_START_MIN + 30
        result = compute_offline_regen(current, target)
        self.assertEqual(result.regen_offline_only_min, 270)
        self.assertEqual(result.offline_needed_min, 280)


if __name__ == "__main__":
    unittest.main()
