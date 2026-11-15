"""Tests for noticing changes to matches."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from custom_components.hockeycompetitie.changes import (
    ChangeType,
    MatchState,
    detect_changes,
    updated_states,
)
from custom_components.hockeycompetitie.models import Match, MatchStatus

from .conftest import load_fixture


def _matches() -> dict[int, Match]:
    page = load_fixture("team_page.json")["data"]["poules"][0]["matches"]
    return {m.id: m for item in page if (m := Match.from_api(item)) is not None}


def _states(matches: dict[int, Match]) -> dict[int, MatchState]:
    return {match_id: MatchState.of(match) for match_id, match in matches.items()}


def _types(changes) -> list[tuple[int, ChangeType]]:
    return [(change.match.id, change.type) for change in changes]


def test_nothing_changed() -> None:
    """The same matches give no changes; a match never seen is not a change."""
    matches = _matches()
    before = _states(matches)
    del before[9005]
    assert detect_changes(before, matches.values()) == []


def test_cancelled_and_reinstated() -> None:
    """A cancellation is reported alone; a cancelled match coming back is too."""
    matches = _matches()
    before = _states(matches)
    cancelled = replace(
        matches[9003], status=MatchStatus.CANCELLED, start=datetime(2026, 11, 15, tzinfo=UTC)
    )
    reinstated = replace(matches[9004], status=MatchStatus.SCHEDULED)
    assert _types(detect_changes(before, [cancelled, reinstated])) == [
        (9003, ChangeType.CANCELLED),
        (9004, ChangeType.REINSTATED),
    ]


def test_rescheduled_and_location() -> None:
    """A new time and a different pitch are changes; a first pitch assignment is not."""
    matches = _matches()
    before = _states(matches)
    moved = replace(matches[9003], start=datetime(2026, 11, 14, 13, 0, tzinfo=UTC), field="Veld 5")
    assigned = replace(matches[9005], field="Veld 1")
    changes = detect_changes(before, [moved, assigned])
    assert _types(changes) == [
        (9003, ChangeType.RESCHEDULED),
        (9003, ChangeType.LOCATION_CHANGED),
    ]
    assert changes[1].previous.field == "Veld 2"


def test_result() -> None:
    """A result is a change when it first appears and when it is corrected."""
    matches = _matches()
    before = _states(matches)
    played = replace(matches[9003], status=MatchStatus.FINAL, score_home=4, score_away=0)
    corrected = replace(matches[9001], score_home=3, score_away=2)
    live = replace(matches[9005], status=MatchStatus.LIVE, score_home=1, score_away=0)
    assert _types(detect_changes(before, [played, corrected, live])) == [
        (9003, ChangeType.RESULT),
        (9001, ChangeType.RESULT),
    ]


def test_states_stored_and_pruned() -> None:
    """States survive storage; matches long past are forgotten, missing ones kept."""
    matches = _matches()
    states = _states(matches)
    for state in states.values():
        assert MatchState.from_dict(state.as_dict()) == state
    assert MatchState.from_dict({"status": 3}) is None

    later = updated_states(states, [matches[9005]], datetime(2027, 1, 15, tzinfo=UTC))
    assert set(later) == {9004, 9005}
