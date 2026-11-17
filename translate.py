from __future__ import annotations

from collections import abc
from typing import Any, TypedDict, TYPE_CHECKING

from exceptions import MinerException
from utils import json_load, json_save
from constants import IS_PACKAGED, LANG_PATH, DEFAULT_LANG

if TYPE_CHECKING:
    from typing_extensions import NotRequired


class StatusMessages(TypedDict):
    terminated: str
    watching: str
    goes_online: str
    goes_offline: str
    claimed_drop: str
    no_channel: str
    no_campaign: str


class BrowserMessages(TypedDict):
    startup: str
    login_to_complete: str
    no_token: str
    closed_window: str
    not_found: str


class LoginMessages(TypedDict):
    browser: BrowserMessages
    error_code: str
    unexpected_content: str
    email_code_required: str
    twofa_code_required: str
    incorrect_login_pass: str
    incorrect_email_code: str
    incorrect_twofa_code: str


class ErrorMessages(TypedDict):
    captcha: str
    no_connection: str
    site_down: str


class GUIStatus(TypedDict):
    name: str
    diagnostics: str
    idle: str
    exiting: str
    terminated: str
    cleanup: str
    gathering: str
    switching: str
    fetching_inventory: str
    fetching_campaigns: str
    adding_campaigns: str


class GUIHUD(TypedDict):
    button: str
    title: str
    waiting: str
    no_drop: str
    game: str
    open: str


class GUIHistory(TypedDict):
    title: str
    subtitle: str
    total: str
    today: str
    session: str
    search: str
    period: str
    period_all: str
    period_today: str
    period_week: str
    period_session: str
    export: str
    column_time: str
    column_game: str
    column_campaign: str
    column_reward: str
    empty: str
    no_match: str
    count: str
    export_title: str
    export_filename: str
    export_error: str
    exported: str


class GUITabs(TypedDict):
    main: str
    inventory: str
    settings: str
    help: str
    history: str


class GUITray(TypedDict):
    notification_title: str
    minimize: str
    show: str
    hud: str
    quit: str


class GUILoginForm(TypedDict):
    name: str
    labels: str
    logging_in: str
    logged_in: str
    logged_out: str
    request: str
    required: str
    username: str
    password: str
    twofa_code: str
    button: str


class GUIWebsocket(TypedDict):
    name: str
    websocket: str
    initializing: str
    connected: str
    disconnected: str
    connecting: str
    disconnecting: str
    reconnecting: str


class GUIProgress(TypedDict):
    name: str
    drop: str
    game: str
    campaign: str
    remaining: str
    drop_progress: str
    campaign_progress: str


class GUIChannelHeadings(TypedDict):
    channel: str
    status: str
    game: str
    viewers: str


class GUIChannels(TypedDict):
    name: str
    switch: str
    online: str
    pending: str
    offline: str
    headings: GUIChannelHeadings


class GUIInvFilter(TypedDict):
    name: str
    show: str
    not_linked: str
    upcoming: str
    expired: str
    excluded: str
    finished: str
    refresh: str


class GUIInvStatus(TypedDict):
    linked: str
    not_linked: str
    active: str
    expired: str
    upcoming: str
    claimed: str
    ready_to_claim: str


class GUIInvRadar(TypedDict):
    title: str
    summary: str
    session: str
    duration_30: str
    duration_60: str
    duration_90: str
    duration_120: str
    duration_180: str
    duration_240: str
    empty: str
    deadline: str
    starts: str
    effort: str
    session_fits: str
    session_shortfall: str
    risk: str
    tight: str
    safe: str
    prioritize: str
    prioritized: str
    focus: str


class GUIInvAgenda(TypedDict):
    button: str
    title: str
    intro: str
    period: str
    period_today: str
    period_7: str
    period_30: str
    event_all: str
    event_starts: str
    event_ends: str
    column_time: str
    column_event: str
    column_game: str
    column_campaign: str
    column_reward: str
    all_rewards: str
    count: str
    empty: str
    view: str
    close: str
    export: str
    export_title: str
    export_filename: str
    exported: str
    export_failed: str


