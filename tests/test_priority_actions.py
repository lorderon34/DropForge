import unittest

from priority_actions import add_game_to_priority, remove_game_from_priority


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

    def test_removes_all_duplicates_and_preserves_other_games_in_order(self):
        priority = ["Remove", "First", "Remove", "Second"]
        self.assertTrue(remove_game_from_priority("Remove", priority))
        self.assertEqual(priority, ["First", "Second"])
        self.assertFalse(remove_game_from_priority("Remove", priority))
        self.assertEqual(priority, ["First", "Second"])


if __name__ == "__main__":
    unittest.main()
