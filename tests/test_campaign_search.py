import unittest
from dataclasses import dataclass, field

from campaign_search import campaign_matches_search, passes_game_filter


@dataclass
class FakeGame:
    name: str


@dataclass
class FakeDrop:
    name: str
    reward: str

    def rewards_text(self):
        return self.reward


@dataclass
class FakeCampaign:
    game: FakeGame = field(default_factory=lambda: FakeGame("Starfall"))
    name: str = "Launch Week"
    drops: list[FakeDrop] = field(
        default_factory=lambda: [FakeDrop("Day 1", "Moonlit Badge")]
    )


class CampaignSearchTests(unittest.TestCase):
    def setUp(self):
        self.campaign = FakeCampaign()

    def test_matches_game_campaign_drop_and_reward_names(self):
        for query in ("starfall", "launch week", "day 1", "moonlit badge"):
            with self.subTest(query=query):
                self.assertTrue(campaign_matches_search(self.campaign, query))

    def test_search_is_case_insensitive_and_ignores_outer_spaces(self):
        self.assertTrue(campaign_matches_search(self.campaign, "  MOONLIT "))

    def test_empty_or_missing_query_does_not_filter(self):
        self.assertTrue(campaign_matches_search(self.campaign, ""))
        self.assertTrue(campaign_matches_search(self.campaign, "  "))
        self.assertFalse(campaign_matches_search(self.campaign, "missing"))


class InventoryGameFilterTests(unittest.TestCase):
    def test_search_reveals_games_outside_priority_only(self):
        self.assertTrue(
            passes_game_filter(
                "Other",
                query="other",
                priority_games=["Favorite"],
                excluded_games=set(),
                priority_only=True,
                show_excluded=False,
            )
        )

    def test_search_does_not_override_explicit_exclusion(self):
        self.assertFalse(
            passes_game_filter(
                "Blocked",
                query="blocked",
                priority_games=[],
                excluded_games={"Blocked"},
                priority_only=True,
                show_excluded=False,
            )
        )

    def test_show_excluded_filter_exposes_excluded_games(self):
        self.assertTrue(
            passes_game_filter(
                "Blocked",
                query="",
                priority_games=[],
                excluded_games={"Blocked"},
                priority_only=True,
                show_excluded=True,
            )
        )


if __name__ == "__main__":
    unittest.main()
