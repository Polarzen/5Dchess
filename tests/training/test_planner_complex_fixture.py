"""Deterministic complex-state regression coverage for ActionPlanner ordering.

The fixture is a fixed canonical Action trace captured once from the temporary
branch-heavy generator.  Replaying it never consults a model, RNG, planner
wall-clock budget, or engine internals: every recorded Move is resolved from
canonical legal moves, executed with ``execute_action_move`` and each Action is
finished with exactly one ``submit_action``.
"""
from __future__ import annotations

from copy import deepcopy
import json
import time
import warnings

import src.ai.action_planner as action_planner
from src.ai.action_planner import ActionPlanner, ActionSearchBudget, engine_state_signature
from src.engine import ActionRules, BoardCoord, FiveDEngine, Square5D
from src.utils.constants import ChessColor, PieceType


# Captured by CI run 33788877050 from the temporary no-wall-clock generator.
# The resulting state has 32 timelines, 32 required boards and move_counter=50.
FIXTURE_TRACE = json.loads(r'''[[{"destination":[0,0,"white",0,4],"promotion":null,"source":[0,0,"white",0,6]}],[{"destination":[0,0,"black",0,2],"promotion":null,"source":[0,0,"black",1,0]}],[{"destination":[0,0,"white",1,5],"promotion":null,"source":[0,1,"white",1,7]}],[{"destination":[0,0,"black",1,2],"promotion":null,"source":[1,0,"black",1,0]}],[{"destination":[-1,0,"white",1,5],"promotion":null,"source":[-1,1,"white",1,7]}],[{"destination":[1,0,"black",1,2],"promotion":null,"source":[2,0,"black",1,0]}],[{"destination":[-2,0,"white",1,3],"promotion":null,"source":[-2,1,"white",1,5]}],[{"destination":[2,0,"black",1,2],"promotion":null,"source":[3,0,"black",1,0]}],[{"destination":[-3,0,"white",1,3],"promotion":null,"source":[-3,1,"white",1,5]}],[{"destination":[3,0,"black",1,2],"promotion":null,"source":[4,0,"black",1,0]}],[{"destination":[-4,0,"white",1,1],"promotion":null,"source":[-4,1,"white",1,3]}],[{"destination":[4,0,"black",1,2],"promotion":null,"source":[5,0,"black",1,0]}],[{"destination":[-5,0,"white",1,1],"promotion":null,"source":[-5,1,"white",1,3]}],[{"destination":[5,0,"black",1,2],"promotion":null,"source":[6,0,"black",1,0]}],[{"destination":[-6,0,"white",3,1],"promotion":null,"source":[-6,1,"white",1,1]}],[{"destination":[5,0,"black",1,1],"promotion":null,"source":[7,0,"black",1,0]}],[{"destination":[-7,0,"white",1,5],"promotion":null,"source":[-7,1,"white",1,7]}],[{"destination":[6,0,"black",1,1],"promotion":null,"source":[8,0,"black",1,0]}],[{"destination":[-8,0,"white",1,5],"promotion":null,"source":[-8,1,"white",1,7]}],[{"destination":[8,0,"black",1,2],"promotion":null,"source":[9,0,"black",1,0]}],[{"destination":[-9,0,"white",1,3],"promotion":null,"source":[-9,1,"white",1,5]}],[{"destination":[9,0,"black",1,2],"promotion":null,"source":[10,0,"black",1,0]}],[{"destination":[-10,0,"white",1,3],"promotion":null,"source":[-10,1,"white",1,5]}],[{"destination":[10,0,"black",1,2],"promotion":null,"source":[11,0,"black",1,0]}],[{"destination":[-11,0,"white",1,1],"promotion":null,"source":[-11,1,"white",1,3]}],[{"destination":[11,0,"black",1,2],"promotion":null,"source":[12,0,"black",1,0]}],[{"destination":[-12,0,"white",1,1],"promotion":null,"source":[-12,1,"white",1,3]}],[{"destination":[12,0,"black",1,2],"promotion":null,"source":[13,0,"black",1,0]}],[{"destination":[-13,0,"white",3,1],"promotion":null,"source":[-13,1,"white",1,1]}],[{"destination":[12,0,"black",1,1],"promotion":null,"source":[14,0,"black",1,0]}],[{"destination":[-14,0,"white",1,5],"promotion":null,"source":[-14,1,"white",1,7]}],[{"destination":[13,0,"black",1,1],"promotion":null,"source":[15,0,"black",1,0]}],[{"destination":[-15,0,"white",1,5],"promotion":null,"source":[-15,1,"white",1,7]}],[{"destination":[16,0,"black",0,2],"promotion":null,"source":[16,0,"black",1,0]}],[{"destination":[1,1,"white",0,3],"promotion":null,"source":[1,1,"white",1,5]},{"destination":[2,1,"white",0,3],"promotion":null,"source":[2,1,"white",1,5]},{"destination":[3,1,"white",0,1],"promotion":null,"source":[3,1,"white",1,3]},{"destination":[4,1,"white",0,1],"promotion":null,"source":[4,1,"white",1,3]},{"destination":[5,1,"white",3,0],"promotion":null,"source":[5,1,"white",1,1]},{"destination":[6,1,"white",3,0],"promotion":null,"source":[6,1,"white",1,1]},{"destination":[7,1,"white",1,0],"promotion":null,"source":[7,1,"white",3,1]},{"destination":[8,1,"white",0,3],"promotion":null,"source":[8,1,"white",1,5]},{"destination":[9,1,"white",0,3],"promotion":null,"source":[9,1,"white",1,5]},{"destination":[10,1,"white",0,1],"promotion":null,"source":[10,1,"white",1,3]},{"destination":[11,1,"white",0,1],"promotion":null,"source":[11,1,"white",1,3]},{"destination":[12,1,"white",3,0],"promotion":null,"source":[12,1,"white",1,1]},{"destination":[13,1,"white",3,0],"promotion":null,"source":[13,1,"white",1,1]},{"destination":[14,1,"white",1,0],"promotion":null,"source":[14,1,"white",3,1]},{"destination":[15,1,"white",0,3],"promotion":null,"source":[15,1,"white",1,5]},{"destination":[16,1,"white",0,3],"promotion":null,"source":[16,1,"white",1,5]}]]''')


