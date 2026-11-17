import unittest
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from diagnostics import diagnose_campaigns


NOW = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)


@dataclass
class FakeGame:
    name: str


@dataclass
class FakeDrop:
    required_minutes: int = 30
    is_claimed: bool = False
    starts_at: datetime = NOW - timedelta(hours=1)
    ends_at: datetime = NOW + timedelta(hours=2)
    preconditions_met: bool = True
    extra_current_minutes: int = 0


@dataclass
class FakeCampaign:
    name: str = "Campaign"
    game: FakeGame = field(default_factory=lambda: FakeGame("Game"))
    upcoming: bool = False
    expired: bool = False
    finished: bool = False
    eligible: bool = True
    has_badge_or_emote: bool = False
    earnable: bool = True
    drops: list[FakeDrop] = field(default_factory=lambda: [FakeDrop()])

    def can_earn_within(self, _stamp):
        return self.earnable


class CampaignDiagnosticsTests(unittest.TestCase):
    def diagnose(self, campaign, **overrides):
        options = {
            "priority_games": [],
            "excluded_games": [],
            "priority_only": False,
            "now": NOW,
        }
        options.update(overrides)
        return diagnose_campaigns([campaign], **options)[0].reason

    def test_priority_only_reports_missing_game(self):
        self.assertEqual(
            self.diagnose(FakeCampaign(), priority_only=True, priority_games=["Other"]),
            "priority",
        )

    def test_exclusion_is_reported_before_priority_filter(self):
        self.assertEqual(
            self.diagnose(
                FakeCampaign(),
                priority_only=True,
                priority_games=["Game"],
                excluded_games=["Game"],
            ),
            "excluded",
        )

    def test_account_and_partial_badge_support_are_distinguished(self):
        self.assertEqual(self.diagnose(FakeCampaign(eligible=False)), "not_linked")
        self.assertEqual(
            self.diagnose(FakeCampaign(eligible=False, has_badge_or_emote=True)),
            "badges_disabled",
        )

    def test_lifecycle_statuses_are_reported(self):
        self.assertEqual(self.diagnose(FakeCampaign(upcoming=True)), "upcoming")
        self.assertEqual(self.diagnose(FakeCampaign(expired=True)), "expired")
        self.assertEqual(self.diagnose(FakeCampaign(finished=True)), "finished")

    def test_eligible_campaign_has_no_blocking_reason(self):
        self.assertIsNone(self.diagnose(FakeCampaign()))

    def test_drop_schedule_and_dependency_reasons(self):
        late_drop = FakeDrop(starts_at=NOW + timedelta(hours=2))
        self.assertEqual(
            self.diagnose(FakeCampaign(earnable=False, drops=[late_drop])),
            "drop_starts_later",
        )
        blocked_drop = FakeDrop(preconditions_met=False)
        self.assertEqual(
            self.diagnose(FakeCampaign(earnable=False, drops=[blocked_drop])),
            "waiting_for_previous",
        )

    def test_expired_drop_and_unsynced_progress_are_reported(self):
        expired_drop = FakeDrop(ends_at=NOW - timedelta(minutes=1))
        self.assertEqual(
            self.diagnose(FakeCampaign(earnable=False, drops=[expired_drop])),
            "drop_expired",
        )
        capped_drop = FakeDrop(extra_current_minutes=10_000)
        self.assertEqual(
            self.diagnose(FakeCampaign(earnable=False, drops=[capped_drop])),
            "progress_sync",
        )


if __name__ == "__main__":
    unittest.main()
