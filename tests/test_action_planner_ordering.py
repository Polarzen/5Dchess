"""Regression coverage for deterministic ActionPlanner move ordering."""

import src.ai.action_planner as action_planner
from src.ai.action_planner import ActionPlanner, ActionSearchBudget, _move_sort_key
from src.engine import ActionRules, FiveDEngine, Piece, Position
from src.engine.coordinates import BoardCoord, Square5D
from src.engine.move_generator import Move
from src.utils.constants import ChessColor, PieceType


def _square(timeline: int, x: int, y: int) -> Square5D:
    return Square5D(BoardCoord(timeline, 0, ChessColor.WHITE), x, y)


def _legacy_move_sort_key(move: Move) -> tuple:
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


def _candidate_signature(candidate) -> tuple:
    return tuple(
        (spec.source, spec.destination, spec.promotion)
        for spec in candidate
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


def test_non_branching_moves_sort_before_branching_moves_without_filtering():
    piece = Piece(PieceType.ROOK, ChessColor.WHITE)
    branching = Move(
        piece=piece,
        source=_square(-1, 0, 0),
        destination=_square(-2, 0, 1),
        is_branching=True,
        created_timeline=-3,
    )
    ordinary = Move(
        piece=piece,
        source=_square(1, 7, 7),
        destination=_square(1, 7, 6),
    )

    # The branching move has the lexicographically earlier source coordinate,
    # so the historical coordinate-first key would place it first.  Planner
    # ordering must instead prefer a non-branching witness while retaining both.
    ordered = sorted((branching, ordinary), key=_move_sort_key)

    assert ordered == [ordinary, branching]
    assert branching in ordered
    assert ordinary in ordered


def test_ordering_change_preserves_complete_candidate_set(monkeypatch):
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

    assert before.termination_reason is None
    assert after.termination_reason is None
    before_set = {_candidate_signature(candidate) for candidate in before.candidates}
    after_set = {_candidate_signature(candidate) for candidate in after.candidates}
    assert before_set
    assert before_set == after_set
