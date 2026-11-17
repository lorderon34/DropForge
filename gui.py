from __future__ import annotations

import os
import re
import sys
import shlex
import ctypes
import asyncio
import logging
import plistlib
import tkinter as tk
from pathlib import Path
from collections import Counter
from collections import abc
from textwrap import dedent
from math import log10, ceil
from dataclasses import dataclass
from tkinter.font import Font, nametofont
from functools import partial, cached_property
from datetime import datetime, timedelta, timezone
from tkinter import Tk, ttk, StringVar, DoubleVar, IntVar, filedialog
from typing import Any, Union, Tuple, TypedDict, NoReturn, Generic, TYPE_CHECKING

import pystray
from yarl import URL
from PIL.ImageTk import PhotoImage
from PIL import Image as Image_module

if sys.platform == "win32":
    import win32api
    import win32con
    import win32gui

if sys.platform == "darwin":
    import AppKit

from translate import _
from cache import ImageCache
from campaign_agenda import (
    CampaignAgendaEvent,
    build_campaign_agenda,
    serialize_campaign_calendar,
)
from campaign_search import campaign_matches_search, passes_game_filter
from claim_history import ClaimHistoryStore, ClaimRecord
from game_profiles import GameProfilesStore, ProfileLimitError, apply_game_profile
from deadline_radar import (
    DeadlineCandidate,
    SessionRecommendation,
    rank_deadline_candidates,
    rank_for_session,
)
from diagnostics import diagnose_campaigns
from priority_actions import add_game_to_priority, remove_game_from_priority
from exceptions import MinerException, ExitRequest
from utils import resource_path, set_root_icon, webopen, task_wrapper, Game, _T
from window_state import WindowGeometry, parse_window_geometry, window_geometry_is_visible
from constants import (
    APP_NAME,
    MAX_INT,
    SELF_PATH,
    IS_PACKAGED,
    SCRIPTS_PATH,
    WINDOW_TITLE,
    LOGGING_LEVELS,
    MAX_WEBSOCKETS,
    WS_TOPICS_LIMIT,
    OUTPUT_FORMATTER,
    State,
    PriorityMode,
)
if sys.platform == "win32":
    from registry import RegistryKey, ValueType, ValueNotFound


if TYPE_CHECKING:
    from twitch import Twitch
    from channel import Channel
    from settings import Settings
    from inventory import DropsCampaign, TimedDrop


logger = logging.getLogger("TwitchDrops")
TK_PADDING = Union[int, Tuple[int, int], Tuple[int, int, int], Tuple[int, int, int, int]]
DIGITS = ceil(log10(WS_TOPICS_LIMIT))


######################
# GUI ELEMENTS START #
######################


class _TKOutputHandler(logging.Handler):
    def __init__(self, output: GUIManager):
        super().__init__()
        self._output = output

    def emit(self, record):
        self._output.print(self.format(record))


class PlaceholderEntry(ttk.Entry):
    def __init__(
        self,
        master: ttk.Widget,
        *args: Any,
        placeholder: str,
        prefill: str = '',
        placeholdercolor: str = "grey60",
        **kwargs: Any,
    ):
        super().__init__(master, *args, **kwargs)
        self._prefill: str = prefill
        self._show: str = kwargs.get("show", '')
        self._text_color: str = kwargs.get("foreground", '')
        self._ph_color: str = placeholdercolor
        self._ph_text: str = placeholder
        self.bind("<FocusIn>", self._focus_in)
        self.bind("<FocusOut>", self._focus_out)
        if isinstance(self, ttk.Combobox):
            # only bind this for comboboxes
            self.bind("<<ComboboxSelected>>", self._combobox_select)
        self._ph: bool = False
        self._insert_placeholder()

    def _insert_placeholder(self) -> None:
        """
        If we're empty, insert a placeholder, set placeholder text color and make sure it's shown.
        If we're not empty, leave the box as is.
        """
        if not super().get():
            self._ph = True
            super().config(foreground=self._ph_color, show='')
            super().insert("end", self._ph_text)

    def _remove_placeholder(self) -> None:
        """
        If we've had a placeholder, clear the box and set normal text colour and show.
        """
        if self._ph:
            self._ph = False
            super().delete(0, "end")
            super().config(foreground=self._text_color, show=self._show)
            if self._prefill:
                super().insert("end", self._prefill)

    def _focus_in(self, event: tk.Event[PlaceholderEntry]) -> None:
        self._remove_placeholder()

    def _focus_out(self, event: tk.Event[PlaceholderEntry]) -> None:
        self._insert_placeholder()

    def _combobox_select(self, event: tk.Event[PlaceholderEntry]):
        # combobox clears and inserts the selected value internally, bypassing the insert method.
        # disable the placeholder flag and set the color here, so _focus_in doesn't clear the entry
        self._ph = False
        super().config(foreground=self._text_color, show=self._show)

    def _store_option(
        self, options: dict[str, object], name: str, attr: str, *, remove: bool = False
    ) -> None:
        if name in options:
            if remove:
                value = options.pop(name)
            else:
                value = options[name]
            setattr(self, attr, value)

    def configure(self, *args: Any, **kwargs: Any) -> Any:
        options: dict[str, Any] = {}
        if args and args[0] is not None:
            options.update(args[0])
        if kwargs:
            options.update(kwargs)
        self._store_option(options, "show", "_show")
        self._store_option(options, "foreground", "_text_color")
        self._store_option(options, "placeholder", "_ph_text", remove=True)
        self._store_option(options, "prefill", "_prefill", remove=True)
        self._store_option(options, "placeholdercolor", "_ph_color", remove=True)
        return super().configure(**kwargs)

    def config(self, *args: Any, **kwargs: Any) -> Any:
        # because 'config = configure' makes mypy complain
        self.configure(*args, **kwargs)

    def get(self) -> str:
        if self._ph:
            return ''
        return super().get()

    def insert(self, index: str | int, content: str) -> None:
        # when inserting into the entry externally, disable the placeholder flag
        if not content:
            # if an empty string was passed in
            return
        self._remove_placeholder()
        super().insert(index, content)

    def delete(self, first: str | int, last: str | int | None = None) -> None:
        super().delete(first, last)
        self._insert_placeholder()

    def clear(self) -> None:
        self.delete(0, "end")

    def replace(self, content: str) -> None:
        super().delete(0, "end")
        self.insert("end", content)


class PlaceholderCombobox(PlaceholderEntry, ttk.Combobox):
    pass


class PaddedListbox(tk.Listbox):
    def __init__(self, master: ttk.Widget, *args, padding: TK_PADDING = (0, 0, 0, 0), **kwargs):
        # we place the listbox inside a frame with the same background
        # this means we need to forward the 'grid' method to the frame, not the listbox
        self._frame = tk.Frame(master)
        self._frame.rowconfigure(0, weight=1)
        self._frame.columnconfigure(0, weight=1)
        super().__init__(self._frame)
        # mimic default listbox style with sunken relief and borderwidth of 1
        if "relief" not in kwargs:
            kwargs["relief"] = "sunken"
        if "borderwidth" not in kwargs:
            kwargs["borderwidth"] = 1
        self.configure(*args, padding=padding, **kwargs)

    def grid(self, *args, **kwargs):
        return self._frame.grid(*args, **kwargs)

    def grid_remove(self) -> None:
        return self._frame.grid_remove()

    def grid_info(self) -> tk._GridInfo:
        return self._frame.grid_info()

    def grid_forget(self) -> None:
        return self._frame.grid_forget()

    def configure(self, *args: Any, **kwargs: Any) -> Any:
        options: dict[str, Any] = {}
        if args and args[0] is not None:
            options.update(args[0])
        if kwargs:
            options.update(kwargs)
        # NOTE on processed options:
        # • relief is applied to the frame only
        # • background is copied, so that both listbox and frame change color
        # • borderwidth is applied to the frame only
        # bg is folded into background for easier processing
        if "bg" in options:
            options["background"] = options.pop("bg")
        frame_options = {}
        if "relief" in options:
            frame_options["relief"] = options.pop("relief")
        if "background" in options:
            frame_options["background"] = options["background"]  # copy
        if "borderwidth" in options:
            frame_options["borderwidth"] = options.pop("borderwidth")
        self._frame.configure(frame_options)
        # update padding
        if "padding" in options:
            padding: TK_PADDING = options.pop("padding")
            padx1: tk._ScreenUnits
            padx2: tk._ScreenUnits
            pady1: tk._ScreenUnits
            pady2: tk._ScreenUnits
            if not isinstance(padding, tuple) or len(padding) == 1:
                if isinstance(padding, tuple):
                    padding = padding[0]
                padx1 = padx2 = pady1 = pady2 = padding
            elif len(padding) == 2:
                padx1 = padx2 = padding[0]
                pady1 = pady2 = padding[1]
            elif len(padding) == 3:
                padx1, padx2 = padding[0], padding[1]
                pady1 = pady2 = padding[2]
            else:
                padx1, padx2, pady1, pady2 = padding
            super().grid(column=0, row=0, padx=(padx1, padx2), pady=(pady1, pady2), sticky="nsew")
        else:
            super().grid(column=0, row=0, sticky="nsew")
        # listbox uses flat relief to blend in with the inside of the frame
        options["relief"] = "flat"
        return super().configure(options)

    def config(self, *args: Any, **kwargs: Any) -> Any:
        # because 'config = configure' makes mypy complain
        self.configure(*args, **kwargs)

    def configure_theme(self, *, bg: str, fg: str, sel_bg: str, sel_fg: str):
        # Apply basic colors for dark/light mode
        super().config(bg=bg, fg=fg, selectbackground=sel_bg, selectforeground=sel_fg)


class MouseOverLabel(ttk.Label):
    def __init__(self, *args, alt_text: str = '', reverse: bool = False, **kwargs) -> None:
        self._org_text: str = ''
        self._alt_text: str = ''
        self._alt_reverse: bool = reverse
        self._bind_enter: str | None = None
        self._bind_leave: str | None = None
        super().__init__(*args, **kwargs)
        self.configure(text=kwargs.get("text", ''), alt_text=alt_text, reverse=reverse)

    def _set_org(self, event: tk.Event[MouseOverLabel]):
        super().config(text=self._org_text)

    def _set_alt(self, event: tk.Event[MouseOverLabel]):
        super().config(text=self._alt_text)

    def configure(self, *args: Any, **kwargs: Any) -> Any:
        options: dict[str, Any] = {}
        if args and args[0] is not None:
            options.update(args[0])
        if kwargs:
            options.update(kwargs)
        applicable_options: set[str] = set((
            "text",
            "reverse",
            "alt_text",
        ))
        if applicable_options.intersection(options.keys()):
            # we need to pop some options, because they can't be passed down to the label,
            # as that will result in an error later down the line
            events_change: bool = False
            if "text" in options:
                if bool(self._org_text) != bool(options["text"]):
                    events_change = True
                self._org_text = options["text"]
            if "alt_text" in options:
                if bool(self._alt_text) != bool(options["alt_text"]):
                    events_change = True
                self._alt_text = options.pop("alt_text")
            if "reverse" in options:
                if bool(self._alt_reverse) != bool(options["reverse"]):
                    events_change = True
                self._alt_reverse = options.pop("reverse")
            if self._org_text and not self._alt_text:
                options["text"] = self._org_text
            elif (not self._org_text or self._alt_reverse) and self._alt_text:
                options["text"] = self._alt_text
            if events_change:
                if self._bind_enter is not None:
                    self.unbind(self._bind_enter)
                    self._bind_enter = None
                if self._bind_leave is not None:
                    self.unbind(self._bind_leave)
                    self._bind_leave = None
                if self._org_text and self._alt_text:
                    if self._alt_reverse:
                        self._bind_enter = self.bind("<Enter>", self._set_org)
                        self._bind_leave = self.bind("<Leave>", self._set_alt)
                    else:
                        self._bind_enter = self.bind("<Enter>", self._set_alt)
                        self._bind_leave = self.bind("<Leave>", self._set_org)
        return super().configure(options)

    def config(self, *args: Any, **kwargs: Any) -> Any:
        # because 'config = configure' makes mypy complain
        self.configure(*args, **kwargs)


class LinkLabel(ttk.Label):
    def __init__(self, *args, link: str, **kwargs) -> None:
        self._link: str = link
        # style provides font and foreground color
        if "style" not in kwargs:
            kwargs["style"] = "Link.TLabel"
        elif not kwargs["style"]:
            super().__init__(*args, **kwargs)
            return
        if "cursor" not in kwargs:
            kwargs["cursor"] = "hand2"
        if "padding" not in kwargs:
            # W, N, E, S
            kwargs["padding"] = (0, 2, 0, 2)
        super().__init__(*args, **kwargs)
        self.bind("<ButtonRelease-1>", lambda e: webopen(self._link))


class SelectMenu(tk.Menubutton, Generic[_T]):
    def __init__(
        self,
        master: tk.Misc,
        *args: Any,
        tearoff: bool = False,
        options: dict[str, _T],
        command: abc.Callable[[_T], Any] | None = None,
        default: str | None = None,
        relief: tk._Relief = "solid",
        background: str = "white",
        **kwargs: Any,
    ):
        width = max((len(k) for k in options.keys()), default=20)
        super().__init__(
            master, *args, background=background, relief=relief, width=width, **kwargs
        )
        self._menu_options: dict[str, _T] = options
        self._command = command
        self.menu = tk.Menu(self, tearoff=tearoff)
        self.config(menu=self.menu)
        for name in options.keys():
            self.menu.add_command(label=name, command=partial(self._select, name))
        if default is not None and default in self._menu_options:
            self.config(text=default)

    def _select(self, option: str) -> None:
        self.config(text=option)
        if self._command is not None:
            self._command(self._menu_options[option])

    def get(self) -> _T:
        return self._menu_options[self.cget("text")]


class SelectCombobox(ttk.Combobox):
    def __init__(
        self,
        master: tk.Misc,
        *args,
        width_offset: int = 0,
        width: int | None = None,
        textvariable: tk.StringVar,
        values: list[str] | tuple[str, ...],
        command: abc.Callable[[tk.Event[SelectCombobox]], None] | None = None,
        **kwargs,
    ) -> None:
        if width is None:
            font = Font(master, ttk.Style().lookup("TCombobox", "font"))
            # font.measure returns width in pixels, using '0' as the average character,
            # which is 6 pixels wide. We can convert it to width in characters by dividing.
            width = max(font.measure(v) // 6 + 1 for v in values)
        width += width_offset
        super().__init__(
            master,
            *args,
            width=width,
            values=values,
            state="readonly",
            exportselection=False,
            textvariable=textvariable,
            **kwargs,
        )
        if command is not None:
            self.bind("<<ComboboxSelected>>", command)


###########################################
# GUI ELEMENTS END / GUI DEFINITION START #
###########################################


class StatusBar:
    def __init__(self, manager: GUIManager, master: ttk.Widget):
        self._manager = manager
        self._text = ""
        frame = ttk.Frame(master, style="Topbar.TFrame", padding=(16, 12))
        frame.grid(column=0, row=0, columnspan=3, sticky="ew", pady=(0, 12))
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text=_("gui", "status", "name").upper(), style="Overline.TLabel").grid(
            column=0, row=0, sticky="w"
        )
        self._label = ttk.Label(frame, anchor="e", style="LiveStatus.TLabel")
        self._label.grid(column=2, row=0, sticky="e", padx=(0, 12))
        ttk.Button(
            frame,
            text=_("gui", "status", "diagnostics"),
            command=manager.show_diagnostics,
        ).grid(column=3, row=0, sticky="e")
        ttk.Button(
            frame,
            text=_("gui", "hud", "button"),
            command=manager.show_hud,
            style="Primary.TButton",
        ).grid(column=4, row=0, sticky="e", padx=(8, 0))

    def update(self, text: str):
        self._text = text
        self._label.config(text=text)
        self._manager.update_hud_status(text)

    def clear(self):
        self.update("")


class MiniHUD:
    """Compact always-on-top campaign companion for checking progress in-game."""

    WIDTH = 370

    def __init__(self, manager: GUIManager):
        self._manager = manager
        self.window = window = tk.Toplevel(manager._root)
        window.withdraw()
        window.title("DropForge Mini HUD")
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        window.resizable(False, False)
        window.configure(background=manager._style.lookup("HUD.TFrame", "background"))
        left, top, right, bottom = self._work_area(manager._root)
        scale = float(window.tk.call("tk", "scaling")) * 0.75
        self._width = min(round(self.WIDTH * scale), right - left - 16)
        self._compact = False
        self._has_drop = False
        self._drag_offset: tuple[int, int] | None = None

        self._status = StringVar(window, value=_("gui", "hud", "waiting"))
        self._game = StringVar(window, value="...")
        self._campaign = StringVar(window, value="...")
        self._reward = StringVar(window, value=_("gui", "hud", "no_drop"))
        self._percentage = StringVar(window, value="--%")
        self._remaining = StringVar(window, value="—")
        self._progress = DoubleVar(window, value=0.0)
        self._campaign_progress = DoubleVar(window, value=0.0)
        self._campaign_summary = StringVar(window, value="—")

        shell = ttk.Frame(window, style="HUD.TFrame", padding=1)
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1)

        header = ttk.Frame(shell, style="HUDHeader.TFrame", padding=(12, 5))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(2, weight=1)
        self._live = ttk.Label(header, text="●", style="HUDIdle.TLabel")
        self._live.grid(row=0, column=0, sticky="w", padx=(0, 7))
        title = ttk.Label(
            header,
            text=_("gui", "hud", "title"),
            style="HUDTitle.TLabel",
        )
        title.grid(row=0, column=1, sticky="w")
        self._status_label = CampaignProgress._name_label(header, self._status, "HUDIdle.TLabel")
        self._status_label.configure(anchor="e")
        self._status_label.grid(row=0, column=2, sticky="ew", padx=(8, 9))
        ttk.Button(
            header,
            text="×",
            width=2,
            command=manager.close_hud,
            style="HUDClose.TButton",
        ).grid(row=0, column=3, sticky="e")

        content = ttk.Frame(shell, style="HUDContent.TFrame", padding=(12, 9))
        content.grid(row=1, column=0, sticky="ew")
        content.columnconfigure(0, weight=1)
        CampaignProgress._name_label(content, self._game, "HUDGame.TLabel").grid(
            row=0, column=0, sticky="ew"
        )
        self._reward_label = CampaignProgress._name_label(content, self._reward, "HUDReward.TLabel")
        self._reward_label.grid(row=1, column=0, sticky="ew", pady=(3, 0))
        ttk.Label(content, text=_("gui", "hud", "remaining"), style="HUDMuted.TLabel").grid(
            row=0, column=1, sticky="e", padx=(12, 0)
        )
        ttk.Label(content, textvariable=self._remaining, style="HUDTimer.TLabel").grid(
            row=1, column=1, sticky="e", padx=(12, 0), pady=(3, 0)
        )
        ttk.Progressbar(
            content,
            mode="determinate",
            maximum=1,
            variable=self._progress,
            style="HUD.Horizontal.TProgressbar",
        ).grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(content, textvariable=self._percentage, style="HUDPercent.TLabel").grid(
            row=2, column=1, sticky="e", padx=(12, 0), pady=(8, 0)
        )

        self._details = details = ttk.Frame(content, style="HUDContent.TFrame")
        details.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        details.columnconfigure(0, weight=1)
        ttk.Separator(details).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 7))
        ttk.Label(details, text=_("gui", "hud", "campaign"), style="HUDMuted.TLabel").grid(
            row=1, column=0, sticky="w"
        )
        ttk.Label(details, textvariable=self._campaign_summary, style="HUDMuted.TLabel").grid(
            row=1, column=1, sticky="e", padx=(8, 0)
        )
        CampaignProgress._name_label(details, self._campaign, "HUDGame.TLabel").grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(2, 5)
        )
        ttk.Progressbar(
            details,
            mode="determinate",
            maximum=1,
            variable=self._campaign_progress,
            style="Campaign.Horizontal.TProgressbar",
        ).grid(row=3, column=0, columnspan=2, sticky="ew")

        footer = ttk.Frame(shell, style="HUDHeader.TFrame", padding=(12, 5))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self._details_button = ttk.Button(
            footer,
            text=_("gui", "hud", "compact"),
            command=self._toggle_compact,
            style="HUDClose.TButton",
        )
        self._details_button.grid(row=0, column=0, sticky="w")
        ttk.Button(
            footer,
            text=_("gui", "hud", "open"),
            command=lambda: manager.grab_attention(sound=False),
            style="HUDClose.TButton",
        ).grid(row=0, column=1, sticky="e")

        for widget in (header, self._live, title, self._status_label):
            widget.configure(cursor="fleur")
            widget.bind("<ButtonPress-1>", self._drag_start, add="+")
            widget.bind("<B1-Motion>", self._drag_move, add="+")
        window.bind("<Escape>", lambda _event: manager.close_hud())
        window.update_idletasks()
        height = window.winfo_reqheight()
        x = max(left + 8, right - self._width - 20)
        y = max(top + 8, bottom - height - 20)
        window.geometry(f"{self._width}x{height}+{x}+{y}")
        window.deiconify()

    @staticmethod
    def _work_area(widget: tk.Misc) -> tuple[int, int, int, int]:
        if sys.platform == "win32":
            try:
                monitor = win32api.MonitorFromWindow(
                    widget.winfo_id(), win32con.MONITOR_DEFAULTTONEAREST
                )
                return win32api.GetMonitorInfo(monitor)["Work"]
            except win32api.error:
                pass
        return (0, 0, widget.winfo_screenwidth(), widget.winfo_screenheight())

    def _toggle_compact(self) -> None:
        self._compact = not self._compact
        if self._compact:
            self._details.grid_remove()
        else:
            self._details.grid()
        self._details_button.configure(
            text=_("gui", "hud", "expand" if self._compact else "compact")
        )
        self._resize()

    def _resize(self) -> None:
        window = self.window
        window.update_idletasks()
        height = window.winfo_reqheight()
        left, top, right, bottom = self._work_area(window)
        x = max(left, min(window.winfo_x(), right - self._width))
        y = max(top, min(window.winfo_y(), bottom - height))
        window.geometry(f"{self._width}x{height}+{x}+{y}")

    def _drag_start(self, event: tk.Event) -> None:
        self._drag_offset = (event.x_root - self.window.winfo_x(), event.y_root - self.window.winfo_y())

    def _drag_move(self, event: tk.Event) -> None:
        if self._drag_offset is None:
            return
        offset_x, offset_y = self._drag_offset
        self.window.geometry(f"+{event.x_root - offset_x}+{event.y_root - offset_y}")

    def update_status(self, text: str) -> None:
        self._status.set(text.strip() or _("gui", "hud", "waiting"))

    def update_drop(self, drop: TimedDrop | None) -> None:
        self._has_drop = drop is not None
        self._live.configure(style="HUDLive.TLabel" if self._has_drop else "HUDIdle.TLabel")
        if drop is None:
            self._game.set("...")
            self._campaign.set("...")
            self._reward.set(_("gui", "hud", "no_drop"))
            self._percentage.set("--%")
            self._progress.set(0.0)
            self._remaining.set("—")
            self._campaign_progress.set(0.0)
            self._campaign_summary.set("—")
            return
        campaign = drop.campaign
        campaign_progress = campaign.progress
        self._game.set(campaign.game.name)
        self._campaign.set(campaign.name)
        self._reward.set(drop.rewards_text())
        self._percentage.set(f"{drop.progress:.0%}")
        self._progress.set(drop.progress)
        self._campaign_progress.set(campaign_progress)
        self._campaign_summary.set(
            _("gui", "hud", "campaign_progress").format(
                percent=f"{campaign_progress:.0%}",
                claimed=campaign.claimed_drops,
                total=campaign.total_drops,
            )
        )

    def update_remaining(self, text: str) -> None:
        if self._has_drop:
            timer = re.search(r"\d+:\d{2}(?::\d{2})?", text)
            self._remaining.set(timer.group() if timer else "—")

    def refresh_theme(self) -> None:
        self.window.configure(background=self._manager._style.lookup("HUD.TFrame", "background"))
        self._resize()


