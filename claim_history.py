"""Small local journal of successfully claimed Twitch drops."""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from constants import DROP_HISTORY_PATH
from utils import json_save


logger = logging.getLogger("TwitchDrops")


@dataclass(frozen=True)
class ClaimRecord:
    record_id: str
    claimed_at: datetime
    game: str
    campaign: str
    reward: str

    @classmethod
    def from_data(cls, data: Any) -> ClaimRecord | None:
        if not isinstance(data, dict):
            return None
        try:
            claimed_at = datetime.fromisoformat(str(data["claimed_at"]))
            if claimed_at.tzinfo is None:
                claimed_at = claimed_at.replace(tzinfo=timezone.utc)
            return cls(
                record_id=str(data["record_id"]),
                claimed_at=claimed_at.astimezone(timezone.utc),
                game=str(data["game"]),
                campaign=str(data["campaign"]),
                reward=str(data["reward"]),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def to_data(self) -> dict[str, str]:
        data = asdict(self)
        data["claimed_at"] = self.claimed_at.astimezone(timezone.utc).isoformat()
        return data


class ClaimHistoryStore:
    MAX_RECORDS = 500

    def __init__(self, path: Path = DROP_HISTORY_PATH):
        self._path = path
        self._records = self._load()

    @property
    def records(self) -> tuple[ClaimRecord, ...]:
        return tuple(self._records)

    def _load(self) -> list[ClaimRecord]:
        candidates = (
            self._path.with_name(f"{self._path.name}.new"),
            self._path,
        )
        for candidate_path in candidates:
            if not candidate_path.exists():
                continue
            try:
                with candidate_path.open("r", encoding="utf8") as file:
                    data = json.load(file)
                raw_records = data.get("records", []) if isinstance(data, dict) else []
                if not isinstance(raw_records, list):
                    raise TypeError("Drop history records are not a list")
            except (OSError, json.JSONDecodeError, TypeError, AttributeError):
                logger.warning(
                    "Unable to read the local drop history file %s",
                    candidate_path,
                    exc_info=True,
                )
                continue
            records = [
                record
                for item in raw_records
                if (record := ClaimRecord.from_data(item)) is not None
            ]
            return records[-self.MAX_RECORDS:]
        return []

    def _save(self) -> None:
        try:
            json_save(
                self._path,
                {"version": 1, "records": [record.to_data() for record in self._records]},
            )
        except (OSError, TypeError, ValueError):
            # A history write must never interrupt a successful Twitch claim.
            logger.warning("Unable to save the local drop history", exc_info=True)

    def record_claim(
        self,
        campaign: Any,
        drop: Any,
        *,
        claimed_at: datetime | None = None,
    ) -> ClaimRecord | None:
        record_id = f"{campaign.id}:{drop.id}"
        if any(record.record_id == record_id for record in self._records):
            return None
        claimed_at = claimed_at or datetime.now(timezone.utc)
        if claimed_at.tzinfo is None:
            claimed_at = claimed_at.replace(tzinfo=timezone.utc)
        record = ClaimRecord(
            record_id=record_id,
            claimed_at=claimed_at.astimezone(timezone.utc),
            game=str(campaign.game.name),
            campaign=str(campaign.name),
            reward=str(drop.rewards_text()),
        )
        self._records.append(record)
        self._records = self._records[-self.MAX_RECORDS:]
        self._save()
        return record

    def export_csv(self, path: Path) -> None:
        with path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(("Claimed at (UTC)", "Game", "Campaign", "Reward"))
            for record in reversed(self._records):
                writer.writerow(
                    (
                        record.claimed_at.astimezone(timezone.utc).isoformat(),
                        record.game,
                        record.campaign,
                        record.reward,
                    )
                )
