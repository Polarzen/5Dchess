from copy import deepcopy

from src.ai.action_planner import MoveSpec, engine_state_signature, resolve_move_spec
from src.data.archive import GameArchive
from src.engine.action import ActionRules
from src.engine.board import Position
from src.engine.engine import FiveDEngine
from src.engine.piece import Piece
from src.engine.timeline import Timeline
from src.utils.constants import ChessColor, GameState, PieceType


def _position(timeline_id, time_point, side, *pieces, en_passant_target=None):
    board = [["" for _ in range(8)] for _ in range(8)]
    board[7][7] = "K"
    board[0][7] = "k"
    for x, y, char in pieces:
        board[y][x] = char
    return Position(
        board=board,
        turn=side,
        timeline_id=timeline_id,
        time_point=time_point,
        en_passant_target=en_passant_target,
        unmoved_pawns=set(),
    )


def _single_timeline_engine(*positions):
    engine = FiveDEngine()
    manager = engine.timeline_manager
    timeline = Timeline(timeline_id=0)
    for position in positions:
        timeline.add_position(position)
    manager.timelines = {0: timeline}
    manager.active_timeline_id = 0
    manager._next_positive_id = 1
    manager._next_negative_id = -1
    manager.refresh_activity()
    engine.game_state = GameState.PLAYING
    engine.move_history = []
    engine.action_history = []
    engine.move_counter = max((p.move_number for p in positions), default=0)
    engine.current_turn_color = positions[-1].turn
    engine.current_action = ActionRules.begin(
        engine.current_turn_color, manager.timelines
    )
    return engine


def _advanced_engine():
    engine = FiveDEngine()
    move = next(
        move for move in engine.get_legal_moves()
        if move.source.x == 4 and move.source.y == 6
        and move.destination.x == 4 and move.destination.y == 4
    )
    assert engine.execute_action_move(move)
    assert engine.submit_action(evaluate_outcome=False)
    engine.rule_warning = "clone-me"
    return engine


def test_simulation_clone_matches_deepcopy_rule_state():
    engine = _advanced_engine()
    legacy = deepcopy(engine)
    clone = engine.clone_for_simulation()

    assert engine_state_signature(clone) == engine_state_signature(legacy)
    assert clone.rule_warning == legacy.rule_warning == "clone-me"
    assert clone.timeline_manager is not engine.timeline_manager
    assert clone.current_action is not engine.current_action
    assert clone.action_history is not engine.action_history
    assert clone.action_history[0] is not engine.action_history[0]
    assert clone.move_history is not engine.move_history
    assert clone.rules_engine is not engine.rules_engine


def test_simulation_clone_mutations_do_not_alias_source():
    engine = _advanced_engine()
    before = engine_state_signature(engine)
    clone = engine.clone_for_simulation()
    latest = clone.get_current_position()

    latest.board[0][0] = ""
    latest.castling_rights["black_kingside"] = False
    latest.en_passant_target = (0, 0)
    latest.unmoved_pawns.add((0, 0))
    clone.current_action.moves.append(clone.move_history[-1])
    clone.action_history[0].moves.clear()
    clone.move_history.clear()
    clone.timeline_manager._next_positive_id += 7
    clone.timeline_manager._next_negative_id -= 7
    clone.timeline_manager.timelines[0].positions.pop(0)
    clone.rules_engine.timelines[99] = Timeline(timeline_id=99)

    assert engine_state_signature(engine) == before
    assert 0 in engine.timeline_manager.timelines[0].positions
    assert 99 not in engine.rules_engine.timelines

    reverse = engine.clone_for_simulation()
    reverse_before = engine_state_signature(reverse)
    engine.timeline_manager._next_positive_id += 3
    engine.current_action.moves.append(engine.move_history[-1])
    assert engine_state_signature(reverse) == reverse_before


def test_simulation_clone_execute_and_submit_match_deepcopy():
    engine = FiveDEngine()
    move = next(
        move for move in engine.get_legal_moves()
        if move.source.x == 4 and move.source.y == 6
    )
    spec = MoveSpec.from_move(move)
    legacy = deepcopy(engine)
    clone = engine.clone_for_simulation()

    for state in (legacy, clone):
        resolved = resolve_move_spec(state, spec)
        assert state.execute_action_move(resolved)
    assert engine_state_signature(clone) == engine_state_signature(legacy)
    assert clone.can_submit_action() == legacy.can_submit_action() is True
    assert clone.submit_action(evaluate_outcome=False)
    assert legacy.submit_action(evaluate_outcome=False)
    assert engine_state_signature(clone) == engine_state_signature(legacy)


def test_simulation_clone_branching_matches_deepcopy():
    old = _position(0, 0, ChessColor.WHITE)
    latest = _position(0, 2, ChessColor.WHITE, (3, 3, "R"))
    engine = _single_timeline_engine(old, latest)
    branching = next(
        move for move in engine.get_legal_moves_from_square(latest, 3, 3)
        if move.is_branching
        and move.destination.timeline == 0
        and move.destination.board.legacy_time_point == 0
    )
    spec = MoveSpec.from_move(branching)
    legacy = deepcopy(engine)
    clone = engine.clone_for_simulation()

    for state in (legacy, clone):
        resolved = resolve_move_spec(state, spec)
        assert resolved.is_branching
        assert state.execute_action_move(resolved)

    assert engine_state_signature(clone) == engine_state_signature(legacy)
    assert clone.timeline_manager._next_positive_id == 2
    assert clone.timeline_manager.get_timeline(1) is not None
    assert clone.can_submit_action() == legacy.can_submit_action()


def test_simulation_clone_accepts_but_drops_archive_only_replay_origin():
    engine = FiveDEngine()
    origin = GameArchive.set_replay_origin(engine)
    before = deepcopy(origin)

    clone = engine.clone_for_simulation()

    # Replay origin is storage-only metadata: canonical move/search simulation
    # never reads it, so carrying the potentially large mutable JSON snapshot
    # into every child clone would add aliasing/copy cost with no rule benefit.
    assert not hasattr(clone, "_replay_origin")
    assert engine._replay_origin == before
    assert engine._replay_origin is origin
    assert engine_state_signature(clone) == engine_state_signature(engine)


def test_simulation_clone_fails_closed_on_unknown_dynamic_state():
    engine = FiveDEngine()
    engine.unmodeled_mutable_state = []
    try:
        engine.clone_for_simulation()
    except RuntimeError as exc:
        assert "unmodeled_mutable_state" in str(exc)
    else:
        raise AssertionError("unknown mutable state must fail closed")