class CampaignDiagnosticsDialog:
    REASON_ORDER = (
        "priority",
        "excluded",
        "not_linked",
        "badges_disabled",
        "waiting_for_previous",
        "drop_starts_later",
        "drop_expired",
        "progress_sync",
        "drop_not_ready",
        "upcoming",
        "expired",
        "finished",
    )

    def __init__(self, manager: GUIManager):
        self._manager = manager
        twitch = manager._twitch
        text = lambda key: _("gui", "diagnostics", key)
        settings = twitch.settings
        diagnoses = diagnose_campaigns(
            twitch.inventory,
            priority_games=settings.priority,
            excluded_games=settings.exclude,
            priority_only=settings.priority_mode is PriorityMode.PRIORITY_ONLY,
        )
        available = sum(item.reason is None for item in diagnoses)
        grouped = Counter(item.reason for item in diagnoses if item.reason is not None)

        window = tk.Toplevel(manager._root)
        self.window = window
        window.title(text("title"))
        window.transient(manager._root)
        window.minsize(580, 440)
        window.resizable(True, True)
        window.configure(background=manager._style.lookup("TFrame", "background"))
        shell = ttk.Frame(window, padding=16)
        shell.grid(column=0, row=0, sticky="nsew")
        window.rowconfigure(0, weight=1)
        window.columnconfigure(0, weight=1)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(3, weight=1)

        ttk.Label(
            shell,
            text=text("title"),
            style="Section.TLabel",
            font=manager._fonts["section"],
        ).grid(column=0, row=0, sticky="w")
        ttk.Label(
            shell,
            text=text("intro"),
            style="Muted.TLabel",
            wraplength=620,
            justify="left",
        ).grid(column=0, row=1, sticky="w", pady=(5, 10))
        ttk.Label(
            shell,
            text=text("summary").format(
                campaigns=self._campaign_count(len(diagnoses), text),
                ready=self._campaign_count(available, text),
            ),
            style="Status.TLabel",
        ).grid(column=0, row=2, sticky="w", pady=(0, 10))

        report = ttk.Frame(shell, style="Card.TFrame", padding=1)
        report.grid(column=0, row=3, sticky="nsew")
        report.rowconfigure(0, weight=1)
        report.columnconfigure(0, weight=1)
        scroll = ttk.Scrollbar(report, orient="vertical")
        content = tk.Text(
            report,
            wrap="word",
            height=15,
            state="normal",
            padx=14,
            pady=12,
            borderwidth=0,
            highlightthickness=0,
            font=manager._fonts["default"],
            background=manager._style.lookup("Card.TFrame", "background"),
            foreground=manager._style.lookup("TLabel", "foreground"),
            selectbackground=manager._style.lookup("Treeview", "background"),
            yscrollcommand=scroll.set,
        )
        scroll.configure(command=content.yview)
        content.grid(column=0, row=0, sticky="nsew")
        scroll.grid(column=1, row=0, sticky="ns")
        content.tag_configure(
            "reason",
            foreground=manager._style.lookup("Section.TLabel", "foreground"),
            font=manager._fonts["section"],
            spacing1=8,
        )
        content.tag_configure(
            "muted", foreground=manager._style.lookup("Muted.TLabel", "foreground")
        )
        if not diagnoses:
            content.insert("end", text("empty") + "\n\n", "reason")
            content.insert("end", text("empty_tip") + "\n", "muted")
        else:
            if available:
                content.insert(
                    "end",
                    text("ready").format(
                        count=self._campaign_count(available, text)
                    ) + "\n\n",
                    "reason",
                )
            for reason in self.REASON_ORDER:
                count = grouped.get(reason, 0)
                if not count:
                    continue
                content.insert(
                    "end",
                    text("count_reason").format(
                        count=self._campaign_count(count, text),
                        reason=text("reasons")[reason],
                    ) + "\n",
                    "reason",
                )
                games = list(dict.fromkeys(
                    item.game for item in diagnoses if item.reason == reason
                ))
                game_list = ", ".join(games[:4])
                if len(games) > 4:
                    game_list += f" + {len(games) - 4}"
                content.insert("end", text("games").format(games=game_list) + "\n")
                content.insert(
                    "end",
                    text("action").format(tip=text("tips")[reason]) + "\n\n",
                    "muted",
                )
        content.configure(state="disabled")

        actions = ttk.Frame(shell)
        actions.grid(column=0, row=4, sticky="e", pady=(12, 0))
        ttk.Button(
            actions,
            text=text("open_campaigns"),
            command=partial(webopen, "https://www.twitch.tv/drops/campaigns"),
        ).grid(column=0, row=0, padx=(0, 6))
        ttk.Button(
            actions,
            text=text("settings"),
            command=self._open_settings,
        ).grid(column=1, row=0, padx=6)
        ttk.Button(
            actions,
            text=text("refresh"),
            command=self._reload_campaigns,
        ).grid(column=2, row=0, padx=6)
        ttk.Button(
            actions,
            text=text("close"),
            command=window.destroy,
        ).grid(column=3, row=0, padx=(6, 0))

        window.bind("<Escape>", lambda _event: window.destroy())
        window.update_idletasks()
        width = max(620, window.winfo_reqwidth())
        height = max(480, window.winfo_reqheight())
        x = manager._root.winfo_rootx() + (manager._root.winfo_width() - width) // 2
        y = manager._root.winfo_rooty() + (manager._root.winfo_height() - height) // 2
        window.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")
        window.focus_set()

    @staticmethod
    def _campaign_count(count: int, translate) -> str:
        key = "campaign_one" if count == 1 else "campaign_many"
        return translate(key).format(count=count)

    def _open_settings(self) -> None:
        self.window.destroy()
        self._manager.tabs.select_tab(2)

    def _reload_campaigns(self) -> None:
        self.window.destroy()
        self._manager._twitch.change_state(State.INVENTORY_FETCH)


class _WSEntry(TypedDict):
    status: str
    topics: int


class WebsocketStatus:
    def __init__(self, manager: GUIManager, master: ttk.Widget):
        frame = ttk.LabelFrame(
            master, text=_("gui", "websocket", "name"), padding=(12, 10),
        )
        frame.grid(column=1, row=2, sticky="nsew", padx=(6, 8), pady=(8, 10))
        self._status_var = StringVar(frame)
        self._topics_var = StringVar(frame)
        ttk.Label(
            frame,
            text='\n'.join(
                _("gui", "websocket", "websocket").format(id=i)
                for i in range(1, MAX_WEBSOCKETS + 1)
            ),
            style="MS.TLabel",
        ).grid(column=0, row=0)
        ttk.Label(
            frame,
            textvariable=self._status_var,
            width=16,
            justify="left",
            style="MS.TLabel",
        ).grid(column=1, row=0)
        ttk.Label(
            frame,
            textvariable=self._topics_var,
            width=(DIGITS * 2 + 1),
            justify="right",
            style="MS.TLabel",
        ).grid(column=2, row=0)
        self._items: dict[int, _WSEntry | None] = {i: None for i in range(MAX_WEBSOCKETS)}
        self._update()

    def update(self, idx: int, status: str | None = None, topics: int | None = None):
        if status is None and topics is None:
            raise TypeError("You need to provide at least one of: status, topics")
        entry = self._items.get(idx)
        if entry is None:
            entry = self._items[idx] = _WSEntry(
                status=_("gui", "websocket", "disconnected"), topics=0
            )
        if status is not None:
            entry["status"] = status
        if topics is not None:
            entry["topics"] = topics
        self._update()

    def remove(self, idx: int):
        if idx in self._items:
            del self._items[idx]
            self._update()

    def _update(self):
        status_lines: list[str] = []
        topic_lines: list[str] = []
        for idx in range(MAX_WEBSOCKETS):
            if (item := self._items.get(idx)) is None:
                status_lines.append('')
                topic_lines.append('')
            else:
                status_lines.append(item["status"])
                topic_lines.append(f"{item['topics']:>{DIGITS}}/{WS_TOPICS_LIMIT}")
        self._status_var.set('\n'.join(status_lines))
        self._topics_var.set('\n'.join(topic_lines))


@dataclass
class LoginData:
    username: str
    password: str
    token: str


class LoginForm:
    def __init__(self, manager: GUIManager, master: ttk.Widget):
        self._manager = manager
        self._var = StringVar(master)
        frame = ttk.LabelFrame(
            master, text=_("gui", "login", "name"), padding=(12, 10),
        )
        frame.grid(column=0, row=2, sticky="nsew", padx=(0, 6), pady=(8, 10))
        frame.columnconfigure(0, weight=2)
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text=_("gui", "login", "labels"), style="Muted.TLabel").grid(
            column=0, row=0, sticky="w", pady=(0, 8)
        )
        ttk.Label(frame, textvariable=self._var, justify="right", style="Value.TLabel").grid(
            column=1, row=0, sticky="e", pady=(0, 8)
        )
        self._login_entry = PlaceholderEntry(frame, placeholder=_("gui", "login", "username"))
        # self._login_entry.grid(column=0, row=1, columnspan=2)
        self._pass_entry = PlaceholderEntry(
            frame, placeholder=_("gui", "login", "password"), show='•'
        )
        # self._pass_entry.grid(column=0, row=2, columnspan=2)
        self._token_entry = PlaceholderEntry(frame, placeholder=_("gui", "login", "twofa_code"))
        # self._token_entry.grid(column=0, row=3, columnspan=2)

        self._confirm = asyncio.Event()
        self._button = ttk.Button(
            frame,
            text=_("gui", "login", "button"),
            command=self._confirm.set,
            state="disabled",
            style="Primary.TButton",
        )
        self._button.grid(column=0, row=4, columnspan=2, sticky="ew", pady=(4, 0))
        self.update(_("gui", "login", "logged_out"), None)

    def clear(self, login: bool = False, password: bool = False, token: bool = False):
        clear_all = not login and not password and not token
        if login or clear_all:
            self._login_entry.clear()
        if password or clear_all:
            self._pass_entry.clear()
        if token or clear_all:
            self._token_entry.clear()

    async def wait_for_login_press(self) -> None:
        self._confirm.clear()
        try:
            self._button.config(state="normal")
            await self._manager.coro_unless_closed(self._confirm.wait())
        finally:
            self._button.config(state="disabled")

    async def ask_login(self) -> LoginData:
        self.update(_("gui", "login", "required"), None)
        # ensure the window isn't hidden into tray when this runs
        self._manager.grab_attention(sound=False)
        while True:
            self._manager.print(_("gui", "login", "request"))
            await self.wait_for_login_press()
            login_data = LoginData(
                self._login_entry.get().strip(),
                self._pass_entry.get(),
                self._token_entry.get().strip(),
            )
            # basic input data validation: 3-25 characters in length, only ascii and underscores
            if (
                not 3 <= len(login_data.username) <= 25
                and re.match(r'^[a-zA-Z0-9_]+$', login_data.username)
            ):
                self.clear(login=True)
                continue
            if len(login_data.password) < 8:
                self.clear(password=True)
                continue
            if login_data.token and len(login_data.token) < 6:
                self.clear(token=True)
                continue
            return login_data

    async def ask_enter_code(self, page_url: URL, user_code: str) -> None:
        self.update(_("gui", "login", "required"), None)
        # ensure the window isn't hidden into tray when this runs
        self._manager.grab_attention(sound=False)
        self._manager.print(_("gui", "login", "request"))
        await self.wait_for_login_press()
        self._manager.print(f"Enter this code on the Twitch's device activation page: {user_code}")
        await asyncio.sleep(4)
        webopen(page_url)

    def update(self, status: str, user_id: int | None):
        if user_id is not None:
            user_str = str(user_id)
        else:
            user_str = "-"
        self._var.set(f"{status}\n{user_str}")


class _BaseVars(TypedDict):
    progress: DoubleVar
    percentage: StringVar
    remaining: StringVar


class _CampaignVars(_BaseVars):
    name: StringVar
    game: StringVar


class _DropVars(_BaseVars):
    rewards: StringVar


class _ProgressVars(TypedDict):
    campaign: _CampaignVars
    drop: _DropVars


class CampaignProgress:
    ALMOST_DONE_SECONDS = 10

    def __init__(self, manager: GUIManager, master: ttk.Widget):
        self._manager = manager
        self._vars: _ProgressVars = {
            "campaign": {
                "name": StringVar(master),  # campaign name
                "game": StringVar(master),  # game name
                "progress": DoubleVar(master),  # controls the progress bar
                "percentage": StringVar(master),  # percentage display string
                "remaining": StringVar(master),  # time remaining string, filled via _update_time
            },
            "drop": {
                "rewards": StringVar(master),  # drop rewards
                "progress": DoubleVar(master),  # as above
                "percentage": StringVar(master),  # as above
                "remaining": StringVar(master),  # as above
            },
        }
        self._frame = frame = ttk.Frame(master, style="Hero.TFrame", padding=(16, 10))
        frame.grid(column=0, row=1, columnspan=2, sticky="nsew", padx=(0, 8), pady=(0, 8))
        frame.columnconfigure(0, weight=1)
        ttk.Label(
            frame,
            text=_("gui", "progress", "name").upper(),
            style="HeroOverline.TLabel",
        ).grid(column=0, row=0, sticky="w", pady=(0, 6))
        ttk.Label(
            frame,
            textvariable=self._vars["campaign"]["percentage"],
            style="HeroStat.TLabel",
        ).grid(column=1, row=0, sticky="e", padx=(8, 0), pady=(0, 6))
        game_campaign = ttk.Frame(frame, style="Hero.TFrame", borderwidth=0, relief="flat")
        game_campaign.grid(column=0, row=1, columnspan=2, sticky="ew", pady=(0, 6))
        game_campaign.columnconfigure(0, weight=1, uniform="progress-metadata")
        game_campaign.columnconfigure(1, weight=2, uniform="progress-metadata")
        ttk.Label(
            game_campaign, text=_("gui", "progress", "game"), style="HeroMuted.TLabel"
        ).grid(column=0, row=0, sticky="w")
        self._name_label(game_campaign, self._vars["campaign"]["game"], "HeroValue.TLabel").grid(
            column=0, row=1, sticky="ew"
        )
        ttk.Label(
            game_campaign, text=_("gui", "progress", "campaign"), style="HeroMuted.TLabel"
        ).grid(column=1, row=0, sticky="w", padx=(12, 0))
        self._name_label(game_campaign, self._vars["campaign"]["name"], "HeroValue.TLabel").grid(
            column=1, row=1, sticky="ew", padx=(12, 0)
        )
        ttk.Progressbar(
            frame,
            mode="determinate",
            maximum=1,
            variable=self._vars["campaign"]["progress"],
            style="Campaign.Horizontal.TProgressbar",
        ).grid(column=0, row=2, columnspan=2, sticky="ew")
        ttk.Label(
            frame,
            textvariable=self._vars["campaign"]["remaining"],
            style="HeroMuted.TLabel",
        ).grid(column=0, row=3, columnspan=2, sticky="e", pady=(2, 6))
        ttk.Separator(frame, orient="horizontal", style="Hero.TSeparator").grid(
            column=0, row=4, columnspan=2, sticky="ew", pady=(0, 6)
        )
        ttk.Label(
            frame, text=_("gui", "progress", "drop"), style="HeroOverline.TLabel"
        ).grid(column=0, row=5, sticky="w")
        ttk.Label(
            frame, textvariable=self._vars["drop"]["percentage"], style="HeroPercent.TLabel"
        ).grid(column=1, row=5, rowspan=2, sticky="e", padx=(8, 0))
        self._name_label(frame, self._vars["drop"]["rewards"], "HeroReward.TLabel").grid(
            column=0, row=6, sticky="ew", pady=(0, 5)
        )
        ttk.Progressbar(
            frame,
            mode="determinate",
            maximum=1,
            variable=self._vars["drop"]["progress"],
            style="Drop.Horizontal.TProgressbar",
        ).grid(column=0, row=7, columnspan=2, sticky="ew")
        ttk.Label(
            frame, textvariable=self._vars["drop"]["remaining"], style="HeroMuted.TLabel"
        ).grid(column=0, row=8, columnspan=2, sticky="e", pady=(2, 0))
        self._drop: TimedDrop | None = None
        self._seconds: int = 0
        self._timer_task: asyncio.Task[None] | None = None
        self.display(None)

    @staticmethod
    def _name_label(master: ttk.Frame, value: StringVar, style: str) -> ttk.Label:
        # Long reward names should fit the card without resizing the channel list.
        label = ttk.Label(master, width=1, style=style)
        styles = ttk.Style(master)

        def fit_name(*_args) -> None:
            available = label.winfo_width() - 4
            if available <= 0:
                return
            name = " ".join(value.get().split())
            font = Font(root=label, font=styles.lookup(style, "font") or "TkDefaultFont")
            if font.measure(name) > available:
                if font.measure("…") > available:
                    name = ""
                else:
                    start, end = 0, len(name)
                    while start < end:
                        middle = (start + end + 1) // 2
                        if font.measure(name[:middle] + "…") <= available:
                            start = middle
                        else:
                            end = middle - 1
                    name = name[:start].rstrip() + "…"
            if label.cget("text") != name:
                label.configure(text=name)

        label.bind("<Configure>", fit_name)
        label.bind("<<ThemeChanged>>", fit_name)
        value.trace_add("write", fit_name)
        return label

    def _divmod(self, minutes: int) -> tuple[int, int]:
        if self._seconds < 60 and minutes > 0:
            minutes -= 1
        hours, minutes = divmod(minutes, 60)
        return (hours, minutes)

    def _update_time(self, seconds: int | None = None):
        if seconds is not None:
            self._seconds = seconds
        drop = self._drop
        if drop is not None:
            drop_minutes = drop.remaining_minutes
            campaign_minutes = drop.campaign.remaining_minutes
        else:
            drop_minutes = 0
            campaign_minutes = 0
        drop_vars: _DropVars = self._vars["drop"]
        campaign_vars: _CampaignVars = self._vars["campaign"]
        dseconds = self._seconds % 60
        hours, minutes = self._divmod(drop_minutes)
        drop_vars["remaining"].set(
            _("gui", "progress", "remaining").format(time=f"{hours:>2}:{minutes:02}:{dseconds:02}")
        )
        hours, minutes = self._divmod(campaign_minutes)
        campaign_vars["remaining"].set(
            _("gui", "progress", "remaining").format(time=f"{hours:>2}:{minutes:02}:{dseconds:02}")
        )
        self._manager.update_hud_remaining(drop_vars["remaining"].get())

    async def _timer_loop(self):
        self._update_time(60)
        while self._seconds > 0:
            await asyncio.sleep(1)
            self._seconds -= 1
            self._update_time()
        self._timer_task = None

    def start_timer(self):
        if self._timer_task is None:
            if self._drop is None or self._drop.remaining_minutes <= 0:
                # if we're starting the timer at 0 drop minutes,
                # all we need is a single instant time update setting seconds to 60,
                # to avoid substracting a minute from campaign minutes
                self._update_time(60)
            else:
                self._timer_task = asyncio.create_task(self._timer_loop())

    def stop_timer(self):
        if self._timer_task is not None:
            self._timer_task.cancel()
            self._timer_task = None

    def minute_almost_done(self) -> bool:
        # already or almost done
        return self._timer_task is None or self._seconds <= self.ALMOST_DONE_SECONDS

    def display(self, drop: TimedDrop | None, *, countdown: bool = True, subone: bool = False):
        self._drop = drop
        vars_drop = self._vars["drop"]
        vars_campaign = self._vars["campaign"]
        self.stop_timer()
        if drop is None:
            # clear the drop display
            vars_drop["rewards"].set("...")
            vars_drop["progress"].set(0.0)
            vars_drop["percentage"].set("-%")
            vars_campaign["name"].set("...")
            vars_campaign["game"].set("...")
            vars_campaign["progress"].set(0.0)
            vars_campaign["percentage"].set("-%")
            self._update_time(0)
            return
        vars_drop["rewards"].set(drop.rewards_text())
        vars_drop["progress"].set(drop.progress)
        vars_drop["percentage"].set(f"{drop.progress:6.1%}")
        campaign = drop.campaign
        vars_campaign["name"].set(campaign.name)
        vars_campaign["game"].set(campaign.game.name)
        vars_campaign["progress"].set(campaign.progress)
        vars_campaign["percentage"].set(
            f"{campaign.progress:6.1%} ({campaign.claimed_drops}/{campaign.total_drops})"
        )
        if countdown:
            # restart our seconds update timer
            self.start_timer()
        elif subone:
            # display the current remaining time at 0 seconds (after substracting the minute)
            # this is because the watch loop will substract this minute
            # right after the first watch payload returns with a time update
            self._update_time(0)
        else:
            # display full time with no substracting
            self._update_time(60)


