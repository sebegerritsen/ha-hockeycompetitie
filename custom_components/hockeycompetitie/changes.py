"""Detect what changed about a team's matches between two updates."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from .models import STATUSES_WITH_SCORE, Match, MatchStatus

# Forget matches this long after their start: nothing about them changes any more.
SNAPSHOT_KEEP = timedelta(days=60)

RESULT_STATUSES = frozenset({MatchStatus.RESULT, MatchStatus.FINAL, MatchStatus.DISCONTINUED})


class ChangeType(StrEnum):
    """What happened to a match."""

    CANCELLED = "cancelled"
    REINSTATED = "reinstated"
    RESCHEDULED = "rescheduled"
    LOCATION_CHANGED = "location_changed"
    RESULT = "result"


@dataclass(frozen=True, slots=True)
class MatchState:
    """What we remember of a match to notice changes."""

    status: str
    start: str | None
    facility: str | None
    field: str | None
    score: tuple[int, int] | None

    @classmethod
    def of(cls, match: Match) -> MatchState:
        """Return the state of a match."""
        score = None
        if (
            match.score_home is not None
            and match.score_away is not None
            and match.status in RESULT_STATUSES
        ):
            score = (match.score_home, match.score_away)
        return cls(
            status=match.status.value,
            start=match.start.isoformat() if match.start else None,
            facility=match.facility,
            field=match.field,
            score=score,
        )

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-able dict, for storage."""
        return {
            "status": self.status,
            "start": self.start,
            "facility": self.facility,
            "field": self.field,
            "score": list(self.score) if self.score else None,
        }

    @classmethod
    def from_dict(cls, data: Any) -> MatchState | None:
        """Read a stored state; None if it is not usable."""
        if not isinstance(data, dict) or not isinstance(data.get("status"), str):
            return None
        score = data.get("score")
        return cls(
            status=data["status"],
            start=data.get("start") if isinstance(data.get("start"), str) else None,
            facility=data.get("facility") if isinstance(data.get("facility"), str) else None,
            field=data.get("field") if isinstance(data.get("field"), str) else None,
            score=(score[0], score[1])
            if isinstance(score, list)
            and len(score) == 2
            and all(isinstance(v, int) for v in score)
            else None,
        )


@dataclass(frozen=True, slots=True)
class MatchChange:
    """A change to a match."""

    type: ChangeType
    match: Match
    previous: MatchState


def detect_changes(previous: dict[int, MatchState], matches: Iterable[Match]) -> list[MatchChange]:
    """Return the changes between remembered states and the current matches.

    A match not seen before is not a change. A cancellation is reported alone;
    a pitch being assigned for the first time is not a change, a different one is.
    """
    changes: list[MatchChange] = []
    for match in matches:
        if (before := previous.get(match.id)) is None:
            continue
        now = MatchState.of(match)
        was_cancelled = before.status == MatchStatus.CANCELLED
        is_cancelled = match.status == MatchStatus.CANCELLED
        if is_cancelled and not was_cancelled:
            changes.append(MatchChange(ChangeType.CANCELLED, match, before))
            continue
        if is_cancelled:
            continue
        if was_cancelled:
            changes.append(MatchChange(ChangeType.REINSTATED, match, before))
        elif before.start and now.start and before.start != now.start:
            changes.append(MatchChange(ChangeType.RESCHEDULED, match, before))
        moved = (before.facility and before.facility != now.facility) or (
            before.field and before.field != now.field
        )
        if moved and match.status not in STATUSES_WITH_SCORE:
            changes.append(MatchChange(ChangeType.LOCATION_CHANGED, match, before))
        if now.score is not None and now.score != before.score:
            changes.append(MatchChange(ChangeType.RESULT, match, before))
    return changes


def updated_states(
    previous: dict[int, MatchState], matches: Iterable[Match], now: datetime
) -> dict[int, MatchState]:
    """Return the remembered states with the current matches merged in.

    Matches that are not in this update (a pool not fetched yet after a restart) are
    kept, until they are long past.
    """
    states = dict(previous)
    for match in matches:
        states[match.id] = MatchState.of(match)
    cutoff = now - SNAPSHOT_KEEP
    return {
        match_id: state for match_id, state in states.items() if not _before(state.start, cutoff)
    }


def _before(value: str | None, moment: datetime) -> bool:
    if value is None:
        return False
    try:
        return datetime.fromisoformat(value) < moment
    except ValueError:
        return True
