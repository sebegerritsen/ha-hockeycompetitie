"""Tests for parsing API data leniently."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.knhb_hockey.coordinator import TeamData, match_duration, match_result
from custom_components.knhb_hockey.models import (
    Club,
    ClubDetail,
    Match,
    MatchStatus,
    TeamPage,
    TeamRef,
)


def _match(**overrides) -> dict:
    data = {
        "id": 1,
        "date": "2026-11-14T12:00:00+01:00",
        "status": "final",
        "home": {"id": 10, "name": "Home"},
        "away": {"id": 20, "name": "Away"},
        "score": {"home": 1, "away": 3},
    }
    return data | overrides


def test_unknown_status() -> None:
    """A status we don't know yet is UNKNOWN, not an error."""
    assert MatchStatus.parse("postponed") is MatchStatus.UNKNOWN
    assert MatchStatus.parse(None) is MatchStatus.UNKNOWN
    assert MatchStatus.parse("FINAL") is MatchStatus.FINAL


def test_match_with_missing_fields() -> None:
    """A match with only an id still parses."""
    match = Match.from_api({"id": "7"})
    assert match is not None
    assert match.id == 7
    assert match.start is None
    assert match.status is MatchStatus.UNKNOWN
    assert match.home == TeamRef(None, "?", None, None, None)
    assert match.facility is None
    assert match.remarks is None
    assert Match.from_api({"date": "2026-11-14"}) is None


def test_scheduled_match_has_no_score() -> None:
    """A scheduled match reports 0-0, which is not a score."""
    match = Match.from_api(_match(status="scheduled", score={"home": 0, "away": 0}))
    assert match is not None
    assert not match.has_score
    assert match.goals(10) is None


def test_naive_date_is_dutch_time() -> None:
    """A date without an offset is taken as Dutch time."""
    match = Match.from_api(_match(date="2026-07-01T10:00:00"))
    assert match is not None
    assert match.start == datetime(2026, 7, 1, 8, 0, tzinfo=UTC)
    assert Match.from_api(_match(date="not a date")).start is None


def test_bad_types_are_ignored() -> None:
    """Fields of the wrong type are treated as missing."""
    match = Match.from_api(
        _match(home="x", score=[1, 2], location={"facility": None}, remarks="x", round=True)
    )
    assert match is not None
    assert match.home.name == "?"
    assert match.score_home is None
    assert match.round is None
    page = TeamPage.from_api({"poules": "x", "neighbors": [{"no": "id"}], "season_id": 3})
    assert page.poules == []
    assert page.same_season_poules() == []


def test_club_search() -> None:
    """Clubs are found by name, short name or town, ignoring case."""
    club = Club.from_api(
        {"federation_reference_id": "X1", "name": "HC Voorbeeld", "city": "Ergens"}
    )
    assert club is not None
    assert club.matches_query("voorbeeld")
    assert club.matches_query(" ERGENS ")
    assert not club.matches_query("elders")
    assert Club.from_api({"name": "no id"}) is None
    assert ClubDetail.from_api({"name": "no id"}) is None


def test_result_from_team_point_of_view() -> None:
    """Win, draw or loss depends on which side the team played."""
    match = Match.from_api(_match())
    data_home = TeamData(team_id=10, match_duration=timedelta(minutes=90), matches=[match])
    data_away = TeamData(team_id=20, match_duration=timedelta(minutes=90), matches=[match])
    assert match_result(match, 10) == "loss"
    assert match_result(match, 20) == "win"
    assert data_home.form(10) == ["loss"]
    assert data_away.form(20) == ["win"]


def test_match_duration() -> None:
    """Indoor and the youngest play shorter matches."""
    assert match_duration("VE", "Junioren") == timedelta(minutes=90)
    assert match_duration("ZA", "Senioren") == timedelta(minutes=60)
    assert match_duration("VE", "Jongste jeugd") == timedelta(minutes=60)
