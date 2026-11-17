from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from constants import MAX_EXTRA_MINUTES

if TYPE_CHECKING:
    from inventory import DropsCampaign


@dataclass(frozen=True)
class CampaignDiagnosis:
    game: str
    campaign: str
    reason: str | None


def diagnose_campaigns(
    campaigns: Iterable[DropsCampaign],
    *,
    priority_games: Iterable[str],
    excluded_games: Iterable[str],
    priority_only: bool,
    now: datetime | None = None,
) -> list[CampaignDiagnosis]:
    """Explain how each loaded campaign currently interacts with miner settings."""
    current_time = now or datetime.now(timezone.utc)
    horizon = current_time + timedelta(hours=1)
    priority = set(priority_games)
    excluded = set(excluded_games)
    results: list[CampaignDiagnosis] = []

    for campaign in campaigns:
        game_name = campaign.game.name
        reason: str | None

        if campaign.upcoming:
            reason = "upcoming"
        elif campaign.expired:
            reason = "expired"
        elif campaign.finished:
            reason = "finished"
        elif not campaign.eligible:
            reason = "badges_disabled" if campaign.has_badge_or_emote else "not_linked"
        elif game_name in excluded:
            reason = "excluded"
        elif priority_only and game_name not in priority:
            reason = "priority"
        elif campaign.can_earn_within(horizon):
            reason = None
        else:
            reason = _diagnose_unavailable_drops(campaign, current_time, horizon)

        results.append(CampaignDiagnosis(game_name, campaign.name, reason))

    return results


def _diagnose_unavailable_drops(
    campaign: DropsCampaign,
    now: datetime,
    horizon: datetime,
) -> str:
    unclaimed = [drop for drop in campaign.drops if not drop.is_claimed]
    if not unclaimed:
        return "finished"

    timed = [drop for drop in unclaimed if drop.required_minutes > 0]
    if not timed:
        return "finished"

    in_window = [drop for drop in timed if drop.ends_at > now and drop.starts_at < horizon]
    if not in_window:
        if all(drop.ends_at <= now for drop in timed):
            return "drop_expired"
        if all(drop.starts_at >= horizon for drop in timed if drop.ends_at > now):
            return "drop_starts_later"
        return "drop_not_ready"

    if all(not drop.preconditions_met for drop in in_window):
        return "waiting_for_previous"
    if all(drop.extra_current_minutes >= MAX_EXTRA_MINUTES for drop in in_window):
        return "progress_sync"
    return "drop_not_ready"
