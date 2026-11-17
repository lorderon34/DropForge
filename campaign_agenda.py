"""List campaign and drop dates for the inventory agenda."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from json import dumps
from typing import Literal, TYPE_CHECKING
from uuid import NAMESPACE_URL, uuid5

if TYPE_CHECKING:
    from inventory import DropsCampaign, TimedDrop


@dataclass(frozen=True)
class CampaignAgendaEvent:
    campaign: DropsCampaign
    when: datetime
    kind: Literal["starts", "ends"]
    drop: TimedDrop | None = None


def build_campaign_agenda(
    campaigns: Iterable[DropsCampaign],
    *,
    now: datetime,
    days: int,
) -> tuple[CampaignAgendaEvent, ...]:
    """List future events through the inclusive end of the selected period."""
    if days <= 0:
        return ()
    now = now.astimezone(timezone.utc)
    through = now + timedelta(days=days)
    events: list[CampaignAgendaEvent] = []
    for campaign in campaigns:
        start, end = campaign.starts_at, campaign.ends_at
        if campaign.expired or campaign.finished or end <= now or start >= end or start > through:
            continue
        if now < start:
            events.append(CampaignAgendaEvent(campaign, start, "starts"))
        if end <= through:
            events.append(CampaignAgendaEvent(campaign, end, "ends"))

        for drop in campaign.drops:
            if drop.is_claimed or drop.required_minutes <= 0:
                continue
            drop_start = max(start, drop.starts_at)
            drop_end = min(end, drop.ends_at)
            if drop_start >= drop_end:
                continue
            if drop_start != start and now < drop_start <= through:
                events.append(CampaignAgendaEvent(campaign, drop_start, "starts", drop))
            if drop_end != end and now < drop_end <= through:
                events.append(CampaignAgendaEvent(campaign, drop_end, "ends", drop))

    events.sort(
        key=lambda event: (
            event.when,
            event.kind != "ends",
            event.campaign.game.name.casefold(),
            event.campaign.name.casefold(),
            event.drop.name.casefold() if event.drop is not None else "",
        )
    )
    return tuple(events)


def _calendar_date(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _calendar_text(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(",", "\\,")
        .replace(";", "\\;")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "\\n")
    )


def _fold_calendar_line(line: str) -> bytes:
    encoded = line.encode("utf-8")
    chunks: list[bytes] = []
    offset, capacity = 0, 75
    while len(encoded) - offset > capacity:
        end = offset + capacity
        # A continuation byte cannot start a physical line.
        while encoded[end] & 0xC0 == 0x80:
            end -= 1
        chunks.append(encoded[offset:end])
        offset, capacity = end, 74  # The continuation line starts with a space.
    chunks.append(encoded[offset:])
    return b"\r\n ".join(chunks)


def serialize_campaign_calendar(
    events: Iterable[CampaignAgendaEvent],
    *,
    stamp: datetime,
    event_label: Callable[[str], str],
) -> bytes:
    """Export the selected agenda as UTF-8 iCalendar date markers."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//DropForge//Campaign Agenda//EN"]
    dtstamp = _calendar_date(stamp)
    for event in events:
        campaign = event.campaign
        drop = event.drop
        identity = dumps((campaign.id, drop.id if drop is not None else None, event.kind))
        uid = uuid5(NAMESPACE_URL, f"dropforge:campaign-agenda:{identity}")
        reward = None if drop is None else (drop.rewards_text() or drop.name)
        summary = f"{event_label(event.kind)} · {campaign.game.name} — {campaign.name}"
        if reward is not None:
            summary += f" · {reward}"
        lines.extend(
            (
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{dtstamp}",
                f"DTSTART:{_calendar_date(event.when)}",
                f"SUMMARY:{_calendar_text(summary)}",
                "TRANSP:TRANSPARENT",
            )
        )
        if reward is not None:
            lines.append(f"DESCRIPTION:{_calendar_text(reward)}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return b"\r\n".join(_fold_calendar_line(line) for line in lines) + b"\r\n"
