import unittest

from core.training import TrainingInput, compute_training_plan


class TrainingTests(unittest.TestCase):
    def test_compute_training_plan_basic(self):
        plan = compute_training_plan(
            TrainingInput(
                skill="Sword",
                vocation="Knight",
                from_level=100,
                to_level=101,
                weapon_kind="Standard (500)",
                percent_left=50,
            )
        )
        self.assertTrue(plan.ok)
        self.assertGreater(plan.total_charges, 0)
        self.assertGreater(plan.weapons, 0)
        self.assertGreater(plan.hours, 0)
        self.assertGreater(plan.total_cost_gp, 0)

    def test_rejects_invalid_target(self):
        plan = compute_training_plan(
            TrainingInput(
                skill="Magic Level",
                vocation="Sorcerer",
                from_level=10,
                to_level=10,
                weapon_kind="Standard (500)",
                percent_left=100,
            )
        )
        self.assertFalse(plan.ok)
        self.assertIn("maior", plan.error.lower())


if __name__ == "__main__":
    unittest.main()
