import asyncio
import tkinter as tk
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from tkinter import ttk
from unittest.mock import Mock

from constants import PriorityMode, State
from gui import InventoryOverview, SettingsPanel
from translate import _


NOW = datetime.now(timezone.utc)


class FakeCache:
    def __init__(self, root):
        self.root = root
        self.images = []

    async def get(self, _url, size=None):
        image = tk.PhotoImage(master=self.root, width=2, height=2)
        self.images.append(image)
        return image


class FakeDrop:
    id = "drop-1"
    name = "Moonlit Drop"
    benefits = []
    is_claimed = False
    can_claim = False
    current_minutes = 0
    required_minutes = 60
    progress = 0.0
    starts_at = NOW - timedelta(hours=1)
    ends_at = NOW + timedelta(hours=2)

    def __init__(self, campaign):
        self.campaign = campaign

    def can_earn(self):
        return False

    @property
    def total_remaining_minutes(self):
        return max(0, self.required_minutes - self.current_minutes)

    def rewards_text(self):
        return "Moonlit Badge"


class FakeCampaign:
    name = "Launch Week"
    eligible = True
    active = True
    upcoming = False
    expired = False
    finished = False
    required_minutes = 60
    starts_at = NOW - timedelta(hours=1)
    ends_at = NOW + timedelta(hours=2)
    link_url = "https://example.com/campaign"
    image_url = "https://example.com/game.png"
    allowed_channels = []

    def __init__(self, game_name="Starfall"):
        self.game = SimpleNamespace(name=game_name)
        self.drops = [FakeDrop(self)]


