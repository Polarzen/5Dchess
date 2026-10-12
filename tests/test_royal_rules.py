"""Tests for canonical multiverse royal safety."""

import gzip
import json
from copy import deepcopy
from pathlib import Path

import pytest

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
from src.engine.multiverse import MultiverseBoardView
from src.engine.royal_rules import RoyalThreat


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


@pytest.mark.parametrize('fixture', [
    'easy20_king_escape_state', 'control43_active_rewind_state',
    'easy20_two_fixed_attackers_state', 'seed53_uncapturable_threat_state',
    'seed43_twenty_seven_required_state', 'seed43_twenty_eight_required_state',
    'hard20_twenty_three_required_state', 'outcome_action_92_white',
])
def test_integer_prefilter_preserves_full_canonical_threat_enumeration(fixture):
    from src.data.archive import GameArchive

    path = Path(__file__).parent / 'fixtures' / f'{fixture}.json.gz'
    engine = GameArchive.restore(json.loads(gzip.decompress(path.read_bytes())))
    for color in ChessColor:
        rules = RoyalRules(engine.timeline_manager.timelines)
        for timelines in [rules.timelines, rules._after_virtual_present_pass(color)]:
            view = MultiverseBoardView(timelines)
            attacker_color = color.opposite()
            kings = []
            for board in view.iter_boards(side=attacker_color):
                # Independent scan: cross-board arrivals can add another King.
                for y, row in enumerate(board.position.board):
                    for x, char in enumerate(row):
                        if char == ('K' if color == ChessColor.WHITE else 'k'):
                            kings.append(Square5D(board.coord, x, y))
            reference = []
            for board in view.iter_boards(side=attacker_color, playable_only=True):
                for x, y, piece in board.position.get_all_pieces(attacker_color):
                    source = Square5D(board.coord, x, y)
                    for king in kings:
                        if RoyalRules._attacks_prevalidated_square_with_view(piece, source, king, view):
                            reference.append(RoyalThreat(piece, source, king))
            assert tuple(RoyalRules._iter_direct_threats_in(timelines, color)) == tuple(reference)


@pytest.mark.parametrize('piece', list(PieceType))
@pytest.mark.parametrize('color', list(ChessColor))
def test_spatial_prefilter_retains_every_geometric_attack(piece, color):
    for dx in range(-7, 8):
        for dy in range(-7, 8):
            possible = RoyalRules._spatial_delta_can_attack(piece.value, color == ChessColor.WHITE, dx, dy)
            if possible:
                continue
            # Include long pure-time/lane rays as well as all short leapers.
            for dt in range(-9, 10):
                for dl in range(-9, 10):
                    assert not RoyalRules._attack_delta_matches(piece, color, dx, dy, dt, dl)


@pytest.mark.parametrize('fixture', [
    'hard20_twenty_three_required_state', 'seed42_twenty_required_arrival_defense_state',
    'seed43_twenty_eight_required_state', 'easy20_king_escape_state',
    'hard20_last_active_branch_terminal_state', 'hard20_rewind_three_state',
])
def test_borrowed_history_matches_isolated_virtual_pass(fixture):
    from src.data.archive import GameArchive
    path = Path(__file__).parent / 'fixtures' / f'{fixture}.json.gz'
    engine = GameArchive.restore(json.loads(gzip.decompress(path.read_bytes())))
    before = deepcopy(engine.timeline_manager.timelines)
    rules = RoyalRules(engine.timeline_manager.timelines)
    for color in ChessColor:
        isolated = rules._after_virtual_present_pass(color)
        borrowed = rules._after_virtual_present_pass(color, copy_history=False)
        assert isolated == borrowed
        reference = rules._direct_threats_in(isolated, color)
        assert rules.threats_against(color) == reference
        assert rules.is_in_check(color) == bool(reference)
    assert engine.timeline_manager.timelines == before


def test_virtual_pass_copies_only_touched_storage_for_internal_reads():
    present = _position(0, 0, (7, 7, 'K'), (7, 0, 'k'))
    present.en_passant_target = (4, 5)
    other = _position(1, 1, (7, 7, 'K'), (7, 0, 'k'))
    timelines = {0: _timeline(0, present), 1: _timeline(1, other)}
    before = deepcopy(timelines)
    rules = RoyalRules(timelines)
    borrowed = rules._after_virtual_present_pass(ChessColor.WHITE, copy_history=False)
    assert borrowed[1] is timelines[1]
    assert borrowed[0] is not timelines[0]
    assert borrowed[0].positions is not timelines[0].positions
    assert borrowed[0].positions[0] is present
    successor = borrowed[0].positions[1]
    assert successor.en_passant_target is None
    assert successor.turn == ChessColor.BLACK and successor.time_point == 1
    successor.board[7][7] = ''
    successor.castling_rights['white_kingside'] = False
    successor.unmoved_pawns.add((3, 3))
    assert timelines == before
    isolated = rules._after_virtual_present_pass(ChessColor.WHITE)
    assert isolated[1] is not timelines[1]
    assert isolated[0].positions[0] is not present
    isolated[0].positions[0].board[7][7] = ''
    assert timelines == before


@pytest.mark.parametrize('custom', ['timeline_attribute', 'position_attribute', 'timeline_subclass', 'position_subclass', 'rules_subclass'])
def test_virtual_pass_falls_back_to_isolation_for_nonstandard_objects(custom):
    position = _position(0, 0, (7, 7, 'K'), (7, 0, 'k'))
    timeline = _timeline(0, position)
    rules_type = RoyalRules
    if custom == 'timeline_attribute':
        timeline.extra = []
    elif custom == 'position_attribute':
        position.extra = []
    elif custom == 'timeline_subclass':
        class CustomTimeline(Timeline):
            pass
        timeline = CustomTimeline(**vars(timeline))
    elif custom == 'position_subclass':
        class CustomPosition(Position):
            pass
        position = CustomPosition(**vars(position))
        timeline.positions[0] = position
    else:
        class CustomRules(RoyalRules):
            pass
        rules_type = CustomRules
    simulated = rules_type({0: timeline})._after_virtual_present_pass(ChessColor.WHITE, copy_history=False)
    assert simulated[0] is not timeline
    assert simulated[0].positions[0] is not position
    if custom == 'timeline_attribute':
        simulated[0].extra.append(1)
        assert timeline.extra == []
    elif custom == 'position_attribute':
        simulated[0].positions[0].extra.append(1)
        assert position.extra == []


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
