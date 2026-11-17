import unittest
from copy import deepcopy
from functools import partial
from pathlib import Path
from tkinter import ttk
from types import SimpleNamespace
from unittest.mock import patch

from gui import GUIManager, SettingsPanel
from settings import default_settings
from translate import _


class DashboardLayoutTests(unittest.TestCase):
    def setUp(self):
        previous_language = _.current
        _.set_language("Português")
        self.addCleanup(_.set_language, previous_language)
        settings = SimpleNamespace(**deepcopy(default_settings), tray=False)
        settings.dark_mode = True
        twitch = SimpleNamespace(
            settings=settings,
            change_state=lambda _state: None,
            state_change=lambda state: partial(twitch.change_state, state),
        )
        source = Path(__file__).resolve().parents[1]
        with (
            patch("gui.resource_path", side_effect=lambda path: source / path),
            patch("gui.ImageCache"),
            patch("gui.GameProfilesStore"),
            patch("gui.ClaimHistoryStore"),
            patch.object(SettingsPanel, "_query_autostart", return_value=False),
        ):
            self.gui = GUIManager(twitch)
        self.addCleanup(self.gui.close_window)
        self.gui._root.minsize(1080, 720)

    def assert_widget_visible(self, widget, container):
        self.assertTrue(widget.winfo_ismapped(), str(widget))
        left = widget.winfo_rootx() - container.winfo_rootx()
        top = widget.winfo_rooty() - container.winfo_rooty()
        self.assertGreaterEqual(left, 0, str(widget))
        self.assertGreaterEqual(top, 0, str(widget))
        self.assertLessEqual(left + widget.winfo_width(), container.winfo_width(), str(widget))
        self.assertLessEqual(top + widget.winfo_height(), container.winfo_height(), str(widget))

    def show_drop(self, game, title, reward):
        campaign = SimpleNamespace(
            game=SimpleNamespace(name=game),
            name=title,
            remaining_minutes=208,
            progress=0.476,
            claimed_drops=1,
            total_drops=4,
        )
        drop = SimpleNamespace(
            campaign=campaign,
            rewards_text=lambda: reward,
            progress=0.517,
            remaining_minutes=28,
        )
        self.gui.progress.display(drop, countdown=False)

    def test_drop_and_campaign_progress_fit_dashboard_at_supported_sizes(self):
        dashboard = self.gui.progress._frame.master
        hero = self.gui.progress._frame
        self.show_drop("Marvel Rivals", "Season 11 Twitch Drops", "Devil Dinosaur Nameplate")
        self.gui.login.update(_("gui", "login", "logged_in"), 123456789)
        self.gui.websockets.update(0, status=_("gui", "websocket", "connected"), topics=42)
        self.gui.output.print("Aguardando atualizações da campanha")
        self.gui.status.update("Assistindo: Canal de demonstração")

        root = self.gui._root
        sizes = [(1080, 720)]
        # A virtual display may clamp the window before it reaches the larger size.
        if root.winfo_screenwidth() >= 1340 and root.winfo_screenheight() >= 860:
            sizes.append((1320, 800))
        for width, height in sizes:
            with self.subTest(width=width, height=height):
                root.geometry(f"{width}x{height}")
                root.update()
                self.assertEqual(root.winfo_width(), width)
                self.assertEqual(root.winfo_height(), height)
                bars = [
                    widget for widget in hero.winfo_children() if isinstance(widget, ttk.Progressbar)
                ]
                self.assertEqual(len(bars), 2)
                for widget in hero.winfo_children():
                    self.assert_widget_visible(widget, hero)
                    for nested in widget.winfo_children():
                        self.assert_widget_visible(nested, widget)
                self.assert_widget_visible(hero, dashboard)
                login = self.gui.login._button.master
                for widget in login.grid_slaves():
                    self.assert_widget_visible(widget, login)
                connection = dashboard.grid_slaves(row=2, column=1)[0]
                for widget in connection.grid_slaves():
                    self.assert_widget_visible(widget, connection)
                self.assert_widget_visible(self.gui.output._text, dashboard)
                self.assert_widget_visible(self.gui.channels._table, dashboard)

    def test_long_names_do_not_resize_the_channel_panel(self):
        root = self.gui._root
        root.geometry("1080x720")
        self.show_drop("Game", "Campaign", "Reward")
        root.update()
        channels = self.gui.channels._table
        expected_channel_width = channels.winfo_width()
        progress = self.gui.progress

        long_game = "O Reino das Estrelas: edição especial ilustrada com trilha sonora"
        long_campaign = "O Festival da Lua e todos os eventos especiais desta temporada"
        long_reward = "Primeira recompensa e segunda recompensa da edição comemorativa"
        self.show_drop(long_game, long_campaign, long_reward)
        root.update()

        self.assertTrue(channels.winfo_ismapped())
        self.assertEqual(channels.winfo_width(), expected_channel_width)
        self.assertEqual(progress._vars["campaign"]["game"].get(), long_game)
        self.assertEqual(progress._vars["campaign"]["name"].get(), long_campaign)
        self.assertEqual(progress._vars["drop"]["rewards"].get(), long_reward)
        labels = [
            widget for widget in progress._frame.winfo_children()
            if isinstance(widget, ttk.Label)
        ]
        metadata_frames = [
            widget for widget in progress._frame.winfo_children()
            if isinstance(widget, ttk.Frame)
        ]
        for frame in metadata_frames:
            labels.extend(frame.winfo_children())
        truncated = [label for label in labels if label.cget("text").endswith("…")]
        self.assertEqual(len(truncated), 3)
