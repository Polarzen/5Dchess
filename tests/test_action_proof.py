"""Exact terminal certificates and counterexamples to broader pruning."""
import gzip
import json
from pathlib import Path

import pytest

from src.ai.action_planner import (
    AIActionPlan, ActionPlanner, _PRODUCTION_HYBRID_BUDGET,
    apply_action_plan, engine_state_signature,
)
from src.data.archive import GameArchive
from src.engine import ActionRules, ActionSearch, FiveDEngine, Position, Timeline
from src.engine.action_proof import (
    fixed_successor_attackers, move_exposes_fixed_attacker,
    prove_direct_threat, prove_required_board_immobile, prove_required_board_threat,
)
from src.engine.coordinates import BoardCoord
from src.engine.outcome_rules import OutcomeKind, OutcomeRules
from src.engine.piece import Piece
from src.utils.constants import ChessColor, PieceType


def _position(lane, time, pieces):
    board = [["" for _ in range(8)] for _ in range(8)]
    for x, y, symbol in pieces:
        board[y][x] = symbol
    return Position(board=board, timeline_id=lane, time_point=time,
                    turn=BoardCoord.legacy_side_for_time_point(time), unmoved_pawns=set())


def _engine():
    engine = FiveDEngine()
    engine.timeline_manager.timelines = {
        0: Timeline(0, positions={0: _position(0, 0, [(0, 0, 'r'), (7, 0, 'k'), (7, 7, 'K')])}),
        1: Timeline(1, owner=ChessColor.WHITE,
                    positions={1: _position(1, 1, [(0, 0, 'K'), (7, 0, 'k')])}),
    }
    engine.timeline_manager._next_positive_id = 2
    engine.timeline_manager._next_negative_id = -1
    engine.timeline_manager.refresh_activity()
    engine.current_action = ActionRules.begin(ChessColor.WHITE, engine.timeline_manager.timelines)
    return engine


def _captured_engine(name='seed53_uncapturable_threat_state'):
    fixture = Path(__file__).parent / f'fixtures/{name}.json.gz'
    engine = GameArchive.restore(json.loads(gzip.decompress(fixture.read_bytes())))
    del engine._replay_origin
    return engine


def _disable_proofs(monkeypatch):
    monkeypatch.setattr('src.engine.action_search.prove_required_board_threat', lambda *args: None)
    monkeypatch.setattr('src.engine.action_search.prove_direct_threat', lambda *args: None)
    monkeypatch.setattr('src.engine.action_search.prove_required_board_immobile', lambda *args: None)


def _immobile_engine(color=ChessColor.WHITE):
    engine = FiveDEngine()
    white = color == ChessColor.WHITE
    lane, time = (1, 0) if white else (-1, 1)
    rook, pawn, king, enemy = ('R', 'P', 'K', 'k') if white else ('r', 'p', 'k', 'K')
    engine.timeline_manager.timelines = {
        0: Timeline(0, positions={time: _position(0, time, [(3, 3, rook), (2, 4, pawn)])}),
        lane: Timeline(lane, owner=color, positions={
            time: _position(lane, time, [(3, 3, rook)]),
            time + 1: _position(lane, time + 1, [(7, 7, king), (7, 0, enemy)]),
        }),
    }
    engine.timeline_manager._next_positive_id = 2 if white else 1
    engine.timeline_manager._next_negative_id = -1 if white else -2
    engine.current_turn_color = color
    engine.current_action = ActionRules.begin(color, engine.timeline_manager.timelines)
    return engine


@pytest.mark.parametrize('color', list(ChessColor))
def test_immobile_board_matches_exhaustive_canonical_search(monkeypatch, color):
    engine = _immobile_engine(color)
    before = engine_state_signature(engine)
    proof = prove_required_board_immobile(engine, lambda: False)
    assert proof is not None and proof.board.timeline == 0
    _disable_proofs(monkeypatch)
    result = ActionSearch(max_states=None, max_depth=None, max_seconds=None).find_legal_action(engine)
    assert not result.has_legal_action and not result.exhausted
    assert engine_state_signature(engine) == before


