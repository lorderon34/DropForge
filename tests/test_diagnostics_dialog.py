import tkinter as tk
import unittest
from pathlib import Path
from tkinter import font, ttk
from types import SimpleNamespace

from constants import PriorityMode, State

SOURCE_ROOT = Path(__file__).resolve().parents[1]
ENGLISH_TRANSLATION = SOURCE_ROOT / "lang" / "English.json"
ENGLISH_EXISTED_BEFORE_IMPORT = ENGLISH_TRANSLATION.exists()

from gui import CampaignDiagnosticsDialog, InventoryOverview, SettingsPanel
from translate import _


class CampaignDiagnosticsDialogTests(unittest.TestCase):
    def setUp(self):
        self.previous_language = _.current
        _.set_language("Português")
        self.root = tk.Tk()
        self.root.withdraw()
        self.style = ttk.Style(self.root)
        self.style.theme_use("clam")
        self.style.configure("TFrame", background="#0d0e14")
        self.style.configure("Card.TFrame", background="#1b1c25")
        self.style.configure("TLabel", background="#0d0e14", foreground="#f2eff9")
        self.style.configure("Section.TLabel", foreground="#b56dff")
        self.style.configure("Muted.TLabel", foreground="#9b98a9")
        self.style.configure("Status.TLabel", foreground="#b56dff")
        self.style.configure("Treeview", background="#22212c")
        self.selected_tabs = []
        self.changed_states = []
        self.manager = SimpleNamespace(
            _root=self.root,
            _style=self.style,
            _fonts={
                "section": font.Font(self.root, size=11, weight="bold"),
                "default": font.Font(self.root, size=10),
            },
            _twitch=SimpleNamespace(
                inventory=[],
                settings=SimpleNamespace(
                    priority=[],
                    exclude=set(),
                    priority_mode=PriorityMode.PRIORITY_ONLY,
                ),
                change_state=self.changed_states.append,
            ),
            tabs=SimpleNamespace(select_tab=self.selected_tabs.append),
        )

    def tearDown(self):
        self.root.destroy()
        _.set_language(self.previous_language)

    def test_opens_portuguese_empty_state(self):
        dialog = CampaignDiagnosticsDialog(self.manager)
        self.root.update_idletasks()
        self.assertEqual(dialog.window.title(), "Diagnóstico de campanhas")
        text_widgets = []

        def visit(widget):
            if isinstance(widget, tk.Text):
                text_widgets.append(widget.get("1.0", "end"))
            for child in widget.winfo_children():
                visit(child)

        visit(dialog.window)
        self.assertTrue(any("Nenhuma campanha foi carregada" in item for item in text_widgets))

    def test_settings_action_selects_settings_tab(self):
        dialog = CampaignDiagnosticsDialog(self.manager)
        dialog._open_settings()
        self.assertEqual(self.selected_tabs, [2])

    def test_reload_action_requests_inventory_fetch(self):
        dialog = CampaignDiagnosticsDialog(self.manager)
        dialog._reload_campaigns()
        self.assertEqual(self.changed_states, [State.INVENTORY_FETCH])

    def test_inventory_priority_action_updates_settings_and_reloads(self):
        class PriorityList:
            items = []

            def insert(self, _index, game_name):
                self.items.append(game_name)

            def see(self, _index):
                pass

        settings = SimpleNamespace(priority=[], exclude=set(), altered=False)
        settings.alter = lambda: setattr(settings, "altered", True)
        panel = object.__new__(SettingsPanel)
        panel._settings = settings
        panel._priority_list = PriorityList()
        panel.update_priority_choices = lambda: None
        self.manager.settings = panel
        overview = object.__new__(InventoryOverview)
        overview._manager = self.manager
        overview._settings = settings
        overview.refresh = lambda: None

        overview._toggle_game_priority("Game")

        self.assertEqual(settings.priority, ["Game"])
        self.assertEqual(panel._priority_list.items, ["Game"])
        self.assertTrue(settings.altered)
        self.assertEqual(self.changed_states, [State.INVENTORY_FETCH])

    def test_inventory_priority_action_respects_exclude_list(self):
        class PriorityList:
            def insert(self, _index, _game_name):
                raise AssertionError("Excluded game must not be added")

            def see(self, _index):
                pass

        settings = SimpleNamespace(priority=[], exclude={"Game"}, alter=lambda: None)
        panel = object.__new__(SettingsPanel)
        panel._settings = settings
        panel._priority_list = PriorityList()
        panel.update_priority_choices = lambda: None
        self.manager.settings = panel
        overview = object.__new__(InventoryOverview)
        overview._manager = self.manager
        overview._settings = settings

        overview._toggle_game_priority("Game")

        self.assertEqual(settings.priority, [])
        self.assertEqual(self.changed_states, [])


def tearDownModule():
    if not ENGLISH_EXISTED_BEFORE_IMPORT and ENGLISH_TRANSLATION.exists():
        ENGLISH_TRANSLATION.unlink()


if __name__ == "__main__":
    unittest.main()
