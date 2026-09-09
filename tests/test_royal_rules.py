"""Tests for canonical multiverse royal safety."""

from src.engine import (
    Action,
    ActionRules,
    BoardCoord,
    PawnRules,
    Piece,
    PieceMovementRules,
    Position,
    RoyalRules,
    Square5D,
    Timeline,
    TimelineRules,
)
from src.utils.constants import ChessColor, PieceType


def _position(timeline_id: int, time_point: int, *pieces):
    board = [["" for _ in range(8)] for _ in range(8)]
    for x, y, char in pieces:
        board[y][x] = char
    return Position(
        board=board,
        turn=BoardCoord.legacy_side_for_time_point(time_point),
        timeline_id=timeline_id,
        time_point=time_point,
    )


def _timeline(timeline_id: int, *positions, owner=None):
    timeline = Timeline(timeline_id=timeline_id, owner=owner)
    for position in positions:
        timeline.add_position(position)
    return timeline


def _square(position: Position, x: int, y: int) -> Square5D:
    return Square5D(
        BoardCoord.from_legacy_time_point(
            position.timeline_id,
            position.time_point,
            position.turn,
        ),
        x,
        y,
    )


def test_rook_attacks_historical_king_along_time_axis():
    past = _position(0, 1, (4, 4, "K"))
    latest = _position(0, 3, (4, 4, "r"))
    rules = RoyalRules({0: _timeline(0, past, latest)})

    threats = rules.direct_threats_against(ChessColor.WHITE)

    assert len(threats) == 1
    assert threats[0].attacker == _square(latest, 4, 4)
    assert threats[0].king == _square(past, 4, 4)


def test_slider_time_attack_is_blocked_by_missing_intermediate_board():
    past = _position(0, 1, (4, 4, "K"))
    latest = _position(0, 5, (4, 4, "r"))
    rules = RoyalRules({0: _timeline(0, past, latest)})

    assert rules.direct_threats_against(ChessColor.WHITE) == ()


def test_knight_jumps_across_missing_time_board():
    past = _position(0, 1, (3, 4, "K"))
    latest = _position(0, 5, (4, 4, "n"))
    rules = RoyalRules({0: _timeline(0, past, latest)})

    threats = rules.direct_threats_against(ChessColor.WHITE)

    assert len(threats) == 1
    assert threats[0].piece.piece_type.value == "N"


def test_bishop_attacks_on_spatial_time_diagonal():
    past = _position(0, 1, (3, 4, "K"))
    latest = _position(0, 3, (4, 4, "b"))
    rules = RoyalRules({0: _timeline(0, past, latest)})

    assert len(rules.direct_threats_against(ChessColor.WHITE)) == 1


def test_queen_attacks_across_all_four_axes():
    target = _position(0, 1, (3, 3, "K"))
    source = _position(1, 3, (4, 4, "q"))
    timelines = {
        0: _timeline(0, target),
        1: _timeline(1, source, owner=ChessColor.WHITE),
    }
    rules = RoyalRules(timelines)

    assert len(rules.direct_threats_against(ChessColor.WHITE)) == 1


def test_king_attacks_across_adjacent_timeline():
    target = _position(0, 1, (4, 4, "K"))
    source = _position(1, 1, (4, 4, "k"))
    timelines = {
        0: _timeline(0, target),
        1: _timeline(1, source, owner=ChessColor.WHITE),
    }

    assert len(RoyalRules(timelines).direct_threats_against(ChessColor.WHITE)) == 1


def test_pawn_temporal_attack_uses_t_l_capture_plane():
    target = _position(1, 1, (4, 4, "K"))
    source = _position(0, 3, (4, 4, "p"))
    timelines = {
        0: _timeline(0, source),
        1: _timeline(1, target, owner=ChessColor.WHITE),
    }

    assert len(RoyalRules(timelines).direct_threats_against(ChessColor.WHITE)) == 1


def test_historical_attacker_cannot_originate_a_royal_capture():
    target = _position(1, 1, (4, 4, "K"))
    old_attacker = _position(0, 3, (4, 4, "r"))
    latest = _position(0, 5)
    timelines = {
        0: _timeline(0, old_attacker, latest),
        1: _timeline(1, target, owner=ChessColor.WHITE),
    }

    assert RoyalRules(timelines).direct_threats_against(ChessColor.WHITE) == ()