class GUIInventory(TypedDict):
    filter: GUIInvFilter
    status: GUIInvStatus
    radar: GUIInvRadar
    agenda: GUIInvAgenda
    search: str
    visible_count: str
    priority_add: str
    priority_added: str
    priority_excluded: str
    starts: str
    ends: str
    allowed_channels: str
    all_channels: str
    and_more: str
    percent_progress: str
    minutes_progress: str


class GUIDiagnosticReasons(TypedDict):
    upcoming: str
    expired: str
    finished: str
    not_linked: str
    badges_disabled: str
    excluded: str
    priority: str
    drop_expired: str
    drop_starts_later: str
    waiting_for_previous: str
    progress_sync: str
    drop_not_ready: str


class GUIDiagnosticTips(TypedDict):
    upcoming: str
    expired: str
    finished: str
    not_linked: str
    badges_disabled: str
    excluded: str
    priority: str
    drop_expired: str
    drop_starts_later: str
    waiting_for_previous: str
    progress_sync: str
    drop_not_ready: str


class GUIDiagnostics(TypedDict):
    title: str
    intro: str
    summary: str
    campaign_one: str
    campaign_many: str
    empty: str
    empty_tip: str
    ready: str
    count_reason: str
    games: str
    action: str
    settings: str
    refresh: str
    open_campaigns: str
    close: str
    reasons: GUIDiagnosticReasons
    tips: GUIDiagnosticTips


class GUISettingsGeneral(TypedDict):
    name: str
    autostart: str
    tray: str
    tray_notifications: str
    dark_mode: str
    priority_mode: str
    proxy: str


class GUISettingsAdvanced(TypedDict):
    name: str
    warning: str
    warning_text: str
    enable_badges_emotes: str
    available_drops_check: str


class GUIPriorityModes(TypedDict):
    priority_only: str
    ending_soonest: str
    low_availability: str


class GUISettingsProfiles(TypedDict):
    title: str
    description: str
    name: str
    save: str
    apply: str
    delete: str
    name_required: str
    select: str
    saved: str
    applied: str
    already_active: str
    deleted: str
    limit: str
    save_error: str


class GUISettings(TypedDict):
    general: GUISettingsGeneral
    advanced: GUISettingsAdvanced
    priority_modes: GUIPriorityModes
    profiles: GUISettingsProfiles
    game_name: str
    priority: str
    exclude: str
    reload: str
    reload_text: str


class GUIHelpLinks(TypedDict):
    name: str
    inventory: str
    campaigns: str


class GUIHelpInvalidate(TypedDict):
    button: str
    text: str


class GUIHelp(TypedDict):
    links: GUIHelpLinks
    shortcuts: str
    how_it_works: str
    how_it_works_text: str
    getting_started: str
    getting_started_text: str
    invalidate: GUIHelpInvalidate


class GUIMessages(TypedDict):
    output: str
    status: GUIStatus
    hud: GUIHUD
    history: GUIHistory
    diagnostics: GUIDiagnostics
    tabs: GUITabs
    tray: GUITray
    login: GUILoginForm
    websocket: GUIWebsocket
    progress: GUIProgress
    channels: GUIChannels
    inventory: GUIInventory
    settings: GUISettings
    help: GUIHelp


class Translation(TypedDict):
    language_name: NotRequired[str]
    english_name: str
    status: StatusMessages
    login: LoginMessages
    error: ErrorMessages
    gui: GUIMessages


