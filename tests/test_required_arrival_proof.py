"""Targeted move generation and forced arrival safety at timeline capacity."""
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
from src.engine.action_proof import prove_required_board_immobile
from src.engine.coordinates import BoardCoord
from src.engine.move_generator import MoveGenerator
from src.engine.outcome_rules import OutcomeKind, OutcomeRules
from src.utils.constants import ChessColor


def _captured(name):
    path = Path(__file__).parent / 'fixtures' / f'{name}.json.gz'
    engine = GameArchive.restore(json.loads(gzip.decompress(path.read_bytes())))
    del engine._replay_origin
    return engine


@pytest.mark.parametrize('fixture', [
    'seed43_required_arrival_state', 'seed43_forced_unsafe_source_state',
    'hard20_six_required_state',
])
def test_targeted_generation_matches_full_canonical_subset(fixture):
    engine = _captured(fixture)
    before = engine_state_signature(engine)
    manager = engine.timeline_manager
    targets = set(engine.get_required_action_boards())
    for board in ActionRules.movable_boards(engine._ensure_current_action(), manager.timelines):
        position = engine._resolve_position(board)
        full = MoveGenerator(position, manager.timelines).generate_all()
        for allow_branching in (False, True):
            generator = MoveGenerator(position, manager.timelines,
                                      allow_branching=allow_branching, destination_boards=targets)
            expected = [move for move in full if move.destination.board in targets
                        and (allow_branching or not move.is_branching)]
            assert generator.generate_all() == expected
            for x, y, _piece in position.get_all_pieces(engine.current_turn_color):
                assert generator.generate_from_square(x, y) == [
                    move for move in expected if (move.source.x, move.source.y) == (x, y)]
        legal = engine.get_legal_moves(position)
        assert engine.get_legal_moves_to_boards(position, targets) == [
            move for move in legal if move.destination.board in targets]
        assert engine.get_legal_moves_to_boards(position, set()) == []
    assert engine_state_signature(engine) == before


def test_one_required_board_uses_its_optional_arrival():
    engine = _captured('seed43_required_arrival_state')
    before = engine_state_signature(engine)
    required = engine.get_required_action_boards()
    assert len(required) == 1
    assert engine.get_legal_moves(engine._resolve_position(required[0])) == []
    result = ActionPlanner(_PRODUCTION_HYBRID_BUDGET).search(engine)
    assert result.candidates and len(result.candidates[0]) == 1
    assert result.candidates[0][0].source.board not in required
    child = engine.clone_for_simulation()
    apply_action_plan(child, AIActionPlan(engine.current_turn_color, result.candidates[0], before))
    assert child.action_history[-1].submitted
    assert engine_state_signature(engine) == before


def test_captured_forced_arrival_is_proven_terminal():
    engine = _captured('seed43_forced_unsafe_source_state')
    before = engine_state_signature(engine)
    proof = prove_required_board_immobile(engine, lambda: False)
    assert proof is not None and proof.forced_source_threat is not None
    assert proof.board.timeline == -15
    result = ActionPlanner(_PRODUCTION_HYBRID_BUDGET).search(engine)
    assert result.candidates == () and result.termination_reason is None
    assert result.explored_states == 1
    assert OutcomeRules.evaluate(engine).kind == OutcomeKind.STALEMATE
    assert engine_state_signature(engine) == before


@pytest.mark.parametrize('fixture', [
    'seed43_twenty_seven_required_state', 'seed43_twenty_eight_required_state',
])
def test_large_frontier_keeps_complete_candidates_in_primary_budget(fixture):
    engine = _captured(fixture)
    before = engine_state_signature(engine)
    result = ActionPlanner(_PRODUCTION_HYBRID_BUDGET).search(engine)
    assert 0 < len(result.candidates) <= 24
    assert result.explored_states <= 1024
    assert 0 < len(result.candidates[0]) <= 32
    child = engine.clone_for_simulation()
    apply_action_plan(child, AIActionPlan(engine.current_turn_color, result.candidates[0], before))
    assert child.action_history[-1].submitted
    assert engine_state_signature(engine) == before


def _forced_source(color, *, alternate=False, attacker=True):
    white = color == ChessColor.WHITE
    target_time = 0 if white else 1
    source_time = target_time + 2
    king, queen, bishop, knight = ('K', 'Q', 'b', 'N') if white else ('k', 'q', 'B', 'n')

    def position(lane, time, pieces):
        cells = [[''] * 8 for _ in range(8)]
        for x, y, symbol in pieces:
            cells[y][x] = symbol
        return Position(cells, BoardCoord.legacy_side_for_time_point(time), lane, time)

    source_pieces = [(0, 3, queen)] + ([(5, 0, bishop)] if attacker else [])
    engine = FiveDEngine()
    manager = engine.timeline_manager
    manager.timelines = {
        0: Timeline(0, positions={
            source_time - 1: position(0, source_time - 1, [(4, 0, king)]),
            source_time: position(0, source_time, source_pieces),
        }),
        1: Timeline(1, owner=ChessColor.WHITE,
                    positions={target_time: position(1, target_time, [])}),
    }
    if alternate:
        manager.timelines[-1] = Timeline(-1, owner=ChessColor.BLACK,
            positions={source_time: position(-1, source_time, [(0, 3, knight)])})
    manager.max_timelines = len(manager.timelines)
    manager._next_positive_id = 2
    manager._next_negative_id = -2 if alternate else -1
    engine.current_turn_color = color
    engine.current_action = ActionRules.begin(color, manager.timelines)
    return engine


@pytest.mark.parametrize('color', list(ChessColor))
@pytest.mark.parametrize('alternate,attacker,terminal', [
    (False, True, True), (True, True, False), (False, False, False),
])
def test_forced_source_certificate_matches_exhaustive_search(monkeypatch, color, alternate, attacker, terminal):
    engine = _forced_source(color, alternate=alternate, attacker=attacker)
    before = engine_state_signature(engine)
    proof = prove_required_board_immobile(engine, lambda: False)
    assert (proof is not None) == terminal
    if proof is not None:
        assert proof.forced_source_threat is not None
    for name in ('prove_direct_threat', 'prove_required_board_immobile', 'prove_required_board_threat'):
        monkeypatch.setattr(f'src.engine.action_search.{name}', lambda *args: None)
    result = ActionSearch(max_states=None, max_depth=None, max_seconds=None).find_legal_completion(engine)
    assert not result.exhausted
    assert result.has_legal_action != terminal
    assert engine_state_signature(engine) == before


def test_forced_source_certificate_declines_with_spare_capacity():
    engine = _forced_source(ChessColor.BLACK)
    assert prove_required_board_immobile(engine, lambda: False) is not None
    engine.timeline_manager.max_timelines += 1
    assert prove_required_board_immobile(engine, lambda: False) is None


def test_interrupted_forced_source_simulation_is_not_a_proof(monkeypatch):
    engine = _forced_source(ChessColor.BLACK)
    interrupted = [False]
    original = FiveDEngine.execute_action_move

    def delayed(self, move):
        result = original(self, move)
        interrupted[0] = True
        return result

    monkeypatch.setattr(FiveDEngine, 'execute_action_move', delayed)
    assert prove_required_board_immobile(engine, lambda: interrupted[0]) is None