def test_inactive_incoming_move_can_advance_an_empty_required_board():
    engine = _immobile_engine()
    manager = engine.timeline_manager
    manager.timelines[0].positions[0] = _position(0, 0, [])
    manager.timelines[1].positions[0] = _position(1, 0, [])
    manager.timelines[2] = Timeline(2, owner=ChessColor.WHITE,
        positions={0: _position(2, 0, [(3, 3, 'R'), (7, 7, 'K'), (7, 0, 'k')])})
    manager._next_positive_id = 3
    assert prove_required_board_immobile(engine, lambda: False) is None
    move = next(m for m in engine.get_legal_moves(manager.timelines[2].positions[0])
                if m.destination.board.timeline == 0)
    assert engine.execute_action_move(move) and engine.can_submit_action()


def test_clear_ray_to_future_lanes_is_not_immobility_evidence():
    engine = _immobile_engine()
    manager = engine.timeline_manager
    # Arrival on this old board cannot fix its local check, but the clear L ray
    # might reach a safe board on a future new lane. Conservatively decline.
    manager.timelines[1].positions[0] = _position(1, 0, [(7, 7, 'K'), (7, 0, 'r')])
    assert not engine.get_legal_moves(manager.timelines[0].positions[0])
    assert prove_required_board_immobile(engine, lambda: False) is None


def test_immobility_requires_fixed_activity_and_in_time_generation(monkeypatch):
    engine = _immobile_engine()
    engine.timeline_manager.timelines[-1] = Timeline(-1, owner=ChessColor.BLACK,
        positions={1: _position(-1, 1, [(7, 7, 'K'), (7, 0, 'k')])})
    engine.timeline_manager._next_negative_id = -2
    assert prove_required_board_immobile(engine, lambda: False) is None
    engine = _immobile_engine()
    expired = False
    def delayed_moves(*args):
        nonlocal expired
        expired = True
        return []
    monkeypatch.setattr(engine, 'get_legal_moves', delayed_moves)
    assert prove_required_board_immobile(engine, lambda: expired) is None


def test_captured_immobile_required_board_is_stalemate():
    engine = _captured_engine('easy20_immobile_required_state')
    before = engine_state_signature(engine)
    proof = prove_required_board_immobile(engine, lambda: False)
    assert proof is not None and proof.board.timeline == -6
    result = ActionPlanner(_PRODUCTION_HYBRID_BUDGET).search(engine)
    assert not result.candidates and result.termination_reason is None
    assert result.explored_states == 1
    assert OutcomeRules.evaluate(engine).kind == OutcomeKind.STALEMATE
    assert engine_state_signature(engine) == before


def test_certificate_matches_exhaustive_canonical_search(monkeypatch):
    engine = _engine()
    signature = engine_state_signature(engine)
    proof = prove_required_board_threat(engine, lambda: False)
    assert proof is not None and proof.board.timeline == 0
    fast = ActionSearch(max_states=None, max_depth=None, max_seconds=None).find_legal_action(engine)
    _disable_proofs(monkeypatch)
    exhaustive = ActionSearch(max_states=None, max_depth=None, max_seconds=None).find_legal_action(engine)
    assert not fast.has_legal_action and not exhaustive.has_legal_action
    assert fast.termination_reason is exhaustive.termination_reason is None
    assert fast.explored_states == 1 < exhaustive.explored_states
    assert engine_state_signature(engine) == signature


def test_geometric_capture_prevents_certificate_and_is_a_real_escape():
    engine = _engine()
    position = engine.timeline_manager.timelines[0].positions[0]
    position.set_piece(0, 7, Piece(PieceType.ROOK, ChessColor.WHITE))
    assert prove_required_board_threat(engine, lambda: False) is None
    move = next(m for m in engine.get_legal_moves(position) if (m.source.x, m.source.y, m.destination.x, m.destination.y) == (0, 7, 0, 0))
    assert engine.execute_action_move(move)
    assert engine.can_submit_action()


