from copy import deepcopy

import numpy as np
import pytest

from src.ai.action_planner import (
    ActionPlanner,
    ActionSearchBudget,
    InvalidActionPlanError,
    MoveSpec,
    engine_state_signature,
    resolve_move_spec,
)
from src.engine.action import ActionRules
from src.engine.board import Position
from src.engine.coordinates import Square5D
from src.engine.engine import FiveDEngine
from src.engine.timeline import Timeline
from src.training.config import DEFAULT_ENCODING
from src.training.encoding import (
    EncodedCandidates,
    EncodingError,
    _move_feature_vector,
    encode_action,
    encode_candidates,
)
from src.utils.constants import ChessColor, GameState, PieceType


def legacy_encode_action_with_deepcopy(engine, specs, config=DEFAULT_ENCODING):
    specs = tuple(specs)
    if not specs:
        raise EncodingError("an AI Action candidate must contain at least one Move")
    if len(specs) > config.max_moves_per_action:
        raise EncodingError(
            f"Action has {len(specs)} moves, above max {config.max_moves_per_action}"
        )
    moves = np.zeros(
        (config.max_moves_per_action, config.action_move_feature_dim),
        dtype=np.float32,
    )
    move_mask = np.zeros((config.max_moves_per_action,), dtype=np.bool_)
    clone = deepcopy(engine)
    has_branching = False
    has_cross = False
    for index, spec in enumerate(specs):
        resolved = resolve_move_spec(clone, spec)
        if not clone.execute_action_move(resolved):
            raise EncodingError(f"candidate move {index} was rejected during encoding")
        recorded = clone.current_action.moves[-1]
        moves[index] = _move_feature_vector(recorded, clone, config)
        move_mask[index] = True
        has_branching = has_branching or bool(recorded.is_branching)
        has_cross = has_cross or bool(recorded.is_cross_timeline)
    if not clone.can_submit_action():
        raise EncodingError("candidate does not reach a submit-capable Action")
    action_global = np.asarray(
        [
            len(specs) / float(config.max_moves_per_action),
            1.0 if has_branching else 0.0,
            1.0 if has_cross else 0.0,
            1.0,
        ],
        dtype=np.float32,
    )
    return moves, move_mask, action_global


def legacy_encode_candidates(engine, candidates, config=DEFAULT_ENCODING):
    candidates = tuple(tuple(candidate) for candidate in candidates)
    moves = np.zeros(
        (
            len(candidates),
            config.max_moves_per_action,
            config.action_move_feature_dim,
        ),
        dtype=np.float32,
    )
    masks = np.zeros(
        (len(candidates), config.max_moves_per_action), dtype=np.bool_
    )
    globals_ = np.zeros(
        (len(candidates), config.action_global_dim), dtype=np.float32
    )
    for index, candidate in enumerate(candidates):
        moves[index], masks[index], globals_[index] = (
            legacy_encode_action_with_deepcopy(engine, candidate, config)
        )
    return EncodedCandidates(
        moves,
        masks,
        globals_,
        np.ones((len(candidates),), dtype=np.bool_),
    )


def _assert_encoded_equal(expected, actual):
    np.testing.assert_array_equal(actual[0], expected[0])
    np.testing.assert_array_equal(actual[1], expected[1])
    np.testing.assert_array_equal(actual[2], expected[2])


def _assert_candidate_equal(engine, candidate):
    before = engine_state_signature(engine)
    expected = legacy_encode_action_with_deepcopy(engine, candidate)
    actual = encode_action(engine, candidate)
    _assert_encoded_equal(expected, actual)
    assert engine_state_signature(engine) == before


def _position(
    timeline_id,
    time_point,
    side,
    *pieces,
    en_passant_target=None,
    castling_rights=None,
    unmoved_pawns=None,
):
    board = [["" for _ in range(8)] for _ in range(8)]
    board[7][7] = "K"
    board[0][7] = "k"
    for x, y, char in pieces:
        board[y][x] = char
    kwargs = {}
    if castling_rights is not None:
        kwargs["castling_rights"] = castling_rights
    return Position(
        board=board,
        turn=side,
        timeline_id=timeline_id,
        time_point=time_point,
        en_passant_target=en_passant_target,
        unmoved_pawns=set() if unmoved_pawns is None else unmoved_pawns,
        **kwargs,
    )