default_translation: Translation = {
    "english_name": "English",
    "status": {
        "terminated": "\nApplication Terminated.\nClose the window to exit the application.",
        "watching": "Watching: {channel}",
        "goes_online": "{channel} goes ONLINE, switching...",
        "goes_offline": "{channel} goes OFFLINE, switching...",
        "claimed_drop": "Claimed drop: {drop}",
        "no_channel": "No available channels to watch. Waiting for an ONLINE channel...",
        "no_campaign": "No active campaigns to mine drops for. Waiting for an active campaign...",
    },
    "login": {
        "unexpected_content": (
            "Unexpected content type returned, usually due to being redirected. "
            "Do you need to login for internet access?"
        ),
        "browser": {
            "startup": "Opening the browser...",
            "login_to_complete": (
                "Complete the login procedure manually by pressing the Login button again."
            ),
            "no_token": "No authorization token could be found.",
            "closed_window": (
                "The browser window was closed before the login procedure could be completed."
            ),
            "not_found": (
                "No compatible browser could be found. "
                "Please install a compatible browser (Chrome, Edge, or Brave) and try again."
            ),
        },
        "error_code": "Login error code: {error_code}",
        "incorrect_login_pass": "Incorrect username or password.",
        "incorrect_email_code": "Incorrect email code.",
        "incorrect_twofa_code": "Incorrect 2FA code.",
        "email_code_required": "Email code required. Check your email.",
        "twofa_code_required": "2FA token required.",
    },
    "error": {
        "captcha": "Your login attempt was denied by CAPTCHA.\nPlease try again in 12+ hours.",
        "site_down": "Twitch is down, retrying in {seconds} seconds...",
        "no_connection": "Cannot connect to Twitch, retrying in {seconds} seconds... ({url})",
    },
    "gui": {
        "output": "Output",
        "status": {
            "name": "Status",
            "diagnostics": "Diagnóstico",
            "idle": "Idle",
            "exiting": "Exiting...",
            "terminated": "Terminated",
            "cleanup": "Cleaning up channels...",
            "gathering": "Gathering channels...",
            "switching": "Switching the channel...",
            "fetching_inventory": "Fetching inventory...",
            "fetching_campaigns": "Fetching campaigns...",
            "adding_campaigns": "Adding campaigns to inventory... {counter}",
        },
        "hud": {
            "button": "Mini HUD",
            "title": "DROPFORGE · LIVE HUD",
            "waiting": "WAITING",
            "no_drop": "Waiting for a drop",
            "game": "NOW MINING",
            "open": "Open DropForge",
        },
        "history": {
            "title": "Achievement Journal",
            "subtitle": "A private, local record of rewards confirmed by Twitch.",
            "total": "ALL TIME",
            "today": "TODAY",
            "session": "THIS SESSION",
            "search": "Search claims",
            "period": "Period",
            "period_all": "All dates",
            "period_today": "Today",
            "period_week": "Last 7 days",
            "period_session": "This session",
            "export": "Export all (CSV)",
            "column_time": "Claimed",
            "column_game": "Game",
            "column_campaign": "Campaign",
            "column_reward": "Reward",
            "empty": "No claims yet. Confirmed rewards will appear here.",
            "no_match": "No claims match these filters.",
            "count": "{count} rewards in this view",
            "export_title": "Export claim history",
            "export_filename": "DropForge claim history.csv",
            "export_error": "Could not export the claim history.",
            "exported": "Exported {count} claims to CSV.",
        },
        "diagnostics": {
            "title": "Campaign diagnostics",
            "intro": "This report explains how the loaded campaigns match your current settings.",
            "summary": "{campaigns} checked · {ready} ready to mine",
            "campaign_one": "{count} campaign",
            "campaign_many": "{count} campaigns",
            "empty": "No campaigns were loaded from Twitch.",
            "empty_tip": "Check your login and account links, then open the Twitch campaigns page.",
            "ready": "{count} campaign(s) match the filters. The miner is looking for compatible channels.",
            "count_reason": "{count} · {reason}",
            "games": "Games: {games}",
            "action": "Action: {tip}",
            "settings": "Settings",
            "refresh": "Reload campaigns",
            "open_campaigns": "Twitch campaigns",
            "close": "Close",
            "reasons": {
                "upcoming": "Campaign has not started",
                "expired": "Campaign has ended",
                "finished": "Drops are already claimed or require no watch time",
                "not_linked": "Game account is not linked to this campaign",
                "badges_disabled": "Badge and emote support is turned off",
                "excluded": "Game is in the Exclude list",
                "priority": "Game is outside the Priority list",
                "drop_expired": "All timed drops in this campaign have ended",
                "drop_starts_later": "The next timed drop starts later",
                "waiting_for_previous": "Waiting for a previous drop in the campaign",
                "progress_sync": "Drop progress needs to be synchronized",
                "drop_not_ready": "No timed drop is ready to mine right now",
            },
            "tips": {
                "upcoming": "Wait until the start time shown in Inventory.",
                "expired": "This campaign can no longer be mined.",
                "finished": "No action is needed for completed rewards.",
                "not_linked": "Open the campaign in Twitch and link the game's account.",
                "badges_disabled": "Enable partial badge and emote support in Advanced settings.",
                "excluded": "Remove the game from Exclude, then reload campaigns.",
                "priority": "Add the game to Priority, or choose a different priority mode, then reload.",
                "drop_expired": "The campaign may still be listed, but its timed drops have ended.",
                "drop_starts_later": "Wait for the drop start time, then reload campaigns if needed.",
                "waiting_for_previous": "Complete or claim the prerequisite drop first.",
                "progress_sync": "Reload campaigns to refresh Twitch progress.",
                "drop_not_ready": "Check the drop schedule and reload campaigns.",
            },
        },
        "tabs": {
            "main": "Main",
            "inventory": "Inventory",
            "settings": "Settings",
            "help": "Help",
            "history": "Journal",
        },
        "tray": {
            "notification_title": "Mined Drop",
            "minimize": "Minimize to Tray",
            "show": "Show",
            "hud": "Open Mini HUD",
            "quit": "Quit",
        },
        "login": {
            "name": "Login Form",
            "labels": "Status:\nUser ID:",
            "logged_in": "Logged in",
            "logged_out": "Logged out",
            "logging_in": "Logging in...",
            "required": "Login required",
            "request": "Please log in to continue.",
            "username": "Username",
            "password": "Password",
            "twofa_code": "2FA code (optional)",
            "button": "Login",
        },
        "websocket": {
            "name": "Websocket Status",
            "websocket": "Websocket #{id}:",
            "initializing": "Initializing...",
            "connected": "Connected",
            "disconnected": "Disconnected",
            "connecting": "Connecting...",
            "disconnecting": "Disconnecting...",
            "reconnecting": "Reconnecting...",
        },
        "progress": {
            "name": "Campaign Progress",
            "drop": "Drop:",
            "game": "Game:",
            "campaign": "Campaign:",
            "remaining": "{time} remaining",
            "drop_progress": "Progress:",
            "campaign_progress": "Progress:",
        },
        "channels": {
            "name": "Channels",
            "switch": "Switch",
            "online": "ONLINE  ✔",
            "pending": "OFFLINE ⏳",
            "offline": "OFFLINE ❌",
            "headings": {
                "channel": "Channel",
                "status": "Status",
                "game": "Game",
                "viewers": "Viewers",
            },
        },
        "inventory": {
            "filter": {
                "name": "Filter",
                "show": "Show:",
                "not_linked": "Not linked",
                "upcoming": "Upcoming",
                "expired": "Expired",
                "excluded": "Excluded",
                "finished": "Finished",
                "refresh": "Refresh",
            },
            "status": {
                "linked": "Linked ✔",
                "not_linked": "Not Linked ❌",
                "active": "Active ✔",
                "upcoming": "Upcoming ⏳",
                "expired": "Expired ❌",
                "claimed": "Claimed ✔",
                "ready_to_claim": "Ready to claim ⏳",
            },
            "radar": {
                "title": "Deadline Radar",
                "summary": "Top {shown} of {total} · planned for a {session} session",
                "session": "My session:",
                "duration_30": "30 min",
                "duration_60": "1 hour",
                "duration_90": "1h 30m",
                "duration_120": "2 hours",
                "duration_180": "3 hours",
                "duration_240": "4 hours",
                "empty": "No eligible drops have an active deadline right now.",
                "deadline": "Deadline in {time}",
                "starts": "Earning starts in {time}",
                "effort": "Estimated watch time: {time}",
                "session_fits": "Fits {session} · {time} spare",
                "session_shortfall": "Needs {time} beyond your session/window",
                "risk": "At risk · margin {ratio}×",
                "tight": "Tight margin · {ratio}×",
                "safe": "Room to spare · {ratio}×",
                "prioritize": "Prioritize",
                "prioritized": "Prioritized",
                "focus": "View",
            },
            "agenda": {
                "button": "Agenda",
                "title": "Campaign agenda",
                "intro": (
                    "Times are local. The agenda includes loaded campaigns "
                    "outside your priority list."
                ),
                "period": "Period",
                "period_today": "Next 24 hours",
                "period_7": "Next 7 days",
                "period_30": "Next 30 days",
                "event_all": "All events",
                "event_starts": "Starts",
                "event_ends": "Ends",
                "column_time": "Local date and time",
                "column_event": "Event",
                "column_game": "Game",
                "column_campaign": "Campaign",
                "column_reward": "Reward",
                "all_rewards": "Entire campaign",
                "count": "Results ({count})",
                "empty": "No events found for these filters.",
                "view": "View in Inventory",
                "close": "Close",
                "export": "Export calendar",
                "export_title": "Export campaign calendar",
                "export_filename": "DropForge agenda.ics",
                "exported": "Calendar saved ({count} events).",
                "export_failed": "Could not save the calendar file.",
            },
            "search": "Search",
            "visible_count": "{visible} of {total}",
            "priority_add": "☆ Prioritize game",
            "priority_added": "★ Prioritized",
            "priority_excluded": "In Exclude list",
            "starts": "Starts: {time}",
            "ends": "Ends: {time}",
            "allowed_channels": "Allowed Channels:",
            "all_channels": "All",
            "and_more": "and {amount} more...",
            "percent_progress": "{percent} of {minutes} minutes",
            "minutes_progress": "{minutes} minutes",
        },
        "settings": {
            "general": {
                "name": "General",
                "autostart": "Autostart: ",
                "tray": "Autostart into tray: ",
                "tray_notifications": "Tray notifications: ",
                "dark_mode": "Dark mode: ",
                "priority_mode": "Priority mode: ",
                "proxy": "Proxy (requires restart):",
            },
            "advanced": {
                "name": "Advanced",
                "warning": "Warning!",
                "warning_text": (
                    "These options will cause the miner to misbehave.\n"
                    "If you're experiencing any issues, "
                    "make sure all of these options are disabled."
                ),
                "enable_badges_emotes": "Enable partial support for badges and emotes: ",
                "available_drops_check": "Enable extra available drops check: ",
            },
            "priority_modes": {
                "priority_only": "Priority list only",
                "ending_soonest": "Ending soonest",
                "low_availability": "Low availability first",
            },
            "profiles": {
                "title": "Game profiles",
                "description": "Save Priority order and Exclude list together:",
                "name": "Profile:",
                "save": "Save current",
                "apply": "Apply",
                "delete": "Delete",
                "name_required": "Enter a profile name, then save the current lists.",
                "select": "Choose a saved profile first.",
                "saved": "Profile “{name}” saved.",
                "applied": "Profile “{name}” applied and campaigns reloaded.",
                "already_active": "Profile “{name}” is already active.",
                "deleted": "Profile “{name}” deleted.",
                "limit": "You can save up to {limit} profiles.",
                "save_error": "Could not save this profile.",
            },
            "game_name": "Game name",
            "priority": "Priority",
            "exclude": "Exclude",
            "reload": "Reload",
            "reload_text": "Most changes require a reload to take an immediate effect: ",
        },
        "help": {
            "links": {
                "name": "Useful Links",
                "inventory": "See Twitch inventory",
                "campaigns": "See all campaigns and manage account links",
            },
            "shortcuts": "{modifier}+1–5 switches tabs. {modifier}+F opens Inventory or Journal search.",
            "how_it_works": "How It Works",
            "how_it_works_text": (
                "Every several seconds, the application pretends to watch a particular stream "
                "by fetching stream metadata - this is enough to advance the drops. "
                "Note that this completely bypasses the need to download "
                "any actual stream of video and sound. "
                "To keep the status (ONLINE or OFFLINE) of the channels up-to-date, "
                "there's a websocket connection established that receives events about streams "
                "going up or down, or updates regarding the current number of viewers."
            ),
            "getting_started": "Getting Started",
            "getting_started_text": (
                "1. Login to the application.\n"
                "2. Ensure your Twitch account is linked to all campaigns "
                "you're interested in mining.\n"
                "3. If you're interested in mining everything possible, "
                "change the Priority Mode to anything other than \"Priority list only\" "
                "and press on \"Reload\".\n"
                "4. If you want to mine specific games first, use the \"Priority\" list "
                "to set up an ordered list of games of your choice. "
                "Games from the top of the list will be attempted to be mined first, "
                "before the ones lower down the list.\n"
                "5. Keep the \"Priority mode\" selected as \"Priority list only\", "
                "to avoid mining games that are not on the priority list. "
                "Or not - it's up to you.\n"
                "6. Use the \"Exclude\" list to tell the application "
                "which games should never be mined.\n"
                "7. Changing the contents of either of the lists, or changing "
                "the \"Priority mode\", requires you to press on \"Reload\" "
                "for the changes to take an effect."
            ),
            "invalidate": {
                "button": "Invalidate",
                "text": "Invalidate the authentication token (log out):",
            },
        },
    },
}


