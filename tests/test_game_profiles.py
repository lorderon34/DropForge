import json
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from tkinter import ttk
from unittest.mock import Mock, patch

from constants import PriorityMode, State
from game_profiles import (
    GameProfile,
    GameProfilesStore,
    ProfileLimitError,
    apply_game_profile,
)
from gui import SettingsPanel
from translate import _


class GameProfilesStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name, "game-profiles.json")
        self.store = GameProfilesStore(self.path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_saves_and_restores_ordered_priority_and_exclusions(self):
        profile = self.store.save_profile(
            "Weekend",
            ["  Starfall ", "Night Harbor", "starfall"],
            {"Avoided Game", "STARFALL"},
        )

        loaded = GameProfilesStore(self.path)
        self.assertEqual(profile.priority, ("Night Harbor",))
        self.assertEqual(profile.excluded, ("Avoided Game", "STARFALL"))
        self.assertEqual(loaded.get("weekEND"), profile)

    def test_saving_same_name_case_insensitively_updates_existing(self):
        self.store.save_profile("Raid", ["First"], [])

        updated = self.store.save_profile(" raid ", ["Second"], ["First"])

        self.assertEqual(self.store.names, ("Raid",))
        self.assertEqual(updated.priority, ("Second",))
        self.assertEqual(updated.excluded, ("First",))

    def test_rejects_empty_and_multiline_names(self):
        for name in ("", "  ", "Two\nLines"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.store.save_profile(name, [], [])

    def test_limits_new_profiles_but_allows_updates(self):
        self.store.MAX_PROFILES = 2
        self.store.save_profile("One", [], [])
        self.store.save_profile("Two", [], [])

        with self.assertRaises(ProfileLimitError):
            self.store.save_profile("Three", [], [])
        self.store.save_profile("one", ["Starfall"], [])

        self.assertEqual(self.store.names, ("One", "Two"))
        self.assertEqual(self.store.get("One").priority, ("Starfall",))

    def test_corrupt_file_does_not_break_startup(self):
        self.path.write_text("{broken", encoding="utf8")

        with self.assertLogs("TwitchDrops", level="WARNING"):
            recovered = GameProfilesStore(self.path)

        self.assertEqual(recovered.profiles, ())

    def test_ignores_malformed_records_and_duplicate_names_when_loading(self):
        self.path.write_text(
            json.dumps(
                {
                    "profiles": [
                        {"name": "Valid", "priority": ["A"], "excluded": []},
                        {"name": "valid", "priority": ["B"], "excluded": []},
                        {"name": "Bad", "priority": "A", "excluded": []},
                    ]
                }
            ),
            encoding="utf8",
        )

        loaded = GameProfilesStore(self.path)

        self.assertEqual(loaded.names, ("Valid",))


class ApplyGameProfileTests(unittest.TestCase):
    def test_applies_both_lists_and_reports_when_no_change_is_needed(self):
        profile = GameProfile("Focus", ("Starfall", "Eclipse"), ("Avoided",))
        updates = []
        settings = SimpleNamespace(
            priority=["Old"],
            exclude={"Old Exclusion"},
            alter=lambda: updates.append(True),
        )

        self.assertTrue(apply_game_profile(settings, profile))
        self.assertEqual(settings.priority, ["Starfall", "Eclipse"])
        self.assertEqual(settings.exclude, {"Avoided"})
        self.assertEqual(updates, [True])
        self.assertFalse(apply_game_profile(settings, profile))
        self.assertEqual(updates, [True])


class GameProfilePanelActionTests(unittest.TestCase):
    class Variable:
        def __init__(self, value=""):
            self.value = value

        def get(self):
            return self.value

        def set(self, value):
            self.value = value

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = GameProfilesStore(Path(self.temp_dir.name, "profiles.json"))
        self.states = []

    def tearDown(self):
        self.temp_dir.cleanup()

    def make_panel(self, name, *, priority=None, excluded=None):
        from gui import SettingsPanel

        panel = object.__new__(SettingsPanel)
        panel._profile_store = self.store
        panel._profile_name = self.Variable(name)
        panel._profile_status = self.Variable()
        panel._profile_combo = SimpleNamespace(configure=Mock())
        panel._profile_apply_button = SimpleNamespace(configure=Mock())
        panel._profile_delete_button = SimpleNamespace(configure=Mock())
        panel._settings = SimpleNamespace(
            priority=list(priority or []),
            exclude=set(excluded or []),
            alter=Mock(),
        )
        panel._priority_list = Mock()
        panel._exclude_list = Mock()
        panel._manager = SimpleNamespace(
            _twitch=SimpleNamespace(change_state=self.states.append)
        )
        panel.update_priority_choices = Mock()
        panel.update_excluded_choices = Mock()
        return panel

    def test_apply_action_updates_visible_lists_and_reloads_inventory(self):
        self.store.save_profile("Controller", ["Starfall", "Eclipse"], ["Blocked"])
        panel = self.make_panel("Controller", priority=["Old"], excluded=["Old Block"])

        panel.apply_game_profile()

        self.assertEqual(panel._settings.priority, ["Starfall", "Eclipse"])
        self.assertEqual(panel._settings.exclude, {"Blocked"})
        panel._priority_list.delete.assert_called_once_with(0, "end")
        panel._priority_list.insert.assert_called_once_with("end", "Starfall", "Eclipse")
        panel._exclude_list.insert.assert_called_once_with("end", "Blocked")
        self.assertEqual(len(self.states), 1)

    def test_save_action_uses_current_lists_and_reports_success(self):
        panel = self.make_panel("Streaming", priority=["Starfall"], excluded=["Blocked"])

        panel.save_game_profile()

        self.assertEqual(self.store.get("Streaming").priority, ("Starfall",))
        self.assertEqual(panel._profile_status.get(), "Profile “Streaming” saved.")


class SettingsPanelProfileWidgetsTests(unittest.TestCase):
    def setUp(self):
        self.previous_language = _.current
        _.set_language("Português")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = GameProfilesStore(Path(self.temp_dir.name, "profiles.json"))
        self.root = tk.Tk()
        self.root.withdraw()
        self.master = ttk.Frame(self.root)
        self.master.grid()
        self.states = []
        self.settings = SimpleNamespace(
            priority_mode=PriorityMode.PRIORITY_ONLY,
            priority=["Starfall"],
            exclude={"Blocked"},
            proxy="",
            autostart_tray=False,
            dark_mode=True,
            tray_notifications=True,
            enable_badges_emotes=False,
            available_drops_check=False,
            alter=Mock(),
        )
        self.twitch = SimpleNamespace(
            settings=self.settings,
            state_change=lambda _state: lambda: None,
            change_state=self.states.append,
        )
        self.manager = SimpleNamespace(_twitch=self.twitch)

    def tearDown(self):
        self.root.destroy()
        self.temp_dir.cleanup()
        _.set_language(self.previous_language)

    def test_settings_panel_shows_profile_controls_and_applies_saved_selection(self):
        with (
            patch("gui.GameProfilesStore", return_value=self.store),
            patch.object(SettingsPanel, "_query_autostart", return_value=False),
        ):
            panel = SettingsPanel(self.manager, self.master)
        self.root.update_idletasks()

        self.assertFalse(panel._profile_combo.cget("values"))
        self.assertEqual(str(panel._profile_apply_button.cget("state")), "disabled")
        panel._profile_name.set("Stream Night")
        panel.save_game_profile()
        self.assertEqual(tuple(panel._profile_combo.cget("values")), ("Stream Night",))
        self.assertEqual(str(panel._profile_apply_button.cget("state")), "normal")

        self.settings.priority = ["Other Game"]
        self.settings.exclude = {"Other Block"}
        panel.apply_game_profile()

        self.assertEqual(self.settings.priority, ["Starfall"])
        self.assertEqual(self.settings.exclude, {"Blocked"})
        self.assertEqual(self.states, [State.INVENTORY_FETCH])


if __name__ == "__main__":
    unittest.main()