def test_black_certificate_matches_exhaustive_search(monkeypatch):
    engine = _engine()
    manager = engine.timeline_manager
    manager.timelines = {
        0: Timeline(0, positions={1: _position(0, 1, [(0, 0, 'R'), (7, 0, 'K'), (7, 7, 'k')])}),
        -1: Timeline(-1, owner=ChessColor.BLACK,
            positions={2: _position(-1, 2, [(0, 0, 'k'), (7, 0, 'K')])}),
    }
    manager._next_positive_id = 1
    manager._next_negative_id = -2
    engine.current_turn_color = ChessColor.BLACK
    engine.current_action = ActionRules.begin(ChessColor.BLACK, manager.timelines)
    assert prove_required_board_threat(engine, lambda: False) is not None
    _disable_proofs(monkeypatch)
    exhaustive = ActionSearch(max_states=None, max_depth=None, max_seconds=None).find_legal_action(engine)
    assert not exhaustive.has_legal_action and not exhaustive.exhausted


@pytest.mark.parametrize('clear_path', [False, True])
def test_optional_capture_source_and_missing_immutable_path(clear_path):
    engine = _engine()
    engine.timeline_manager.timelines[2] = Timeline(2, owner=ChessColor.WHITE,
        positions={0: _position(2, 0, [(0, 0, 'R'), (7, 7, 'K'), (7, 0, 'k')])})
    engine.timeline_manager._next_positive_id = 3
    engine.timeline_manager.refresh_activity()
    assert not engine.timeline_manager.timelines[2].is_active
    if clear_path:
        engine.timeline_manager.timelines[1].positions[0] = _position(
            1, 0, [(7, 7, 'K'), (7, 0, 'k')],
        )
    # A new lane >=3 cannot fill the missing intermediate White board on lane1.
    # With the path supplied, the inactive source is a real canonical escape.
    proof = prove_required_board_threat(engine, lambda: False)
    assert (proof is None) == clear_path
    if clear_path:
        position = engine.timeline_manager.timelines[2].positions[0]
        move = next(m for m in engine.get_legal_moves_from_square(position, 0, 0)
                    if m.destination.board.timeline == 0)
        assert engine.execute_action_move(move)
        assert engine.can_submit_action()


def test_locally_pinned_capture_cannot_become_legal_later(monkeypatch):
    engine = _engine()
    manager = engine.timeline_manager
    manager.timelines[0].positions[0] = _position(
        0, 0, [(3, 0, 'r'), (7, 0, 'k'), (0, 3, 'r'), (3, 3, 'R'), (7, 3, 'K')],
    )
    manager.timelines[1].positions[1] = _position(1, 1, [(3, 0, 'K'), (7, 0, 'k')])
    proof = prove_required_board_threat(engine, lambda: False)
    assert proof is not None and (proof.threat.attacker.x, proof.threat.attacker.y) == (3, 0)
    _disable_proofs(monkeypatch)
    exhaustive = ActionSearch(max_states=None, max_depth=None, max_seconds=None).find_legal_action(engine)
    assert not exhaustive.has_legal_action and not exhaustive.exhausted


def test_two_fixed_attackers_cannot_both_be_removed(monkeypatch):
    engine = _engine()
    manager = engine.timeline_manager
    position = manager.timelines[0].positions[0]
    position.set_piece(1, 0, Piece(PieceType.ROOK, ChessColor.BLACK))
    for x in (0, 1):
        position.set_piece(x, 7, Piece(PieceType.ROOK, ChessColor.WHITE))
        assert any(m.destination.x == x and m.destination.y == 0
                   for m in engine.get_legal_moves_from_square(position, x, 7))
    manager.timelines[2] = Timeline(2, owner=ChessColor.WHITE,
        positions={1: _position(2, 1, [(1, 0, 'K'), (7, 0, 'k')])})
    manager._next_positive_id = 3
    proof = prove_required_board_threat(engine, lambda: False)
    assert proof is not None and proof.other_threat is not None
    assert proof.threat.attacker != proof.other_threat.attacker
    _disable_proofs(monkeypatch)
    exhaustive = ActionSearch(max_states=None, max_depth=None, max_seconds=None).find_legal_action(engine)
    assert not exhaustive.has_legal_action and not exhaustive.exhausted


