import asyncio
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk
from types import SimpleNamespace
from unittest.mock import Mock, patch

SOURCE_ROOT = Path(__file__).resolve().parents[1]
ENGLISH_TRANSLATION = SOURCE_ROOT / "lang" / "English.json"
ENGLISH_EXISTED_BEFORE_IMPORT = ENGLISH_TRANSLATION.exists()

from gui import MiniHUD, StatusBar, TrayIcon
from translate import _


class MiniHUDTests(unittest.TestCase):
    def setUp(self):
        self.previous_language = _.current
        _.set_language("Português")
        self.root = tk.Tk()
        self.root.withdraw()
        self.style = ttk.Style(self.root)
        self.style.theme_use("clam")
        for name, color in (
            ("HUD.TFrame", "#343240"),
            ("HUDContent.TFrame", "#171821"),
            ("HUDHeader.TFrame", "#1b1c25"),
        ):
            self.style.configure(name, background=color)
        self.manager = SimpleNamespace(
            _root=self.root,
            _style=self.style,
            close_hud=lambda: setattr(self.manager, "closed", True),
            grab_attention=lambda **kwargs: setattr(self.manager, "opened", kwargs),
            closed=False,
            opened=None,
            status_updates=[],
            update_hud_status=lambda text: self.manager.status_updates.append(text),
        )

    def tearDown(self):
        self.root.destroy()
        _.set_language(self.previous_language)

    def test_hud_displays_live_campaign_progress_and_time(self):
        hud = MiniHUD(self.manager)
        self.root.update_idletasks()
        drop = SimpleNamespace(
            campaign=SimpleNamespace(
                game=SimpleNamespace(name="Hades II"),
                name="Launch Celebration",
            ),
            progress=0.625,
            rewards_text=lambda: "Moonstone cloak",
        )

        hud.update_status("Watching: channel")
        hud.update_drop(drop)
        hud.update_remaining("00:45 remaining")

        self.assertEqual(hud._status.get(), "Watching: channel")
        self.assertEqual(hud._game.get(), "Hades II")
        self.assertEqual(hud._campaign.get(), "Launch Celebration")
        self.assertEqual(hud._reward.get(), "Moonstone cloak")
        self.assertEqual(hud._percentage.get(), "62%")
        self.assertEqual(hud._progress.get(), 0.625)
        self.assertEqual(hud._remaining.get(), "00:45 remaining")
        self.assertTrue(hud.window.attributes("-topmost"))

    def test_hud_clears_progress_when_no_drop_is_active(self):
        hud = MiniHUD(self.manager)
        hud.update_drop(None)

        self.assertEqual(hud._game.get(), "...")
        self.assertEqual(hud._campaign.get(), "...")
        self.assertEqual(hud._reward.get(), "Aguardando um drop")
        self.assertEqual(hud._percentage.get(), "--%")
        self.assertEqual(hud._progress.get(), 0.0)
        self.assertEqual(hud._remaining.get(), "")

    def test_long_status_is_trimmed_to_keep_overlay_layout_compact(self):
        hud = MiniHUD(self.manager)
        hud.update_status("Adicionando as campanhas para o sistema... 20")

        self.assertLessEqual(len(hud._status.get()), 18)
        self.assertTrue(hud._status.get().endswith("…"))

    def test_quick_actions_restore_app_and_close_hud(self):
        hud = MiniHUD(self.manager)
        buttons = []

        def visit(widget):
            if isinstance(widget, ttk.Button):
                buttons.append(widget)
            for child in widget.winfo_children():
                visit(child)

        visit(hud.window)
        next(button for button in buttons if button.cget("text") == "Abrir DropForge").invoke()
        next(button for button in buttons if button.cget("text") == "×").invoke()

        self.assertEqual(self.manager.opened, {"sound": False})
        self.assertTrue(self.manager.closed)

    def test_status_bar_forwards_live_status_to_hud_manager(self):
        manager = SimpleNamespace(
            update_hud_status=self.manager.update_hud_status,
            show_diagnostics=lambda: None,
            show_hud=lambda: None,
        )
        status = StatusBar(manager, ttk.Frame(self.root))
        status.update("Conectado")

        self.assertEqual(self.manager.status_updates, ["Conectado"])
        self.assertEqual(status._text, "Conectado")

    def test_tray_menu_can_open_the_hud_while_main_window_is_minimized(self):
        class FakeMenu:
            SEPARATOR = "separator"

            def __init__(self, *items):
                self.items = items

        class FakeMenuItem:
            def __init__(self, text, action, **kwargs):
                self.text = text
                self.action = action
                self.options = kwargs

        class FakeIcon:
            def __init__(self, _name, _image, _title, menu):
                self.menu = menu

            def run(self):
                pass

            def stop(self):
                pass

        class FakeImage:
            def close(self):
                pass

        manager = SimpleNamespace(
            progress=SimpleNamespace(_drop=None),
            show_hud=Mock(),
        )
        tray = object.__new__(TrayIcon)
        tray._manager = manager
        tray._icon_state = "dropforge"
        tray._icon_images = {"dropforge": FakeImage()}
        tray.get_title = lambda _drop: "DropForge"

        async def open_from_tray():
            loop = asyncio.get_running_loop()
            with (
                patch("gui.pystray.Menu", FakeMenu),
                patch("gui.pystray.MenuItem", FakeMenuItem),
                patch("gui.pystray.Icon", FakeIcon),
                patch.object(loop, "run_in_executor", return_value=None),
            ):
                tray._start()
                hud_item = next(
                    item for item in tray.icon.menu.items
                    if getattr(item, "text", None) == "Abrir Mini HUD"
                )
                hud_item.action()
                await asyncio.sleep(0)

        asyncio.run(open_from_tray())
        manager.show_hud.assert_called_once_with()


def tearDownModule():
    if not ENGLISH_EXISTED_BEFORE_IMPORT and ENGLISH_TRANSLATION.exists():
        ENGLISH_TRANSLATION.unlink()


if __name__ == "__main__":
    unittest.main()
