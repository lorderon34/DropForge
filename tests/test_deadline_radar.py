import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from deadline_radar import rank_deadline_candidates, rank_for_session


NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


def make_drop(name, required_minutes, *, starts_in=0, ends_in=240, claimed=False):
    return SimpleNamespace(
        name=name,
        is_claimed=claimed,
        total_remaining_minutes=required_minutes,
        starts_at=NOW + timedelta(minutes=starts_in),
        ends_at=NOW + timedelta(minutes=ends_in),
    )


def make_campaign(name, game, drops, *, active=True, eligible=True, finished=False):
    return SimpleNamespace(
        name=name,
        game=SimpleNamespace(name=game),
        drops=drops,
        active=active,
        eligible=eligible,
        finished=finished,
    )


class DeadlineRadarTests(unittest.TestCase):
    def test_ranks_lowest_time_margin_first(self):
        comfortable = make_campaign("Comfortable", "A", [make_drop("A drop", 60, ends_in=360)])
        tight = make_campaign("Tight", "B", [make_drop("B drop", 60, ends_in=90)])
        impossible = make_campaign("At risk", "C", [make_drop("C drop", 120, ends_in=60)])

        result = rank_deadline_candidates(
            [comfortable, tight, impossible], now=NOW, limit=None
        )

        self.assertEqual([item.campaign.name for item in result], ["At risk", "Tight", "Comfortable"])
        self.assertEqual(result[0].margin_ratio, 0.5)
        self.assertEqual(result[1].margin_ratio, 1.5)

    def test_uses_drop_deadline_and_prerequisite_time_for_tightest_drop(self):
        campaign = make_campaign(
            "Launch Week",
            "Starfall",
            [
                make_drop("Long window", 45, ends_in=240),
                make_drop("Early expiry", 30, ends_in=45),
            ],
        )

        candidate = rank_deadline_candidates([campaign], now=NOW)[0]

        self.assertEqual(candidate.drop.name, "Early expiry")
        self.assertEqual(candidate.required_minutes, 30)
        self.assertEqual(candidate.available_minutes, 45)
        self.assertEqual(candidate.deadline, NOW + timedelta(minutes=45))

    def test_future_drop_window_starts_at_its_start_time(self):
        campaign = make_campaign(
            "Starts later",
            "Starfall",
            [make_drop("Future drop", 60, starts_in=120, ends_in=300)],
        )

        candidate = rank_deadline_candidates([campaign], now=NOW)[0]

        self.assertEqual(candidate.available_minutes, 180)
        self.assertEqual(candidate.margin_ratio, 3.0)

    def test_skips_unavailable_campaigns_and_claimed_or_expired_drops(self):
        active = make_campaign(
            "Active",
            "Starfall",
            [
                make_drop("Claimed", 0, claimed=True),
                make_drop("Expired", 60, ends_in=-1),
                make_drop("Available", 60, ends_in=90),
            ],
        )
        campaigns = [
            active,
            make_campaign("Unlinked", "Other", [make_drop("Drop", 60)], eligible=False),
            make_campaign("Upcoming", "Other", [make_drop("Drop", 60)], active=False),
            make_campaign("Finished", "Other", [make_drop("Drop", 60)], finished=True),
            make_campaign("Excluded", "Ignored", [make_drop("Drop", 60)]),
        ]

        result = rank_deadline_candidates(
            campaigns,
            excluded_games={"Ignored"},
            now=NOW,
            limit=None,
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].drop.name, "Available")

    def test_limit_is_applied_after_urgency_sort(self):
        campaigns = [
            make_campaign(str(index), str(index), [make_drop("Drop", 60, ends_in=360 - index * 60)])
            for index in range(5)
        ]

        result = rank_deadline_candidates(campaigns, now=NOW, limit=2)

        self.assertEqual([item.campaign.name for item in result], ["4", "3"])
        self.assertEqual(rank_deadline_candidates(campaigns, now=NOW, limit=0), [])

    def test_session_fit_moves_completable_rewards_ahead_of_urgent_ones(self):
        candidates = rank_deadline_candidates(
            [
                make_campaign("Urgent", "A", [make_drop("Long", 120, ends_in=130)]),
                make_campaign("Fits", "B", [make_drop("Short", 45, ends_in=180)]),
                make_campaign("Deadline miss", "C", [make_drop("Late", 60, ends_in=50)]),
            ],
            now=NOW,
            limit=None,
        )

        result = rank_for_session(candidates, session_minutes=60)

        self.assertEqual([item.candidate.campaign.name for item in result], ["Fits", "Deadline miss", "Urgent"])
        self.assertTrue(result[0].fits_session)
        self.assertFalse(result[1].fits_session)
        self.assertEqual(result[1].difference_minutes, 10)
        self.assertEqual(result[2].difference_minutes, 60)


if __name__ == "__main__":
    unittest.main()
