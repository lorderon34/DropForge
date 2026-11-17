import asyncio
import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from tkinter import Tk, font, ttk
from unittest.mock import patch

from claim_history import ClaimHistoryStore
from inventory import BaseDrop
from translate import _
from gui import AchievementJournal


class ClaimHistoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name, "drop-history.json")
        self.store = ClaimHistoryStore(self.path)
        self.campaign = SimpleNamespace(
            id="campaign-1",
            name="Launch Event",
            game=SimpleNamespace(name="Starfall"),
        )
        self.drop = SimpleNamespace(
            id="drop-1",
            rewards_text=lambda: "Moonlit Badge",
        )
        self.claimed_at = datetime(2026, 11, 16, 12, 30, tzinfo=timezone.utc)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_persists_confirmed_claims_without_user_identifiers(self):
        record = self.store.record_claim(
            self.campaign,
            self.drop,
            claimed_at=self.claimed_at,
        )
        loaded = ClaimHistoryStore(self.path)

        self.assertEqual(record.record_id, "campaign-1:drop-1")
        self.assertEqual(record.game, "Starfall")
        self.assertEqual(loaded.records, (record,))
        file_text = self.path.read_text(encoding="utf8")
        self.assertIn("Moonlit Badge", file_text)
        self.assertNotIn("user_id", file_text.casefold())
        self.assertNotIn("token", file_text.casefold())

    def test_duplicate_claims_are_ignored(self):
        self.store.record_claim(self.campaign, self.drop, claimed_at=self.claimed_at)

        duplicate = self.store.record_claim(
            self.campaign,
            self.drop,
            claimed_at=self.claimed_at + timedelta(minutes=1),
        )

        self.assertIsNone(duplicate)
        self.assertEqual(len(self.store.records), 1)

    def test_history_is_bounded_to_the_most_recent_records(self):
        self.store.MAX_RECORDS = 2
        for index in range(3):
            campaign = SimpleNamespace(
                id=f"campaign-{index}",
                name=f"Campaign {index}",
                game=SimpleNamespace(name="Starfall"),
            )
            drop = SimpleNamespace(id=f"drop-{index}", rewards_text=lambda: "Reward")
            self.store.record_claim(
                campaign,
                drop,
                claimed_at=self.claimed_at + timedelta(minutes=index),
            )

        self.assertEqual([record.campaign for record in self.store.records], ["Campaign 1", "Campaign 2"])
        self.assertEqual(len(ClaimHistoryStore(self.path).records), 2)

    def test_corrupt_history_is_ignored_without_blocking_startup(self):
        self.path.write_text("{ broken", encoding="utf8")

        with self.assertLogs("TwitchDrops", level="WARNING"):
            store = ClaimHistoryStore(self.path)

        self.assertEqual(store.records, ())

    def test_recovers_newer_atomic_temp_file_or_falls_back_to_old_file(self):
        first = self.store.record_claim(self.campaign, self.drop, claimed_at=self.claimed_at)
        newer_campaign = SimpleNamespace(
            id="campaign-2",
            name="Second Event",
            game=SimpleNamespace(name="Starfall"),
        )
        newer_drop = SimpleNamespace(id="drop-2", rewards_text=lambda: "Second Reward")
        second = ClaimHistoryStore(self.path).record_claim(
            newer_campaign,
            newer_drop,
            claimed_at=self.claimed_at + timedelta(minutes=1),
        )
        self.path.write_text(
            json.dumps({"version": 1, "records": [first.to_data()]}),
            encoding="utf8",
        )
        temp_path = self.path.with_name(f"{self.path.name}.new")
        temp_path.write_text(
            json.dumps({"version": 1, "records": [first.to_data(), second.to_data()]}),
            encoding="utf8",
        )

        recovered = ClaimHistoryStore(self.path)
        self.assertEqual([record.record_id for record in recovered.records], [first.record_id, second.record_id])

        temp_path.write_text("{broken", encoding="utf8")
        with self.assertLogs("TwitchDrops", level="WARNING"):
            fallback = ClaimHistoryStore(self.path)
        self.assertEqual([record.record_id for record in fallback.records], [first.record_id])

    def test_exports_csv_with_all_rewards(self):
        self.store.record_claim(self.campaign, self.drop, claimed_at=self.claimed_at)
        export_path = Path(self.temp_dir.name, "claims.csv")
        self.store.export_csv(export_path)

        with export_path.open("r", encoding="utf-8-sig", newline="") as file:
            rows = list(csv.reader(file))

        self.assertEqual(rows[0], ["Claimed at (UTC)", "Game", "Campaign", "Reward"])
        self.assertEqual(rows[1][1:], ["Starfall", "Launch Event", "Moonlit Badge"])

    def test_claim_hook_records_only_a_new_successful_claim(self):
        calls = []
        twitch = SimpleNamespace(
            gui=SimpleNamespace(
                history=SimpleNamespace(record_claim=lambda campaign, drop: calls.append(drop.id)),
                tray=SimpleNamespace(notify=lambda *_args: None),
            ),
            print=lambda _message: None,
        )
        campaign = SimpleNamespace(
            id="event",
            name="Event",
            game=SimpleNamespace(name="Starfall"),
            claimed_drops=1,
            total_drops=1,
        )
        drop = object.__new__(BaseDrop)
        drop._twitch = twitch
        drop.campaign = campaign
        drop.id = "reward"
        drop.is_claimed = False
        drop._claim = lambda: asyncio.sleep(0, result=True)
        drop.rewards_text = lambda: "Reward"

        self.assertTrue(asyncio.run(BaseDrop.claim(drop)))
        self.assertEqual(calls, ["reward"])
        self.assertTrue(drop.is_claimed)

        calls.clear()
        drop.is_claimed = True
        self.assertTrue(asyncio.run(BaseDrop.claim(drop)))
        self.assertEqual(calls, [])


