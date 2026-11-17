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
                progress=0.375,
                claimed_drops=1,
                total_drops=4,
            ),
            progress=0.625,
            rewards_text=lambda: "Moonstone cloak",
        )

        hud.update_status("Watching: channel")
        hud.update_drop(drop)
        hud.update_remaining(" 0:14:45 restante")

        self.assertEqual(hud._status.get(), "Watching: channel")
        self.assertEqual(hud._game.get(), "Hades II")
        self.assertEqual(hud._campaign.get(), "Launch Celebration")
        self.assertEqual(hud._reward.get(), "Moonstone cloak")
        self.assertEqual(hud._percentage.get(), "62%")
        self.assertEqual(hud._progress.get(), 0.625)
        self.assertEqual(hud._remaining.get(), "0:14:45")
        self.assertEqual(hud._campaign_progress.get(), 0.375)
        self.assertEqual(hud._campaign_summary.get(), "38% · 1/4 coletados")
        self.assertEqual(hud._live.cget("style"), "HUDLive.TLabel")
        self.assertTrue(hud.window.attributes("-topmost"))

    def test_hud_clears_progress_when_no_drop_is_active(self):
        hud = MiniHUD(self.manager)
        hud.update_drop(None)
        hud.update_remaining("0:00:00 restante")

        self.assertEqual(hud._game.get(), "...")
        self.assertEqual(hud._campaign.get(), "...")
        self.assertEqual(hud._reward.get(), "Aguardando um drop")
        self.assertEqual(hud._percentage.get(), "--%")
        self.assertEqual(hud._progress.get(), 0.0)
        self.assertEqual(hud._remaining.get(), "—")
        self.assertEqual(hud._campaign_progress.get(), 0.0)
        self.assertEqual(hud._campaign_summary.get(), "—")
        self.assertEqual(hud._live.cget("style"), "HUDIdle.TLabel")

    def test_long_status_is_trimmed_to_keep_overlay_layout_compact(self):
        hud = MiniHUD(self.manager)
        long_status = "Adicionando as campanhas para o sistema... 20"
        hud.update_status(long_status)
        self.root.update()

        self.assertEqual(hud._status.get(), long_status)
        self.assertTrue(hud._status_label.cget("text").endswith("…"))

    def test_compact_toggle_keeps_timer_visible_and_restores_campaign(self):
        hud = MiniHUD(self.manager)
        self.root.update()
        height = hud.window.winfo_height()
        position = (hud.window.winfo_x(), hud.window.winfo_y())
        self.assertTrue(hud._details.winfo_ismapped())

        hud._details_button.invoke()
        self.root.update()
        self.assertFalse(hud._details.winfo_ismapped())
        self.assertLess(hud.window.winfo_height(), height)
        self.assertEqual((hud.window.winfo_x(), hud.window.winfo_y()), position)
        self.assertTrue(hud._reward_label.winfo_ismapped())
        self.assertEqual(hud._details_button.cget("text"), "Mostrar campanha")

        hud._details_button.invoke()
        self.root.update()
        self.assertTrue(hud._details.winfo_ismapped())
        self.assertEqual(hud.window.winfo_height(), height)
        self.assertEqual(hud._details_button.cget("text"), "Ocultar campanha")

    def test_expanding_at_bottom_keeps_controls_on_left_monitor(self):
        left_monitor = (-1920, 0, 0, 1032)
        with patch.object(MiniHUD, "_work_area", return_value=left_monitor):
            hud = MiniHUD(self.manager)
            self.root.update()
            self.assertLess(hud.window.winfo_x(), 0)

            hud._details_button.invoke()
            self.root.update()
            bottom = left_monitor[3]
            x = -400
            hud.window.geometry(f"+{x}+{bottom - hud.window.winfo_height()}")
            self.root.update()

            hud._details_button.invoke()
            self.root.update()
            self.assertEqual(hud.window.winfo_x(), x)
            self.assertEqual(hud.window.winfo_y() + hud.window.winfo_height(), bottom)
            self.assertTrue(hud._details_button.winfo_ismapped())

    def test_long_reward_fits_with_the_layout_scaled_up(self):
        previous_scaling = self.root.tk.call("tk", "scaling")
        self.root.tk.call("tk", "scaling", 2.0)
        try:
            hud = MiniHUD(self.manager)
            name = "Recompensa especial " * 12
            hud._reward.set(name)
            self.root.update()
            self.assertTrue(hud._reward_label.cget("text").endswith("…"))
            self.assertEqual(hud._reward.get(), name)
            self.assertGreater(hud.window.winfo_width(), MiniHUD.WIDTH)
            self.assertGreaterEqual(hud.window.winfo_height(), hud.window.winfo_reqheight())
            self.assertLess(
                hud._details_button.winfo_rooty() + hud._details_button.winfo_height(),
                hud.window.winfo_rooty() + hud.window.winfo_height(),
            )
        finally:
            self.root.tk.call("tk", "scaling", previous_scaling)

    def test_status_label_drags_the_overlay(self):
        hud = MiniHUD(self.manager)
        self.root.update()
        x, y = hud.window.winfo_x(), hud.window.winfo_y()
        hud._status_label.event_generate("<ButtonPress-1>", rootx=x + 90, rooty=y + 12)
        hud._status_label.event_generate("<B1-Motion>", rootx=x + 67, rooty=y - 18)
        self.root.update()
        self.assertEqual((hud.window.winfo_x(), hud.window.winfo_y()), (x - 23, y - 30))

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
