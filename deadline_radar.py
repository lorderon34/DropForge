"""Rank active campaigns by how little time remains to finish their next drop."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import ceil
from typing import Any, Iterable


@dataclass(frozen=True)
class DeadlineCandidate:
    campaign: Any
    drop: Any
    deadline: datetime
    required_minutes: int
    available_minutes: int
    margin_ratio: float


@dataclass(frozen=True)
class SessionRecommendation:
    candidate: DeadlineCandidate
    fits_session: bool
    difference_minutes: int


def rank_deadline_candidates(
    campaigns: Iterable[Any],
    *,
    excluded_games: set[str] | frozenset[str] = frozenset(),
    now: datetime | None = None,
    limit: int | None = 3,
) -> list[DeadlineCandidate]:
    """Return eligible, unfinished campaigns from the tightest deadline outward.

    The margin compares the minutes left in each drop's earning window with the
    remaining watch time, including prerequisite drops. A value under 1 means
    the estimate requires more continuous watch time than the window provides.
    """
    now = now or datetime.now(timezone.utc)
    candidates: list[DeadlineCandidate] = []
    for campaign in campaigns:
        if (
            not campaign.active
            or not campaign.eligible
            or campaign.finished
            or campaign.game.name in excluded_games
        ):
            continue

        drop_candidates: list[DeadlineCandidate] = []
        for drop in campaign.drops:
            if drop.is_claimed:
                continue
            required_minutes = int(drop.total_remaining_minutes)
            if required_minutes <= 0:
                continue
            deadline = drop.ends_at
            earning_starts = max(now, drop.starts_at)
            available_minutes = max(0, ceil((deadline - earning_starts).total_seconds() / 60))
            if available_minutes <= 0:
                continue
            drop_candidates.append(
                DeadlineCandidate(
                    campaign=campaign,
                    drop=drop,
                    deadline=deadline,
                    required_minutes=required_minutes,
                    available_minutes=available_minutes,
                    margin_ratio=available_minutes / required_minutes,
                )
            )

        if drop_candidates:
            candidates.append(
                min(drop_candidates, key=lambda item: (item.margin_ratio, item.deadline))
            )

    candidates.sort(key=lambda item: (item.margin_ratio, item.deadline, item.campaign.name))
    if limit is not None:
        candidates = candidates[:max(0, limit)]
    return candidates


def rank_for_session(
    candidates: Iterable[DeadlineCandidate], session_minutes: int
) -> list[SessionRecommendation]:
    """Put rewards that fit both the session and earning window first."""
    recommendations: list[SessionRecommendation] = []
    session_minutes = max(0, int(session_minutes))
    for candidate in candidates:
        difference = max(
            0,
            candidate.required_minutes - session_minutes,
            candidate.required_minutes - candidate.available_minutes,
        )
        recommendations.append(
            SessionRecommendation(
                candidate=candidate,
                fits_session=difference == 0,
                difference_minutes=difference,
            )
        )

    recommendations.sort(
        key=lambda item: (
            not item.fits_session,
            item.difference_minutes if not item.fits_session else item.candidate.margin_ratio,
            item.candidate.margin_ratio,
            item.candidate.deadline,
        )
    )
    return recommendations