def test_one_attacker_with_two_targets_still_has_capture_escape():
    engine = _engine()
    manager = engine.timeline_manager
    manager.timelines[1].positions[1] = _position(1, 1, [(1, 1, 'K'), (7, 0, 'k')])
    manager.timelines[2] = Timeline(2, owner=ChessColor.WHITE,
        positions={1: _position(2, 1, [(0, 0, 'K'), (7, 0, 'k')])})
    manager._next_positive_id = 3
    # Queen at (0,0) attacks both historical Kings; these are not two attackers.
    position = manager.timelines[0].positions[0]
    position.set_piece(0, 0, Piece(PieceType.QUEEN, ChessColor.BLACK))
    position.set_piece(0, 7, Piece(PieceType.ROOK, ChessColor.WHITE))
    # Keep the local White King out of the Queen's diagonal.
    position.set_piece(7, 7, None)
    position.set_piece(7, 6, Piece(PieceType.KING, ChessColor.WHITE))
    assert prove_required_board_threat(engine, lambda: False) is None
    move = next(m for m in engine.get_legal_moves_from_square(position, 0, 7)
                if m.destination.x == 0 and m.destination.y == 0)
    assert engine.execute_action_move(move) and engine.can_submit_action()


def test_second_attacker_against_virtual_king_can_be_evaded():
    engine = _engine()
    manager = engine.timeline_manager
    position = manager.timelines[0].positions[0]
    position.set_piece(1, 0, Piece(PieceType.ROOK, ChessColor.BLACK))
    position.set_piece(0, 7, Piece(PieceType.ROOK, ChessColor.WHITE))
    manager.timelines[2] = Timeline(2, owner=ChessColor.WHITE,
        positions={0: _position(2, 0, [(1, 0, 'K'), (7, 0, 'k')])})
    manager.timelines[-1] = Timeline(-1, owner=ChessColor.BLACK,
        positions={1: _position(-1, 1, [(7, 7, 'K'), (7, 0, 'k')])})
    manager._next_positive_id = 3
    manager._next_negative_id = -2
    assert prove_required_board_threat(engine, lambda: False) is None
    move = next(m for m in engine.get_legal_moves(manager.timelines[2].positions[0])
                if m.is_spatial and m.destination.x == 2 and m.destination.y == 1)
    assert engine.execute_action_move(move)
    capture = next(m for m in engine.get_legal_moves_from_square(position, 0, 7)
                   if m.destination.x == 0 and m.destination.y == 0)
    assert engine.execute_action_move(capture) and engine.can_submit_action()


def test_direct_threat_matches_exhaustive_search_with_optional_moves(monkeypatch):
    engine = _engine()
    # Materialize the attack by making an otherwise legal King move on L0.
    move = next(m for m in engine.get_legal_moves() if m.piece.piece_type == PieceType.KING)
    assert engine.execute_action_move(move)
    manager = engine.timeline_manager
    manager.timelines[2] = Timeline(2, owner=ChessColor.WHITE,
        positions={0: _position(2, 0, [(7, 7, 'K'), (7, 0, 'k')])})
    manager._next_positive_id = 3
    signature = engine_state_signature(engine)
    assert ActionRules.movable_boards(engine.current_action, manager.timelines)
    proof = prove_direct_threat(engine, lambda: False)
    assert proof is not None
    fast = ActionSearch(max_states=None, max_depth=None, max_seconds=None).find_legal_action(engine)
    _disable_proofs(monkeypatch)
    exhaustive = ActionSearch(max_states=None, max_depth=None, max_seconds=None).find_legal_action(engine)
    assert not fast.has_legal_action and not exhaustive.has_legal_action
    assert fast.termination_reason is exhaustive.termination_reason is None
    assert fast.explored_states == 1 < exhaustive.explored_states
    assert engine_state_signature(engine) == signature


