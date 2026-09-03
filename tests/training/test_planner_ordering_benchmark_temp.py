"""Temporary candidate-set telemetry for the planner ordering experiment.

This test is intentionally removed after telemetry is captured from CI.
"""
from __future__ import annotations

import hashlib
import json
import warnings

import src.ai.action_planner as action_planner
from src.ai.action_planner import ActionPlanner, ActionSearchBudget
from src.engine import ActionRules, FiveDEngine, Piece, Position
from src.utils.constants import ChessColor, PieceType


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


def _small_complete_search_engine() -> FiveDEngine:
    engine = FiveDEngine()
    manager = engine.timeline_manager
    main = manager.get_timeline(0)
    main.positions.clear()
    board = [["" for _ in range(8)] for _ in range(8)]
    board[7][7] = "K"
    board[0][7] = "k"
    position = Position(
        board=board,
        turn=ChessColor.WHITE,
        timeline_id=0,
        time_point=0,
        unmoved_pawns=set(),
    )
    position.set_piece(0, 6, Piece(PieceType.ROOK, ChessColor.WHITE))
    main.add_position(position)
    manager.refresh_activity()
    engine.current_turn_color = ChessColor.WHITE
    engine.action_history = []
    engine.current_action = ActionRules.begin(
        ChessColor.WHITE,
        manager.timelines,
    )
    return engine


def _square_signature(square):
    return (
        square.board.timeline,
        square.board.turn,
        square.board.side.value,
        square.x,
        square.y,
    )


def _candidate_signature(candidate):
    return tuple(
        (
            _square_signature(spec.source),
            _square_signature(spec.destination),
            spec.promotion.value if spec.promotion else "",
        )
        for spec in candidate
    )


def _set_hash(signatures) -> str:
    payload = json.dumps(sorted(signatures), separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def test_candidate_equivalence_telemetry(monkeypatch):
    engine = _small_complete_search_engine()
    budget = ActionSearchBudget(
        max_states=4096,
        max_actions=None,
        max_move_depth=8,
        max_seconds=5.0,
    )
    new_key = action_planner._move_sort_key

    monkeypatch.setattr(action_planner, "_move_sort_key", _legacy_move_sort_key)
    before = ActionPlanner(budget).search(engine)
    monkeypatch.setattr(action_planner, "_move_sort_key", new_key)
    after = ActionPlanner(budget).search(engine)

    before_sequence = [_candidate_signature(candidate) for candidate in before.candidates]
    after_sequence = [_candidate_signature(candidate) for candidate in after.candidates]
    before_set = set(before_sequence)
    after_set = set(after_sequence)
    telemetry = {
        "before_count": len(before_sequence),
        "after_count": len(after_sequence),
        "before_termination": before.termination_reason,
        "after_termination": after.termination_reason,
        "before_set_hash": _set_hash(before_set),
        "after_set_hash": _set_hash(after_set),
        "same_canonical_set": before_set == after_set,
        "ordering_changed": before_sequence != after_sequence,
    }
    warnings.warn("CANDIDATE_EQUIVALENCE_TELEMETRY=" + json.dumps(telemetry, sort_keys=True))

    assert before.termination_reason is None
    assert after.termination_reason is None
    assert before_set
    assert before_set == after_set
