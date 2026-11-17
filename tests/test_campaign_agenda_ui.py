import asyncio
import tempfile
import tkinter as tk
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tkinter import ttk
from types import SimpleNamespace
from unittest.mock import patch

from constants import PriorityMode
from gui import InventoryOverview
from test_inventory_ui import FakeCache, FakeCampaign
from translate import _


class CampaignAgendaUiTests(unittest.TestCase):
    def setUp(self):
        previous_language = _.current
        _.set_language("Português")
        self.addCleanup(_.set_language, previous_language)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.now = datetime.now(timezone.utc)
        self.settings = SimpleNamespace(
            priority_mode=PriorityMode.PRIORITY_ONLY,
            priority=[],
            exclude={"Aster"},
        )
        self.state_changes = []
        manager = SimpleNamespace(
            _root=self.root,
            _style=ttk.Style(self.root),
            _cache=FakeCache(self.root),
            _twitch=SimpleNamespace(
                settings=self.settings,
                change_state=self.state_changes.append,
            ),
            tabs=SimpleNamespace(
                add_view_event=lambda _callback: None,
                current_tab=lambda: 1,
                select_tab=lambda _index: None,
            ),
        )
        master = ttk.Frame(self.root)
        master.grid()
        self.inventory = InventoryOverview(manager, master)

    def add_campaign(self, game, name, start_delta, end_delta, *, linked=True):
        campaign = FakeCampaign(game)
        campaign.id = name
        campaign.name = name
        campaign.starts_at = self.now + start_delta
        campaign.ends_at = self.now + end_delta
        campaign.eligible = linked
        campaign.upcoming = start_delta > timedelta()
        campaign.active = not campaign.upcoming
        drop = campaign.drops[0]
        drop.id = f"{name}-drop"
        drop.starts_at = campaign.starts_at
        drop.ends_at = campaign.ends_at
        asyncio.run(self.inventory.add_campaign(campaign))
        self.root.update_idletasks()
        return campaign

    def open_agenda(self):
        self.inventory._open_agenda()
        self.root.update_idletasks()
        return self.inventory._agenda

    @staticmethod
    def table_rows(agenda):
        return [agenda.table.item(iid, "values") for iid in agenda.table.get_children()]

    def choose_filter(self, combobox, index):
        combobox.current(index)
        combobox.event_generate("<<ComboboxSelected>>")
        self.root.update_idletasks()

    def test_period_and_event_filters_keep_chronological_schedule(self):
        self.add_campaign("Sirius", "Closing Event", -timedelta(hours=2), timedelta(hours=8))
        self.add_campaign("Vega", "Weekend Event", timedelta(days=2), timedelta(days=4))
        self.add_campaign("Arcturus", "Monthly Event", timedelta(days=12), timedelta(days=19))
        agenda = self.open_agenda()

        self.assertEqual(agenda.period.current(), 1)
        self.assertEqual(agenda.event_filter.current(), 0)
        starts = _("gui", "inventory", "agenda", "event_starts")
        ends = _("gui", "inventory", "agenda", "event_ends")
        self.assertEqual(
            [row[1:4] for row in self.table_rows(agenda)],
            [
                (ends, "Sirius", "Closing Event"),
                (starts, "Vega", "Weekend Event"),
                (ends, "Vega", "Weekend Event"),
            ],
        )

        self.choose_filter(agenda.event_filter, 1)
        self.assertEqual(
            [row[1:4] for row in self.table_rows(agenda)],
            [(starts, "Vega", "Weekend Event")],
        )
        self.choose_filter(agenda.period, 0)
        self.assertEqual(self.table_rows(agenda), [])
        self.assertTrue(agenda.view_button.instate(("disabled",)))
        self.choose_filter(agenda.event_filter, 2)
        self.assertEqual(
            [row[1:4] for row in self.table_rows(agenda)],
            [(ends, "Sirius", "Closing Event")],
        )
        self.choose_filter(agenda.period, 2)
        self.assertEqual(
            [row[3] for row in self.table_rows(agenda)],
            ["Closing Event", "Weekend Event", "Monthly Event"],
        )

    def test_open_agenda_reuses_window_and_refreshes_when_inventory_changes(self):
        agenda = self.open_agenda()
        self.assertIs(self.open_agenda(), agenda)
        self.assertEqual(self.table_rows(agenda), [])

        campaign = self.add_campaign(
            "Sirius", "Short Event", -timedelta(hours=1), timedelta(hours=2)
        )
        self.assertEqual([row[3] for row in self.table_rows(agenda)], ["Short Event"])

        drop = campaign.drops[0]
        drop.is_claimed = True
        campaign.finished = True
        self.inventory.update_drop(drop)
        self.root.update_idletasks()
        self.assertEqual(self.table_rows(agenda), [])

        self.add_campaign("Vega", "Weekend Event", timedelta(days=2), timedelta(days=4))
        self.assertEqual(len(self.table_rows(agenda)), 2)
        self.inventory.clear()
        self.root.update_idletasks()
        self.assertEqual(self.table_rows(agenda), [])

    def test_calendar_export_writes_only_events_matching_both_filters(self):
        ending = self.add_campaign(
            "Sirius", "Closing Event", -timedelta(hours=2), timedelta(hours=8)
        )
        self.add_campaign("Vega", "Morning Event", timedelta(hours=10), timedelta(days=2))
        self.add_campaign("Arcturus", "Monthly Event", timedelta(days=5), timedelta(days=6))
        agenda = self.open_agenda()
        self.choose_filter(agenda.period, 0)
        self.choose_filter(agenda.event_filter, 2)

        self.assertTrue(agenda.export_button.instate(("!disabled",)))
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "agenda.ics"
            with patch("gui.filedialog.asksaveasfilename", return_value=str(path)) as dialog:
                agenda.export_button.invoke()
            dialog.assert_called_once()
            contents = path.read_text(encoding="utf-8")

        self.assertEqual(contents.count("BEGIN:VEVENT"), 1)
        self.assertIn(f"DTSTART:{ending.ends_at:%Y%m%dT%H%M%SZ}", contents)
        self.assertIn("Closing Event", contents)
        self.assertNotIn("Morning Event", contents)
        self.assertNotIn("Monthly Event", contents)

        self.inventory.clear()
        self.root.update_idletasks()
        self.assertTrue(agenda.export_button.instate(("disabled",)))

    def test_view_reveals_campaign_without_changing_mining_preferences(self):
        campaign = self.add_campaign(
            "Aster", "Upcoming Event", timedelta(hours=6), timedelta(days=2), linked=False
        )
        for name in ("excluded", "not_linked", "upcoming"):
            self.inventory._filters[name].set(0)
        self.inventory.refresh()
        display = self.inventory._campaigns[campaign]["frame"]
        self.assertEqual(display.winfo_manager(), "")

        agenda = self.open_agenda()
        first_row = agenda.table.get_children()[0]
        agenda.table.selection_set(first_row)
        agenda.table.event_generate("<<TreeviewSelect>>")
        self.root.update_idletasks()
        agenda.view_button.invoke()
        self.root.update_idletasks()

        self.assertFalse(agenda.window.winfo_exists())
        self.assertEqual(self.inventory._search_var.get(), "Upcoming Event")
        self.assertEqual(display.winfo_manager(), "grid")
        self.assertEqual(self.settings.priority, [])
        self.assertEqual(self.settings.exclude, {"Aster"})
        self.assertEqual(self.state_changes, [])
