import asyncio
import tkinter as tk
import unittest
from tkinter import ttk

from gui import LoginForm
from translate import _


class LoginManager:
    async def coro_unless_closed(self, operation):
        return await operation


class SettingsAccountTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        previous_language = _.current
        _.set_language("Português")
        self.addCleanup(_.set_language, previous_language)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.dashboard = ttk.Frame(self.root)
        self.account = ttk.Frame(self.root)
        self.form = LoginForm(LoginManager(), self.dashboard)

    async def test_settings_button_updates_the_existing_browser_login_event(self):
        self.form.build_settings_view(self.account)
        button = self.form._settings_button
        self.assertTrue(button.instate(("disabled",)))

        login = asyncio.create_task(self.form.wait_for_login_press())
        await asyncio.sleep(0)
        self.assertFalse(login.done())
        self.assertTrue(button.instate(("!disabled",)))
        self.assertTrue(self.form._button.instate(("!disabled",)))
        self.assertEqual(button.cget("text"), _("gui", "login", "settings_continue"))

        button.invoke()

        await asyncio.wait_for(login, timeout=1)
        self.assertTrue(button.instate(("disabled",)))
        self.assertTrue(self.form._button.instate(("disabled",)))

    async def test_opening_settings_during_login_shares_state_and_cancellation(self):
        login = asyncio.create_task(self.form.wait_for_login_press())
        await asyncio.sleep(0)
        self.form.build_settings_view(self.account)
        button = self.form._settings_button
        self.assertTrue(button.instate(("!disabled",)))
        self.assertEqual(
            self.form._settings_hint.get(), _("gui", "login", "settings_continue_hint"),
        )

        login.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await login

        self.assertTrue(button.instate(("disabled",)))
        self.assertTrue(self.form._button.instate(("disabled",)))
        self.assertEqual(
            self.form._settings_hint.get(), _("gui", "login", "settings_sign_in_hint"),
        )

    def test_account_view_reflects_connection_status_and_omits_user_id(self):
        self.form.build_settings_view(self.account)
        button = self.form._settings_button
        self.assertEqual(self.form._settings_status.get(), _("gui", "login", "logged_out"))
        self.assertEqual(button.winfo_manager(), "grid")

        connected = _("gui", "login", "logged_in")
        self.form.update(connected, 123456789)

        self.assertEqual(self.form._settings_status.get(), connected)
        self.assertEqual(self.form._var.get(), f"{connected}\n123456789")
        self.assertEqual(button.winfo_manager(), "")
        self.assertEqual(
            self.form._settings_hint.get(), _("gui", "login", "settings_connected_hint"),
        )

        logging_in = _("gui", "login", "logging_in")
        self.form.update(logging_in, None)

        self.assertEqual(self.form._settings_status.get(), logging_in)
        self.assertEqual(button.winfo_manager(), "grid")
        self.assertTrue(button.instate(("disabled",)))
