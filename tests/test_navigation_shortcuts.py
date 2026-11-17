import tkinter as tk
import unittest
from tkinter import ttk
from types import SimpleNamespace

from gui import Notebook


class NavigationShortcutTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        master = ttk.Frame(self.root)
        master.pack(fill="both", expand=True)
        self.notebook = Notebook(SimpleNamespace(_root=self.root), master)
        self.pages = [ttk.Frame(self.notebook.page_host) for _ in range(5)]
        self.main_entry = ttk.Entry(self.pages[0])
        self.inventory_entry = ttk.Entry(self.pages[1])
        self.journal_entry = ttk.Entry(self.pages[4])
        for entry in (self.main_entry, self.inventory_entry, self.journal_entry):
            entry.pack()
        self.notebook.add_tab(self.pages[0], name="Main")
        self.notebook.add_tab(
            self.pages[1], name="Inventory", search=self.inventory_entry.focus_set
        )
        self.notebook.add_tab(self.pages[2], name="Settings")
        self.notebook.add_tab(self.pages[3], name="Help")
        self.notebook.add_tab(
            self.pages[4], name="Journal", search=self.journal_entry.focus_set
        )
        self.root.update()
        self.root.focus_force()

    def press(self, key):
        self.root.update()
        focused = self.root.focus_get()
        focused.event_generate(f"<{Notebook.SHORTCUT_MODIFIER}-KeyPress-{key}>")
        self.root.update()

    def test_number_shortcuts_select_tabs_from_a_text_field(self):
        self.main_entry.focus_force()
        for number in (3, 5, 2, 4, 1):
            with self.subTest(number=number):
                self.press(number)
                self.assertEqual(self.notebook.current_tab(), number - 1)
                self.assertTrue(self.pages[number - 1].winfo_ismapped())

    def test_find_defaults_to_inventory_but_stays_in_journal_when_open(self):
        self.main_entry.focus_force()
        self.press("f")
        self.assertEqual(self.notebook.current_tab(), 1)
        self.assertEqual(self.root.focus_get(), self.inventory_entry)

        self.press(5)
        self.press("f")
        self.assertEqual(self.notebook.current_tab(), 4)
        self.assertEqual(self.root.focus_get(), self.journal_entry)
