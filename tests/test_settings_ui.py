import asyncio
import tempfile
import unittest
from copy import deepcopy
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import tkinter as tk
from tkinter import ttk

from game_profiles import GameProfilesStore
from gui import GUIManager, SettingsPanel
from settings import default_settings
from translate import _
from utils import Game


class SettingsUITest(unittest.TestCase):
    def setUp(self):
        previous_language = _.current
        _.set_language("Português")
        self.addCleanup(_.set_language, previous_language)
        self.data = SimpleNamespace(**deepcopy(default_settings), tray=False, alter=Mock())
        self.data.dark_mode = True
        self.twitch = SimpleNamespace(
            settings=self.data, inventory=[], change_state=Mock(),
        )
        self.twitch.state_change = lambda state: partial(self.twitch.change_state, state)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        profile_store = GameProfilesStore(Path(self.temp.name, "game-profiles.json"))
        source = Path(__file__).resolve().parents[1]
        with (
            patch("gui.resource_path", side_effect=lambda path: source / path),
            patch("gui.ImageCache"),
            patch("gui.GameProfilesStore", return_value=profile_store),
            patch("gui.ClaimHistoryStore"),
            patch.object(SettingsPanel, "_query_autostart", return_value=False),
        ):
            self.gui = GUIManager(self.twitch)
        self.addCleanup(self.gui.close_window)
        self.root = self.gui._root
        self.root.minsize(1080, 720)
        self.root.geometry("1080x720")
        self.gui.tabs.select_tab(2)
        self.root.update()
        self.panel = self.gui.settings

    def test_pages_and_collapsible_preferences_at_minimum_window_size(self):
        for section in ("games", "account", "preferences"):
            self.panel._section_buttons[section].invoke()
            self.root.update()
            self.assertEqual(self.panel._active_section, section)
            for key, page in self.panel._sections.items():
                self.assertEqual(bool(page.winfo_ismapped()), key == section)
                if key == section:
                    self.assertGreater(page.winfo_width(), 700)
                    self.assertLessEqual(page.winfo_height(), self.root.winfo_height())

        self.assertFalse(self.panel._advanced_options.winfo_ismapped())
        self.panel._advanced_button.invoke()
        self.root.update()
        self.assertTrue(self.panel._advanced_options.winfo_ismapped())
        self.assertEqual(self.panel._advanced_button.cget("text"), "Ocultar")
        self.panel._advanced_button.invoke()
        self.root.update()
        self.assertFalse(self.panel._advanced_options.winfo_ismapped())

    def test_picker_searches_accents_and_moves_games_to_the_requested_list(self):
        games = {Game({"id": 2, "name": "Ação Galáctica"}), Game({"id": 3, "name": "Aurora"})}
        self.panel.set_games(games)
        self.panel._game_query.set("ACAO gala")
        self.root.update()
        row, = self.panel._game_tree.get_children()
        self.assertEqual(self.panel._game_tree.item(row, "text").strip(), "Ação Galáctica")
        self.panel._game_tree.selection_set(row)
        self.panel._catalog_selection_changed()
        self.panel._catalog_buttons["priority"].invoke()
        self.assertEqual(self.data.priority, ["Ação Galáctica"])
        self.assertEqual(self.panel._priority_list.get(0), "Ação Galáctica")
        self.assertEqual(self.panel._game_tree.item(row, "values"), ("Prioridade",))
        self.panel._catalog_buttons["exclude"].invoke()
        self.assertEqual(self.data.exclude, {"Ação Galáctica"})
        self.assertEqual(self.panel._exclude_list.get(0), "Ação Galáctica")
        self.assertEqual(self.panel._game_tree.item(row, "values"), ("Excluído",))

    def test_picker_loads_campaign_art_only_for_visible_results(self):
        games = {Game({"id": i, "name": f"Game{i:02d}"}) for i in range(30)}
        self.twitch.inventory = [
            SimpleNamespace(game=game, image_url=f"https://example.invalid/{game.id}.png")
            for game in games
        ]
        calls = []

        async def fake_image(url, *, size):
            calls.append((url, size))
            return tk.PhotoImage(master=self.root, width=size[0], height=size[1])

        self.gui._cache.get = fake_image

        async def refresh():
            self.panel.set_games(games)
            self.root.update()
            await asyncio.sleep(0)
            self.root.update()
            task = self.panel._game_icon_task
            if task is not None:
                await task

        asyncio.run(refresh())
        self.assertGreater(len(calls), 0)
        self.assertLess(len(calls), len(games))
        self.assertTrue(all(size == (24, 30) for _url, size in calls))
        first = self.panel._game_tree.get_children()[0]
        rendered = self.panel._game_tree.item(first, "image")[0]
        self.assertNotEqual(str(rendered), str(self.panel._cover_placeholder))


if __name__ == "__main__":
    unittest.main()