class InventorySearchUiTests(unittest.TestCase):
    def setUp(self):
        self.previous_language = _.current
        _.set_language("Português")
        self.root = tk.Tk()
        self.root.withdraw()
        self.settings = SimpleNamespace(
            priority_mode=PriorityMode.PRIORITY_ONLY,
            priority=[],
            exclude=set(),
            alter=Mock(),
        )
        self.states = []

        class Tabs:
            def add_view_event(_self, _callback):
                pass

            def current_tab(_self):
                return 1

        panel = object.__new__(SettingsPanel)
        panel._settings = self.settings
        panel._priority_list = tk.Listbox(self.root)
        panel._priority_entry = ttk.Combobox(self.root)
        panel._game_names = {"Starfall"}

        self.manager = SimpleNamespace(
            _cache=FakeCache(self.root),
            _twitch=SimpleNamespace(
                settings=self.settings,
                change_state=self.states.append,
            ),
            tabs=Tabs(),
            settings=panel,
        )
        self.master = ttk.Frame(self.root)
        self.master.grid()
        self.inventory = InventoryOverview(self.manager, self.master)
        self.campaign = FakeCampaign()
        asyncio.run(self.inventory.add_campaign(self.campaign))
        self.root.update_idletasks()

    def tearDown(self):
        self.root.destroy()
        _.set_language(self.previous_language)

    def test_search_reveals_non_priority_campaign_and_counts_results(self):
        display = self.inventory._campaigns[self.campaign]
        self.assertEqual(display["frame"].winfo_manager(), "")

        self.inventory._search_var.set("moonlit badge")
        self.root.update_idletasks()

        self.assertEqual(display["frame"].winfo_manager(), "grid")
        self.assertEqual(self.inventory._count_label.cget("text"), "1 de 1")

    def test_campaign_button_toggles_priority_and_updates_settings_and_choices(self):
        self.inventory._search_var.set("starfall")
        display = self.inventory._campaigns[self.campaign]
        button = display["priority_button"]
        button.invoke()

        self.assertEqual(self.settings.priority, ["Starfall"])
        self.assertEqual(self.states, [State.INVENTORY_FETCH])
        self.assertEqual(button.cget("text"), _("gui", "inventory", "priority_remove"))
        self.assertTrue(button.instate(["!disabled"]))
        self.assertEqual(self.manager.settings._priority_list.get(0, "end"), ("Starfall",))
        self.assertFalse(self.manager.settings._priority_entry.cget("values"))

        button.invoke()

        self.assertEqual(self.settings.priority, [])
        self.assertEqual(self.states, [State.INVENTORY_FETCH, State.INVENTORY_FETCH])
        self.assertEqual(button.cget("text"), _("gui", "inventory", "priority_add"))
        self.assertEqual(self.manager.settings._priority_list.size(), 0)
        self.assertEqual(self.manager.settings._priority_entry.cget("values"), ("Starfall",))
        self.assertEqual(display["frame"].winfo_manager(), "grid")
        self.assertEqual(self.settings.alter.call_count, 2)

    def test_removing_priority_hides_campaign_without_active_search(self):
        self.manager.settings.add_priority_game("Starfall")
        self.inventory.refresh()
        display = self.inventory._campaigns[self.campaign]
        self.assertEqual(display["frame"].winfo_manager(), "grid")

        display["priority_button"].invoke()

        self.assertEqual(display["frame"].winfo_manager(), "")
        self.assertEqual(self.states, [State.INVENTORY_FETCH])

    def test_excluded_game_stays_hidden_and_is_not_prioritized(self):
        self.settings.exclude.add("Starfall")
        self.inventory._search_var.set("starfall")
        self.inventory.refresh()
        display = self.inventory._campaigns[self.campaign]

        self.assertEqual(display["frame"].winfo_manager(), "")
        self.assertEqual(str(display["priority_button"].cget("state")), "disabled")
        display["priority_button"].invoke()
        self.assertEqual(self.settings.priority, [])
        self.assertEqual(self.states, [])

    def test_removing_duplicate_priority_keeps_exclusion_intact(self):
        self.settings.priority.extend(["Starfall", "Another Game", "Starfall"])
        self.settings.exclude.add("Starfall")
        self.manager.settings._priority_list.insert("end", *self.settings.priority)
        self.inventory._filters["excluded"].set(1)
        self.inventory.refresh()
        button = self.inventory._campaigns[self.campaign]["priority_button"]
        self.assertTrue(button.instate(["!disabled"]))

        button.invoke()
        button.invoke()  # Now disabled because the game is still excluded.

        self.assertEqual(self.settings.priority, ["Another Game"])
        self.assertEqual(self.settings.exclude, {"Starfall"})
        self.assertEqual(self.manager.settings._priority_list.get(0, "end"), ("Another Game",))
        self.assertTrue(button.instate(["disabled"]))
        self.assertEqual(self.states, [State.INVENTORY_FETCH])

    def test_deadline_radar_orders_campaigns_by_available_time_margin(self):
        urgent = FakeCampaign("Urgent Game")
        urgent.name = "Urgent Campaign"
        urgent_drop = FakeDrop(urgent)
        urgent_drop.required_minutes = 60
        urgent_drop.ends_at = NOW + timedelta(minutes=75)
        urgent.drops = [urgent_drop]
        asyncio.run(self.inventory.add_campaign(urgent))
        self.root.update_idletasks()

        self.assertEqual(
            [item.campaign.name for item in self.inventory._deadline_candidates],
            ["Urgent Campaign", "Launch Week"],
        )
        self.assertIn("Top 2 de 2", self.inventory._radar_summary.cget("text"))

    def test_deadline_radar_focus_reveals_non_priority_campaign(self):
        display = self.inventory._campaigns[self.campaign]
        self.assertEqual(display["frame"].winfo_manager(), "")

        self.inventory._focus_campaign(self.campaign)
        self.root.update_idletasks()

        self.assertEqual(self.inventory._search_var.get(), "Launch Week")
        self.assertEqual(display["frame"].winfo_manager(), "grid")

    def test_session_planner_puts_rewards_that_fit_the_selected_window_first(self):
        urgent_but_long = FakeCampaign("Long Game")
        urgent_but_long.name = "Long Campaign"
        long_drop = FakeDrop(urgent_but_long)
        long_drop.required_minutes = 120
        long_drop.ends_at = NOW + timedelta(minutes=130)
        urgent_but_long.drops = [long_drop]
        asyncio.run(self.inventory.add_campaign(urgent_but_long))

        self.assertEqual(
            self.inventory._session_recommendations[0].candidate.campaign.name,
            "Launch Week",
        )

        self.inventory._session_duration.set(_("gui", "inventory", "radar", "duration_180"))
        self.inventory._update_deadline_radar()

        self.assertEqual(
            self.inventory._session_recommendations[0].candidate.campaign.name,
            "Long Campaign",
        )
        self.assertTrue(self.inventory._session_recommendations[0].fits_session)

    def radar_priority_button(self):
        card = self.inventory._radar_cards.winfo_children()[0]
        actions = next(child for child in card.winfo_children() if isinstance(child, ttk.Frame))
        return next(child for child in actions.winfo_children() if isinstance(child, ttk.Button))

    def test_session_card_toggles_priority_and_updates_the_campaign_card(self):
        self.radar_priority_button().invoke()

        self.assertEqual(self.settings.priority, ["Starfall"])
        self.assertEqual(self.states, [State.INVENTORY_FETCH])
        remove = self.radar_priority_button()
        self.assertEqual(remove.cget("text"), _("gui", "inventory", "priority_remove"))
        campaign_button = self.inventory._campaigns[self.campaign]["priority_button"]
        self.assertEqual(campaign_button.cget("text"), remove.cget("text"))

        remove.invoke()

        self.assertEqual(self.settings.priority, [])
        self.assertEqual(self.states, [State.INVENTORY_FETCH, State.INVENTORY_FETCH])
        self.assertEqual(campaign_button.cget("text"), _("gui", "inventory", "priority_add"))


if __name__ == "__main__":
    unittest.main()
