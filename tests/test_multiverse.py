"""Tests for canonical lookup over legacy Timeline.positions storage."""
import pytest

from src.engine.board import Position
from src.engine.coordinates import BoardCoord
from src.engine.multiverse import BoardRole, MultiverseBoardView
from src.engine.timeline import Timeline
from src.utils.constants import ChessColor


def make_position(timeline_id: int, time_point: int) -> Position:
    position = Position.initial(timeline_id=timeline_id, time_point=time_point)
    position.turn = BoardCoord.legacy_side_for_time_point(time_point)
    return position


def make_timeline(timeline_id: int, times: tuple[int, ...], *, active: bool = True) -> Timeline:
    timeline = Timeline(timeline_id=timeline_id, is_active=active)
    for time_point in times:
        timeline.add_position(make_position(timeline_id, time_point))
    return timeline


def test_resolve_canonical_coord_to_legacy_position():
    timeline = make_timeline(0, (0, 1, 2))
    view = MultiverseBoardView({0: timeline})

    position = view.resolve(BoardCoord(0, 0, ChessColor.BLACK))
    assert position is timeline.positions[1]
    assert view.resolve(BoardCoord(0, 3, ChessColor.WHITE)) is None


def test_describe_distinguishes_historical_and_playable_boards():
    timeline = make_timeline(0, (0, 1, 2, 3))
    view = MultiverseBoardView({0: timeline})

    historical = view.describe(BoardCoord(0, 1, ChessColor.WHITE))
    playable = view.describe(BoardCoord(0, 1, ChessColor.BLACK))

    assert historical is not None
    assert historical.role == BoardRole.HISTORICAL
    assert historical.is_historical
    assert playable is not None
    assert playable.role == BoardRole.PLAYABLE
    assert playable.is_playable


def test_latest_coord_uses_canonical_turn_and_side():
    timeline = make_timeline(2, (0, 1, 2, 3, 4, 5, 6, 7))
    view = MultiverseBoardView({2: timeline})

    assert view.latest_coord(2) == BoardCoord(2, 3, ChessColor.BLACK)
    assert view.latest_coord(999) is None


def test_iter_boards_filters_side_activity_and_playable_role():
    active = make_timeline(0, (0, 1, 2), active=True)
    inactive = make_timeline(1, (0, 1, 2, 3, 4), active=False)
    view = MultiverseBoardView({1: inactive, 0: active})

    white_active = list(view.iter_boards(side=ChessColor.WHITE, active_only=True))
    assert [item.coord for item in white_active] == [
        BoardCoord(0, 0, ChessColor.WHITE),
        BoardCoord(0, 1, ChessColor.WHITE),
    ]

    playable = list(view.iter_boards(playable_only=True))
    assert [item.coord for item in playable] == [
        BoardCoord(0, 1, ChessColor.WHITE),
        BoardCoord(1, 2, ChessColor.WHITE),
    ]
    assert [item.timeline_active for item in playable] == [True, False]


def test_wrong_side_coord_is_not_a_board():
    timeline = make_timeline(0, (0, 1))
    view = MultiverseBoardView({0: timeline})

    assert view.resolve(BoardCoord(0, 0, ChessColor.WHITE)) is timeline.positions[0]
    # T0b is legacy t=1; changing only the requested side changes the board id.
    assert view.resolve(BoardCoord(0, 0, ChessColor.BLACK)) is timeline.positions[1]


def test_corrupted_position_metadata_is_rejected():
    timeline = make_timeline(0, (0,))
    timeline.positions[0].timeline_id = 4
    view = MultiverseBoardView({0: timeline})

    with pytest.raises(ValueError, match="stores position for timeline"):
        view.resolve(BoardCoord(0, 0, ChessColor.WHITE))


def test_corrupted_side_phase_is_rejected():
    timeline = make_timeline(0, (0,))
    timeline.positions[0].turn = ChessColor.BLACK
    view = MultiverseBoardView({0: timeline})

    with pytest.raises(ValueError, match="implies white"):
        view.latest_coord(0)
