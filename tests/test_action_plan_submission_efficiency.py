"""Regression coverage for Action-plan submission and resolution hot paths."""

from src.ai import ActionSearchBudget, RandomAI, apply_action_plan
from src.engine import ActionRules, FiveDEngine, Piece, Position, Timeline
from src.utils.constants import ChessColor, PieceType


def _empty_position(timeline_id: int, time_point: int) -> Position:
    board = [["" for _ in range(8)] for _ in range(8)]
    board[7][7] = "K"
    board[0][7] = "k"
    return Position(
        board=board,
        turn=ChessColor.WHITE if time_point % 2 == 0 else ChessColor.BLACK,
        timeline_id=timeline_id,
        time_point=time_point,
        unmoved_pawns=set(),
    )


def _two_timeline_engine() -> tuple[FiveDEngine, Position]:
    engine = FiveDEngine()
    manager = engine.timeline_manager
    main = manager.get_timeline(0)
    main.positions.clear()

    source = _empty_position(0, 0)
    source.set_piece(3, 3, Piece(PieceType.ROOK, ChessColor.WHITE))
    main.add_position(source)

    other = Timeline(timeline_id=1, owner=ChessColor.WHITE)
    other.add_position(_empty_position(1, 0))
    manager.timelines[1] = other
    manager.refresh_activity()

    engine.current_turn_color = ChessColor.WHITE
    engine.action_history = []
    engine.current_action = ActionRules.begin(
        ChessColor.WHITE,
        manager.timelines,
    )
    return engine, source


def test_apply_action_plan_relies_on_submit_action_for_final_validation(monkeypatch):
    engine = FiveDEngine()
    plan = RandomAI(
        ChessColor.WHITE,
        seed=7,
        budget=ActionSearchBudget(
            max_states=256,
            max_actions=8,
            max_move_depth=8,
            max_seconds=1.0,
        ),
    ).plan_action(engine)

    def forbidden_preflight(self):
        raise AssertionError(
            "apply_action_plan must not call can_submit_action before submit_action"
        )

    # Plan construction legitimately uses can_submit_action. Patch only after a
    # complete plan exists so this guards the application boundary specifically.
    monkeypatch.setattr(FiveDEngine, "can_submit_action", forbidden_preflight)

    applied = apply_action_plan(engine, plan)

    assert applied
    assert engine.current_turn_color == ChessColor.BLACK
    assert len(engine.action_history) == 1
    assert engine.action_history[0].submitted


def test_source_scoped_legal_moves_match_full_generation_on_initial_board():
    engine = FiveDEngine()
    position = engine.get_current_position()
    all_moves = engine.get_legal_moves(position)
    sources = sorted({(move.source.x, move.source.y) for move in all_moves})

    assert sources
    for x, y in sources:
        expected = [
            move for move in all_moves
            if move.source.x == x and move.source.y == y
        ]
        assert engine.get_legal_moves_from_square(position, x, y) == expected


def test_source_scoped_legal_moves_match_cross_timeline_subset():
    engine, position = _two_timeline_engine()
    all_moves = engine.get_legal_moves(position)
    expected = [
        move for move in all_moves
        if move.source.x == 3 and move.source.y == 3
    ]

    assert any(move.is_cross_timeline for move in expected)
    assert engine.get_legal_moves_from_square(position, 3, 3) == expected
