from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from inventory import DropsCampaign


def campaign_matches_search(campaign: DropsCampaign, query: str) -> bool:
    """Match a campaign against its game, campaign, drop, and reward names."""
    normalized = query.strip().casefold()
    if not normalized:
        return True

    searchable = [campaign.game.name, campaign.name]
    for drop in campaign.drops:
        searchable.extend((drop.name, drop.rewards_text()))
    return normalized in " ".join(searchable).casefold()


def passes_game_filter(
    game_name: str,
    *,
    query: str,
    priority_games: Iterable[str],
    excluded_games: set[str],
    priority_only: bool,
    show_excluded: bool,
) -> bool:
    """Apply inventory game filters while letting a search reveal non-priority games."""
    if show_excluded:
        return True
    if game_name in excluded_games:
        return False
    return bool(query.strip()) or not priority_only or game_name in priority_games