def test_virtual_threat_and_unadvanced_present_are_not_direct_proof():
    engine = _engine()
    assert not engine.can_submit_action()
    assert prove_direct_threat(engine, lambda: False) is None
    position = engine.timeline_manager.timelines[0].positions[0]
    position.set_piece(0, 7, Piece(PieceType.ROOK, ChessColor.WHITE))
    result = ActionSearch(max_states=None, max_depth=None, max_seconds=None).find_legal_action(engine)
    assert result.has_legal_action


def test_late_direct_threat_scan_never_yields_certificate():
    engine = _engine()
    move = next(m for m in engine.get_legal_moves() if m.piece.piece_type == PieceType.KING)
    assert engine.execute_action_move(move)
    ticks = iter([False, True])
    assert prove_direct_threat(engine, lambda: next(ticks)) is None


def test_late_capture_generation_never_yields_certificate(monkeypatch):
    engine = _engine()
    engine.timeline_manager.timelines[0].positions[0].set_piece(
        0, 7, Piece(PieceType.ROOK, ChessColor.WHITE),
    )
    expired = False
    def delayed_moves(*args, **kwargs):
        nonlocal expired
        expired = True
        return []
    monkeypatch.setattr(engine, 'get_legal_moves_from_square', delayed_moves)
    assert prove_required_board_threat(engine, lambda: expired) is None


@pytest.mark.parametrize('mutation', ['active_branch', 'activate_opponent', 'allocation', 'owner'])
def test_activity_and_allocation_preconditions_fail_closed(mutation):
    engine = _engine()
    manager = engine.timeline_manager
    if mutation == 'active_branch':
        manager.timelines[-1] = Timeline(-1, owner=ChessColor.BLACK,
            positions={1: _position(-1, 1, [(7, 7, 'K'), (7, 0, 'k')])})
        manager._next_negative_id = -2
    elif mutation == 'activate_opponent':
        manager.timelines[-3] = Timeline(-3, owner=ChessColor.BLACK,
            positions={1: _position(-3, 1, [(7, 7, 'K'), (7, 0, 'k')])})
        manager._next_negative_id = -4
    elif mutation == 'allocation':
        manager._next_positive_id = 1
    else:
        manager.timelines[1].owner = ChessColor.BLACK
    assert prove_required_board_threat(engine, lambda: False) is None


def test_virtual_pass_king_is_not_immutable_evidence():
    engine = _engine()
    engine.timeline_manager.timelines[1].positions = {
        0: _position(1, 0, [(0, 0, 'K'), (7, 0, 'k')]),
    }
    # Moving this King on its own required board can avoid the virtual threat.
    assert prove_required_board_threat(engine, lambda: False) is None


def test_active_branch_can_defer_the_threatened_required_board():
    engine = _engine()
    manager = engine.timeline_manager
    manager.timelines[0].positions = {
        0: _position(0, 0, [(7, 0, 'k'), (7, 7, 'K')]),
        2: _position(0, 2, [(0, 0, 'r'), (7, 0, 'k'), (7, 7, 'K')]),
    }
    manager.timelines[1].positions = {3: _position(1, 3, [(0, 0, 'K'), (7, 0, 'k')])}
    manager.timelines[-1] = Timeline(-1, owner=ChessColor.BLACK,
        positions={2: _position(-1, 2, [(0, 7, 'Q'), (7, 7, 'K'), (7, 0, 'k')])})
    manager._next_negative_id = -2
    manager.refresh_activity()
    engine.current_action = ActionRules.begin(ChessColor.WHITE, manager.timelines)
    assert prove_required_board_threat(engine, lambda: False) is None
    move = next(m for m in engine.get_legal_moves(manager.timelines[-1].positions[2])
                if m.is_branching and m.source.x == 0 and m.source.y == 7
                and m.destination.board == BoardCoord(0, 0, ChessColor.WHITE)
                and m.destination.x == 0 and m.destination.y == 7)
    assert engine.execute_action_move(move)
    assert manager.timelines[0].latest_time == 2  # threatened board was not advanced
    assert engine.can_submit_action()