def test_inactive_playable_board_remains_a_valid_attack_source():
    target = _position(0, 3, (4, 4, "K"))
    white_one = _position(1, 3)
    black_source = _position(2, 3, (4, 4, "r"))
    timelines = {
        0: _timeline(0, target),
        1: _timeline(1, white_one, owner=ChessColor.WHITE),
        2: _timeline(2, black_source, owner=ChessColor.WHITE),
    }

    assert not TimelineRules.is_active_timeline(timelines[2], timelines)
    assert len(RoyalRules(timelines).direct_threats_against(ChessColor.WHITE)) == 1


def test_check_virtualizes_passing_the_present_without_mutating_history():
    present = _position(
        0,
        0,
        (4, 7, "K"),
        (4, 0, "r"),
    )
    timeline = _timeline(0, present)
    rules = RoyalRules({0: timeline})

    assert timeline.latest_time == 0
    assert rules.direct_threats_against(ChessColor.WHITE) == ()
    assert rules.is_in_check(ChessColor.WHITE)
    assert timeline.latest_time == 0
    assert sorted(timeline.positions) == [0]


def test_virtual_pass_preserves_slider_blockers():
    present = _position(
        0,
        0,
        (4, 7, "K"),
        (4, 4, "P"),
        (4, 0, "r"),
    )
    rules = RoyalRules({0: _timeline(0, present)})

    assert not rules.is_in_check(ChessColor.WHITE)


def test_action_submission_rejects_multiverse_royal_exposure():
    black_turn = _position(
        0,
        1,
        (4, 7, "K"),
        (4, 0, "r"),
    )
    timelines = {0: _timeline(0, black_turn)}
    action = Action(color=ChessColor.WHITE, starting_present=None)

    assert not ActionRules.can_submit(action, timelines)
    assert not ActionRules.submit(action, timelines)
    assert not action.submitted


def test_action_submission_allows_safe_completed_action():
    black_turn = _position(
        0,
        1,
        (4, 7, "K"),
        (4, 4, "P"),
        (4, 0, "r"),
    )
    timelines = {0: _timeline(0, black_turn)}
    action = Action(color=ChessColor.WHITE, starting_present=None)

    assert ActionRules.can_submit(action, timelines)
    assert ActionRules.submit(action, timelines)
    assert action.submitted


def test_action_safety_boolean_short_circuits_after_first_threat(monkeypatch):
    black_turn = _position(
        0,
        1,
        (4, 7, "K"),
        (4, 0, "r"),
        (0, 0, "r"),
    )
    rules = RoyalRules({0: _timeline(0, black_turn)})
    calls = 0

    def always_threat(piece, source, target, view):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise AssertionError("boolean royal-safety query did not short-circuit")
        return True

    monkeypatch.setattr(
        RoyalRules,
        "_attacks_prevalidated_square_with_view",
        staticmethod(always_threat),
    )

    assert not rules.is_action_safe(ChessColor.WHITE)
    assert calls == 1


def test_fast_royal_geometry_matches_canonical_vector_rules():
    """The allocation-free hot-path predicate must remain rule-equivalent."""
    piece_types = (
        PieceType.ROOK,
        PieceType.BISHOP,
        PieceType.QUEEN,
        PieceType.KING,
        PieceType.KNIGHT,
        PieceType.PAWN,
    )

    for color in (ChessColor.WHITE, ChessColor.BLACK):
        source = Square5D(BoardCoord(0, 3, color), 3, 3)
        for piece_type in piece_types:
            piece = Piece(piece_type, color)
            for timeline in range(-3, 4):
                for turn in range(0, 7):
                    for x in range(8):
                        for y in range(8):
                            target = Square5D(BoardCoord(timeline, turn, color), x, y)
                            vector = source.vector_to(target)
                            if piece_type == PieceType.PAWN:
                                expected = PawnRules.is_valid_vector(
                                    color,
                                    vector,
                                    capture=True,
                                    unmoved=False,
                                )
                            else:
                                expected = PieceMovementRules.is_valid(piece_type, vector)
                            assert RoyalRules._attack_geometry_matches(
                                piece,
                                source,
                                target,
                            ) is expected