def _engine_with_timelines(timelines, color=ChessColor.WHITE):
    engine = FiveDEngine()
    manager = engine.timeline_manager
    manager.timelines = {timeline.timeline_id: timeline for timeline in timelines}
    manager.active_timeline_id = 0
    manager._next_positive_id = max(
        [1, *(tid + 1 for tid in manager.timelines if tid > 0)]
    )
    manager._next_negative_id = min(
        [-1, *(tid - 1 for tid in manager.timelines if tid < 0)]
    )
    manager.refresh_activity()
    engine.game_state = GameState.PLAYING
    engine.move_history = []
    engine.action_history = []
    engine.move_counter = 0
    engine.current_turn_color = color
    engine.current_action = ActionRules.begin(color, manager.timelines)
    return engine


def _single_position_engine(position):
    timeline = Timeline(timeline_id=0)
    timeline.add_position(position)
    return _engine_with_timelines([timeline], position.turn)


def _planner_candidates(engine, limit=24):
    result = ActionPlanner(
        ActionSearchBudget(
            max_states=256,
            max_actions=limit,
            max_move_depth=8,
            max_seconds=None,
        )
    ).search(engine)
    assert result.candidates
    return result.candidates


def test_initial_all_planner_candidates_match_legacy_oracle_exactly():
    engine = FiveDEngine()
    before = engine_state_signature(engine)
    candidates = _planner_candidates(engine)
    expected = legacy_encode_candidates(engine, candidates)
    actual = encode_candidates(engine, candidates)
    np.testing.assert_array_equal(actual.moves, expected.moves)
    np.testing.assert_array_equal(actual.move_mask, expected.move_mask)
    np.testing.assert_array_equal(actual.action_global, expected.action_global)
    np.testing.assert_array_equal(actual.candidate_mask, expected.candidate_mask)
    assert engine_state_signature(engine) == before


def test_repeated_encoding_is_deterministic_and_non_mutating():
    engine = FiveDEngine()
    candidates = _planner_candidates(engine, 6)[:6]
    before = engine_state_signature(engine)
    first = encode_candidates(engine, candidates)
    second = encode_candidates(engine, candidates)
    third = encode_candidates(engine, candidates)
    for attr in ("moves", "move_mask", "action_global", "candidate_mask"):
        np.testing.assert_array_equal(getattr(first, attr), getattr(second, attr))
        np.testing.assert_array_equal(getattr(first, attr), getattr(third, attr))
    assert engine_state_signature(engine) == before


def _branching_engine():
    old = _position(0, 0, ChessColor.WHITE)
    latest = _position(0, 2, ChessColor.WHITE, (3, 3, "R"))
    timeline = Timeline(timeline_id=0)
    timeline.add_position(old)
    timeline.add_position(latest)
    return _engine_with_timelines([timeline]), latest


def test_candidate_order_isolation_including_branch_allocator():
    engine, latest = _branching_engine()
    legal = engine.get_legal_moves_from_square(latest, 3, 3)
    branch = next(move for move in legal if move.is_branching)
    spatial = [move for move in legal if move.is_spatial]
    assert len(spatial) >= 2
    candidates = (
        (MoveSpec.from_move(branch),),
        (MoveSpec.from_move(spatial[0]),),
        (MoveSpec.from_move(spatial[1]),),
    )
    baseline = [encode_action(engine, candidate) for candidate in candidates]
    before = engine_state_signature(engine)
    for order in ((0, 1, 2), (2, 0, 1), (1, 2, 0)):
        ordered = tuple(candidates[index] for index in order)
        encoded = encode_candidates(engine, ordered)
        for row, original_index in enumerate(order):
            expected = baseline[original_index]
            np.testing.assert_array_equal(encoded.moves[row], expected[0])
            np.testing.assert_array_equal(encoded.move_mask[row], expected[1])
            np.testing.assert_array_equal(encoded.action_global[row], expected[2])
        assert engine.timeline_manager._next_positive_id == 1
        assert engine_state_signature(engine) == before


def test_failed_candidate_does_not_pollute_engine_or_later_encoding():
    engine = FiveDEngine()
    candidates = _planner_candidates(engine, 3)[:3]
    assert len(candidates) >= 2
    good_a = candidates[0]
    good_c = candidates[-1]
    first_spec = good_a[0]
    invalid = MoveSpec(
        source=first_spec.source,
        destination=Square5D(first_spec.source.board, first_spec.source.x, first_spec.source.y),
        promotion=first_spec.promotion,
    )
    expected_c = encode_action(engine, good_c)
    before = engine_state_signature(engine)
    with pytest.raises(InvalidActionPlanError):
        encode_candidates(engine, (good_a, (invalid,), good_c))
    assert engine_state_signature(engine) == before
    actual_c = encode_action(engine, good_c)
    _assert_encoded_equal(expected_c, actual_c)


