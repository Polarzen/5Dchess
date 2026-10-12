"""Branch pruning must prove a canonical, irreversible royal attack."""
import gzip
import json
from pathlib import Path

import pytest

from src.ai.action_planner import (
    ActionPlanner, ActionSearchBudget,
    engine_state_signature,
)
from src.data.archive import GameArchive
from src.engine import ActionRules, FiveDEngine, Position, Timeline
from src.engine.action_proof import fixed_branch_arrival_attackers, prove_direct_threat
from src.engine.coordinates import BoardCoord, Square5D
from src.engine.piece import Piece
from src.utils.constants import ChessColor, PieceType


def _arrival_engine(color=ChessColor.WHITE):
    engine = FiveDEngine()
    offset = int(color == ChessColor.BLACK)

    def position(time, pieces):
        board = [[''] * 8 for _ in range(8)]
        for x, y, symbol in pieces:
            board[y][x] = symbol if not offset else symbol.swapcase()
        return Position(board, BoardCoord.legacy_side_for_time_point(time), 0, time,
                        unmoved_pawns=set())

    engine.timeline_manager.timelines = {0: Timeline(0, positions={
        offset: position(offset, [(2, 2, 'r'), (7, 7, 'K'), (7, 0, 'k')]),
        offset + 1: position(offset + 1, [(2, 2, 'K'), (7, 0, 'k')]),
        offset + 2: position(offset + 2, [(2, 3, 'Q'), (7, 7, 'K'), (7, 0, 'k')]),
    })}
    engine.current_turn_color = color
    engine.current_action = ActionRules.begin(color, engine.timeline_manager.timelines)
    return engine, BoardCoord.from_legacy_time_point(0, offset)


@pytest.mark.parametrize('color', list(ChessColor))
def test_branch_certificate_preserves_capturing_escape(color):
    engine, destination = _arrival_engine(color)
    before = engine_state_signature(engine)
    attackers = fixed_branch_arrival_attackers(engine, destination, lambda: False)
    assert attackers == {Square5D(destination, 2, 2)}
    timeline = engine.timeline_manager.timelines[0]
    source = timeline.positions[timeline.latest_time]
    arrivals = [move for move in engine.get_legal_moves(source)
                if move.is_branching and move.destination.board == destination]
    rejected = 0
    capture = None
    for move in arrivals:
        child = engine.clone_for_simulation()
        assert child.execute_action_move(move)
        if move.destination in attackers:
            capture = move
            assert child.can_submit_action()
        else:
            rejected += 1
            assert prove_direct_threat(child, lambda: False) is not None
    assert capture is not None and rejected
    assert engine_state_signature(engine) == before


def test_missing_path_and_pawn_are_not_certificates():
    engine, destination = _arrival_engine()
    engine.timeline_manager._next_positive_id = 2  # L1 path does not exist.
    assert fixed_branch_arrival_attackers(engine, destination, lambda: False) == set()
    engine.timeline_manager._next_positive_id = 1
    engine._resolve_position(destination).set_piece(2, 2, Piece(PieceType.PAWN, ChessColor.BLACK))
    assert fixed_branch_arrival_attackers(engine, destination, lambda: False) == set()


def test_interrupted_branch_scan_is_not_an_empty_certificate():
    engine, destination = _arrival_engine()
    assert fixed_branch_arrival_attackers(engine, destination, lambda: True) is None
    ticks = iter([False, True])
    assert fixed_branch_arrival_attackers(engine, destination, lambda: next(ticks)) is None


def test_captured_branch_rejections_have_canonical_threats():
    path = Path(__file__).parent / 'fixtures/hard20_eight_required_rewind_state.json.gz'
    engine = GameArchive.restore(json.loads(gzip.decompress(path.read_bytes())))
    del engine._replay_origin
    before = engine_state_signature(engine)
    cache = {}
    rejected = 0
    for source in ActionRules.movable_boards(engine.current_action, engine.timeline_manager.timelines):
        for move in engine.get_legal_moves(engine._resolve_position(source)):
            if not move.is_branching:
                continue
            board = move.destination.board
            if board not in cache:
                cache[board] = fixed_branch_arrival_attackers(engine, board, lambda: False)
            if not any(move.destination != square for square in cache[board]):
                continue
            child = engine.clone_for_simulation()
            assert child.execute_action_move(move)
            assert prove_direct_threat(child, lambda: False) is not None
            rejected += 1
    assert rejected >= 20  # The real slow prefix is covered, not just a toy board.
    assert engine_state_signature(engine) == before


def test_probe_avoids_cloning_certified_arrivals(monkeypatch):
    engine, destination = _arrival_engine()
    original = FiveDEngine.execute_action_move

    def checked(self, move):
        if move.is_branching and move.destination.board == destination:
            assert (move.destination.x, move.destination.y) == (2, 2)
        return original(self, move)

    monkeypatch.setattr(FiveDEngine, 'execute_action_move', checked)
    result = ActionPlanner(ActionSearchBudget(1024, 1, 1, None),
                           strategy='probe_then_depth_first').search(engine)
    assert result.candidates
