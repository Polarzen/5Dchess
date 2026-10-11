"""Timeline capacity affects executable legal Moves and terminal proofs."""
import gzip
import json
from pathlib import Path

import pytest

from src.ai.action_planner import ActionPlanner, _PRODUCTION_HYBRID_BUDGET, engine_state_signature
from src.data.archive import GameArchive
from src.engine import ActionRules, ActionSearch, FiveDEngine, Position, Timeline
from src.engine.action_proof import prove_required_board_immobile
from src.engine.coordinates import BoardCoord
from src.engine.move_generator import MoveGenerator
from src.engine.move_validator import MoveValidator
from src.engine.outcome_rules import OutcomeKind, OutcomeRules
from src.utils.constants import ChessColor


def _captured():
    file = Path(__file__).parent / 'fixtures/seed42_full_capacity_state.json.gz'
    engine = GameArchive.restore(json.loads(gzip.decompress(file.read_bytes())))
    del engine._replay_origin
    return engine


def test_full_capacity_lists_exactly_the_executable_nonbranching_moves():
    engine = _captured()
    before = engine_state_signature(engine)
    manager = engine.timeline_manager
    assert len(manager.timelines) == manager.max_timelines
    branching_count = 0
    for board in ActionRules.movable_boards(engine._ensure_current_action(), manager.timelines):
        position = engine._resolve_position(board)
        raw = MoveValidator(manager.timelines).filter_legal_moves(
            position, MoveGenerator(position, manager.timelines).generate_all())
        branching_count += sum(move.is_branching for move in raw)
        expected = [move for move in raw if not move.is_branching]
        assert engine.get_legal_moves(position) == expected
        for move in raw:
            child = engine.clone_for_simulation()
            assert child.execute_action_move(move) == (not move.is_branching)
        for x, y in {(move.source.x, move.source.y) for move in raw}:
            assert engine.get_legal_moves_from_square(position, x, y) == [
                move for move in expected if (move.source.x, move.source.y) == (x, y)]
    assert branching_count > 0
    assert engine_state_signature(engine) == before


def test_capacity_certificate_proves_captured_seed42_stalemate():
    engine = _captured()
    before = engine_state_signature(engine)
    proof = prove_required_board_immobile(engine, lambda: False)
    assert proof is not None and proof.board.timeline == 10
    result = ActionPlanner(_PRODUCTION_HYBRID_BUDGET).search(engine)
    assert not result.candidates and result.termination_reason is None
    assert result.explored_states == 1
    assert OutcomeRules.evaluate(engine).kind == OutcomeKind.STALEMATE
    assert engine_state_signature(engine) == before


@pytest.mark.parametrize('color', list(ChessColor))
def test_capacity_removes_future_destinations_exhaustively(monkeypatch, color):
    white = color == ChessColor.WHITE
    lane, time = (1, 0) if white else (-1, 1)
    own_rook, own_king, enemy_rook = ('R', 'K', 'r') if white else ('r', 'k', 'R')
    def position(lane, time, pieces):
        cells = [[''] * 8 for _ in range(8)]
        for x, y, char in pieces:
            cells[y][x] = char
        return Position(cells, BoardCoord.legacy_side_for_time_point(time), lane, time)
    engine = FiveDEngine()
    manager = engine.timeline_manager
    manager.timelines = {
        0: Timeline(0, positions={time: position(0, time, [(3, 3, own_rook)])}),
        lane: Timeline(lane, owner=color, positions={
            time: position(lane, time, [(7, 7, own_king), (7, 0, enemy_rook)]),
            time + 1: position(lane, time + 1, [(7, 7, own_king)]),
        }),
    }
    manager._next_positive_id = 2 if white else 1
    manager._next_negative_id = -1 if white else -2
    engine.current_turn_color = color
    engine.current_action = ActionRules.begin(color, manager.timelines)
    # A clear ray toward future lanes prevents a proof while branches are possible.
    assert prove_required_board_immobile(engine, lambda: False) is None
    manager.max_timelines = len(manager.timelines)
    assert prove_required_board_immobile(engine, lambda: False) is not None
    for name in ['prove_direct_threat', 'prove_required_board_threat', 'prove_required_board_immobile']:
        monkeypatch.setattr(f'src.engine.action_search.{name}', lambda *args: None)
    result = ActionSearch(max_states=None, max_depth=None, max_seconds=None).find_legal_action(engine)
    assert not result.has_legal_action and not result.exhausted


def test_spare_capacity_still_allows_existing_branch_moves():
    engine = _captured()
    engine.timeline_manager.max_timelines += 1
    board = next(b for b in engine.get_required_action_boards() if b.timeline == 10)
    moves = engine.get_legal_moves(engine._resolve_position(board))
    assert moves and all(move.is_branching for move in moves)
    child = engine.clone_for_simulation()
    assert child.execute_action_move(moves[0])
    assert len(child.timeline_manager.timelines) == len(engine.timeline_manager.timelines) + 1
    assert prove_required_board_immobile(engine, lambda: False) is None