def test_virtual_pass_path_cannot_be_treated_as_fixed():
    engine = _engine()
    manager = engine.timeline_manager
    manager.timelines[1].positions = {0: _position(1, 0, [(7, 7, 'K'), (7, 0, 'k')])}
    manager.timelines[2] = Timeline(2, owner=ChessColor.WHITE,
        positions={1: _position(2, 1, [(0, 0, 'K'), (7, 0, 'k')])})
    manager.timelines[-1] = Timeline(-1, owner=ChessColor.BLACK,
        positions={1: _position(-1, 1, [(7, 7, 'K'), (7, 0, 'k')])})
    manager._next_positive_id = 3
    manager._next_negative_id = -2
    assert prove_required_board_threat(engine, lambda: False) is None


def test_interruption_never_yields_certificate():
    engine = _engine()
    ticks = iter([False, True])
    assert prove_required_board_threat(engine, lambda: next(ticks)) is None
    result = ActionSearch(max_seconds=0).find_legal_action(engine)
    assert result.exhausted and result.termination_reason == 'time_budget'


def test_durable_seed53_state_is_proven_without_budget_exhaustion():
    engine = _captured_engine()
    before = engine_state_signature(engine)
    assert engine.move_counter == 43 and len(engine.action_history) == 40
    proof = prove_required_board_threat(engine, lambda: False)
    assert proof is not None and proof.board == BoardCoord(0, 12, ChessColor.WHITE)
    planner = ActionPlanner(_PRODUCTION_HYBRID_BUDGET).search(engine)
    assert planner.candidates == () and planner.termination_reason is None
    assert planner.explored_states == 1
    outcome = OutcomeRules.evaluate(engine)
    assert outcome.kind == OutcomeKind.CHECKMATE
    assert outcome.winner == ChessColor.BLACK
    assert engine_state_signature(engine) == before


@pytest.mark.parametrize('fixture', [
    'easy20_pinned_bishop_state', 'easy20_pinned_queen_state',
    'easy20_two_fixed_attackers_state',
])
def test_captured_locally_illegal_defense_is_proven_terminal(fixture):
    engine = _captured_engine(fixture)
    before = engine_state_signature(engine)
    assert prove_required_board_threat(engine, lambda: False) is not None
    planner = ActionPlanner(_PRODUCTION_HYBRID_BUDGET).search(engine)
    assert planner.candidates == () and planner.termination_reason is None
    assert planner.explored_states == 1
    outcome = OutcomeRules.evaluate(engine)
    assert outcome.kind == OutcomeKind.CHECKMATE
    assert outcome.winner == engine.current_turn_color.opposite()
    assert engine_state_signature(engine) == before


def test_captured_queen_has_replayable_complete_defenses():
    engine = _captured_engine('easy20_capturable_queen_state')
    before = engine_state_signature(engine)
    assert prove_required_board_threat(engine, lambda: False) is None
    result = ActionPlanner(_PRODUCTION_HYBRID_BUDGET).search(engine)
    assert result.candidates
    for candidate in result.candidates:
        child = engine.clone_for_simulation()
        apply_action_plan(child, AIActionPlan(engine.current_turn_color, candidate, before))
        assert child.action_history[-1].submitted
    assert engine_state_signature(engine) == before


@pytest.mark.parametrize('fixture', [
    'hard20_rewind_four_state', 'hard20_rewind_three_state',
    'hard20_fixed_successors_terminal_state',
])
def test_successor_filter_matches_canonical_direct_threat(fixture):
    engine = _captured_engine(fixture)
    before = engine_state_signature(engine)
    attackers = fixed_successor_attackers(engine, lambda: False)
    assert attackers
    rejected = allowed = branches = 0
    for board in ActionRules.movable_boards(engine.current_action, engine.timeline_manager.timelines):
        for move in engine.get_legal_moves(engine._resolve_position(board)):
            if not move_exposes_fixed_attacker(move, attackers):
                allowed += 1
                branches += move.is_branching
                continue
            rejected += 1
            child = engine.clone_for_simulation()
            assert child.execute_action_move(move)
            assert prove_direct_threat(child, lambda: False) is not None
    assert rejected and allowed and branches
    assert engine_state_signature(engine) == before