class ConsoleOutput:
    def __init__(self, manager: GUIManager, master: ttk.Widget):
        self._manager = manager
        frame = ttk.LabelFrame(
            master, text=_("gui", "output"), padding=(10, 8)
        )
        frame.grid(column=0, row=3, columnspan=3, sticky="nsew", pady=(0, 2))
        # tell master frame that the containing row can expand
        master.rowconfigure(3, weight=1)
        frame.rowconfigure(0, weight=1)  # let the frame expand
        frame.columnconfigure(0, weight=1)
        xscroll = ttk.Scrollbar(frame, orient="horizontal")
        yscroll = ttk.Scrollbar(frame, orient="vertical")
        self._text = tk.Text(
            frame,
            width=52,
            height=8,
            wrap="none",
            state="disabled",
            exportselection=False,
            borderwidth=0,
            highlightthickness=0,
            padx=10,
            pady=8,
            xscrollcommand=xscroll.set,
            yscrollcommand=yscroll.set,
        )
        xscroll.config(command=self._text.xview)
        yscroll.config(command=self._text.yview)
        self._text.grid(column=0, row=0, sticky="nsew")
        xscroll.grid(column=0, row=1, sticky="ew")
        yscroll.grid(column=1, row=0, sticky="ns")

    def print(self, message: str):
        stamp = datetime.now().strftime("%X")
        if '\n' in message:
            message = message.replace('\n', f"\n{stamp}: ")
        self._text.config(state="normal")
        self._text.insert("end", f"{stamp}: {message}\n")
        self._text.see("end")  # scroll to the newly added line
        self._text.config(state="disabled")

    def configure_theme(self, *, bg: str, fg: str, sel_bg: str, sel_fg: str):
        # Apply colors to the Tk Text widget used for console output
        self._text.config(
            bg=bg,
            fg=fg,
            insertbackground=fg,
            selectbackground=sel_bg,
            selectforeground=sel_fg,
            font=self._manager._fonts["monospaced"],
        )


class _Buttons(TypedDict):
    frame: ttk.Frame
    switch: ttk.Button


class ChannelList:
    def __init__(self, manager: GUIManager, master: ttk.Widget):
        self._manager = manager
        frame = ttk.LabelFrame(
            master, text=_("gui", "channels", "name"), padding=(10, 8)
        )
        frame.grid(column=2, row=1, rowspan=2, sticky="nsew", padx=(8, 0), pady=(0, 8))
        # tell master frame that the containing column can expand
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)
        buttons_frame = ttk.Frame(frame)
        self._buttons: _Buttons = {
            "frame": buttons_frame,
            "switch": ttk.Button(
                buttons_frame,
                text=_("gui", "channels", "switch"),
                state="disabled",
                command=manager._twitch.state_change(State.CHANNEL_SWITCH),
                style="Primary.TButton",
            ),
        }
        buttons_frame.grid(column=0, row=0, columnspan=2, sticky="ew", pady=(0, 8))
        self._buttons["switch"].grid(column=0, row=0, sticky="ew")
        scroll = ttk.Scrollbar(frame, orient="vertical")
        self._table = table = ttk.Treeview(
            frame,
            # columns definition is updated by _add_column
            yscrollcommand=scroll.set,
        )
        scroll.config(command=table.yview)
        table.grid(column=0, row=1, sticky="nsew")
        scroll.grid(column=1, row=1, sticky="ns")
        self._font = Font(frame, manager._style.lookup("Treeview", "font"))
        self._heading_font = Font(frame, manager._style.lookup("Treeview.Heading", "font"))
        self._const_width: set[str] = set()
        table.tag_configure("watching", background="#342047", foreground="#f4ecff")
        table.bind("<Button-1>", self._disable_column_resize)
        table.bind("<<TreeviewSelect>>", self._selected)
        self._add_column("#0", '', width=0)
        self._add_column(
            "channel", _("gui", "channels", "headings", "channel"), width=120, anchor='w'
        )
        self._add_column(
            "status",
            _("gui", "channels", "headings", "status"),
            width_template=[
                _("gui", "channels", "online"),
                _("gui", "channels", "pending"),
                _("gui", "channels", "offline"),
            ],
        )
        self._add_column("game", _("gui", "channels", "headings", "game"), width=70)
        self._add_column("drops", "🎁", width_template="✔")
        self._add_column(
            "viewers", _("gui", "channels", "headings", "viewers"), width_template="1234567"
        )
        self._add_column("acl_base", "📋", width_template="✔")
        self._channel_map: dict[str, Channel] = {}

    def _add_column(
        self,
        cid: str,
        name: str,
        *,
        anchor: tk._Anchor = "center",
        width: int | None = None,
        width_template: str | list[str] | None = None,
    ):
        table = self._table
        # NOTE: we don't do this for the icon column
        if cid != "#0":
            # we need to save the column settings and headings before modifying the columns...
            columns: tuple[str, ...] = table.cget("columns") or ()
            column_settings: dict[str, tuple[str, tk._Anchor, int, int, bool]] = {}
            for s_cid in columns:
                s_column = table.column(s_cid)
                assert s_column is not None
                s_heading = table.heading(s_cid)
                assert s_heading is not None
                column_settings[s_cid] = (
                    s_heading["text"],
                    s_heading["anchor"],
                    s_column["width"],
                    s_column["minwidth"],
                    s_column["stretch"],
                )
            # ..., then add the column
            table.config(columns=columns + (cid,))
            # ..., and then restore column settings and headings afterwards
            for s_cid, (s_name, s_anchor, s_width, s_minwidth, s_stretch) in column_settings.items():
                table.heading(s_cid, text=s_name, anchor=s_anchor)
                table.column(s_cid, minwidth=s_minwidth, width=s_width, stretch=s_stretch)
        # set heading and column settings for the new column
        if width_template is not None:
            if isinstance(width_template, str):
                width = max(self._measure(name, heading=True), self._measure(width_template))
            else:
                width = max(
                    self._measure(name, heading=True),
                    max((self._measure(template) for template in width_template), default=20),
                )
            self._const_width.add(cid)
        assert width is not None
        table.heading(cid, text=name, anchor=anchor)
        table.column(
            cid,
            minwidth=width,
            width=width,
            stretch=cid in {"channel", "game"},
        )

    def _disable_column_resize(self, event):
        if self._table.identify_region(event.x, event.y) == "separator":
            return "break"

    def _selected(self, event):
        selection = self._table.selection()
        if selection:
            self._buttons["switch"].config(state="normal")
        else:
            self._buttons["switch"].config(state="disabled")

    def configure_theme(self, *, watching_bg: str, watching_fg: str):
        self._font.configure(**dict(self._manager._fonts["default"].actual()))
        self._heading_font.configure(**dict(self._manager._fonts["tree_heading"].actual()))
        self._table.tag_configure(
            "watching", background=watching_bg, foreground=watching_fg
        )
        for column in self._table.cget("columns"):
            heading = self._table.heading(column, "text")
            if not heading:
                continue
            settings = self._table.column(column)
            minwidth = max(settings["minwidth"], self._measure(heading, heading=True))
            self._table.column(
                column,
                minwidth=minwidth,
                width=max(settings["width"], minwidth),
            )
        self._redraw()

    def _measure(self, text: str, *, heading: bool = False) -> int:
        # we need this because columns have 9-10 pixels of padding that cuts text off
        font = self._heading_font if heading else self._font
        padding = 18 if heading else 10
        return font.measure(text) + padding

    def _redraw(self):
        # this forces a redraw that recalculates widget width
        self._table.event_generate("<<ThemeChanged>>")

    def _adjust_width(self, column: str, value: str):
        # causes the column to expand if the value's width is greater than the current width
        if column in self._const_width:
            return
        value_width = self._measure(value)
        curr_width = self._table.column(column, "width")
        if value_width > curr_width:
            self._table.column(column, width=value_width)
            self._redraw()

    def shrink(self):
        # causes the columns to shrink back after long values have been removed from it
        columns = self._table.cget("columns")
        iids = self._table.get_children()
        for column in columns:
            if column in self._const_width:
                continue
            if iids:
                # table has at least one item
                width = max(self._measure(self._table.set(i, column)) for i in iids)
                self._table.column(column, width=width)
            else:
                # no items - use minwidth
                minwidth = self._table.column(column, "minwidth")
                self._table.column(column, width=minwidth)
        self._redraw()

    def _set(self, iid: str, column: str, value: str):
        self._table.set(iid, column, value)
        self._adjust_width(column, value)

    def _insert(self, iid: str, values: dict[str, str]):
        to_insert: list[str] = []
        for cid in self._table.cget("columns"):
            value = values[cid]
            to_insert.append(value)
            self._adjust_width(cid, value)
        self._table.insert(parent='', index="end", iid=iid, values=to_insert)

    def clear_watching(self):
        for iid in self._table.tag_has("watching"):
            self._table.item(iid, tags='')

    def set_watching(self, channel: Channel):
        self.clear_watching()
        iid = channel.iid
        self._table.item(iid, tags="watching")
        self._table.see(iid)

    def get_selection(self) -> Channel | None:
        if not self._channel_map:
            return None
        selection = self._table.selection()
        if not selection:
            return None
        return self._channel_map[selection[0]]

    def clear_selection(self):
        self._table.selection_set('')

    def clear(self):
        iids = self._table.get_children()
        self._table.delete(*iids)
        self._channel_map.clear()
        self.shrink()

    def display(self, channel: Channel, *, add: bool = False):
        iid = channel.iid
        if not add and iid not in self._channel_map:
            # the channel isn't on the list and we're not supposed to add it
            return
        # ACL-based
        acl_based = "✔" if channel.acl_based else "❌"
        # status
        if channel.online:
            status = _("gui", "channels", "online")
        elif channel.pending_online:
            status = _("gui", "channels", "pending")
        else:
            status = _("gui", "channels", "offline")
        # game
        game = str(channel.game or '')
        # drops
        drops = "✔" if channel.drops_enabled else "❌"
        # viewers
        viewers = ''
        if channel.viewers is not None:
            viewers = str(channel.viewers)
        if iid in self._channel_map:
            self._set(iid, "game", game)
            self._set(iid, "drops", drops)
            self._set(iid, "status", status)
            self._set(iid, "viewers", viewers)
            self._set(iid, "acl_base", acl_based)
        elif add:
            self._channel_map[iid] = channel
            self._insert(
                iid,
                {
                    "game": game,
                    "drops": drops,
                    "status": status,
                    "viewers": viewers,
                    "acl_base": acl_based,
                    "channel": channel.name,
                },
            )

    def remove(self, channel: Channel):
        iid = channel.iid
        del self._channel_map[iid]
        self._table.delete(iid)


