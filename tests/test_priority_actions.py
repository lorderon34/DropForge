import unittest

from priority_actions import add_game_to_priority


class PriorityActionsTests(unittest.TestCase):
    def test_adds_a_new_game(self):
        priority = ["Existing"]
        self.assertTrue(add_game_to_priority("New Game", priority, set()))
        self.assertEqual(priority, ["Existing", "New Game"])

    def test_does_not_add_duplicates_or_empty_names(self):
        priority = ["Existing"]
        self.assertFalse(add_game_to_priority("Existing", priority, set()))
        self.assertFalse(add_game_to_priority("", priority, set()))
        self.assertEqual(priority, ["Existing"])

    def test_does_not_override_the_exclude_list(self):
        priority = []
        self.assertFalse(add_game_to_priority("Excluded", priority, {"Excluded"}))
        self.assertEqual(priority, [])


if __name__ == "__main__":
    unittest.main()
