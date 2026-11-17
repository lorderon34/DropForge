"""Save and restore local game-priority presets."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from constants import GAME_PROFILES_PATH
from utils import json_save


logger = logging.getLogger("TwitchDrops")
MAX_PROFILES = 20
MAX_PROFILE_NAME_LENGTH = 60


@dataclass(frozen=True)
class GameProfile:
    name: str
    priority: tuple[str, ...]
    excluded: tuple[str, ...]

    @classmethod
    def from_data(cls, data: Any) -> GameProfile | None:
        if not isinstance(data, dict):
            return None
        name = data.get("name")
        priority = data.get("priority")
        excluded = data.get("excluded")
        if not isinstance(name, str) or not isinstance(priority, list) or not isinstance(excluded, list):
            return None
        name = name.strip()
        if not name or len(name) > MAX_PROFILE_NAME_LENGTH:
            return None
        if not all(isinstance(item, str) for item in (*priority, *excluded)):
            return None
        priority_names = _clean_names(priority)
        excluded_names = tuple(sorted(_clean_names(excluded), key=str.casefold))
        excluded_keys = {item.casefold() for item in excluded_names}
        priority_names = tuple(item for item in priority_names if item.casefold() not in excluded_keys)
        return cls(name=name, priority=priority_names, excluded=excluded_names)


def _clean_names(values: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        name = value.strip()
        key = name.casefold()
        if name and key not in seen:
            result.append(name)
            seen.add(key)
    return tuple(result)


class ProfileLimitError(ValueError):
    """Raised when a new profile would exceed the local profile limit."""


class GameProfilesStore:
    MAX_PROFILES = MAX_PROFILES

    def __init__(self, path: Path = GAME_PROFILES_PATH):
        self._path = path
        self._profiles = self._load()

    @property
    def profiles(self) -> tuple[GameProfile, ...]:
        return tuple(self._profiles)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(profile.name for profile in self._profiles)

    def get(self, name: str) -> GameProfile | None:
        key = name.strip().casefold()
        return next((profile for profile in self._profiles if profile.name.casefold() == key), None)

    def _load(self) -> list[GameProfile]:
        candidates = (self._path.with_name(f"{self._path.name}.new"), self._path)
        for candidate in candidates:
            if not candidate.exists():
                continue
            try:
                with candidate.open("r", encoding="utf8") as file:
                    data = json.load(file)
                raw_profiles = data.get("profiles", []) if isinstance(data, dict) else []
                if not isinstance(raw_profiles, list):
                    raise TypeError("Game profiles must be a list")
            except (OSError, json.JSONDecodeError, TypeError, AttributeError):
                logger.warning("Unable to read game profiles from %s", candidate, exc_info=True)
                continue
            profiles: list[GameProfile] = []
            seen: set[str] = set()
            for item in raw_profiles:
                profile = GameProfile.from_data(item)
                if profile is None or profile.name.casefold() in seen:
                    continue
                profiles.append(profile)
                seen.add(profile.name.casefold())
            return profiles[-self.MAX_PROFILES:]
        return []

    def _save(self) -> None:
        json_save(
            self._path,
            {
                "version": 1,
                "profiles": [
                    {
                        "name": profile.name,
                        "priority": list(profile.priority),
                        "excluded": list(profile.excluded),
                    }
                    for profile in self._profiles
                ],
            },
        )

    def save_profile(
        self,
        name: str,
        priority: Iterable[str],
        excluded: Iterable[str],
    ) -> GameProfile:
        name = name.strip()
        if not name or len(name) > MAX_PROFILE_NAME_LENGTH or any(char in name for char in "\r\n"):
            raise ValueError("Profile name must contain 1 to 60 characters on one line")
        priority_names = _clean_names(priority)
        excluded_names = tuple(sorted(_clean_names(excluded), key=str.casefold))
        excluded_keys = {item.casefold() for item in excluded_names}
        priority_names = tuple(item for item in priority_names if item.casefold() not in excluded_keys)
        profile = GameProfile(name, priority_names, excluded_names)

        existing = self.get(name)
        if existing is None and len(self._profiles) >= self.MAX_PROFILES:
            raise ProfileLimitError(f"Only {self.MAX_PROFILES} profiles can be saved")
        if existing is None:
            self._profiles.append(profile)
        else:
            index = self._profiles.index(existing)
            profile = GameProfile(existing.name, priority_names, excluded_names)
            self._profiles[index] = profile
        self._save()
        return profile

    def delete_profile(self, name: str) -> bool:
        profile = self.get(name)
        if profile is None:
            return False
        self._profiles.remove(profile)
        self._save()
        return True


def apply_game_profile(settings: Any, profile: GameProfile) -> bool:
    """Apply a preset to settings; return whether the active lists changed."""
    priority = list(profile.priority)
    excluded = set(profile.excluded)
    if list(settings.priority) == priority and set(settings.exclude) == excluded:
        return False
    settings.priority = priority
    settings.exclude = excluded
    settings.alter()
    return True
