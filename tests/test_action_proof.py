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
from src.engine.action_proof import prove_direct_threat, prove_required_board_threat
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
    def delayed_moves(*args):
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


@pytest.mark.parametrize('fixture', ['easy20_pinned_bishop_state', 'easy20_pinned_queen_state'])
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