def _square(raw) -> Square5D:
    timeline, turn, side, x, y = raw
    return Square5D(BoardCoord(timeline, turn, ChessColor(side)), x, y)


def _resolve_recorded_move(engine: FiveDEngine, spec):
    source = _square(spec["source"])
    destination = _square(spec["destination"])
    promotion = PieceType(spec["promotion"]) if spec["promotion"] else None
    position = engine._resolve_position(source.board)
    assert position is not None, {"source": spec["source"]}
    matches = [
        move for move in engine.get_legal_moves(position)
        if move.source == source
        and move.destination == destination
        and move.promotion == promotion
    ]
    assert len(matches) == 1, {
        "source": spec["source"],
        "destination": spec["destination"],
        "promotion": spec["promotion"],
        "matches": len(matches),
    }
    return matches[0]


def build_deterministic_complex_engine() -> FiveDEngine:
    engine = FiveDEngine()
    for action_index, action_specs in enumerate(FIXTURE_TRACE):
        for spec in action_specs:
            move = _resolve_recorded_move(engine, spec)
            assert engine.execute_action_move(move), {
                "action": action_index,
                "spec": spec,
            }
        assert engine.can_submit_action(), {"action": action_index}
        assert engine.submit_action(), {"action": action_index}
    return engine


def _legacy_move_sort_key(move):
    return (
        move.source.board.timeline,
        move.source.board.turn,
        move.source.board.side.value,
        move.source.y,
        move.source.x,
        move.destination.board.timeline,
        move.destination.board.turn,
        move.destination.board.side.value,
        move.destination.y,
        move.destination.x,
        move.promotion.value if move.promotion else "",
        bool(move.is_branching),
        bool(move.is_cross_timeline),
    )


def _benchmark(engine: FiveDEngine, move_key, seconds: float) -> dict:
    original_key = action_planner._move_sort_key
    original_can_submit = FiveDEngine.can_submit_action
    started = time.perf_counter()
    first_candidate_ms = None

    def timed_can_submit(self):
        nonlocal first_candidate_ms
        result = original_can_submit(self)
        if result and first_candidate_ms is None:
            first_candidate_ms = (time.perf_counter() - started) * 1000.0
        return result

    action_planner._move_sort_key = move_key
    FiveDEngine.can_submit_action = timed_can_submit
    try:
        result = ActionPlanner(ActionSearchBudget(
            max_states=256,
            max_actions=24,
            max_move_depth=64,
            max_seconds=seconds,
        )).search(engine)
        wall_ms = (time.perf_counter() - started) * 1000.0
    finally:
        FiveDEngine.can_submit_action = original_can_submit
        action_planner._move_sort_key = original_key

    return {
        "budget": seconds,
        "first_candidate_ms": first_candidate_ms,
        "candidate_count": len(result.candidates),
        "explored_states": result.explored_states,
        "termination": result.termination_reason,
        "wall_ms": wall_ms,
    }


def test_deterministic_complex_fixture_replays_canonical_actions():
    engine = build_deterministic_complex_engine()
    required = ActionRules.required_boards(
        engine._ensure_current_action(), engine.timeline_manager.timelines
    )

    assert len(FIXTURE_TRACE) == 35
    assert len(engine.timeline_manager.timelines) == 32
    assert len(required) == 32
    assert engine.move_counter == 50


def test_current_ordering_finds_legal_complete_action_without_mutating_fixture():
    engine = build_deterministic_complex_engine()
    before = engine_state_signature(engine)
    result = ActionPlanner(ActionSearchBudget(
        max_states=256,
        max_actions=1,
        max_move_depth=64,
        max_seconds=None,
    )).search(engine)

    assert engine_state_signature(engine) == before
    assert result.candidates, result

    probe = deepcopy(engine)
    for spec in result.candidates[0]:
        raw = {
            "source": [
                spec.source.board.timeline,
                spec.source.board.turn,
                spec.source.board.side.value,
                spec.source.x,
                spec.source.y,
            ],
            "destination": [
                spec.destination.board.timeline,
                spec.destination.board.turn,
                spec.destination.board.side.value,
                spec.destination.x,
                spec.destination.y,
            ],
            "promotion": spec.promotion.value if spec.promotion else None,
        }
        assert probe.execute_action_move(_resolve_recorded_move(probe, raw))
    assert probe.can_submit_action()
    assert probe.submit_action()


def test_complex_fixture_ordering_ab_telemetry_only():
    engine = build_deterministic_complex_engine()
    current_key = action_planner._move_sort_key
    legacy = _benchmark(engine, _legacy_move_sort_key, 1.0)
    current = _benchmark(engine, current_key, 1.0)

    # Performance is telemetry only: hosted-runner wall time and candidate
    # breadth are deliberately not CI pass/fail thresholds.
    warnings.warn("DETERMINISTIC_COMPLEX_PLANNER_TELEMETRY=" + json.dumps({
        "timelines": len(engine.timeline_manager.timelines),
        "required_boards": len(ActionRules.required_boards(
            engine._ensure_current_action(), engine.timeline_manager.timelines
        )),
        "legacy": legacy,
        "current": current,
    }, sort_keys=True))