def test_successor_filter_preserves_capture_and_ignores_virtual_targets():
    engine = _engine()
    position = engine.timeline_manager.timelines[0].positions[0]
    position.set_piece(0, 7, Piece(PieceType.ROOK, ChessColor.WHITE))
    attackers = fixed_successor_attackers(engine, lambda: False)
    capture = next(move for move in engine.get_legal_moves(position)
                   if move.destination.x == 0 and move.destination.y == 0)
    assert attackers and not move_exposes_fixed_attacker(capture, attackers)
    assert engine.execute_action_move(capture) and engine.can_submit_action()
    engine = _engine()
    engine.timeline_manager.timelines[1].positions = {
        0: _position(1, 0, [(0, 0, 'K'), (7, 0, 'k')]),
    }
    assert fixed_successor_attackers(engine, lambda: False) == {}


def test_successor_scan_interruption_never_returns_partial_certificate():
    engine = _engine()
    assert fixed_successor_attackers(engine, lambda: True) is None
    ticks = iter([False, False, True])
    assert fixed_successor_attackers(engine, lambda: next(ticks)) is None


def test_black_successor_filter_preserves_the_capturing_escape():
    engine = _engine()
    manager = engine.timeline_manager
    manager.timelines = {
        0: Timeline(0, positions={1: _position(0, 1, [
            (0, 0, 'R'), (7, 0, 'K'), (0, 7, 'r'), (7, 7, 'k'),
        ])}),
        -1: Timeline(-1, owner=ChessColor.BLACK,
                     positions={2: _position(-1, 2, [(0, 0, 'k'), (7, 0, 'K')])}),
    }
    manager._next_positive_id = 1
    manager._next_negative_id = -2
    engine.current_turn_color = ChessColor.BLACK
    engine.current_action = ActionRules.begin(ChessColor.BLACK, manager.timelines)
    attackers = fixed_successor_attackers(engine, lambda: False)
    assert attackers
    capture = None
    for move in engine.get_legal_moves(manager.timelines[0].positions[1]):
        if move_exposes_fixed_attacker(move, attackers):
            child = engine.clone_for_simulation()
            assert child.execute_action_move(move)
            assert prove_direct_threat(child, lambda: False) is not None
        elif move.destination.x == 0 and move.destination.y == 0:
            capture = move
    assert capture is not None
    assert engine.execute_action_move(capture) and engine.can_submit_action()


def test_successor_filter_checks_the_nonbranching_arrival_board():
    engine = _engine()
    manager = engine.timeline_manager
    manager.timelines[1].positions[0] = _position(1, 0, [])
    manager.timelines[2] = Timeline(2, owner=ChessColor.WHITE,
        positions={0: _position(2, 0, [
            (0, 0, 'R'), (0, 7, 'R'), (7, 7, 'K'), (7, 0, 'k'),
        ])})
    manager._next_positive_id = 3
    attackers = fixed_successor_attackers(engine, lambda: False)
    arrivals = [move for move in engine.get_legal_moves(manager.timelines[2].positions[0])
                if move.destination.board == BoardCoord(0, 0, ChessColor.WHITE)]
    capture = next(move for move in arrivals if move.destination.y == 0)
    quiet = next(move for move in arrivals if move.destination.y == 7)
    assert not capture.is_branching and not quiet.is_branching
    assert not move_exposes_fixed_attacker(capture, attackers)
    assert move_exposes_fixed_attacker(quiet, attackers)
    child = engine.clone_for_simulation()
    assert child.execute_action_move(quiet)
    assert prove_direct_threat(child, lambda: False) is not None
    assert engine.execute_action_move(capture) and engine.can_submit_action()