def test_castling_encoding_matches_legacy_and_isolated():
    rights = {
        "white_kingside": True,
        "white_queenside": False,
        "black_kingside": False,
        "black_queenside": False,
    }
    position = _position(
        0, 0, ChessColor.WHITE,
        (4, 7, "K"), (7, 7, "R"),
        castling_rights=rights,
    )
    # _position adds a king at h1; overwrite it so only e1 is White King.
    position.board[7][7] = "R"
    position.board[7][4] = "K"
    engine = _single_position_engine(position)
    move = next(
        move for move in engine.get_legal_moves_from_square(position, 4, 7)
        if move.is_castling and move.destination.x == 6
    )
    _assert_candidate_equal(engine, (MoveSpec.from_move(move),))


def test_en_passant_encoding_matches_legacy_and_isolated():
    position = _position(
        0, 0, ChessColor.WHITE,
        (4, 3, "P"), (3, 3, "p"),
        en_passant_target=(3, 2),
    )
    engine = _single_position_engine(position)
    move = next(
        move for move in engine.get_legal_moves_from_square(position, 4, 3)
        if move.is_en_passant
    )
    _assert_candidate_equal(engine, (MoveSpec.from_move(move),))


def test_promotion_encoding_matches_legacy_and_isolated():
    position = _position(0, 0, ChessColor.WHITE, (0, 1, "P"))
    engine = _single_position_engine(position)
    move = next(
        move for move in engine.get_legal_moves_from_square(position, 0, 1)
        if move.promotion == PieceType.QUEEN
    )
    _assert_candidate_equal(engine, (MoveSpec.from_move(move),))


def test_branching_encoding_matches_legacy_and_isolated():
    engine, latest = _branching_engine()
    move = next(
        move for move in engine.get_legal_moves_from_square(latest, 3, 3)
        if move.is_branching
    )
    _assert_candidate_equal(engine, (MoveSpec.from_move(move),))


def test_cross_timeline_encoding_matches_legacy_and_isolated():
    main_pos = _position(0, 0, ChessColor.WHITE, (3, 3, "R"))
    other_pos = _position(1, 0, ChessColor.WHITE)
    main = Timeline(timeline_id=0)
    main.add_position(main_pos)
    other = Timeline(timeline_id=1, owner=ChessColor.WHITE)
    other.add_position(other_pos)
    engine = _engine_with_timelines([main, other])
    move = next(
        move for move in engine.get_legal_moves_from_square(main_pos, 3, 3)
        if move.is_cross_timeline
        and not move.is_branching
        and move.destination.timeline == 1
        and move.destination.x == 3
        and move.destination.y == 3
    )
    _assert_candidate_equal(engine, (MoveSpec.from_move(move),))


def test_multi_move_action_encoding_matches_legacy_and_isolated():
    main_pos = _position(0, 0, ChessColor.WHITE, (4, 6, "P"), unmoved_pawns={(4, 6)})
    other_pos = _position(1, 0, ChessColor.WHITE, (4, 6, "P"), unmoved_pawns={(4, 6)})
    main = Timeline(timeline_id=0)
    main.add_position(main_pos)
    other = Timeline(timeline_id=1, owner=ChessColor.WHITE)
    other.add_position(other_pos)
    engine = _engine_with_timelines([main, other])

    replay = deepcopy(engine)
    first_pos = replay.timeline_manager.get_timeline(0).positions[0]
    first = next(
        move for move in replay.get_legal_moves_from_square(first_pos, 4, 6)
        if move.is_spatial and move.destination.y == 5
    )
    first_spec = MoveSpec.from_move(first)
    assert replay.execute_action_move(first)
    assert not replay.can_submit_action()

    second_pos = replay.timeline_manager.get_timeline(1).positions[0]
    second = next(
        move for move in replay.get_legal_moves_from_square(second_pos, 4, 6)
        if move.is_spatial and move.destination.y == 5
    )
    second_spec = MoveSpec.from_move(second)
    assert replay.execute_action_move(second)
    assert replay.can_submit_action()

    _assert_candidate_equal(engine, (first_spec, second_spec))
