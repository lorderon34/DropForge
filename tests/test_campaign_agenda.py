import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from campaign_agenda import (
    CampaignAgendaEvent,
    build_campaign_agenda,
    serialize_campaign_calendar,
)


NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)


def hours_from_now(hours):
    return NOW + timedelta(hours=hours)


def make_drop(name, starts_in, ends_in, *, claimed=False, required_minutes=60):
    return SimpleNamespace(
        id=name,
        name=name,
        rewards_text=lambda: name,
        starts_at=hours_from_now(starts_in),
        ends_at=hours_from_now(ends_in),
        is_claimed=claimed,
        required_minutes=required_minutes,
    )


def make_campaign(name, starts_in, ends_in, drops=(), *, expired=False, finished=False, eligible=True):
    return SimpleNamespace(
        id=name,
        name=name,
        game=SimpleNamespace(name=name),
        starts_at=hours_from_now(starts_in),
        ends_at=hours_from_now(ends_in),
        drops=drops,
        expired=expired,
        finished=finished,
        eligible=eligible,
    )


class CampaignAgendaTests(unittest.TestCase):
    def test_sorts_campaign_events_and_places_deadline_first_at_equal_time(self):
        active = make_campaign("Current", -12, 2)
        upcoming = make_campaign("Next", 2, 20)
        events = build_campaign_agenda([upcoming, active], now=NOW, days=1)

        self.assertEqual(
            [(event.campaign.name, event.kind, event.when, event.drop) for event in events],
            [
                ("Current", "ends", hours_from_now(2), None),
                ("Next", "starts", hours_from_now(2), None),
                ("Next", "ends", hours_from_now(20), None),
            ],
        )

    def test_limits_to_future_events_including_the_end_of_the_selected_period(self):
        starts_now = make_campaign("Now", 0, 24)
        ends_now = make_campaign("Past", -5, 0)
        starts_on_horizon = make_campaign("Tomorrow", 24, 25)
        starts_later = make_campaign("Later", 25, 48)
        events = build_campaign_agenda(
            [starts_now, ends_now, starts_on_horizon, starts_later], now=NOW, days=1
        )

        self.assertEqual(
            [(event.campaign.name, event.kind) for event in events],
            [("Now", "ends"), ("Tomorrow", "starts")],
        )
        self.assertEqual(build_campaign_agenda([starts_now], now=NOW, days=0), ())

    def test_includes_distinct_drop_dates_inside_campaign_window(self):
        starts_late = make_drop("Late start", 3, 20)
        ends_early = make_drop("Early end", -1, 10)
        matching = make_drop("Same window", 1, 20)
        outside = make_drop("After campaign", 21, 22)
        campaign = make_campaign("Upcoming", 1, 20, [starts_late, ends_early, matching, outside])
        events = build_campaign_agenda([campaign], now=NOW, days=1)

        self.assertEqual(
            [(event.kind, event.when, event.drop) for event in events],
            [
                ("starts", hours_from_now(1), None),
                ("starts", hours_from_now(3), starts_late),
                ("ends", hours_from_now(10), ends_early),
                ("ends", hours_from_now(20), None),
            ],
        )

    def test_ignores_claimed_and_untimed_drops_but_keeps_unlinked_campaigns(self):
        untimed = make_drop("Untimed", 1, 3, required_minutes=0)
        claimed = make_drop("Claimed", 1, 3, claimed=True)
        pending = make_drop("Pending", -2, 5)
        unlinked = make_campaign("Unlinked", -2, 5, [untimed, claimed, pending], eligible=False)
        expired = make_campaign("Invalid", 1, 3, expired=True)
        finished = make_campaign("Finished", 1, 3, finished=True)
        invalid_window = make_campaign("Invalid window", 8, 4)
        events = build_campaign_agenda([unlinked, expired, finished, invalid_window], now=NOW, days=1)

        self.assertEqual([(event.campaign.name, event.drop) for event in events], [("Unlinked", None)])


class CampaignCalendarTests(unittest.TestCase):
    def test_exports_localized_drop_marker_using_utc(self):
        local_zone = timezone(timedelta(hours=-3))
        campaign = make_campaign("Temporada", 0, 12)
        campaign.game.name = "Jogo"
        drop = make_drop("Nome interno do Drop", 0, 2)
        drop.rewards_text = lambda: "Distintivo"
        event = CampaignAgendaEvent(campaign, hours_from_now(2).astimezone(local_zone), "ends", drop)

        calendar = serialize_campaign_calendar(
            [event], stamp=NOW.astimezone(local_zone), event_label=lambda kind: {"ends": "Término"}[kind]
        )
        lines = calendar.decode("utf-8").split("\r\n")

        self.assertEqual(
            lines[:4],
            ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//DropForge//Campaign Agenda//EN", "BEGIN:VEVENT"],
        )
        self.assertIn("DTSTAMP:20261117T120000Z", lines)
        self.assertIn("DTSTART:20261117T140000Z", lines)
        self.assertIn("SUMMARY:Término · Jogo — Temporada · Distintivo", lines)
        self.assertIn("DESCRIPTION:Distintivo", lines)
        self.assertIn("TRANSP:TRANSPARENT", lines)
        self.assertEqual(lines[-3:], ["END:VEVENT", "END:VCALENDAR", ""])

    def test_escapes_text_and_folds_without_splitting_utf8(self):
        campaign = make_campaign("Evento; A\\B\r\n" + "🚀" * 46, 0, 12)
        campaign.game.name = "Jogo, edição"
        drop = make_drop("Recompensa; edição, final", 0, 2)
        drop.rewards_text = lambda: ""
        event = CampaignAgendaEvent(campaign, hours_from_now(2), "ends", drop)

        calendar = serialize_campaign_calendar([event], stamp=NOW, event_label=lambda _kind: "Término")
        lines = calendar.split(b"\r\n")

        self.assertTrue(any(line.startswith(b" ") for line in lines))
        for line in lines:
            self.assertLessEqual(len(line), 75)
            line.decode("utf-8")
        unfolded = calendar.replace(b"\r\n ", b"").decode("utf-8")
        self.assertIn("SUMMARY:Término · Jogo\\, edição — Evento\\; A\\\\B\\n" + "🚀" * 46, unfolded)
        self.assertIn(" · Recompensa\\; edição\\, final\r\n", unfolded)
        self.assertIn("DESCRIPTION:Recompensa\\; edição\\, final", unfolded)

    def test_keeps_uid_for_same_boundary_across_time_and_label_updates(self):
        campaign = make_campaign("Temporada", 1, 12)
        drop = make_drop("Drop", 2, 4)
        events = [
            CampaignAgendaEvent(campaign, hours_from_now(1), "starts"),
            CampaignAgendaEvent(campaign, hours_from_now(12), "ends"),
            CampaignAgendaEvent(campaign, hours_from_now(2), "starts", drop),
            CampaignAgendaEvent(campaign, hours_from_now(4), "ends", drop),
        ]

        def uids(events, stamp, label):
            payload = serialize_campaign_calendar(events, stamp=stamp, event_label=label)
            return [line for line in payload.split(b"\r\n") if line.startswith(b"UID:")]

        original = uids(events, NOW, lambda kind: kind)
        campaign.name = "Evento renomeado"
        rescheduled = CampaignAgendaEvent(campaign, hours_from_now(2), "starts")

        self.assertEqual(len(set(original)), 4)
        self.assertEqual(uids([rescheduled], hours_from_now(1), lambda _kind: "Início"), original[:1])


if __name__ == "__main__":
    unittest.main()