class Translator:
    def __init__(self) -> None:
        self._langs: list[str] = []
        # start with (and always copy) the default translation
        self._translation: Translation = default_translation.copy()
        # if we're in dev, update the template English.json file
        if not IS_PACKAGED:
            default_langpath = LANG_PATH.joinpath(f"{DEFAULT_LANG}.json")
            json_save(default_langpath, default_translation)
        self._translation["language_name"] = DEFAULT_LANG
        # load available translation names
        for filepath in LANG_PATH.glob("*.json"):
            self._langs.append(filepath.stem)
        self._langs.sort()
        if DEFAULT_LANG in self._langs:
            self._langs.remove(DEFAULT_LANG)
        self._langs.insert(0, DEFAULT_LANG)

    @property
    def languages(self) -> abc.Iterable[str]:
        return iter(self._langs)

    @property
    def current(self) -> str:
        return self._translation["language_name"]

    def set_language(self, language: str):
        if language not in self._langs:
            raise ValueError("Unrecognized language")
        elif self._translation["language_name"] == language:
            # same language as loaded selected
            return
        elif language == DEFAULT_LANG:
            # default language selected - use the memory value
            self._translation = default_translation.copy()
        else:
            self._translation = json_load(
                LANG_PATH.joinpath(f"{language}.json"), default_translation
            )
            if "language_name" in self._translation:
                raise ValueError("Translations cannot define 'language_name'")
        self._translation["language_name"] = language

    def __call__(self, *path: str) -> str:
        if not path:
            raise ValueError("Language path expected")
        v: Any = self._translation
        try:
            for key in path:
                v = v[key]
        except KeyError:
            # this can only really happen for the default translation
            raise MinerException(
                f"{self.current} translation is missing the '{' -> '.join(path)}' translation key"
            )
        return v


_ = Translator()