class TrayIcon:
    TITLE = APP_NAME

    def __init__(self, manager: GUIManager, master: ttk.Widget):
        self._manager = manager
        self.icon: pystray.Icon | None = None  # type: ignore[unused-ignore]
        self._icon_images: dict[str, Image_module.Image] = {
            "dropforge": Image_module.open(resource_path("icons/dropforge.ico")),
            "active": Image_module.open(resource_path("icons/dropforge-active.ico")),
            "idle": Image_module.open(resource_path("icons/dropforge-idle.ico")),
            "error": Image_module.open(resource_path("icons/dropforge-error.ico")),
            "maint": Image_module.open(resource_path("icons/dropforge-maint.ico")),
        }
        self._icon_state: str = "dropforge"
        self._button = ttk.Button(
            master,
            command=self.minimize,
            text=_("gui", "tray", "minimize"),
            style="Tray.TButton",
        )

        # Hides Tray button for macOS
        if sys.platform != "darwin":
            self._button.grid(column=0, row=0, sticky="ew")

    def __del__(self) -> None:
        self.stop()
        for icon_image in self._icon_images.values():
            icon_image.close()

    def _shorten(self, text: str, by_len: int, min_len: int) -> str:
        if (text_len := len(text)) <= min_len + 3 or by_len <= 0:
            # cannot shorten
            return text
        return text[:-min(by_len + 3, text_len - min_len)] + "..."

    def get_title(self, drop: TimedDrop | None) -> str:
        if drop is None:
            return self.TITLE
        campaign = drop.campaign
        title_parts: list[str] = [
            f"{self.TITLE}\n",
            f"{campaign.game.name}\n",
            drop.rewards_text(),
            f" {drop.progress:.1%} ({campaign.claimed_drops}/{campaign.total_drops})"
        ]
        min_len: int = 30
        max_len: int = 127
        missing_len = len(''.join(title_parts)) - max_len
        if missing_len > 0:
            # try shortening the reward text
            title_parts[2] = self._shorten(title_parts[2], missing_len, min_len)
            missing_len = len(''.join(title_parts)) - max_len
        if missing_len > 0:
            # try shortening the game name
            title_parts[1] = self._shorten(title_parts[1], missing_len, min_len)
            missing_len = len(''.join(title_parts)) - max_len
        if missing_len > 0:
            raise MinerException(f"Title couldn't be shortened: {''.join(title_parts)}")
        return ''.join(title_parts)

    def _start(self):
        loop = asyncio.get_running_loop()
        drop = self._manager.progress._drop

        # we need this because tray icon lives in a separate thread
        def bridge(func):
            return lambda: loop.call_soon_threadsafe(func)

        menu = pystray.Menu(
            pystray.MenuItem(_("gui", "tray", "show"), bridge(self.restore), default=True),
            pystray.MenuItem(_("gui", "tray", "hud"), bridge(self._manager.show_hud)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(_("gui", "tray", "quit"), bridge(self.quit)),
        )
        self.icon = pystray.Icon(
            "dropforge", self._icon_images[self._icon_state], self.get_title(drop), menu
        )
        # self.icon.run_detached()
        loop.run_in_executor(None, self.icon.run)

    def stop(self):
        if self.icon is not None:
            self.icon.stop()
            self.icon = None

    def quit(self):
        self._manager.close()

    def minimize(self):
        if sys.platform == "darwin":
            return
        if self.icon is None:
            self._start()
        else:
            self.icon.visible = True
        self._manager._root.withdraw()

    def restore(self):
        if self.icon is not None:
            # self.stop()
            self.icon.visible = False
        self._manager._root.deiconify()
        if self._manager._pending_window_position is not None:
            self._manager._root.after(250, self._manager._apply_pending_window_position)

    def notify(
        self, message: str, title: str | None = None, duration: float = 10
    ) -> asyncio.Task[None] | None:
        # do nothing if the user disabled notifications
        if not self._manager._twitch.settings.tray_notifications:
            return None
        if self.icon is not None:
            icon = self.icon  # nonlocal scope bind

            async def notifier():
                icon.notify(message, title)
                await asyncio.sleep(duration)
                icon.remove_notification()

            return asyncio.create_task(notifier())
        return None

    def update_title(self, drop: TimedDrop | None):
        if self.icon is not None:
            self.icon.title = self.get_title(drop)

    def change_icon(self, state: str):
        if state not in self._icon_images:
            raise ValueError("Invalid icon state")
        self._icon_state = state
        if self.icon is not None:
            self.icon.icon = self._icon_images[state]


class Notebook:
    NAV_MARKS = ("◉", "◇", "⚙", "?", "✦")
    SHORTCUT_MODIFIER = "Command" if sys.platform == "darwin" else "Control"
    SHORTCUT_LABEL = "⌘" if sys.platform == "darwin" else "Ctrl"

    def __init__(self, manager: GUIManager, master: ttk.Widget):
        self._manager = manager
        self._current = -1
        self._pages: list[ttk.Widget] = []
        self._nav_buttons: list[ttk.Button] = []
        self._nav_labels: list[str] = []
        self._view_callbacks: list[abc.Callable[[tk.Event], Any]] = []
        self._search_actions: dict[int, abc.Callable[[], None]] = {}
        manager._root.bind(f"<{self.SHORTCUT_MODIFIER}-Key-f>", self._find)

        shell = ttk.Frame(master, style="AppShell.TFrame")
        shell.grid(column=0, row=0, sticky="nsew")
        shell.rowconfigure(0, weight=1)
        shell.columnconfigure(1, weight=1)
        master.rowconfigure(0, weight=1)
        master.columnconfigure(0, weight=1)

        self.sidebar = ttk.Frame(shell, style="Sidebar.TFrame", padding=(14, 18))
        self.sidebar.grid(column=0, row=0, sticky="ns")
        self.sidebar.configure(width=224)
        self.sidebar.grid_propagate(False)
        self.sidebar.columnconfigure(0, weight=1)
        self.sidebar.rowconfigure(3, weight=1)

        brand = ttk.Frame(self.sidebar, style="Sidebar.TFrame")
        brand.grid(column=0, row=0, sticky="ew", pady=(0, 22))
        brand_art = Image_module.open(resource_path("icons/dropforge-mark.png")).convert("RGBA")
        brand_art.thumbnail((56, 56), Image_module.Resampling.LANCZOS)
        self._brand_image = PhotoImage(master=brand, image=brand_art)
        ttk.Label(brand, image=self._brand_image, style="BrandIcon.TLabel").grid(
            column=0, row=0, rowspan=2, sticky="w", padx=(0, 10)
        )
        ttk.Label(brand, text=APP_NAME, style="Brand.TLabel").grid(
            column=1, row=0, sticky="sw"
        )
        ttk.Label(brand, text="TWITCH DROPS", style="BrandCaption.TLabel").grid(
            column=1, row=1, sticky="nw", pady=(2, 0)
        )

        ttk.Separator(self.sidebar, orient="horizontal").grid(
            column=0, row=1, sticky="ew", pady=(0, 18)
        )
        self._nav_host = ttk.Frame(self.sidebar, style="Sidebar.TFrame")
        self._nav_host.grid(column=0, row=2, sticky="new")
        self._nav_host.columnconfigure(0, weight=1)

        self.tray_slot = ttk.Frame(self.sidebar, style="Sidebar.TFrame")
        self.tray_slot.grid(column=0, row=4, sticky="ew", pady=(0, 12))
        self.tray_slot.columnconfigure(0, weight=1)
        ttk.Label(
            self.sidebar,
            text=f"{self.SHORTCUT_LABEL}+F  ·  {_('gui', 'inventory', 'search')}",
            style="SidebarFoot.TLabel",
        ).grid(column=0, row=5, sticky="w")

        self.page_host = ttk.Frame(shell, style="Content.TFrame", padding=(14, 10, 8, 8))
        self.page_host.grid(column=1, row=0, sticky="nsew")
        self.page_host.rowconfigure(0, weight=1)
        self.page_host.columnconfigure(0, weight=1)

    def add_tab(
        self, widget: ttk.Widget, *, name: str, search: abc.Callable[[], None] | None = None, **kwargs
    ):
        sticky = kwargs.pop("sticky", "nsew")
        kwargs.pop("text", None)
        index = len(self._pages)
        self._pages.append(widget)
        self._nav_labels.append(name)
        if search is not None:
            self._search_actions[index] = search
        if index < 9:
            self._manager._root.bind(
                f"<{self.SHORTCUT_MODIFIER}-Key-{index + 1}>",
                partial(self._select_by_key, index),
            )
        widget.grid(column=0, row=0, sticky=sticky, **kwargs)
        button = ttk.Button(
            self._nav_host,
            text=f"{self.NAV_MARKS[index % len(self.NAV_MARKS)]}   {name}",
            style="Nav.TButton",
            command=partial(self.select_tab, index),
        )
        button.grid(column=0, row=index, sticky="ew", pady=3)
        self._nav_buttons.append(button)
        if self._current == -1:
            self.select_tab(index)
        else:
            widget.grid_remove()

    def _select_by_key(self, index: int, _event: tk.Event) -> str:
        self.select_tab(index)
        return "break"

    def _find(self, _event: tk.Event) -> str:
        if self._search_actions:
            index = self._current
            if index not in self._search_actions:
                index = next(iter(self._search_actions))
                self.select_tab(index)
            self._search_actions[index]()
        return "break"

    def select_tab(self, index: int) -> None:
        if not 0 <= index < len(self._pages):
            return
        if self._current == index:
            self._manager._root.focus_set()
            return
        for page in self._pages:
            page.grid_remove()
        self._pages[index].grid()
        self._pages[index].tkraise()
        self._current = index
        for button_index, button in enumerate(self._nav_buttons):
            button.configure(style="NavActive.TButton" if button_index == index else "Nav.TButton")
        self._manager._root.focus_set()
        event = tk.Event()
        for callback in tuple(self._view_callbacks):
            callback(event)

    def current_tab(self) -> int:
        return self._current

    def add_view_event(self, callback: abc.Callable[[tk.Event[ttk.Notebook]], Any]):
        self._view_callbacks.append(callback)


class CampaignDisplay(TypedDict):
    frame: ttk.Frame
    status: ttk.Label
    priority_button: ttk.Button


class CampaignAgendaDialog:
    PERIODS = (1, 7, 30)
    EVENT_FILTERS = (None, "starts", "ends")
    COLUMNS = ("time", "event", "game", "campaign", "reward")

    def __init__(
        self,
        parent: tk.Misc,
        campaigns: abc.Callable[[], abc.Iterable[DropsCampaign]],
        view_campaign: abc.Callable[[DropsCampaign], None],
    ):
        self._campaigns = campaigns
        self._view_campaign = view_campaign
        self._events: dict[str, CampaignAgendaEvent] = {}
        self._pending_refresh: str | None = None
        self.window = window = tk.Toplevel(parent)
        text = self._text
        window.title(text("title"))
        window.transient(parent)
        window.geometry("860x480")
        window.minsize(650, 385)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)

        content = ttk.Frame(window, padding=16)
        content.grid(sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(2, weight=1)
        intro = ttk.Label(content, text=text("intro"), style="Muted.TLabel", justify="left")
        intro.grid(row=0, sticky="ew", pady=(0, 12))
        intro.bind("<Configure>", lambda event: intro.configure(wraplength=event.width))

        filters = ttk.Frame(content)
        filters.grid(row=1, sticky="ew", pady=(0, 8))
        filters.columnconfigure(3, weight=1)
        ttk.Label(filters, text=text("period")).grid(column=0, row=0, padx=(0, 6))
        self.period = ttk.Combobox(
            filters,
            values=tuple(text(f"period_{key}") for key in ("today", "7", "30")),
            state="readonly",
            width=18,
        )
        self.period.grid(column=1, row=0, sticky="w", padx=(0, 10))
        self.period.current(1)
        self.event_filter = ttk.Combobox(
            filters,
            values=tuple(text(f"event_{key}") for key in ("all", "starts", "ends")),
            state="readonly",
            width=17,
        )
        self.event_filter.grid(column=2, row=0, sticky="w")
        self.event_filter.current(0)
        for combo in (self.period, self.event_filter):
            combo.bind("<<ComboboxSelected>>", self._on_filter_changed)
        self._summary = ttk.Label(filters, style="Muted.TLabel")
        self._summary.grid(column=3, row=0, sticky="e", padx=(8, 0))

        table_frame = ttk.Frame(content)
        table_frame.grid(row=2, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        scroll = ttk.Scrollbar(table_frame, orient="vertical")
        self.table = ttk.Treeview(
            table_frame,
            columns=self.COLUMNS,
            show="headings",
            selectmode="browse",
            yscrollcommand=scroll.set,
        )
        scroll.config(command=self.table.yview)
        self.table.grid(column=0, row=0, sticky="nsew")
        scroll.grid(column=1, row=0, sticky="ns")
        for column, width, minimum, stretch in (
            ("time", 145, 145, False),
            ("event", 99, 99, False),
            ("game", 142, 100, True),
            ("campaign", 222, 110, True),
            ("reward", 190, 120, True),
        ):
            self.table.heading(column, text=text(f"column_{column}"), anchor="w")
            self.table.column(column, width=width, minwidth=minimum, stretch=stretch, anchor="w")

        self._details = ttk.Label(content, style="Muted.TLabel", justify="left")
        self._details.grid(row=3, sticky="ew", pady=(7, 0))
        self._details.bind(
            "<Configure>", lambda event: self._details.configure(wraplength=event.width)
        )
        actions = ttk.Frame(content)
        actions.grid(row=4, sticky="ew", pady=(10, 0))
        actions.columnconfigure(0, weight=1)
        self._feedback = ttk.Label(actions, style="Muted.TLabel")
        self._feedback.grid(column=0, row=0, sticky="w")
        self.export_button = ttk.Button(
            actions, text=text("export"), command=self._export_calendar
        )
        self.export_button.grid(column=1, row=0, padx=(0, 6))
        self.view_button = ttk.Button(
            actions, text=text("view"), command=self._open_selected, style="Primary.TButton"
        )
        self.view_button.grid(column=2, row=0, padx=(0, 6))
        ttk.Button(actions, text=text("close"), command=window.destroy).grid(column=3, row=0)

        self.table.bind("<<TreeviewSelect>>", self._update_selection)
        self.table.bind("<Double-1>", self._on_double_click)
        self.table.bind("<Return>", self._open_selected)
        window.bind("<Escape>", self._on_escape)
        window.bind("<Destroy>", self._on_destroy)
        self.refresh()
        self.table.focus_set()

    @staticmethod
    def _text(key: str) -> str:
        return _("gui", "inventory", "agenda", key)

    def schedule_refresh(self) -> None:
        if self._pending_refresh is None:
            self._pending_refresh = self.window.after_idle(self._refresh_pending)

    def _refresh_pending(self) -> None:
        self._pending_refresh = None
        self.refresh()

    def _on_filter_changed(self, _event: tk.Event) -> None:
        self._feedback.configure(text="")
        self.refresh()

    def refresh(self) -> None:
        kind = self.EVENT_FILTERS[self.event_filter.current()]
        days = self.PERIODS[self.period.current()]
        events = {
            f"{id(event.campaign)}:{id(event.drop)}:{event.kind}": event
            for event in build_campaign_agenda(
                self._campaigns(), now=datetime.now(timezone.utc), days=days
            )
            if kind is None or kind == event.kind
        }
        text = self._text
        self._summary.configure(text=text("count").format(count=len(events)))
        self.export_button.configure(state="normal" if events else "disabled")
        if self._events != events:
            previous_selection = self.table.selection()
            scroll_position = self.table.yview()[0]
            self._events = events
            self.table.delete(*self.table.get_children())
            for item, event in events.items():
                self.table.insert(
                    "", "end", iid=item, values=(
                        event.when.astimezone().strftime("%d/%m/%Y %H:%M"),
                        text(f"event_{event.kind}"),
                        event.campaign.game.name,
                        event.campaign.name,
                        self._reward(event),
                    ),
                )
            if previous_selection and previous_selection[0] in events:
                self.table.selection_set(previous_selection[0])
                self.table.focus(previous_selection[0])
            self.table.yview_moveto(scroll_position)
        self._update_selection()

    def _export_calendar(self) -> None:
        self.refresh()
        events = tuple(self._events.values())
        if not events:
            return
        text = self._text
        target = filedialog.asksaveasfilename(
            parent=self.window,
            title=text("export_title"),
            initialfile=text("export_filename"),
            defaultextension=".ics",
            filetypes=(("iCalendar", "*.ics"),),
        )
        if not target:
            return
        data = serialize_campaign_calendar(
            events,
            stamp=datetime.now(timezone.utc),
            event_label=lambda kind: text(f"event_{kind}"),
        )
        try:
            Path(target).write_bytes(data)
        except OSError:
            logger.exception("Unable to export the campaign agenda")
            self._feedback.configure(text=text("export_failed"))
        else:
            self._feedback.configure(text=text("exported").format(count=len(events)))

    def _reward(self, event: CampaignAgendaEvent) -> str:
        if event.drop is None:
            return self._text("all_rewards")
        return event.drop.rewards_text() or event.drop.name

    def _selected(self) -> CampaignAgendaEvent | None:
        selection = self.table.selection()
        return self._events.get(selection[0]) if selection else None

    def _update_selection(self, _event: tk.Event | None = None) -> None:
        event = self._selected()
        self.view_button.configure(state="normal" if event else "disabled")
        if event:
            detail = f"{event.campaign.game.name}  ·  {event.campaign.name}  ·  {self._reward(event)}"
        else:
            detail = "" if self._events else self._text("empty")
        self._details.configure(text=detail)

    def _open_selected(self, _event: tk.Event | None = None) -> str:
        event = self._selected()
        if event:
            self._view_campaign(event.campaign)
            self.window.destroy()
        return "break"

    def _on_double_click(self, event: tk.Event) -> str | None:
        row = self.table.identify_row(event.y)
        if row:
            self.table.selection_set(row)
            return self._open_selected()
        return None

    def _on_escape(self, _event: tk.Event) -> str:
        self.window.destroy()
        return "break"

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget == self.window and self._pending_refresh is not None:
            self.window.after_cancel(self._pending_refresh)
            self._pending_refresh = None


class InventoryOverview:
    def __init__(self, manager: GUIManager, master: ttk.Widget):
        self._manager = manager
        self._cache: ImageCache = manager._cache
        self._settings: Settings = manager._twitch.settings
        self._agenda: CampaignAgendaDialog | None = None
        self._filters = {
            "not_linked": IntVar(
                master, self._settings.priority_mode is PriorityMode.PRIORITY_ONLY
            ),
            "upcoming": IntVar(master, 1),
            "expired": IntVar(master, 0),
            "excluded": IntVar(master, 0),
            "finished": IntVar(master, 0),
        }
        self._search_var = StringVar(master)
        manager.tabs.add_view_event(self._on_tab_switched)
        # Filtering options
        filter_frame = ttk.LabelFrame(
            master, text=_("gui", "inventory", "filter", "name"), padding=(4, 0, 4, 4)
        )
        LABEL_SPACING = 20
        filter_frame.grid(column=0, row=0, columnspan=2, sticky="nsew")
        ttk.Label(
            filter_frame, text=_("gui", "inventory", "filter", "show"), padding=(0, 0, 10, 0)
        ).grid(column=0, row=0)
        icolumn = 0
        ttk.Checkbutton(
            filter_frame, variable=self._filters["not_linked"], command=self.refresh
        ).grid(column=(icolumn := icolumn + 1), row=0)
        ttk.Label(
            filter_frame,
            text=_("gui", "inventory", "filter", "not_linked"),
            padding=(0, 0, LABEL_SPACING, 0),
        ).grid(column=(icolumn := icolumn + 1), row=0)
        ttk.Checkbutton(
            filter_frame, variable=self._filters["upcoming"], command=self.refresh
        ).grid(column=(icolumn := icolumn + 1), row=0)
        ttk.Label(
            filter_frame,
            text=_("gui", "inventory", "filter", "upcoming"),
            padding=(0, 0, LABEL_SPACING, 0),
        ).grid(column=(icolumn := icolumn + 1), row=0)
        ttk.Checkbutton(
            filter_frame, variable=self._filters["expired"], command=self.refresh
        ).grid(column=(icolumn := icolumn + 1), row=0)
        ttk.Label(
            filter_frame,
            text=_("gui", "inventory", "filter", "expired"),
            padding=(0, 0, LABEL_SPACING, 0),
        ).grid(column=(icolumn := icolumn + 1), row=0)
        ttk.Checkbutton(
            filter_frame, variable=self._filters["excluded"], command=self.refresh
        ).grid(column=(icolumn := icolumn + 1), row=0)
        ttk.Label(
            filter_frame,
            text=_("gui", "inventory", "filter", "excluded"),
            padding=(0, 0, LABEL_SPACING, 0),
        ).grid(column=(icolumn := icolumn + 1), row=0)
        ttk.Checkbutton(
            filter_frame, variable=self._filters["finished"], command=self.refresh
        ).grid(column=(icolumn := icolumn + 1), row=0)
        ttk.Label(
            filter_frame,
            text=_("gui", "inventory", "filter", "finished"),
            padding=(0, 0, LABEL_SPACING, 0),
        ).grid(column=(icolumn := icolumn + 1), row=0)
        ttk.Button(
            filter_frame, text=_("gui", "inventory", "filter", "refresh"), command=self.refresh
        ).grid(column=(icolumn := icolumn + 1), row=0)
        search_frame = ttk.Frame(master)
        search_frame.grid(column=0, row=1, columnspan=2, sticky="ew", pady=(7, 5))
        search_frame.columnconfigure(1, weight=1)
        ttk.Label(search_frame, text=_("gui", "inventory", "search")).grid(
            column=0, row=0, sticky="w", padx=(2, 8)
        )
        self._search_entry = ttk.Entry(
            search_frame,
            textvariable=self._search_var,
            width=32,
        )
        self._search_entry.grid(column=1, row=0, sticky="ew")
        self._search_entry.bind("<Escape>", self._clear_search)
        self._search_var.trace_add("write", lambda *_: self.refresh())
        ttk.Button(
            search_frame,
            text="×",
            width=3,
            command=lambda: self._search_var.set(""),
        ).grid(column=2, row=0, padx=6)
        self._count_label = ttk.Label(
            search_frame,
            text=_("gui", "inventory", "visible_count").format(visible=0, total=0),
            style="Muted.TLabel",
        )
        self._count_label.grid(column=3, row=0, sticky="e", padx=(8, 2))
        radar = ttk.LabelFrame(
            master,
            text=_("gui", "inventory", "radar", "title"),
            padding=(8, 6),
        )
        self._radar_frame = radar
        radar.grid(column=0, row=2, columnspan=2, sticky="ew", pady=(3, 7))
        radar.columnconfigure(0, weight=1)
        radar_header = ttk.Frame(radar)
        radar_header.grid(column=0, row=0, sticky="ew", pady=(0, 5))
        radar_header.columnconfigure(0, weight=1)
        self._radar_summary = ttk.Label(radar_header, style="Muted.TLabel")
        self._radar_summary.grid(column=0, row=0, sticky="w")
        duration_keys = (30, 60, 90, 120, 180, 240)
        self._session_values = {
            _("gui", "inventory", "radar", f"duration_{minutes}"): minutes
            for minutes in duration_keys
        }
        default_session = _("gui", "inventory", "radar", "duration_60")
        self._session_duration = StringVar(master, value=default_session)
        ttk.Label(
            radar_header,
            text=_("gui", "inventory", "radar", "session"),
            style="Muted.TLabel",
        ).grid(column=1, row=0, sticky="e", padx=(8, 5))
        session_combo = ttk.Combobox(
            radar_header,
            textvariable=self._session_duration,
            values=tuple(self._session_values),
            state="readonly",
            width=9,
        )
        session_combo.grid(column=2, row=0, sticky="e")
        session_combo.bind(
            "<<ComboboxSelected>>", lambda _event: self._update_deadline_radar()
        )
        ttk.Button(
            radar_header,
            text=_("gui", "inventory", "agenda", "button"),
            command=self._open_agenda,
        ).grid(column=3, row=0, sticky="e", padx=(8, 0))
        self._radar_cards = ttk.Frame(radar)
        self._radar_cards.grid(column=0, row=1, sticky="ew")
        for column in range(3):
            self._radar_cards.columnconfigure(column, weight=1, uniform="deadline-card")
        # Inventory view
        self._canvas = tk.Canvas(master, scrollregion=(0, 0, 0, 0))
        self._canvas.grid(column=0, row=3, sticky="nsew")
        master.rowconfigure(3, weight=1)
        master.columnconfigure(0, weight=1)
        xscroll = ttk.Scrollbar(master, orient="horizontal", command=self._canvas.xview)
        xscroll.grid(column=0, row=4, sticky="ew")
        yscroll = ttk.Scrollbar(master, orient="vertical", command=self._canvas.yview)
        yscroll.grid(column=1, row=3, sticky="ns")
        self._canvas.configure(xscrollcommand=xscroll.set, yscrollcommand=yscroll.set)
        self._canvas.bind("<Configure>", self._canvas_update)
        self._main_frame = ttk.Frame(self._canvas)
        self._canvas.bind(
            "<Enter>", lambda e: self._canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        )
        self._canvas.bind("<Leave>", lambda e: self._canvas.unbind_all("<MouseWheel>"))
        self._canvas.create_window(0, 0, anchor="nw", window=self._main_frame)
        self._campaigns: dict[DropsCampaign, CampaignDisplay] = {}
        self._drops: dict[str, ttk.Label] = {}
        self._deadline_candidates: list[DeadlineCandidate] = []
        self._update_deadline_radar()
        self._radar_timer = master.after(60_000, self._refresh_deadline_radar_clock)

    def configure_theme(self, *, bg: str):
        # Canvas background needs manual control
        self._canvas.configure(bg=bg)

    def _update_visibility(self, campaign: DropsCampaign):
        # True if the campaign is supposed to show, False makes it hidden.
        frame = self._campaigns[campaign]["frame"]
        not_linked = bool(self._filters["not_linked"].get())
        expired = bool(self._filters["expired"].get())
        excluded = bool(self._filters["excluded"].get())
        upcoming = bool(self._filters["upcoming"].get())
        finished = bool(self._filters["finished"].get())
        priority_only = self._settings.priority_mode is PriorityMode.PRIORITY_ONLY
        search_query = self._search_var.get()
        if (
            campaign_matches_search(campaign, search_query)
            and campaign.required_minutes > 0  # don't show sub-only campaigns
            and (not_linked or campaign.eligible)
            and (campaign.active or upcoming and campaign.upcoming or expired and campaign.expired)
            and passes_game_filter(
                campaign.game.name,
                query=search_query,
                priority_games=self._settings.priority,
                excluded_games=self._settings.exclude,
                priority_only=priority_only,
                show_excluded=excluded,
            )
            and (finished or not campaign.finished)
        ):
            frame.grid()
        else:
            frame.grid_remove()

    def _clear_search(self, _event: tk.Event) -> str:
        self._search_var.set("")
        return "break"

    def focus_search(self) -> None:
        self._search_entry.focus_set()
        self._search_entry.selection_range(0, "end")

    def _on_tab_switched(self, event: tk.Event[ttk.Notebook]) -> None:
        if self._manager.tabs.current_tab() == 1:
            # refresh only if we're switching to the tab
            self.refresh()

    def get_status(self, campaign: DropsCampaign) -> tuple[str, str]:
        if campaign.active:
            status_text: str = _("gui", "inventory", "status", "active")
            status_color: str = "green"
        elif campaign.upcoming:
            status_text = _("gui", "inventory", "status", "upcoming")
            status_color = "goldenrod"
        else:
            status_text = _("gui", "inventory", "status", "expired")
            status_color = "red"
        return (status_text, status_color)

    def refresh(self):
        for campaign in self._campaigns:
            # status
            status_label = self._campaigns[campaign]["status"]
            status_text, status_color = self.get_status(campaign)
            status_label.config(text=status_text, foreground=status_color)
            priority_button = self._campaigns[campaign]["priority_button"]
            priority_button.configure(**self._priority_button_options(campaign.game.name))
            # visibility
            self._update_visibility(campaign)
        self._update_deadline_radar()
        self._update_visible_count()
        self._canvas_update()

    def _update_visible_count(self) -> None:
        visible = sum(
            bool(display["frame"].winfo_manager()) for display in self._campaigns.values()
        )
        self._count_label.config(
            text=_("gui", "inventory", "visible_count").format(
                visible=visible,
                total=len(self._campaigns),
            )
        )

    @staticmethod
    def _format_minutes(minutes: int) -> str:
        minutes = max(0, minutes)
        days, remainder = divmod(minutes, 24 * 60)
        hours, minutes = divmod(remainder, 60)
        if days:
            return f"{days}d {hours}h"
        if hours:
            return f"{hours}h {minutes:02}m"
        return f"{minutes}m"

    def _refresh_deadline_radar_clock(self) -> None:
        try:
            if not self._radar_cards.winfo_exists():
                return
            self._update_deadline_radar()
            self._schedule_agenda_refresh()
            self._radar_timer = self._radar_cards.after(
                60_000, self._refresh_deadline_radar_clock
            )
        except tk.TclError:
            return

    def _update_deadline_radar(self) -> None:
        candidates = rank_deadline_candidates(
            self._campaigns,
            excluded_games=self._settings.exclude,
            limit=None,
        )
        self._deadline_candidates = candidates
        session_minutes = self._session_values.get(self._session_duration.get(), 60)
        session_candidates = rank_for_session(candidates, session_minutes)
        self._session_recommendations = session_candidates
        for child in self._radar_cards.winfo_children():
            child.destroy()

        shown = session_candidates[:3]
        self._radar_summary.config(
            text=(
                _("gui", "inventory", "radar", "summary").format(
                    shown=len(shown),
                    total=len(candidates),
                    session=self._format_minutes(session_minutes),
                )
                if candidates
                else ""
            )
        )
        if not shown:
            ttk.Label(
                self._radar_cards,
                text=_("gui", "inventory", "radar", "empty"),
                style="Muted.TLabel",
            ).grid(column=0, row=0, sticky="w", padx=4, pady=(3, 6))
            return

        for column, recommendation in enumerate(shown):
            self._add_deadline_card(recommendation, column)

    def _add_deadline_card(
        self, recommendation: SessionRecommendation, column: int
    ) -> None:
        candidate = recommendation.candidate
        campaign = candidate.campaign
        game_name = campaign.game.name
        card = ttk.Frame(
            self._radar_cards,
            style="Card.TFrame",
            padding=(9, 7),
            relief="solid",
            borderwidth=1,
        )
        card.grid(column=column, row=0, sticky="nsew", padx=3, pady=2)
        card.columnconfigure(0, weight=1)
        ttk.Label(
            card,
            text=game_name,
            style="Section.TLabel",
            anchor="w",
        ).grid(column=0, row=0, sticky="ew")
        ttk.Label(
            card,
            text=campaign.name,
            style="Value.TLabel",
            anchor="w",
            wraplength=260,
        ).grid(column=0, row=1, sticky="ew", pady=(1, 0))
        ttk.Label(
            card,
            text=candidate.drop.rewards_text(),
            style="Muted.TLabel",
            anchor="w",
            wraplength=260,
        ).grid(column=0, row=2, sticky="ew", pady=(1, 4))

        now = datetime.now(timezone.utc)
        starts_in = max(0, int((candidate.drop.starts_at - now).total_seconds() // 60))
        if starts_in:
            deadline_text = _("gui", "inventory", "radar", "starts").format(
                time=self._format_minutes(starts_in)
            )
        else:
            deadline_text = _("gui", "inventory", "radar", "deadline").format(
                time=self._format_minutes(candidate.available_minutes)
            )
        ttk.Label(
            card,
            text=deadline_text,
            style="Value.TLabel",
            anchor="w",
        ).grid(column=0, row=3, sticky="ew", pady=(2, 0))
        ttk.Label(
            card,
            text=_("gui", "inventory", "radar", "effort").format(
                time=self._format_minutes(candidate.required_minutes)
            ),
            style="Muted.TLabel",
            anchor="w",
        ).grid(column=0, row=4, sticky="ew")

        session_minutes = self._session_values.get(self._session_duration.get(), 60)
        if recommendation.fits_session:
            spare_minutes = min(
                session_minutes - candidate.required_minutes,
                candidate.available_minutes - candidate.required_minutes,
            )
            session_text = _("gui", "inventory", "radar", "session_fits").format(
                session=self._format_minutes(session_minutes),
                time=self._format_minutes(spare_minutes),
            )
            session_style = "green.TLabel"
        else:
            session_text = _("gui", "inventory", "radar", "session_shortfall").format(
                time=self._format_minutes(recommendation.difference_minutes)
            )
            session_style = "yellow.TLabel"
        ttk.Label(
            card,
            text=session_text,
            style=session_style,
            anchor="w",
            wraplength=260,
        ).grid(column=0, row=5, sticky="ew", pady=(2, 0))

        if candidate.margin_ratio < 1:
            margin_key, margin_style = "risk", "red.TLabel"
        elif candidate.margin_ratio < 2:
            margin_key, margin_style = "tight", "yellow.TLabel"
        else:
            margin_key, margin_style = "safe", "green.TLabel"
        ttk.Label(
            card,
            text=_("gui", "inventory", "radar", margin_key).format(
                ratio=f"{candidate.margin_ratio:.1f}"
            ),
            style=margin_style,
            anchor="w",
        ).grid(column=0, row=6, sticky="ew", pady=(2, 5))

        actions = ttk.Frame(card, style="Card.TFrame")
        actions.grid(column=0, row=7, sticky="ew")
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        ttk.Button(
            actions,
            command=partial(self._toggle_game_priority, game_name),
            **self._priority_button_options(game_name),
        ).grid(column=0, row=0, sticky="ew", padx=(0, 3))
        ttk.Button(
            actions,
            text=_("gui", "inventory", "radar", "focus"),
            command=lambda campaign=campaign: self._focus_campaign(campaign),
        ).grid(column=1, row=0, sticky="ew", padx=(3, 0))

    def _open_agenda(self) -> None:
        if self._agenda is not None and self._agenda.window.winfo_exists():
            self._agenda.window.lift()
            self._agenda.table.focus_set()
        else:
            self._agenda = CampaignAgendaDialog(
                self._canvas.winfo_toplevel(), self._campaigns.keys, self._reveal_agenda_campaign
            )

    def _schedule_agenda_refresh(self) -> None:
        if self._agenda is not None and self._agenda.window.winfo_exists():
            self._agenda.schedule_refresh()

    def _reveal_agenda_campaign(self, campaign: DropsCampaign) -> None:
        if campaign not in self._campaigns:
            return
        if not campaign.eligible:
            self._filters["not_linked"].set(1)
        if campaign.upcoming:
            self._filters["upcoming"].set(1)
        if campaign.game.name in self._settings.exclude:
            self._filters["excluded"].set(1)
        self._focus_campaign(campaign)

    def _focus_campaign(self, campaign: DropsCampaign) -> None:
        display = self._campaigns.get(campaign)
        if display is None:
            return
        self._search_var.set(campaign.name)
        self._canvas.update_idletasks()
        frame = display["frame"]
        bounds = self._canvas.bbox("all")
        if frame.winfo_manager() and bounds and bounds[3] > 0:
            self._canvas.yview_moveto(max(0.0, frame.winfo_y() / bounds[3]))

    def _canvas_update(self, event: tk.Event[tk.Canvas] | None = None):
        self._canvas.update_idletasks()
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_mousewheel(self, event: tk.Event[tk.Misc]):
        delta = -1 if event.delta > 0 else 1
        state: int = event.state if isinstance(event.state, int) else 0
        if state & 1:
            scroll = self._canvas.xview_scroll
        else:
            scroll = self._canvas.yview_scroll
        scroll(delta, "units")

    async def add_campaign(self, campaign: DropsCampaign) -> None:
        campaign_frame = ttk.Frame(
            self._main_frame,
            style="Card.TFrame",
            relief="solid",
            borderwidth=1,
            padding=10,
        )
        campaign_frame.grid(column=0, row=len(self._campaigns), sticky="nsew", padx=2, pady=5)
        campaign_frame.rowconfigure(4, weight=1)
        campaign_frame.columnconfigure(1, weight=1)
        campaign_frame.columnconfigure(3, weight=10000)
        # Name
        ttk.Label(
            campaign_frame, text=campaign.name, takefocus=False, width=45
        ).grid(column=0, row=0, columnspan=2, sticky="w")
        # Status
        status_text, status_color = self.get_status(campaign)
        status_label = ttk.Label(
            campaign_frame, text=status_text, takefocus=False, foreground=status_color
        )
        status_row = ttk.Frame(campaign_frame)
        status_row.grid(column=1, row=1, sticky="ew", padx=4)
        status_row.columnconfigure(0, weight=1)
        status_label.grid(column=0, row=0, sticky="w")
        game_name = campaign.game.name
        priority_button = ttk.Button(
            status_row,
            command=partial(self._toggle_game_priority, game_name),
            **self._priority_button_options(game_name),
        )
        priority_button.grid(column=1, row=0, sticky="e")
        # NOTE: We have to save the campaign's frame and status before any awaits happen,
        # otherwise the len(self._campaigns) call may overwrite an existing frame,
        # if the campaigns are added concurrently.
        self._campaigns[campaign] = {
            "frame": campaign_frame,
            "status": status_label,
            "priority_button": priority_button,
        }
        self._schedule_agenda_refresh()
        # Starts / Ends
        MouseOverLabel(
            campaign_frame,
            text=_("gui", "inventory", "ends").format(
                time=campaign.ends_at.astimezone().replace(microsecond=0, tzinfo=None)
            ),
            alt_text=_("gui", "inventory", "starts").format(
                time=campaign.starts_at.astimezone().replace(microsecond=0, tzinfo=None)
            ),
            reverse=campaign.upcoming,
            takefocus=False,
        ).grid(column=1, row=2, sticky="w", padx=4)
        # Linking status
        if campaign.eligible:
            link_kwargs = {
                "style": '',
                "text": _("gui", "inventory", "status", "linked"),
                "foreground": "green",
            }
        else:
            link_kwargs = {
                "text": _("gui", "inventory", "status", "not_linked"),
                "foreground": "red",
            }
        LinkLabel(
            campaign_frame,
            link=campaign.link_url,
            takefocus=False,
            padding=0,
            **link_kwargs,
        ).grid(column=1, row=3, sticky="w", padx=4)
        # ACL channels
        acl = campaign.allowed_channels
        if acl:
            if len(acl) <= 5:
                allowed_text: str = '\n'.join(ch.name for ch in acl)
            else:
                allowed_text = '\n'.join(ch.name for ch in acl[:4])
                allowed_text += (
                    f"\n{_('gui', 'inventory', 'and_more').format(amount=len(acl) - 4)}"
                )
        else:
            allowed_text = _("gui", "inventory", "all_channels")
        ttk.Label(
            campaign_frame,
            text=f"{_('gui', 'inventory', 'allowed_channels')}\n{allowed_text}",
            takefocus=False,
        ).grid(column=1, row=4, sticky="nw", padx=4)
        # Image
        campaign_image = await self._cache.get(campaign.image_url, size=(108, 144))
        ttk.Label(campaign_frame, image=campaign_image).grid(column=0, row=1, rowspan=4)
        # Drops separator
        ttk.Separator(
            campaign_frame, orient="vertical", takefocus=False
        ).grid(column=2, row=0, rowspan=5, sticky="ns")
        # Drops display
        drops_row = ttk.Frame(campaign_frame)
        drops_row.grid(column=3, row=0, rowspan=5, sticky="nsew", padx=4)
        drops_row.rowconfigure(0, weight=1)
        for i, drop in enumerate(campaign.drops):
            drop_frame = ttk.Frame(
                drops_row,
                style="Card.TFrame",
                relief="solid",
                borderwidth=1,
                padding=8,
            )
            drop_frame.grid(column=i, row=0, padx=4)
            benefits_frame = ttk.Frame(drop_frame)
            benefits_frame.grid(column=0, row=0)
            benefit_images: list[PhotoImage] = await asyncio.gather(
                *(self._cache.get(benefit.image_url, (80, 80)) for benefit in drop.benefits)
            )
            for i, benefit, image in zip(range(len(drop.benefits)), drop.benefits, benefit_images):
                ttk.Label(
                    benefits_frame,
                    text=benefit.name,
                    image=image,
                    compound="bottom",
                ).grid(column=i, row=0, padx=5)
            self._drops[drop.id] = label = ttk.Label(drop_frame, justify=tk.CENTER)
            self.update_progress(drop, label)
            label.grid(column=0, row=1)
        if self._manager.tabs.current_tab() == 1:
            self._update_visibility(campaign)
            self._update_deadline_radar()
            self._update_visible_count()
            self._canvas_update()
        else:
            self._update_deadline_radar()

    def _priority_button_options(self, game_name: str) -> dict[str, str]:
        if game_name in self._settings.priority:
            return {"text": _("gui", "inventory", "priority_remove"), "state": "normal"}
        if game_name in self._settings.exclude:
            return {"text": _("gui", "inventory", "priority_excluded"), "state": "disabled"}
        return {"text": _("gui", "inventory", "priority_add"), "state": "normal"}

    def _toggle_game_priority(self, game_name: str) -> None:
        panel = self._manager.settings
        if game_name in self._settings.priority:
            changed = panel.remove_priority_game(game_name)
        else:
            changed = panel.add_priority_game(game_name)
        if changed:
            self._manager._twitch.change_state(State.INVENTORY_FETCH)
            self.refresh()

    def clear(self) -> None:
        for child in self._main_frame.winfo_children():
            child.destroy()
        self._drops.clear()
        self._campaigns.clear()
        self._schedule_agenda_refresh()
        self._update_deadline_radar()
        self._update_visible_count()

    def update_progress(self, drop: TimedDrop, label: ttk.Label) -> None:
        progress_text: str
        progress_color: str = ''
        if drop.is_claimed:
            progress_color = "green"
            progress_text = _("gui", "inventory", "status", "claimed")
        elif drop.can_claim:
            progress_color = "goldenrod"
            progress_text = _("gui", "inventory", "status", "ready_to_claim")
        elif drop.current_minutes or drop.can_earn():
            progress_text = _("gui", "inventory", "percent_progress").format(
                percent=f"{drop.progress:3.1%}",
                minutes=drop.required_minutes,
            )
            if drop.ends_at < drop.campaign.ends_at:
                # this drop becomes unavailable earlier than the campaign ends
                progress_text += '\n' + _("gui", "inventory", "ends").format(
                    time=drop.ends_at.astimezone().replace(microsecond=0, tzinfo=None)
                )
        else:
            if drop.required_minutes > 0:
                progress_text = _("gui", "inventory", "minutes_progress").format(
                    minutes=drop.required_minutes
                )
            else:
                # required_minutes is zero for subscription-based drops
                progress_text = ''
            if datetime.now(timezone.utc) < drop.starts_at > drop.campaign.starts_at:
                # this drop can only be earned later than the campaign start
                progress_text += '\n' + _("gui", "inventory", "starts").format(
                    time=drop.starts_at.astimezone().replace(microsecond=0, tzinfo=None)
                )
            elif drop.ends_at < drop.campaign.ends_at:
                # this drop becomes unavailable earlier than the campaign ends
                progress_text += '\n' + _("gui", "inventory", "ends").format(
                    time=drop.ends_at.astimezone().replace(microsecond=0, tzinfo=None)
                )
        label.config(text=progress_text, foreground=progress_color)

    def update_drop(self, drop: TimedDrop) -> None:
        self._schedule_agenda_refresh()
        label = self._drops.get(drop.id)
        if label is None:
            self._update_deadline_radar()
            return
        self.update_progress(drop, label)
        self._update_deadline_radar()


def proxy_validate(entry: PlaceholderEntry, settings: Settings) -> bool:
    raw_url = entry.get().strip()
    entry.replace(raw_url)
    url = URL(raw_url)
    valid = url.host is not None and url.port is not None
    if not valid:
        entry.clear()
        url = URL()
    settings.proxy = url
    return valid


class _SettingsVars(TypedDict):
    tray: IntVar
    proxy: StringVar
    autostart: IntVar
    dark_mode: IntVar
    language: StringVar
    priority_mode: StringVar
    tray_notifications: IntVar
    enable_badges_emotes: IntVar
    available_drops_check: IntVar


class SettingsPanel:
    AUTOSTART_NAME: str = APP_NAME
    AUTOSTART_KEY: str = "HKCU/Software/Microsoft/Windows/CurrentVersion/Run"

    @cached_property
    def PRIORITY_MODES(self) -> dict[PriorityMode, str]:
        # NOTE: Translation calls have to be deferred here,
        # to allow changing the language before the settings panel is initialized.
        return {
            PriorityMode.PRIORITY_ONLY: _("gui", "settings", "priority_modes", "priority_only"),
            PriorityMode.ENDING_SOONEST: _("gui", "settings", "priority_modes", "ending_soonest"),
            PriorityMode.LOW_AVBL_FIRST: _(
                "gui", "settings", "priority_modes", "low_availability"
            ),
        }

    def __init__(self, manager: GUIManager, master: ttk.Widget):
        self._manager = manager
        self._settings: Settings = manager._twitch.settings
        self._profile_store = GameProfilesStore()
        priority_mode = self._settings.priority_mode
        if priority_mode not in self.PRIORITY_MODES:
            priority_mode = PriorityMode.PRIORITY_ONLY
            self._settings.priority_mode = priority_mode
        self._vars: _SettingsVars = {
            "autostart": IntVar(master, 0),
            "language": StringVar(master, _.current),
            "proxy": StringVar(master, str(self._settings.proxy)),
            "tray": IntVar(master, self._settings.autostart_tray),
            "dark_mode": IntVar(master, int(self._settings.dark_mode)),
            "priority_mode": StringVar(master, self.PRIORITY_MODES[priority_mode]),
            "tray_notifications": IntVar(master, self._settings.tray_notifications),
            "enable_badges_emotes": IntVar(
                master, int(self._settings.enable_badges_emotes)
            ),
            "available_drops_check": IntVar(
                master, int(self._settings.available_drops_check)
            ),
        }
        self._game_names: set[str] = set()
        master.rowconfigure(0, weight=1)
        master.columnconfigure(0, weight=1)
        # use a frame to center the content within the tab
        center_frame = ttk.Frame(master)
        center_frame.grid(column=0, row=0)

        # General section
        general_frame = ttk.LabelFrame(
            center_frame, padding=(4, 0, 4, 4), text=_("gui", "settings", "general", "name")
        )
        general_frame.grid(column=0, row=0, sticky="nsew")
        # use another frame to center the options within the section
        # NOTE: this can be adjusted or removed later on if more options were to be added
        general_frame.rowconfigure(0, weight=1)
        general_frame.columnconfigure(0, weight=1)
        general_center = ttk.Frame(general_frame)
        general_center.grid(column=0, row=0)

        # language frame
        language_frame = ttk.Frame(general_center)
        language_frame.grid(column=0, row=0)
        ttk.Label(language_frame, text="Language 🌐 (requires restart): ").grid(column=0, row=0)
        SelectCombobox(
            language_frame,
            values=list(_.languages),
            textvariable=self._vars["language"],
            command=lambda e: setattr(self._settings, "language", self._vars["language"].get()),
        ).grid(column=1, row=0)

        # checkboxes frame
        checkboxes_frame = ttk.Frame(general_center)
        checkboxes_frame.grid(column=0, row=1)
        ttk.Label(
            checkboxes_frame, text=_("gui", "settings", "general", "autostart")
        ).grid(column=0, row=(irow := 0), sticky="e")
        ttk.Checkbutton(
            checkboxes_frame, variable=self._vars["autostart"], command=self.update_autostart
        ).grid(column=1, row=irow, sticky="w")
        self._vars["autostart"].set(self._query_autostart())
        if sys.platform != "darwin":
            ttk.Label(
                checkboxes_frame, text=_("gui", "settings", "general", "tray")
            ).grid(column=0, row=(irow := irow + 1), sticky="e")
            ttk.Checkbutton(
                checkboxes_frame, variable=self._vars["tray"], command=self.update_autostart
            ).grid(column=1, row=irow, sticky="w")
            ttk.Label(
                checkboxes_frame, text=_("gui", "settings", "general", "tray_notifications")
            ).grid(column=0, row=(irow := irow + 1), sticky="e")
            ttk.Checkbutton(
                checkboxes_frame,
                variable=self._vars["tray_notifications"],
                command=lambda: setattr(
                    self._settings,
                    "tray_notifications",
                    bool(self._vars["tray_notifications"].get()),
                ),
            ).grid(column=1, row=irow, sticky="w")
        ttk.Label(
            checkboxes_frame, text=_("gui", "settings", "general", "dark_mode")
        ).grid(column=0, row=(irow := irow + 1), sticky="e")
        ttk.Checkbutton(
            checkboxes_frame,
            variable=self._vars["dark_mode"],
            command=self.update_dark_mode,
        ).grid(column=1, row=irow, sticky="w")
        ttk.Label(
            checkboxes_frame, text=_("gui", "settings", "general", "priority_mode")
        ).grid(column=0, row=(irow := irow + 1), sticky="e")
        SelectCombobox(
            checkboxes_frame,
            command=self.priority_mode,
            textvariable=self._vars["priority_mode"],
            values=list(self.PRIORITY_MODES.values()),
        ).grid(column=1, row=irow, sticky="w")

        # proxy frame
        proxy_frame = ttk.Frame(general_center)
        proxy_frame.grid(column=0, row=2)
        ttk.Label(proxy_frame, text=_("gui", "settings", "general", "proxy")).grid(column=0, row=0)
        self._proxy = PlaceholderEntry(
            proxy_frame,
            width=37,
            validate="focusout",
            prefill="http://",
            textvariable=self._vars["proxy"],
            placeholder="http://username:password@address:port",
        )
        self._proxy.config(validatecommand=partial(proxy_validate, self._proxy, self._settings))
        self._proxy.grid(column=0, row=1)

        # Advanced section
        advanced_frame = ttk.LabelFrame(
            center_frame, padding=(4, 0, 4, 4), text=_("gui", "settings", "advanced", "name")
        )
        advanced_frame.grid(column=0, row=1, sticky="nsew")
        advanced_frame.columnconfigure(0, weight=1)
        advanced_frame.rowconfigure(0, weight=1)
        advanced_center = ttk.Frame(advanced_frame)
        advanced_center.grid(column=0, row=0)

        # Warning message
        ttk.Label(
            advanced_center, text=_("gui", "settings", "advanced", "warning"), foreground="red"
        ).grid(column=0, row=(irow := 0), columnspan=2)
        ttk.Label(
            advanced_center,
            text=_("gui", "settings", "advanced", "warning_text"),
            foreground="goldenrod",
        ).grid(column=0, row=(irow := irow + 1), columnspan=2)
        # Toggles for badges and emotes, and available drops check
        ttk.Label(
            advanced_center, text=_("gui", "settings", "advanced", "enable_badges_emotes")
        ).grid(column=0, row=(irow := irow + 1), sticky="e")
        ttk.Checkbutton(
            advanced_center,
            variable=self._vars["enable_badges_emotes"],
            command=lambda: setattr(
                self._settings,
                "enable_badges_emotes",
                bool(self._vars["enable_badges_emotes"].get()),
            ),
        ).grid(column=1, row=irow, sticky="w")
        ttk.Label(
            advanced_center, text=_("gui", "settings", "advanced", "available_drops_check")
        ).grid(column=0, row=(irow := irow + 1), sticky="e")
        ttk.Checkbutton(
            advanced_center,
            variable=self._vars["available_drops_check"],
            command=lambda: setattr(
                self._settings,
                "available_drops_check",
                bool(self._vars["available_drops_check"].get()),
            ),
        ).grid(column=1, row=irow, sticky="w")

        # Priority section
        priority_frame = ttk.LabelFrame(
            center_frame, padding=(4, 0, 4, 4), text=_("gui", "settings", "priority")
        )
        priority_frame.grid(column=1, row=0, rowspan=2, sticky="nsew")
        self._priority_entry = PlaceholderCombobox(
            priority_frame, placeholder=_("gui", "settings", "game_name"), width=30
        )
        self._priority_entry.grid(column=0, row=0, sticky="ew")
        priority_frame.columnconfigure(0, weight=1)
        ttk.Button(
            priority_frame, text="➕", command=self.priority_add, width=3, style="Large.TButton"
        ).grid(column=1, row=0, sticky="nsew")
        self._priority_list = PaddedListbox(
            priority_frame,
            height=12,
            padding=(1, 0),
            activestyle="none",
            selectmode="single",
            highlightthickness=0,
            exportselection=False,
        )
        self._priority_list.grid(column=0, row=1, rowspan=5, sticky="nsew")
        self._priority_list.insert("end", *self._settings.priority)
        weight_scale: int = 5
        ttk.Button(  # Move to top
            priority_frame,
            width=2,
            text="⇈",
            style="Arrow.TButton",
            command=partial(self.priority_move, MAX_INT),
        ).grid(column=1, row=1, sticky="nsew")
        priority_frame.rowconfigure(1, weight=1)
        ttk.Button(  # Move up
            priority_frame,
            width=2,
            text="↑",
            style="Arrow.TButton",
            command=partial(self.priority_move, 1),
        ).grid(column=1, row=2, sticky="nsew")
        priority_frame.rowconfigure(2, weight=weight_scale)
        ttk.Button(  # Move down
            priority_frame,
            width=2,
            text="↓",
            style="Arrow.TButton",
            command=partial(self.priority_move, -1),
        ).grid(column=1, row=3, sticky="nsew")
        priority_frame.rowconfigure(3, weight=weight_scale)
        ttk.Button(  # Move to bottom
            priority_frame,
            width=2,
            text="⇊",
            style="Arrow.TButton",
            command=partial(self.priority_move, -MAX_INT),
        ).grid(column=1, row=4, sticky="nsew")
        priority_frame.rowconfigure(4, weight=1)
        ttk.Button(
            priority_frame, text="❌", command=self.priority_delete, width=3, style="Large.TButton"
        ).grid(column=1, row=5, sticky="nsew")
        priority_frame.rowconfigure(5, weight=1)

        # Exclude section
        exclude_frame = ttk.LabelFrame(
            center_frame, padding=(4, 0, 4, 4), text=_("gui", "settings", "exclude")
        )
        exclude_frame.grid(column=2, row=0, rowspan=2, sticky="nsew")
        self._exclude_entry = PlaceholderCombobox(
            exclude_frame, placeholder=_("gui", "settings", "game_name"), width=26
        )
        self._exclude_entry.grid(column=0, row=0, sticky="ew")
        ttk.Button(
            exclude_frame, text="➕", command=self.exclude_add, width=3, style="Large.TButton"
        ).grid(column=1, row=0)
        self._exclude_list = PaddedListbox(
            exclude_frame,
            height=12,
            padding=(1, 0),
            activestyle="none",
            selectmode="single",
            highlightthickness=0,
            exportselection=False,
        )
        self._exclude_list.grid(column=0, row=1, columnspan=2, sticky="nsew")
        exclude_frame.rowconfigure(1, weight=1)
        # insert them alphabetically
        self._exclude_list.insert("end", *sorted(self._settings.exclude))
        ttk.Button(
            exclude_frame, text="❌", command=self.exclude_delete, width=3, style="Large.TButton"
        ).grid(column=0, row=2, columnspan=2, sticky="nsew")

        # Game profiles preserve the priority order and exclusion list together.
        profiles_frame = ttk.LabelFrame(
            center_frame,
            text=_("gui", "settings", "profiles", "title"),
            padding=(8, 5),
        )
        profiles_frame.grid(column=0, row=2, columnspan=3, sticky="ew", pady=(2, 4))
        profiles_frame.columnconfigure(1, weight=1)
        ttk.Label(
            profiles_frame,
            text=_("gui", "settings", "profiles", "description"),
        ).grid(column=0, row=0, columnspan=5, sticky="w", pady=(0, 4))
        ttk.Label(
            profiles_frame,
            text=_("gui", "settings", "profiles", "name"),
        ).grid(column=0, row=1, sticky="w", padx=(0, 8))
        self._profile_name = StringVar(master)
        self._profile_combo = ttk.Combobox(
            profiles_frame,
            textvariable=self._profile_name,
            values=self._profile_store.names,
            width=24,
        )
        self._profile_combo.grid(column=1, row=1, sticky="ew", padx=(0, 6))
        self._profile_status = StringVar(master)
        self._profile_status_label = ttk.Label(
            profiles_frame,
            textvariable=self._profile_status,
            style="Muted.TLabel",
        )
        self._profile_status_label.grid(
            column=0, row=2, columnspan=5, sticky="w", pady=(4, 0)
        )
        ttk.Button(
            profiles_frame,
            text=_("gui", "settings", "profiles", "save"),
            command=self.save_game_profile,
        ).grid(column=2, row=1, padx=3)
        self._profile_apply_button = ttk.Button(
            profiles_frame,
            text=_("gui", "settings", "profiles", "apply"),
            command=self.apply_game_profile,
        )
        self._profile_apply_button.grid(column=3, row=1, padx=3)
        self._profile_delete_button = ttk.Button(
            profiles_frame,
            text=_("gui", "settings", "profiles", "delete"),
            command=self.delete_game_profile,
        )
        self._profile_delete_button.grid(column=4, row=1, padx=(3, 0))
        self._profile_combo.bind(
            "<<ComboboxSelected>>", lambda _event: self._profile_status.set("")
        )
        self._refresh_game_profile_choices()

        # Reload button
        reload_frame = ttk.Frame(center_frame)
        reload_frame.grid(column=0, row=3, columnspan=3, pady=4)
        ttk.Label(reload_frame, text=_("gui", "settings", "reload_text")).grid(column=0, row=0)
        ttk.Button(
            reload_frame,
            text=_("gui", "settings", "reload"),
            command=self._manager._twitch.state_change(State.INVENTORY_FETCH),
        ).grid(column=1, row=0)

    def clear_selection(self) -> None:
        self._priority_list.selection_clear(0, "end")
        self._exclude_list.selection_clear(0, "end")

    def _refresh_game_profile_choices(self) -> None:
        names = self._profile_store.names
        self._profile_combo.configure(values=names)
        state = "normal" if names else "disabled"
        self._profile_apply_button.configure(state=state)
        self._profile_delete_button.configure(state=state)

    def save_game_profile(self) -> None:
        name = self._profile_name.get().strip()
        if not name:
            self._profile_status.set(_("gui", "settings", "profiles", "name_required"))
            return
        try:
            profile = self._profile_store.save_profile(
                name,
                self._settings.priority,
                self._settings.exclude,
            )
        except ProfileLimitError:
            self._profile_status.set(
                _("gui", "settings", "profiles", "limit").format(
                    limit=self._profile_store.MAX_PROFILES
                )
            )
            return
        except (OSError, ValueError):
            logger.exception("Unable to save a game profile")
            self._profile_status.set(_("gui", "settings", "profiles", "save_error"))
            return
        self._profile_name.set(profile.name)
        self._refresh_game_profile_choices()
        self._profile_status.set(
            _("gui", "settings", "profiles", "saved").format(name=profile.name)
        )

    def apply_game_profile(self) -> None:
        profile = self._profile_store.get(self._profile_name.get())
        if profile is None:
            self._profile_status.set(_("gui", "settings", "profiles", "select"))
            return
        changed = apply_game_profile(self._settings, profile)
        if changed:
            self._priority_list.delete(0, "end")
            self._priority_list.insert("end", *self._settings.priority)
            self._exclude_list.delete(0, "end")
            self._exclude_list.insert("end", *sorted(self._settings.exclude))
            self.update_priority_choices()
            self.update_excluded_choices()
            self._manager._twitch.change_state(State.INVENTORY_FETCH)
            message = "applied"
        else:
            message = "already_active"
        self._profile_status.set(
            _("gui", "settings", "profiles", message).format(name=profile.name)
        )

    def delete_game_profile(self) -> None:
        name = self._profile_name.get().strip()
        profile = self._profile_store.get(name)
        if profile is None or not self._profile_store.delete_profile(name):
            self._profile_status.set(_("gui", "settings", "profiles", "select"))
            return
        self._profile_name.set("")
        self._refresh_game_profile_choices()
        self._profile_status.set(
            _("gui", "settings", "profiles", "deleted").format(name=profile.name)
        )

    def update_dark_mode(self) -> None:
        self._settings.dark_mode = bool(self._vars["dark_mode"].get())
        self._manager.apply_theme(self._settings.dark_mode)

    def _get_self_path(self) -> str:
        # NOTE: we need double quotes in case the path contains spaces
        return f'"{SELF_PATH.resolve()!s}"'

    def _get_autostart_path(self) -> str:
        flags: list[str] = []
        # if applicable, include the current logging level as well
        for lvl_idx, lvl_value in LOGGING_LEVELS.items():
            if lvl_value == self._settings.logging_level:
                if lvl_idx > 0:
                    flags.append(f"-{'v' * lvl_idx}")
                break
        if self._vars["tray"].get():
            flags.append("--tray")
        if not IS_PACKAGED:
            # non-packaged autostart has to be done through the venv path pythonw
            return f"\"{SCRIPTS_PATH / 'pythonw'!s}\" {self._get_self_path()} {' '.join(flags)}"
        return f"{self._get_self_path()} {' '.join(flags)}"

    def _get_linux_autostart_filepath(self) -> Path:
        autostart_folder: Path = Path("~/.config/autostart").expanduser()
        if (config_home := os.environ.get("XDG_CONFIG_HOME")) is not None:
            config_autostart: Path = Path(config_home, "autostart").expanduser()
            if config_autostart.exists():
                autostart_folder = config_autostart
        return autostart_folder / f"{self.AUTOSTART_NAME}.desktop"

    def _get_mac_autostart_filepath(self) -> Path:
        return Path(
            Path.home(), f"Library/LaunchAgents/com.devilxd.{self.AUTOSTART_NAME.lower()}.plist"
        )

    def _query_autostart(self) -> bool:
        if sys.platform == "win32":
            with RegistryKey(self.AUTOSTART_KEY, read_only=True) as key:
                try:
                    value_type, value = key.get(self.AUTOSTART_NAME)
                except ValueNotFound:
                    return False
                # TODO: Consider deleting the old value to avoid autostart errors
                return (
                    value_type is ValueType.REG_SZ
                    and self._get_self_path() in value
                )
        elif sys.platform == "linux":
            autostart_file: Path = self._get_linux_autostart_filepath()
            if not autostart_file.exists():
                return False
            with autostart_file.open('r', encoding="utf8") as file:
                # TODO: Consider deleting the old file to avoid autostart errors
                return self._get_self_path() in file.read()
        elif sys.platform == "darwin":
            plist_file = self._get_mac_autostart_filepath()
            if not plist_file.exists():
                return False
            with plist_file.open('r', encoding="utf8") as file:
                return str(SELF_PATH.resolve()) in file.read()

    def update_autostart(self) -> None:
        enabled = bool(self._vars["autostart"].get())
        self._settings.autostart_tray = bool(self._vars["tray"].get())
        if sys.platform == "win32":
            if enabled:
                with RegistryKey(self.AUTOSTART_KEY) as key:
                    key.set(
                        self.AUTOSTART_NAME,
                        ValueType.REG_SZ,
                        self._get_autostart_path(),
                    )
            else:
                with RegistryKey(self.AUTOSTART_KEY) as key:
                    key.delete(self.AUTOSTART_NAME, silent=True)
        elif sys.platform == "linux":
            autostart_file: Path = self._get_linux_autostart_filepath()
            if enabled:
                file_contents: str = dedent(
                    f"""
                    [Desktop Entry]
                    Type=Application
                    Name=DropForge
                    Description=Manage Twitch drops with DropForge
                    Exec=sh -c '{self._get_autostart_path()}'
                    """
                )
                with autostart_file.open('w', encoding="utf8") as file:
                    file.write(file_contents)
            else:
                autostart_file.unlink(missing_ok=True)
        elif sys.platform == "darwin":
            plist_file = self._get_mac_autostart_filepath()

            if enabled:
                command_parts = shlex.split(self._get_autostart_path())
                plist_data = {
                    "Label": f"com.devilxd.{self.AUTOSTART_NAME.lower()}",
                    "ProgramArguments": command_parts,
                    "RunAtLoad": True,
                }
                plist_file.parent.mkdir(parents=True, exist_ok=True)
                with plist_file.open("wb") as file:
                    plistlib.dump(plist_data, file)
            else:
                plist_file.unlink(missing_ok=True)

    def update_excluded_choices(self) -> None:
        self._exclude_entry.config(
            values=sorted(self._game_names.difference(self._settings.exclude))
        )

    def update_priority_choices(self) -> None:
        self._priority_entry.config(
            values=sorted(self._game_names.difference(self._settings.priority))
        )

    def set_games(self, games: set[Game]) -> None:
        self._game_names.update(game.name for game in games)
        self.update_excluded_choices()
        self.update_priority_choices()

    def add_priority_game(self, game_name: str) -> bool:
        if not add_game_to_priority(
            game_name,
            self._settings.priority,
            self._settings.exclude,
        ):
            return False
        self._priority_list.insert("end", game_name)
        self._priority_list.see("end")
        self._settings.alter()
        self.update_priority_choices()
        return True

    def remove_priority_game(self, game_name: str) -> bool:
        if not remove_game_from_priority(game_name, self._settings.priority):
            return False
        self._priority_list.delete(0, "end")
        self._priority_list.insert("end", *self._settings.priority)
        self._settings.alter()
        self.update_priority_choices()
        return True

    def priority_add(self) -> None:
        game_name: str = self._priority_entry.get()
        if not game_name:
            # prevent adding empty strings
            return
        self._priority_entry.clear()
        if not self.add_priority_game(game_name) and game_name in self._settings.priority:
            existing_idx = self._settings.priority.index(game_name)
            self._priority_list.selection_set(existing_idx)
            self._priority_list.see(existing_idx)

    def _priority_idx(self) -> int | None:
        selection: tuple[int, ...] = self._priority_list.curselection()
        if not selection:
            return None
        return selection[0]

    def priority_move(self, amount: int) -> None:
        # amount > 0 = up, amount < 0 = down
        idx: int | None = self._priority_idx()
        max_idx: int = self._priority_list.size() - 1
        if (
            idx is None
            or amount == 0
            or amount > 0 and idx == 0
            or amount < 0 and idx == max_idx
        ):
            return
        insert_idx: int = idx - amount
        if insert_idx <= 0:
            insert_idx = 0
        elif insert_idx >= max_idx:
            insert_idx = max_idx

        item: str = self._priority_list.get(idx)
        self._priority_list.delete(idx)
        self._priority_list.insert(insert_idx, item)
        # reselect the item and scroll the list if needed
        self._priority_list.selection_set(insert_idx)
        self._priority_list.see(insert_idx)
        # update the underlying settings list too
        self._settings.priority.pop(idx)
        self._settings.priority.insert(insert_idx, item)
        self._settings.alter()

    def priority_delete(self) -> None:
        idx: int | None = self._priority_idx()
        if idx is None:
            return
        self.remove_priority_game(self._settings.priority[idx])

    def priority_mode(self, event: tk.Event[ttk.Combobox]) -> None:
        mode_name: str = self._vars["priority_mode"].get()
        for value, name in self.PRIORITY_MODES.items():
            if mode_name == name:
                self._settings.priority_mode = value
                break

    def exclude_add(self) -> None:
        game_name: str = self._exclude_entry.get()
        if not game_name:
            # prevent adding empty strings
            return
        self._exclude_entry.clear()
        if game_name not in self._settings.exclude:
            self._settings.exclude.add(game_name)
            self._settings.alter()
            self.update_excluded_choices()
            # insert it alphabetically
            for i, item in enumerate(self._exclude_list.get(0, "end")):
                if game_name < item:
                    self._exclude_list.insert(i, game_name)
                    self._exclude_list.see(i)
                    break
            else:
                self._exclude_list.insert("end", game_name)
                self._exclude_list.see("end")
        else:
            # it was already there, select it
            for i, item in enumerate(self._exclude_list.get(0, "end")):
                if item == game_name:
                    existing_idx = i
                    break
            else:
                # something went horribly wrong and it's not there after all - just return
                return
            self._exclude_list.selection_set(existing_idx)
            self._exclude_list.see(existing_idx)

    def exclude_delete(self) -> None:
        selection: tuple[int, ...] = self._exclude_list.curselection()
        if not selection:
            return None
        idx: int = selection[0]
        item: str = self._exclude_list.get(idx)
        if item in self._settings.exclude:
            self._exclude_list.delete(idx)
            self._settings.exclude.discard(item)
            self._settings.alter()
            self.update_excluded_choices()


class HelpTab:
    WIDTH = 800

    def __init__(self, manager: GUIManager, master: ttk.Widget):
        self._twitch = manager._twitch
        master.rowconfigure(0, weight=1)
        master.columnconfigure(0, weight=1)
        # use a frame to center the content within the tab
        center_frame = ttk.Frame(master)
        center_frame.grid(column=0, row=0)
        # use a frame for the bottom row specifically
        bottom_frame = ttk.Frame(master)
        bottom_frame.grid(column=0, row=1, sticky="nsew")
        irow = 0
        # About
        about = ttk.LabelFrame(center_frame, padding=(4, 0, 4, 4), text="About")
        about.grid(column=0, row=(irow := irow + 1), sticky="nsew", padx=2)
        about.columnconfigure(2, weight=1)
        # About - created by
        ttk.Label(
            about, text="Application created by: ", anchor="e"
        ).grid(column=0, row=0, sticky="nsew")
        LinkLabel(
            about, link="https://github.com/DevilXD", text="DevilXD"
        ).grid(column=1, row=0, sticky="nsew")
        # About - repo link
        ttk.Label(about, text="Repository: ", anchor="e").grid(column=0, row=1, sticky="nsew")
        LinkLabel(
            about,
            link="https://github.com/DevilXD/TwitchDropsMiner",
            text="https://github.com/DevilXD/TwitchDropsMiner",
        ).grid(column=1, row=1, sticky="nsew")
        # About - donate
        ttk.Separator(
            about, orient="horizontal"
        ).grid(column=0, row=2, columnspan=3, sticky="nsew")
        ttk.Label(about, text="Donate: ", anchor="e").grid(column=0, row=3, sticky="nsew")
        LinkLabel(
            about,
            link="https://www.buymeacoffee.com/DevilXD",
            text=(
                "If you like the application and found it useful, "
                "please consider donating a small amount of money to support me. Thank you!"
            ),
            wraplength=self.WIDTH,
        ).grid(column=1, row=3, sticky="nsew")
        # Useful links
        links = ttk.LabelFrame(
            center_frame, padding=(4, 0, 4, 4), text=_("gui", "help", "links", "name")
        )
        links.grid(column=0, row=(irow := irow + 1), sticky="nsew", padx=2)
        LinkLabel(
            links,
            link="https://www.twitch.tv/drops/inventory",
            text=_("gui", "help", "links", "inventory"),
        ).grid(column=0, row=0, sticky="nsew")
        LinkLabel(
            links,
            link="https://www.twitch.tv/drops/campaigns",
            text=_("gui", "help", "links", "campaigns"),
        ).grid(column=0, row=1, sticky="nsew")
        ttk.Label(
            links,
            text=_("gui", "help", "shortcuts").format(modifier=Notebook.SHORTCUT_LABEL),
            style="Muted.TLabel",
            wraplength=self.WIDTH,
        ).grid(column=0, row=2, sticky="w", pady=(4, 0))
        # How It Works
        howitworks = ttk.LabelFrame(
            center_frame, padding=(4, 0, 4, 4), text=_("gui", "help", "how_it_works")
        )
        howitworks.grid(column=0, row=(irow := irow + 1), sticky="nsew", padx=2)
        ttk.Label(
            howitworks, text=_("gui", "help", "how_it_works_text"), wraplength=self.WIDTH
        ).grid(sticky="nsew")
        getstarted = ttk.LabelFrame(
            center_frame, padding=(4, 0, 4, 4), text=_("gui", "help", "getting_started")
        )
        getstarted.grid(column=0, row=(irow := irow + 1), sticky="nsew", padx=2)
        ttk.Label(
            getstarted, text=_("gui", "help", "getting_started_text"), wraplength=self.WIDTH
        ).grid(sticky="nsew")

        # Invalidate button
        invalidate_frame = ttk.Frame(bottom_frame)
        bottom_frame.columnconfigure(0, weight=1)  # center within the column
        invalidate_frame.grid(column=0, row=0, sticky="nse")
        ttk.Label(
            invalidate_frame, text=_("gui", "help", "invalidate", "text")
        ).grid(column=0, row=0)
        self._invalidate_button: ttk.Button = ttk.Button(
            invalidate_frame,
            text=_("gui", "help", "invalidate", "button"),
            command=self.invalidate_token,
            state="disabled",
        )
        self._invalidate_button.grid(column=1, row=0)

    def invalidate_token(self) -> None:
        # sync to async bridge
        asyncio.create_task(task_wrapper(self._invalidate_token)())

    async def _invalidate_token(self) -> None:
        auth_state = await self._twitch.get_auth()
        async with self._twitch.request(
            "POST",
            "https://id.twitch.tv/oauth2/revoke",
            data={
                "client_id": self._twitch._client_type.CLIENT_ID,
                "token": auth_state.access_token,
            }
        ) as response:
            if response.status == 200:
                auth_state.invalidate(delete_cookies=True)
            else:
                logger.error(f"Failed to invalidate the auth token: {response.status}")
        self._twitch.change_state(State.RESTART)


##########################################
# GUI DEFINITION END / GUI MANAGER START #
##########################################


class AchievementJournal:
    """Searchable local record of confirmed drop claims."""

    COLUMNS = ("claimed_at", "game", "campaign", "reward")
    PERIODS = ("all", "today", "week", "session")

    def __init__(
        self,
        manager: GUIManager,
        master: ttk.Widget,
        *,
        store: ClaimHistoryStore | None = None,
    ):
        self._manager = manager
        self._store = store or ClaimHistoryStore()
        self._search = StringVar(master)
        self._search.trace_add("write", lambda *_: self.refresh())

        master.columnconfigure(0, weight=1)
        master.rowconfigure(4, weight=1)
        header = ttk.Frame(master, style="Page.TFrame")
        header.grid(column=0, row=0, sticky="ew", pady=(2, 15))
        header.columnconfigure(0, weight=1)
        ttk.Label(
            header,
            text=_("gui", "history", "title"),
            style="HistoryTitle.TLabel",
        ).grid(column=0, row=0, sticky="w")
        ttk.Label(
            header,
            text=_("gui", "history", "subtitle"),
            style="Muted.TLabel",
        ).grid(column=0, row=1, sticky="w", pady=(3, 0))

        self._stats: dict[str, StringVar] = {
            key: StringVar(master, value="0")
            for key in ("total", "today", "session")
        }
        stats_frame = ttk.Frame(master, style="Page.TFrame")
        stats_frame.grid(column=0, row=1, sticky="ew", pady=(0, 13))
        for column, key in enumerate(("total", "today", "session")):
            stats_frame.columnconfigure(column, weight=1, uniform="history-stats")
            card = ttk.Frame(
                stats_frame,
                style="Card.TFrame",
                padding=(15, 11),
                relief="solid",
                borderwidth=1,
            )
            card.grid(column=column, row=0, sticky="ew", padx=(4, 4))
            ttk.Label(
                card,
                text=_("gui", "history", key),
                style="Overline.TLabel",
            ).grid(column=0, row=0, sticky="w")
            ttk.Label(
                card,
                textvariable=self._stats[key],
                style="HeroPercent.TLabel",
            ).grid(column=0, row=1, sticky="w", pady=(2, 0))

        toolbar = ttk.Frame(master, style="Page.TFrame")
        toolbar.grid(column=0, row=2, sticky="ew", pady=(1, 6))
        toolbar.columnconfigure(1, weight=1)
        ttk.Label(toolbar, text=_("gui", "history", "search")).grid(
            column=0, row=0, sticky="w", padx=(0, 8)
        )
        self._search_entry = ttk.Entry(toolbar, textvariable=self._search, width=20)
        self._search_entry.grid(column=1, row=0, sticky="ew")
        self._search_entry.bind("<Escape>", self._clear_search)
        ttk.Button(
            toolbar,
            text="×",
            width=3,
            command=lambda: self._search.set(""),
        ).grid(column=2, row=0, padx=6)
        ttk.Label(toolbar, text=_("gui", "history", "period")).grid(
            column=3, row=0, sticky="w", padx=(8, 6)
        )
        self._period = ttk.Combobox(
            toolbar,
            values=tuple(_("gui", "history", f"period_{period}") for period in self.PERIODS),
            state="readonly",
            exportselection=False,
            width=17,
        )
        self._period.current(0)
        self._period.grid(column=4, row=0, padx=(0, 10))
        self._period.bind("<<ComboboxSelected>>", lambda _event: self.refresh())
        ttk.Button(
            toolbar,
            text=_("gui", "history", "export"),
            command=self.export_csv,
        ).grid(column=5, row=0, sticky="e")

        self._result_count = ttk.Label(master, text="", style="Muted.TLabel")
        self._result_count.grid(column=0, row=3, sticky="w", pady=(0, 5))
        table_frame = ttk.Frame(master, style="Card.TFrame", padding=1)
        table_frame.grid(column=0, row=4, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        scroll = ttk.Scrollbar(table_frame, orient="vertical")
        self._table = ttk.Treeview(
            table_frame,
            columns=self.COLUMNS,
            show="headings",
            selectmode="browse",
            yscrollcommand=scroll.set,
        )
        scroll.config(command=self._table.yview)
        for column, key, width, stretch in (
            ("claimed_at", "time", 145, False),
            ("game", "game", 180, True),
            ("campaign", "campaign", 260, True),
            ("reward", "reward", 300, True),
        ):
            self._table.heading(
                column,
                text=_("gui", "history", f"column_{key}"),
                anchor="w",
            )
            self._table.column(
                column,
                width=width,
                minwidth=95,
                stretch=stretch,
                anchor="w",
            )
        self._table.grid(column=0, row=0, sticky="nsew")
        scroll.grid(column=1, row=0, sticky="ns")
        self.refresh()
        master.bind("<Map>", lambda _event: self.refresh(), add="+")

    def focus_search(self) -> None:
        self._search_entry.focus_set()
        self._search_entry.selection_range(0, "end")
        self._search_entry.icursor("end")

    def _clear_search(self, _event: tk.Event) -> str:
        self._search.set("")
        return "break"

    @staticmethod
    def _date_text(record: ClaimRecord) -> str:
        return record.claimed_at.astimezone().strftime("%d/%m/%Y %H:%M")

    def record_claim(self, campaign: DropsCampaign, drop: TimedDrop) -> None:
        if self._store.record_claim(campaign, drop) is not None:
            self.refresh()

    def refresh(self) -> None:
        records = self._store.records
        local_today = datetime.now().astimezone().date()
        session_started = self._manager._session_started
        self._stats["total"].set(str(len(records)))
        self._stats["today"].set(
            str(sum(record.claimed_at.astimezone().date() == local_today for record in records))
        )
        self._stats["session"].set(
            str(sum(record.claimed_at >= session_started for record in records))
        )

        period_index = self._period.current()
        period = self.PERIODS[period_index] if period_index >= 0 else "all"
        if period == "today":
            records = tuple(
                record for record in records if record.claimed_at.astimezone().date() == local_today
            )
        elif period == "week":
            first_day = local_today - timedelta(days=6)
            records = tuple(
                record for record in records
                if first_day <= record.claimed_at.astimezone().date() <= local_today
            )
        elif period == "session":
            records = tuple(record for record in records if record.claimed_at >= session_started)

        query = self._search.get().strip().casefold()
        if query:
            records = tuple(
                record
                for record in records
                if query
                in " ".join(
                    (
                        self._date_text(record),
                        record.game,
                        record.campaign,
                        record.reward,
                    )
                ).casefold()
            )
        self._table.delete(*self._table.get_children())
        for record in reversed(records):
            self._table.insert(
                "",
                "end",
                iid=record.record_id,
                values=(
                    self._date_text(record),
                    record.game,
                    record.campaign,
                    record.reward,
                ),
            )
        if not self._store.records:
            result_text = _("gui", "history", "empty")
        elif not records:
            result_text = _("gui", "history", "no_match")
        else:
            result_text = _("gui", "history", "count").format(count=len(records))
        self._result_count.config(text=result_text)

    def export_csv(self) -> None:
        path = filedialog.asksaveasfilename(
            parent=self._manager._root,
            title=_("gui", "history", "export_title"),
            initialfile=_("gui", "history", "export_filename"),
            defaultextension=".csv",
            filetypes=(("CSV", "*.csv"),),
        )
        if not path:
            return
        try:
            self._store.export_csv(Path(path))
        except OSError:
            logger.exception("Unable to export the local drop history")
            self._result_count.config(text=_("gui", "history", "export_error"))
        else:
            self._result_count.config(
                text=_("gui", "history", "exported").format(
                    count=len(self._store.records)
                )
            )


class GUIManager:
    def __init__(self, twitch: Twitch):
        self._twitch: Twitch = twitch
        self._session_started = datetime.now(timezone.utc)
        self._poll_task: asyncio.Task[NoReturn] | None = None
        self._close_requested = asyncio.Event()
        self._diagnostics_window: tk.Toplevel | None = None
        self._hud_window: MiniHUD | None = None
        self._root = root = Tk(className=WINDOW_TITLE)
        # withdraw immediately to prevent the window from flashing
        self._root.withdraw()
        # root.resizable(False, True)
        set_root_icon(root, resource_path("icons/dropforge.ico"))
        root.title(WINDOW_TITLE)  # window title
        root.bind_all("<KeyPress-Escape>", self.unfocus)  # pressing ESC unfocuses selection
        # Image cache for displaying images
        self._cache = ImageCache(self)

        # style adjustements
        self._style = style = ttk.Style(root)
        # theme
        theme = ''
        # theme = style.theme_names()[6]
        # style.theme_use(theme)
        # fix treeview's background color from tags not working (also see '_fixed_map')
        style.map(
            "Treeview",
            foreground=self._fixed_map("foreground"),
            background=self._fixed_map("background"),
        )
        # Keep checkboxes clean; page navigation now lives in the app rail.
        if theme != "classic" and sys.platform != "darwin":
            # remove Checkbutton.focus dotted line from checkbuttons
            style.configure("TCheckbutton", padding=0)
            original = style.layout("TCheckbutton")
            sublayout = original[0][1]["children"]
            sublayout[1] = sublayout[1][1]["children"][0]
            del original[0][1]["children"][1]
            style.layout("TCheckbutton", original)
        # label style - green, yellow and red text
        style.configure("green.TLabel", foreground="green")
        style.configure("yellow.TLabel", foreground="goldenrod")
        style.configure("red.TLabel", foreground="red")
        # fonts storage
        self._fonts: dict[str, Font] = {}
        # end of style changes

        root_frame = ttk.Frame(root, padding=12)
        root_frame.grid(column=0, row=0, sticky="nsew")
        root.rowconfigure(0, weight=1)
        root.columnconfigure(0, weight=1)
        # Notebook
        self.tabs = Notebook(self, root_frame)
        # Tray action stays in the navigation rail, separate from the active page.
        self.tray = TrayIcon(self, self.tabs.tray_slot)
        # Main tab
        main_frame = ttk.Frame(self.tabs.page_host, style="Page.TFrame", padding=12)
        main_frame.columnconfigure(0, weight=1)
        main_frame.columnconfigure(2, weight=4)
        # Keep the connection readout at its requested width. ConsoleOutput's
        # weighted row absorbs changes in height.
        self.tabs.add_tab(main_frame, name=_("gui", "tabs", "main"))
        self.status = StatusBar(self, main_frame)
        self.websockets = WebsocketStatus(self, main_frame)
        self.login = LoginForm(self, main_frame)
        self.progress = CampaignProgress(self, main_frame)
        self.output = ConsoleOutput(self, main_frame)
        self.channels = ChannelList(self, main_frame)
        # Inventory tab
        inv_frame = ttk.Frame(self.tabs.page_host, style="Page.TFrame", padding=12)
        self.inv = InventoryOverview(self, inv_frame)
        self.tabs.add_tab(
            inv_frame, name=_("gui", "tabs", "inventory"), search=self.inv.focus_search
        )
        # Settings tab
        settings_frame = ttk.Frame(self.tabs.page_host, style="Page.TFrame", padding=12)
        self.settings = SettingsPanel(self, settings_frame)
        self.tabs.add_tab(settings_frame, name=_("gui", "tabs", "settings"))
        # Help tab
        help_frame = ttk.Frame(self.tabs.page_host, style="Page.TFrame", padding=12)
        self.help = HelpTab(self, help_frame)
        self.tabs.add_tab(help_frame, name=_("gui", "tabs", "help"))
        history_frame = ttk.Frame(self.tabs.page_host, style="Page.TFrame", padding=12)
        self.history = AchievementJournal(self, history_frame)
        self.tabs.add_tab(
            history_frame, name=_("gui", "tabs", "history"), search=self.history.focus_search
        )
        # clamp minimum window size (update geometry first)
        root.update_idletasks()
        root.minsize(
            width=max(root.winfo_reqwidth(), 1080),
            height=max(root.winfo_reqheight(), 720),
        )
        root.geometry("1320x800")
        self._last_normal_geometry: WindowGeometry | None = None
        self._pending_window_position: tuple[int, int] | None = None
        root.bind("<Configure>", self._record_window_geometry, add="+")
        root.bind("<Map>", self._on_window_mapped, add="+")
        self._restore_window_geometry()
        # register logging handler
        self._handler = _TKOutputHandler(self)
        self._handler.setFormatter(OUTPUT_FORMATTER)
        logger = logging.getLogger("TwitchDrops")
        logger.addHandler(self._handler)
        if (logging_level := logger.getEffectiveLevel()) < logging.ERROR:
            self.print(f"Logging level: {logging.getLevelName(logging_level)}")
        # gracefully handle Windows shutdown closing the application
        if sys.platform == "win32":
            # NOTE: this root.update() is required for the below to work - don't remove
            root.update()
            self._message_map = {
                # window close request
                win32con.WM_CLOSE: self.close,
                # shutdown request
                win32con.WM_QUERYENDSESSION: self.close,
            }
            # This hooks up the wnd_proc function as the message processor for the root window.
            self.old_wnd_proc = win32gui.SetWindowLong(
                self._handle, win32con.GWL_WNDPROC, self.wnd_proc
            )
            # This ensures all of this works when the application is withdrawn or iconified
            ctypes.windll.user32.ShutdownBlockReasonCreate(
                self._handle, ctypes.c_wchar_p(_("gui", "status", "exiting"))
            )
            # DEV NOTE: use this to remove the reason in the future
            # ctypes.windll.user32.ShutdownBlockReasonDestroy(self._handle)
        else:
            # use old-style window closing protocol for non-windows platforms
            root.protocol("WM_DELETE_WINDOW", self.close)
            root.protocol("WM_DESTROY_WINDOW", self.close)
        # Save current theme and apply palette after widgets are created
        try:
            self._orig_theme_name = self._style.theme_use()
        except Exception:
            self._orig_theme_name = ''
        self.apply_theme(self._twitch.settings.dark_mode)
        # stay hidden in tray if needed, otherwise show the window when everything's ready
        if self._twitch.settings.tray and sys.platform != "darwin":
            # NOTE: this starts the tray icon thread
            self._root.after_idle(self.tray.minimize)
        else:
            self._root.after_idle(self._show_window)

    # https://stackoverflow.com/questions/56329342/tkinter-treeview-background-tag-not-working
    def _fixed_map(self, option):
        # Fix for setting text colour for Tkinter 8.6.9
        # From: https://core.tcl.tk/tk/info/509cafafae
        #
        # Returns the style map for 'option' with any styles starting with
        # ('!disabled', '!selected', ...) filtered out.

        # style.map() returns an empty list for missing options, so this
        # should be future-safe.
        return [
            elm for elm in self._style.map("Treeview", query_opt=option)
            if elm[:2] != ("!disabled", "!selected")
        ]

    def wnd_proc(self, hwnd, msg, w_param, l_param):
        """
        This function serves as a message processor for all messages sent
        to the application by Windows.
        """
        if msg == win32con.WM_DESTROY:
            win32api.SetWindowLong(self._handle, win32con.GWL_WNDPROC, self.old_wnd_proc)
        if msg in self._message_map:
            return self._message_map[msg](w_param, l_param)
        return win32gui.CallWindowProc(self.old_wnd_proc, hwnd, msg, w_param, l_param)

    @cached_property
    def _handle(self) -> int:
        return int(self._root.wm_frame(), 16)

    @property
    def running(self) -> bool:
        return self._poll_task is not None

    @property
    def close_requested(self) -> bool:
        return self._close_requested.is_set()

    async def wait_until_closed(self):
        # wait until the user closes the window
        await self._close_requested.wait()

    async def coro_unless_closed(self, coro: abc.Awaitable[_T]) -> _T:
        # In Python 3.11, we need to explicitly wrap awaitables
        tasks = [asyncio.ensure_future(coro), asyncio.ensure_future(self._close_requested.wait())]
        done: set[asyncio.Task[Any]]
        pending: set[asyncio.Task[Any]]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        if self._close_requested.is_set():
            raise ExitRequest()
        return await next(iter(done))

    def prevent_close(self):
        self._close_requested.clear()

    def start(self):
        if self._poll_task is None:
            self._poll_task = asyncio.create_task(self._poll())
        # self.progress.start_timer()

    def stop(self):
        self.progress.stop_timer()
        if self._poll_task is not None:
            self._poll_task.cancel()
            self._poll_task = None

    async def _poll(self):
        """
        This runs the Tkinter event loop via asyncio instead of calling mainloop.
        0.05s gives similar performance and CPU usage.
        Not ideal, but the simplest way to avoid threads, thread safety,
        loop.call_soon_threadsafe, futures and all of that.

        Uses TKINTER_DONT_WAIT to prevent Tcl/Tk from hanging inside native
        system calls (e.g. X11/Wayland input contexts) during heavy UI redraws.
        """
        do_one_event = self._root.dooneevent
        # TKINTER_DONT_WAIT (1 << 1) tells Tcl to return immediately
        # if no events are ready in the queue.
        DONT_WAIT = 1 << 1

        while True:
            try:
                # Drain pending Tk events non-blockingly
                while do_one_event(DONT_WAIT):
                    pass
            except tk.TclError:
                # Root window was destroyed
                break
            await asyncio.sleep(0.05)

        self._poll_task = None

    def _monitor_rectangles(self) -> list[tuple[int, int, int, int]]:
        if sys.platform == "win32":
            try:
                return [
                    tuple(int(value) for value in monitor[2])
                    for monitor in win32api.EnumDisplayMonitors()
                ]
            except Exception:
                pass

        try:
            left = self._root.winfo_vrootx()
            top = self._root.winfo_vrooty()
            width = self._root.winfo_vrootwidth()
            height = self._root.winfo_vrootheight()
        except tk.TclError:
            left = top = 0
            width = height = 0
        if width <= 1 or height <= 1:
            left = top = 0
            width = self._root.winfo_screenwidth()
            height = self._root.winfo_screenheight()
        return [(left, top, left + width, top + height)]

    def _restore_window_geometry(self) -> None:
        geometry = parse_window_geometry(self._twitch.settings.window_geometry)
        monitors = self._monitor_rectangles()
        if geometry is None or not window_geometry_is_visible(geometry, monitors):
            return

        width = geometry["width"]
        height = geometry["height"]
        x = geometry["x"]
        y = geometry["y"]
        try:
            self._root.geometry(f"{width}x{height}")
            if sys.platform == "win32":
                self._root.update_idletasks()
                left, top, right, bottom = win32gui.GetWindowRect(self._handle)
                outer_width = right - left
                outer_height = bottom - top
                virtual_right = self._root.winfo_vrootx() + self._root.winfo_vrootwidth()
                virtual_bottom = self._root.winfo_vrooty() + self._root.winfo_vrootheight()
                geometry_x = x if x >= 0 else x - (virtual_right - outer_width)
                geometry_y = y if y >= 0 else y - (virtual_bottom - outer_height)
                self._root.geometry(
                    f"{width}x{height}{geometry_x:+d}{geometry_y:+d}"
                )
                self._root.update_idletasks()
                self._pending_window_position = (x, y)
            else:
                self._root.geometry(f"{width}x{height}{x:+d}{y:+d}")
        except Exception:
            logger.warning("Unable to restore the saved window position", exc_info=True)
            return
        self._last_normal_geometry = geometry

    def _apply_pending_window_position(self) -> None:
        if self._pending_window_position is None:
            return
        x, y = self._pending_window_position
        try:
            win32gui.SetWindowPos(
                self._handle,
                win32con.HWND_TOP,
                x,
                y,
                0,
                0,
                win32con.SWP_NOSIZE | win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE,
            )
        except Exception:
            logger.warning("Unable to apply the saved window position", exc_info=True)
            return
        self._pending_window_position = None

    def _on_window_mapped(self, event: tk.Event) -> None:
        if event.widget is self._root and self._pending_window_position is not None:
            self._root.after(250, self._apply_pending_window_position)

    def _show_window(self) -> None:
        self._root.deiconify()
        if self._pending_window_position is not None:
            self._root.after(250, self._apply_pending_window_position)

    def _capture_window_geometry(self) -> None:
        try:
            if self._root.wm_state() != "normal":
                return
            x = self._root.winfo_x()
            y = self._root.winfo_y()
            if sys.platform == "win32":
                x, y, _, _ = win32gui.GetWindowRect(self._handle)
            geometry = parse_window_geometry(
                {
                    "width": self._root.winfo_width(),
                    "height": self._root.winfo_height(),
                    "x": x,
                    "y": y,
                }
            )
        except Exception:
            return
        if geometry is not None:
            self._last_normal_geometry = geometry

    def _record_window_geometry(self, event: tk.Event) -> None:
        if event.widget is self._root:
            self._capture_window_geometry()

    def close(self, *args) -> int:
        """
        Requests the GUI application to close.
        The window itself will be closed in the closing sequence later.
        """
        self._capture_window_geometry()
        if self._last_normal_geometry is not None:
            self._twitch.settings.window_geometry = self._last_normal_geometry
        self._close_requested.set()
        # notify client we're supposed to close
        self._twitch.close()
        return 0

    def close_window(self):
        """
        Closes the window. Invalidates the logger.
        """
        self.tray.stop()
        self.close_hud()
        logging.getLogger("TwitchDrops").removeHandler(self._handler)
        self._root.destroy()

    def unfocus(self, event):
        # support pressing ESC to unfocus
        self._root.focus_set()
        self.channels.clear_selection()
        self.settings.clear_selection()

    # these are here to interface with underlaying GUI components
    def save(self, *, force: bool = False) -> None:
        self._cache.save(force=force)

    def grab_attention(self, *, sound: bool = True):
        self.tray.restore()
        self._root.focus_set()
        if sound:
            self._root.bell()

    def set_games(self, games: set[Game]) -> None:
        self.settings.set_games(games)

    def show_diagnostics(self) -> None:
        if self._diagnostics_window is not None:
            try:
                if self._diagnostics_window.winfo_exists():
                    self._diagnostics_window.lift()
                    self._diagnostics_window.focus_set()
                    return
            except tk.TclError:
                pass
        dialog = CampaignDiagnosticsDialog(self)
        self._diagnostics_window = dialog.window

    def show_hud(self) -> None:
        if self._hud_window is not None:
            try:
                if self._hud_window.window.winfo_exists():
                    self._hud_window.window.deiconify()
                    self._hud_window.window.lift()
                    return
            except tk.TclError:
                pass
        self._hud_window = MiniHUD(self)
        self._hud_window.update_status(self.status._text)
        self.update_hud_drop(self.progress._drop)

    def close_hud(self) -> None:
        hud = self._hud_window
        self._hud_window = None
        if hud is not None:
            try:
                if hud.window.winfo_exists():
                    hud.window.destroy()
            except tk.TclError:
                pass

    def update_hud_status(self, text: str) -> None:
        if self._hud_window is not None:
            self._hud_window.update_status(text)

    def update_hud_drop(self, drop: TimedDrop | None) -> None:
        if self._hud_window is not None:
            self._hud_window.update_drop(drop)
            if drop is not None:
                self.update_hud_remaining(self.progress._vars["drop"]["remaining"].get())

    def update_hud_remaining(self, text: str) -> None:
        if self._hud_window is not None:
            self._hud_window.update_remaining(text)

    def display_drop(
        self, drop: TimedDrop, *, countdown: bool = True, subone: bool = False
    ) -> None:
        self.progress.display(drop, countdown=countdown, subone=subone)  # main tab
        self.update_hud_drop(drop)
        # inventory overview is updated from within drops themselves via change events
        self.tray.update_title(drop)  # tray

    def clear_drop(self):
        self.progress.display(None)
        self.update_hud_drop(None)
        self.tray.update_title(None)

    def print(self, message: str):
        # print to our custom output
        self.output.print(message)

    def _set_title_bar_color(self, color: int) -> None:
        """
        Set the Windows title bar color to match the theme.
        Only works on Windows with DWM enabled.

        Args:
            color: ARGB color value (e.g., 0x001E1E1E for dark gray).
        """
        if sys.platform != "win32":
            return
        # DWMWA_CAPTION_COLOR = 35
        DWMWA_CAPTION_COLOR = 35
        hwnd = self._root.winfo_id()
        frame_hwnd = ctypes.windll.user32.GetParent(hwnd)
        color_value = ctypes.c_int(color)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            frame_hwnd,
            DWMWA_CAPTION_COLOR,
            ctypes.byref(color_value),
            ctypes.sizeof(ctypes.c_int),
        )

    def apply_theme(self, dark: bool) -> None:
        """
        Apply dark/light palette to ttk styles and Tk widgets in a minimal, non-invasive way.
        """
        # Palette
        if dark:
            # Switch to a configurable ttk theme for better color control
            if sys.platform != "darwin" and self._style.theme_use() != "clam":
                self._style.theme_use("clam")
            bg = "#0d0e14"
            fg = "#f2eff9"
            sel_bg = "#573578"
            sel_fg = "#ffffff"
            link = "#d0a2ff"
            surface = "#171821"
            header = "#22212c"
            fieldbg = "#12131a"
            border = "#343240"
            muted = "#9b98a9"
            accent = "#b56dff"
            accent_hover = "#c68eff"
            card = "#1b1c25"
            sidebar = "#11121a"
            hero = "#261a33"
            hero_border = "#48305d"
            hero_muted = "#c1b4d0"
            mint = "#62e8cf"
            watching_bg = "#332341"
            watching_fg = "#f4ecff"
        else:
            # Restore original theme if we changed it
            if getattr(self, "_orig_theme_name", '') and self._style.theme_use() == "clam":
                self._style.theme_use(self._orig_theme_name)
            # Use platform defaults but ensure toggling back is readable
            bg = "#f6f3fa"
            fg = "#251d2e"
            sel_bg = "#e8dcf7"
            sel_fg = "#000000"
            link = "#6632a8"
            surface = "#ffffff"
            header = "#f0ebf6"
            fieldbg = "#ffffff"
            border = "#ddd5e8"
            muted = "#6d6577"
            accent = "#783fdb"
            accent_hover = "#6530bd"
            card = "#ffffff"
            sidebar = "#eee9f4"
            hero = "#eee6f7"
            hero_border = "#d6c4ea"
            hero_muted = "#6f5d82"
            mint = "#087f75"
            watching_bg = "#e8daf7"
            watching_fg = "#39215d"

        # Setting theme for macOS
        if sys.platform == "darwin":
            app = AppKit.NSApplication.sharedApplication()
            if dark:
                appearance = AppKit.NSAppearance.appearanceNamed_(AppKit.NSAppearanceNameDarkAqua)
            else:
                appearance = AppKit.NSAppearance.appearanceNamed_(AppKit.NSAppearanceNameAqua)
            app.setAppearance_(appearance)

        s = self._style
        # Fonts
        default_font = nametofont("TkDefaultFont")
        default_font.config(size=10)
        nametofont("TkTextFont").config(size=10)
        self._fonts["default"] = default_font
        # Font - button style with a larger font
        self._fonts["large"] = default_font.copy()
        self._fonts["large"].config(size=11)
        s.configure("Large.TButton", font=self._fonts["large"])
        self._fonts["value"] = default_font.copy()
        self._fonts["value"].config(size=11, weight="bold")
        self._fonts["section"] = default_font.copy()
        self._fonts["section"].config(size=11, weight="bold")
        self._fonts["tree_heading"] = default_font.copy()
        self._fonts["tree_heading"].config(size=10, weight="bold")
        self._fonts["brand"] = default_font.copy()
        self._fonts["brand"].config(size=16, weight="bold")
        self._fonts["brand_caption"] = default_font.copy()
        self._fonts["brand_caption"].config(size=9, weight="bold")
        self._fonts["tray"] = default_font.copy()
        self._fonts["tray"].config(size=9)
        self._fonts["overline"] = default_font.copy()
        self._fonts["overline"].config(size=9, weight="bold")
        self._fonts["hero_value"] = default_font.copy()
        self._fonts["hero_value"].config(size=13, weight="bold")
        self._fonts["hero_percent"] = default_font.copy()
        self._fonts["hero_percent"].config(size=24, weight="bold")
        self._fonts["hero_stat"] = default_font.copy()
        self._fonts["hero_stat"].config(size=12, weight="bold")
        # Font - button style for sorting arrows
        self._fonts["arrow"] = default_font.copy()
        self._fonts["arrow"].config(size=16)
        s.configure("Arrow.TButton", font=self._fonts["arrow"])
        s.configure("Arrow.TButton", padding=-4)  # reduce padding on arrow buttons
        # Font - label style that mimics links
        self._fonts["underlined"] = default_font.copy()
        self._fonts["underlined"].config(underline=True)
        s.configure("Link.TLabel", font=self._fonts["underlined"], foreground=link)
        # Font - label style with a monospace font
        self._fonts["monospaced"] = default_font.copy()
        self._fonts["monospaced"].config(family="Courier New", size=10)
        s.configure("MS.TLabel", font=self._fonts["monospaced"])

        # Base containers and labels
        s.configure("TFrame", background=bg)
        s.configure("AppShell.TFrame", background=bg)
        s.configure("Content.TFrame", background=bg)
        s.configure("Page.TFrame", background=bg)
        s.configure("Sidebar.TFrame", background=sidebar)
        s.configure(
            "Header.TFrame",
            background=card,
            relief="solid",
            borderwidth=1,
            bordercolor=border,
        )
        s.configure(
            "Topbar.TFrame",
            background=surface,
            relief="solid",
            borderwidth=1,
            bordercolor=border,
        )
        s.configure(
            "Hero.TFrame",
            background=hero,
            relief="solid",
            borderwidth=1,
            bordercolor=hero_border,
        )
        s.configure("Hero.TSeparator", background=hero, bordercolor=hero_border)
        s.configure(
            "Card.TFrame",
            background=card,
            relief="solid",
            borderwidth=1,
            bordercolor=border,
        )
        s.configure("TLabel", background=bg, foreground=fg)
        s.configure("Brand.TLabel", background=sidebar, foreground=fg, font=self._fonts["brand"])
        s.configure("BrandIcon.TLabel", background=sidebar)
        s.configure(
            "BrandCaption.TLabel",
            background=sidebar,
            foreground=muted,
            font=self._fonts["brand_caption"],
        )
        s.configure("SidebarFoot.TLabel", background=sidebar, foreground=muted, font=self._fonts["overline"])
        s.configure("Overline.TLabel", background=surface, foreground=muted, font=self._fonts["overline"])
        s.configure("LiveStatus.TLabel", background=surface, foreground=mint, font=self._fonts["value"])
        s.configure(
            "HUD.TFrame",
            background=border,
            relief="solid",
            borderwidth=1,
        )
        s.configure("HUDContent.TFrame", background=surface)
        s.configure("HUDHeader.TFrame", background=card)
        s.configure(
            "HUDTitle.TLabel",
            background=card,
            foreground=accent,
            font=self._fonts["brand_caption"],
        )
        s.configure(
            "HUDLive.TLabel",
            background=card,
            foreground=mint,
            font=self._fonts["overline"],
        )
        s.configure(
            "HUDIdle.TLabel",
            background=card,
            foreground=muted,
            font=self._fonts["overline"],
        )
        s.configure("HUDMuted.TLabel", background=surface, foreground=muted)
        s.configure(
            "HUDGame.TLabel",
            background=surface,
            foreground=fg,
            font=self._fonts["value"],
        )
        s.configure(
            "HUDReward.TLabel",
            background=surface,
            foreground=accent,
            font=self._fonts["hero_value"],
        )
        s.configure(
            "HUDPercent.TLabel",
            background=surface,
            foreground=mint,
            font=self._fonts["hero_stat"],
        )
        s.configure(
            "HUDTimer.TLabel",
            background=surface,
            foreground=fg,
            font=self._fonts["hero_value"],
        )
        s.configure(
            "HUDClose.TButton",
            background=card,
            foreground=muted,
            bordercolor=card,
            padding=(3, 0),
        )
        s.map("HUDClose.TButton", background=[("active", header)], foreground=[("active", fg)])
        s.configure("Status.TLabel", background=card, foreground=accent, font=self._fonts["value"])
        s.configure("Muted.TLabel", foreground=muted)
        s.configure("Value.TLabel", foreground=fg, font=self._fonts["value"])
        s.configure("Section.TLabel", foreground=accent, font=self._fonts["section"])
        s.configure("HistoryTitle.TLabel", background=surface, foreground=fg, font=self._fonts["brand"])
        s.configure("HeroOverline.TLabel", background=hero, foreground=mint, font=self._fonts["overline"])
        s.configure("HeroMuted.TLabel", background=hero, foreground=hero_muted)
        s.configure("HeroValue.TLabel", background=hero, foreground=fg, font=self._fonts["hero_value"])
        s.configure("HeroReward.TLabel", background=hero, foreground=fg, font=self._fonts["value"])
        s.configure("HeroPercent.TLabel", background=hero, foreground=mint, font=self._fonts["hero_percent"])
        s.configure("HeroStat.TLabel", background=surface, foreground=accent, font=self._fonts["hero_stat"])
        s.configure(
            "TLabelframe",
            background=surface,
            foreground=fg,
            bordercolor=border,
            relief="solid",
            borderwidth=1,
        )
        s.configure(
            "TLabelframe.Label",
            background=surface,
            foreground=muted,
            font=self._fonts["section"],
        )
        # Buttons and checks
        s.configure(
            "TButton", background=surface, foreground=fg, bordercolor=border, padding=(10, 7)
        )
        s.map(
            "TButton",
            background=[("active", header), ("pressed", border)],
            foreground=[("disabled", muted)],
        )
        s.configure(
            "Primary.TButton",
            background=accent,
            foreground="#ffffff",
            bordercolor=accent,
            padding=(12, 7),
        )
        s.map(
            "Primary.TButton",
            background=[("disabled", surface), ("pressed", accent_hover), ("active", accent_hover)],
            foreground=[("disabled", muted), ("!disabled", "#ffffff")],
        )
        s.configure(
            "Tray.TButton",
            background=sidebar,
            foreground=muted,
            padding=(10, 9),
            anchor="w",
            font=self._fonts["tray"],
        )
        s.map("Tray.TButton", background=[("active", header)], foreground=[("active", fg)])
        s.configure(
            "Nav.TButton",
            background=sidebar,
            foreground=muted,
            bordercolor=sidebar,
            padding=(12, 11),
            anchor="w",
        )
        s.map("Nav.TButton", background=[("active", header)], foreground=[("active", fg)])
        s.configure(
            "NavActive.TButton",
            background=hero,
            foreground=accent,
            bordercolor=hero,
            padding=(12, 11),
            anchor="w",
        )
        s.map("NavActive.TButton", background=[("active", hero)], foreground=[("active", accent)])
        s.configure(
            "TCheckbutton",
            background=bg,
            foreground=fg,
            focuscolor=bg,
            bordercolor=border,
        )
        s.map(
            "TCheckbutton",
            # Remove hover visuals by mapping active/pressed to the base background
            background=[
                ("active", bg),
                ("pressed", bg),
            ],
            foreground=[("disabled", muted)],
            indicatorcolor=[
                ("selected", accent if dark else fg),
                ("!selected", border),
            ],
        )
        # Notebook
        s.configure("TNotebook", background=bg, bordercolor=bg, tabmargins=(0, 0, 0, 0))
        s.configure(
            "TNotebook.Tab",
            background=surface,
            foreground=muted,
            bordercolor=border,
            padding=(14, 9),
        )
        s.map(
            "TNotebook.Tab",
            background=[("selected", bg), ("active", header)],
            foreground=[("selected", accent), ("active", fg), ("disabled", muted)],
        )
        # Entries/Combos
        s.configure(
            "TEntry", fieldbackground=fieldbg, background=fieldbg, foreground=fg, insertcolor=fg
        )
        s.configure(
            "TCombobox", fieldbackground=fieldbg, background=fieldbg, foreground=fg, arrowcolor=fg
        )
        # Ensure readability for readonly comboboxes (Language, Priority mode)
        s.map(
            "TCombobox",
            foreground=[("readonly", fg), ("disabled", muted)],
            fieldbackground=[("readonly", fieldbg)],
            background=[("readonly", fieldbg)],
            arrowcolor=[("readonly", fg)],
        )
        s.map("TEntry", foreground=[("disabled", muted)])
        # Treeview
        s.configure(
            "Treeview",
            background=surface,
            fieldbackground=surface,
            foreground=fg,
            bordercolor=border,
            rowheight=30,
        )
        s.map(
            "Treeview",
            background=[("selected", sel_bg)],
            foreground=[("selected", sel_fg)],
        )
        s.configure(
            "Treeview.Heading",
            background=header,
            foreground=fg,
            bordercolor=border,
            font=self._fonts["tree_heading"],
            padding=(8, 7),
        )
        # Progressbar
        s.configure("TProgressbar", background=accent, troughcolor=header, thickness=11)
        s.configure("Campaign.Horizontal.TProgressbar", background=accent, troughcolor=header, thickness=6)
        s.configure("Drop.Horizontal.TProgressbar", background=mint, troughcolor=header, thickness=13)
        s.configure(
            "HUD.Horizontal.TProgressbar",
            background=mint,
            troughcolor=header,
            bordercolor=header,
            thickness=8,
        )
        # Scrollbars
        s.configure(
            "Vertical.TScrollbar",
            background=surface,
            troughcolor=bg,
            arrowcolor=fg,
            bordercolor=border,
        )
        s.configure(
            "Horizontal.TScrollbar",
            background=surface,
            troughcolor=bg,
            arrowcolor=fg,
            bordercolor=border,
        )

        # Pure Tk widgets
        # Console text
        self.output.configure_theme(bg=surface, fg=fg, sel_bg=sel_bg, sel_fg=sel_fg)
        self.channels.configure_theme(watching_bg=watching_bg, watching_fg=watching_fg)
        # Listboxes
        self.settings._priority_list.configure_theme(
            bg=surface, fg=fg, sel_bg=sel_bg, sel_fg=sel_fg
        )
        self.settings._exclude_list.configure_theme(
            bg=surface, fg=fg, sel_bg=sel_bg, sel_fg=sel_fg
        )
        # Inventory canvas
        self.inv.configure_theme(bg=bg)

        # Tk option database for selection/popup list readability (affects Tk-backed widgets)
        # Global selection colors and listbox defaults (covers Combobox dropdown)
        self._root.option_add("*selectBackground", sel_bg)
        self._root.option_add("*selectForeground", sel_fg)
        # Combobox dropdown list (Tk Listbox)
        for key in (
            "*TCombobox*Listbox.background",
            "*TCombobox*Listbox.Background",
            "*Listbox.background",
        ):
            self._root.option_add(key, surface)
        for key in (
            "*TCombobox*Listbox.foreground",
            "*TCombobox*Listbox.Foreground",
            "*Listbox.foreground",
        ):
            self._root.option_add(key, fg)
        for key in (
            "*TCombobox*Listbox.selectBackground",
            "*Listbox.selectBackground",
        ):
            self._root.option_add(key, sel_bg)
        for key in (
            "*TCombobox*Listbox.selectForeground",
            "*Listbox.selectForeground",
        ):
            self._root.option_add(key, sel_fg)

        # Set Windows title bar color to match dark theme
        if dark:
            # Use the application background color in ARGB format.
            self._set_title_bar_color(0x000D0E14)
        else:
            # Reset to system default title bar color
            self._set_title_bar_color(0xFFFFFFFF)
        if self._hud_window is not None:
            self._hud_window.refresh_theme()


###################
# GUI MANAGER END #
###################


if __name__ == "__main__":
    # Everything below is for debug purposes only
    import aiohttp
    from types import SimpleNamespace

    class StrNamespace(SimpleNamespace):
        __hash__ = object.__hash__  # type: ignore

        def __str__(self):
            if hasattr(self, "_str__"):
                return self._str__(self)
            return super().__str__()

    class HashNamespace(SimpleNamespace):
        __hash__ = object.__hash__  # type: ignore

    def create_game(id: int, name: str):
        return StrNamespace(name=name, id=id, _str__=lambda s: s.name)

    iid = 0

    def create_channel(
        name: str,
        status: int,
        game: str | None,
        drops: bool,
        viewers: int,
        acl_based: bool,
    ):
        # status: 0 -> OFFLINE, 1 -> PENDING_ONLINE, 2 -> ONLINE
        if status == 1:
            status = False
            pending = True
        else:
            pending = False
        if game is not None:
            game_obj: StrNamespace | None = create_game(0, game)
        else:
            game_obj = None
        global iid
        return SimpleNamespace(
            name=name,
            iid=(iid := iid + 1),
            online=bool(status),
            pending_online=pending,
            game=game_obj,
            drops_enabled=drops,
            viewers=viewers,
            acl_based=acl_based,
        )

    def create_drop(
        campaign_name: str,
        game_name: str,
        rewards: list[str],
        claimed_drops: int,
        total_drops: int,
        current_minutes: int,
        total_minutes: int,
    ):
        cd = claimed_drops
        td = total_drops
        cm = current_minutes
        tm = total_minutes
        ref_stamp = datetime.now(timezone.utc)
        drop_image_url = (
            "https://static-cdn.jtvnw.net/twitch-quests-assets/"
            "REWARD/e0ede26e-b071-47f0-af5f-b80b26fa9fb4.png"
        )
        campaign_image_url = "https://static-cdn.jtvnw.net/ttv-boxart/515025-120x160.jpg"
        benefits = [SimpleNamespace(name=name, image_url=drop_image_url) for name in rewards]
        mock = SimpleNamespace(
            id="0",
            campaign=HashNamespace(
                name=campaign_name,
                id="campaign",
                game=create_game(0, game_name),
                expired=False,
                active=False,
                upcoming=True,
                eligible=False,
                finished=False,
                link_url="https://google.com",
                image_url=campaign_image_url,
                allowed_channels=[],
                starts_at=ref_stamp,
                ends_at=ref_stamp + timedelta(days=7),
                timed_drops={},
                claimed_drops=cd,
                total_drops=td,
                required_minutes=tm,
                remaining_drops=td - cd,
                progress=(cd * tm + cm) / (td * tm),
                remaining_minutes=(td - cd) * tm - cm,
            ),
            image_url=drop_image_url,
            can_claim=False,
            can_earn=lambda: False,
            is_claimed=False,
            preconditions=True,
            benefits=benefits,
            rewards_text=lambda: ', '.join(b.name for b in benefits),
            starts_at=ref_stamp + timedelta(seconds=2),
            ends_at=ref_stamp + timedelta(days=7) - timedelta(seconds=2),
            progress=cm/tm,
            current_minutes=cm,
            required_minutes=tm,
            remaining_minutes=tm-cm,
        )
        mock.campaign.timed_drops["0"] = mock
        mock.campaign.drops = mock.campaign.timed_drops.values()
        return mock

    async def main(exit_event: asyncio.Event):
        # Initialize GUI debug
        mock = SimpleNamespace(
            settings=SimpleNamespace(
                tray=False,
                priority=[],
                proxy=URL(),
                dark_mode=False,
                alter=lambda: None,
                language="English",
                autostart_tray=False,
                exclude={"Lit Game"},
                tray_notifications=True,
                enable_badges_emotes=False,
                available_drops_check=False,
                logging_level=LOGGING_LEVELS[0],
                priority_mode=PriorityMode.PRIORITY_ONLY,
            )
        )
        mock.change_state = lambda state: mock.gui.print(f"State change: {state.value}")
        mock.state_change = lambda state: partial(mock.change_state, state)
        mock.request = aiohttp.request
        # _.set_language("Русский")
        gui = GUIManager(mock)  # type: ignore
        mock.gui = gui
        mock.close = gui.stop
        gui.start()
        assert gui._poll_task is not None
        gui._poll_task.add_done_callback(lambda t: exit_event.set())
        # Login form
        gui.login.update("Login required", None)
        # Game selector and settings panel games
        gui.set_games(set([
            create_game(420690, "Lit Game"),
            create_game(123456, "Best Game"),
            create_game(654321, "My Game Very Long Name"),
        ]))
        # Channel list
        gui.channels.display(
            create_channel(
                name="Thomus",
                status=0,
                game=None,
                drops=False,
                viewers=0,
                acl_based=True,
            ),
            add=True,
        )
        channel = create_channel(
            name="Traitus", status=1, game=None, drops=False, viewers=0, acl_based=True
        )
        gui.channels.display(channel, add=True)
        gui.channels.set_watching(channel)
        gui.channels.display(
            create_channel(
                name="Testus",
                status=2,
                game="Best Game",
                drops=True,
                viewers=42,
                acl_based=False,
            ),
            add=True,
        )
        gui.channels.display(
            create_channel(
                name="Livus",
                status=2,
                game="Best Game",
                drops=True,
                viewers=69,
                acl_based=False,
            ),
            add=True,
        )
        gui._root.update()
        gui.channels.get_selection()
        # Inventory overview
        drop = create_drop(
            "Wardrobe Cleaning", "Cleaning Masters", ["Fancy Pants"], 2, 7, 0, 240
        )
        campaign = drop.campaign
        await gui.inv.add_campaign(campaign)

        gui.print("Single-line test message")
        await asyncio.sleep(1)
        gui.print("Multi-line\ntest\nmessage")

        # Tray
        # gui.tray.minimize()
        await asyncio.sleep(2)
        claim_text = (
            f"{campaign.game.name}\n"
            f"{drop.rewards_text()} ({campaign.claimed_drops}/{campaign.total_drops})"
        )
        gui.tray.notify(claim_text, "Mined Drop")

        # Drop progress
        gui.display_drop(drop, countdown=False)
        await asyncio.sleep(3)

        gui.progress.start_timer()
        await asyncio.sleep(5)

        gui.clear_drop()
        await asyncio.sleep(5)

        campaign.can_earn = lambda: True
        gui.inv.update_drop(drop)
        gui.display_drop(drop)
        await asyncio.sleep(10)

        drop.current_minutes = 239
        drop.remaining_minutes = 1
        drop.progress = 239/240
        campaign.remaining_minutes -= 1
        gui.inv.update_drop(drop)
        gui.display_drop(drop)
        await asyncio.sleep(63)

        drop.current_minutes = 240
        drop.remaining_minutes = 0
        drop.progress = 1.0
        campaign.remaining_minutes -= 1
        campaign.progress = 3/7
        campaign.claimed_drops = 3
        campaign.remaining_drops = 4
        gui.inv.update_drop(drop)
        gui.display_drop(drop)

    def main_exit(task: asyncio.Task[None]) -> None:
        if task.exception() is not None:
            exit_event.set()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    exit_event = asyncio.Event()
    main_task = loop.create_task(main(exit_event))
    main_task.add_done_callback(main_exit)
    loop.run_until_complete(exit_event.wait())
    if main_task.done():
        loop.run_until_complete(main_task)
