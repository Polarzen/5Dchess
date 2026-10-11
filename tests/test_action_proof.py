"""Exact terminal certificates and counterexamples to broader pruning."""
import gzip
import json
from pathlib import Path

import pytest

from src.ai.action_planner import ActionPlanner, _PRODUCTION_HYBRID_BUDGET, engine_state_signature
from src.data.archive import GameArchive
from src.engine import ActionRules, ActionSearch, FiveDEngine, Position, Timeline
from src.engine.action_proof import prove_required_board_threat
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


def _captured_engine():
    fixture = Path(__file__).parent / 'fixtures/seed53_uncapturable_threat_state.json.gz'
    engine = GameArchive.restore(json.loads(gzip.decompress(fixture.read_bytes())))
    del engine._replay_origin
    return engine


def test_certificate_matches_exhaustive_canonical_search(monkeypatch):
    engine = _engine()
    signature = engine_state_signature(engine)
    proof = prove_required_board_threat(engine, lambda: False)
    assert proof is not None and proof.board.timeline == 0
    fast = ActionSearch(max_states=None, max_depth=None, max_seconds=None).find_legal_action(engine)
    monkeypatch.setattr('src.engine.action_search.prove_required_board_threat', lambda *args: None)
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
    monkeypatch.setattr('src.engine.action_search.prove_required_board_threat', lambda *args: None)
    exhaustive = ActionSearch(max_states=None, max_depth=None, max_seconds=None).find_legal_action(engine)
    assert not exhaustive.has_legal_action and not exhaustive.exhausted


def test_optional_source_is_included_even_when_capture_path_is_blocked():
    engine = _engine()
    engine.timeline_manager.timelines[2] = Timeline(2, owner=ChessColor.WHITE,
        positions={0: _position(2, 0, [(0, 0, 'R'), (7, 7, 'K'), (7, 0, 'k')])})
    engine.timeline_manager._next_positive_id = 3
    engine.timeline_manager.refresh_activity()
    assert not engine.timeline_manager.timelines[2].is_active
    # The intermediate White board on lane 1 is missing. Geometry alone still
    # refuses a certificate, even though this capture is currently blocked.
    assert prove_required_board_threat(engine, lambda: False) is None


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