class AchievementJournalTests(unittest.TestCase):
    def setUp(self):
        self.previous_language = _.current
        _.set_language("Português")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = ClaimHistoryStore(Path(self.temp_dir.name, "journal.json"))
        self.root = Tk()
        self.root.withdraw()
        self.style = ttk.Style(self.root)
        self.style.theme_use("clam")
        self.manager = SimpleNamespace(
            _root=self.root,
            _fonts={"brand": font.Font(self.root, size=16, weight="bold")},
            _session_started=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        self.master = ttk.Frame(self.root)
        self.master.grid()
        self.journal = AchievementJournal(self.manager, self.master, store=self.store)
        self.campaign = SimpleNamespace(
            id="campaign-ui",
            name="Lançamento",
            game=SimpleNamespace(name="Starfall"),
        )
        self.drop = SimpleNamespace(id="drop-ui", rewards_text=lambda: "Emblema lunar")

    def tearDown(self):
        self.root.destroy()
        self.temp_dir.cleanup()
        _.set_language(self.previous_language)

    def test_claim_updates_session_totals_table_and_live_search(self):
        self.journal.record_claim(self.campaign, self.drop)
        self.root.update_idletasks()

        self.assertEqual(self.journal._stats["total"].get(), "1")
        self.assertEqual(self.journal._stats["session"].get(), "1")
        self.assertEqual(len(self.journal._table.get_children()), 1)
        self.assertEqual(self.journal._table.item(self.journal._table.get_children()[0], "values")[1], "Starfall")

        self.journal._search.set("inexistente")
        self.assertEqual(len(self.journal._table.get_children()), 0)
        self.assertEqual(
            self.journal._result_count.cget("text"),
            "Nenhuma conquista corresponde aos filtros.",
        )

    def test_loads_existing_claims_on_open(self):
        self.store.record_claim(self.campaign, self.drop)
        journal = AchievementJournal(self.manager, ttk.Frame(self.root), store=self.store)

        self.assertEqual(journal._stats["total"].get(), "1")
        self.assertEqual(len(journal._table.get_children()), 1)

    def test_date_filters_combine_with_search_and_keep_unfiltered_totals(self):
        now = datetime.now().astimezone().replace(hour=12, minute=0, second=0, microsecond=0)
        self.manager._session_started = (now - timedelta(minutes=20)).astimezone(timezone.utc)
        for name, claimed_at in (
            ("Old badge", now - timedelta(days=7)),
            ("Week badge", now - timedelta(days=6)),
            ("Earlier badge", now - timedelta(hours=1)),
            ("Current badge", now - timedelta(minutes=10)),
        ):
            drop = SimpleNamespace(id=name, rewards_text=lambda: name)
            self.store.record_claim(self.campaign, drop, claimed_at=claimed_at)

        def rewards_in_view():
            table = self.journal._table
            return tuple(table.set(row, "reward") for row in table.get_children())

        self.assertEqual(str(self.journal._period.cget("state")), "readonly")
        with patch("gui.datetime", wraps=datetime) as clock:
            clock.now.return_value = now
            for index, expected in enumerate((
                ("Current badge", "Earlier badge", "Week badge", "Old badge"),
                ("Current badge", "Earlier badge"),
                ("Current badge", "Earlier badge", "Week badge"),
                ("Current badge",),
            )):
                with self.subTest(period=index):
                    self.journal._period.current(index)
                    self.journal._period.event_generate("<<ComboboxSelected>>")
                    self.assertEqual(rewards_in_view(), expected)

            self.journal._search.set("earlier")
            self.assertEqual(rewards_in_view(), ())
            self.journal._period.current(1)
            self.journal._period.event_generate("<<ComboboxSelected>>")
            self.assertEqual(rewards_in_view(), ("Earlier badge",))

        self.assertEqual(self.journal._stats["total"].get(), "4")
        self.assertEqual(self.journal._stats["today"].get(), "2")
        self.assertEqual(self.journal._stats["session"].get(), "1")

    def test_csv_includes_all_claims_when_view_is_filtered(self):
        self.store.record_claim(self.campaign, self.drop)
        self.journal._search.set("inexistente")
        export_path = Path(self.temp_dir.name, "full-history.csv")

        with patch("gui.filedialog.asksaveasfilename", return_value=str(export_path)):
            self.journal.export_csv()

        with export_path.open("r", encoding="utf-8-sig", newline="") as file:
            rows = list(csv.reader(file))
        self.assertEqual(rows[1][1:], ["Starfall", "Lançamento", "Emblema lunar"])


if __name__ == "__main__":
    unittest.main()
