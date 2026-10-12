"""Deterministic bounded encoders for canonical multiverse states and Actions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np

from src.ai.action_planner import MoveSpec, resolve_move_spec
from src.engine.action import ActionRules
from src.engine.multiverse import MultiverseBoardView, ResolvedBoard
from src.engine.timeline_rules import TimelineRules
from src.training.config import DEFAULT_ENCODING, EncodingConfig
from src.utils.constants import ChessColor, GameState, PieceType


class EncodingError(ValueError):
    pass


PIECE_TYPES = (
    PieceType.KING,
    PieceType.QUEEN,
    PieceType.ROOK,
    PieceType.BISHOP,
    PieceType.KNIGHT,
    PieceType.PAWN,
)
PIECE_INDEX = {piece_type: index for index, piece_type in enumerate(PIECE_TYPES)}


@dataclass(frozen=True, slots=True)
class EncodedState:
    boards: np.ndarray
    board_meta: np.ndarray
    board_mask: np.ndarray
    global_features: np.ndarray


@dataclass(frozen=True, slots=True)
class EncodedCandidates:
    moves: np.ndarray
    move_mask: np.ndarray
    action_global: np.ndarray
    candidate_mask: np.ndarray

    @property
    def candidate_count(self) -> int:
        return int(self.candidate_mask.sum())


def _color_sign(color: ChessColor | None) -> float:
    if color == ChessColor.WHITE:
        return 1.0
    if color == ChessColor.BLACK:
        return -1.0
    return 0.0


def _piece_channel(piece_type: PieceType, color: ChessColor) -> int:
    base = PIECE_INDEX[piece_type]
    return base if color == ChessColor.WHITE else base + len(PIECE_TYPES)


def _relevant_boards(engine, config: EncodingConfig) -> tuple[ResolvedBoard, ...]:
    """Select a deterministic bounded view without double-counting history.

    All playable frontier boards are preferred, followed by the current Present,
    then the newest historical context.  A board can only appear once.
    """
    timelines = engine.timeline_manager.timelines
    view = MultiverseBoardView(timelines)
    present = engine.get_present()
    present_set = set(present.boards if present else ())
    action = engine._ensure_current_action()
    required = set(ActionRules.required_boards(action, timelines))
    movable = set(ActionRules.movable_boards(action, timelines))

    boards = list(view.iter_boards())

    def priority(board: ResolvedBoard) -> tuple:
        active = TimelineRules.is_active_timeline(
            timelines[board.coord.timeline], timelines
        )
        return (
            0 if board.is_playable else 1,
            0 if board.coord in present_set else 1,
            0 if board.coord in required else 1,
            0 if board.coord in movable else 1,
            0 if active else 1,
            -board.coord.legacy_time_point,
            board.coord.timeline,
            board.coord.turn,
            board.coord.side.value,
        )

    boards.sort(key=priority)
    return tuple(boards[: config.max_relevant_boards])


def encode_state(
    engine,
    perspective: ChessColor | None = None,
    config: EncodingConfig = DEFAULT_ENCODING,
) -> EncodedState:
    """Encode the canonical multiverse using fixed shapes and explicit masks."""
    if perspective is None:
        perspective = engine.current_turn_color
    if not isinstance(perspective, ChessColor):
        perspective = ChessColor(perspective)

    max_boards = config.max_relevant_boards
    boards_tensor = np.zeros(
        (max_boards, config.board_channels, 8, 8), dtype=np.float32
    )
    board_meta = np.zeros((max_boards, config.board_meta_dim), dtype=np.float32)
    board_mask = np.zeros((max_boards,), dtype=np.bool_)

    timelines = engine.timeline_manager.timelines
    present = engine.get_present()
    present_set = set(present.boards if present else ())
    action = engine._ensure_current_action()
    required = set(ActionRules.required_boards(action, timelines))
    movable = set(ActionRules.movable_boards(action, timelines))
    max_timeline_scale = float(max(1, engine.max_timelines))
    max_turn_scale = float(max(1, engine.max_turns))

    selected = _relevant_boards(engine, config)
    for index, resolved in enumerate(selected):
        coord = resolved.coord
        position = resolved.position
        timeline = timelines[coord.timeline]
        active = TimelineRules.is_active_timeline(timeline, timelines)
        board_mask[index] = True
        for y in range(8):
            for x in range(8):
                piece = position.get_piece(x, y)
                if piece is None:
                    continue
                boards_tensor[
                    index,
                    _piece_channel(piece.piece_type, piece.color),
                    y,
                    x,
                ] = 1.0

        board_meta[index] = np.asarray(
            [
                np.clip(coord.timeline / max_timeline_scale, -1.0, 1.0),
                np.clip(coord.turn / max_turn_scale, 0.0, 1.0),
                _color_sign(coord.side),
                1.0 if active else 0.0,
                1.0 if resolved.is_playable else 0.0,
                1.0 if resolved.is_historical else 0.0,
                1.0 if coord in required else 0.0,
                1.0 if coord in movable else 0.0,
                1.0 if coord in present_set else 0.0,
                _color_sign(timeline.owner),
                np.clip(coord.legacy_time_point / (2.0 * max_turn_scale), 0.0, 1.0),
                1.0,
            ],
            dtype=np.float32,
        )

    counts = TimelineRules.creator_counts(timelines)
    active_count = sum(
        1 for timeline in timelines.values()
        if TimelineRules.is_active_timeline(timeline, timelines)
    )
    required_count = len(required)
    movable_count = len(movable)
    present_turn = present.turn if present else 0
    present_side = present.side if present else None
    present_board_count = len(present.boards) if present else 0
    action_move_count = len(action.moves)
    can_submit = engine.can_submit_action()

    global_features = np.asarray(
        [
            _color_sign(perspective),
            _color_sign(engine.current_turn_color),
            1.0 if perspective == engine.current_turn_color else -1.0,
            min(1.0, action_move_count / float(max(1, config.max_moves_per_action))),
            np.clip(present_turn / max_turn_scale, 0.0, 1.0),
            _color_sign(present_side),
            min(1.0, present_board_count / float(max_boards)),
            min(1.0, required_count / float(max_boards)),
            min(1.0, movable_count / float(max_boards)),
            min(1.0, counts[ChessColor.WHITE] / float(max_boards)),
            min(1.0, counts[ChessColor.BLACK] / float(max_boards)),
            min(1.0, active_count / float(max_boards)),
            min(1.0, len(timelines) / float(max_boards)),
            1.0 if can_submit else 0.0,
            1.0 if engine.game_state == GameState.PLAYING else 0.0,
            1.0,
        ],
        dtype=np.float32,
    )
    if global_features.shape != (config.global_dim,):
        raise EncodingError(
            f"global feature shape {global_features.shape} != {(config.global_dim,)}"
        )
    return EncodedState(boards_tensor, board_meta, board_mask, global_features)


def _move_feature_vector(move, engine, config: EncodingConfig) -> np.ndarray:
    max_timeline_scale = float(max(1, engine.max_timelines))
    max_turn_scale = float(max(1, engine.max_turns))
    source = move.source
    destination = move.destination
    vector = move.vector
    features = np.zeros((config.action_move_feature_dim,), dtype=np.float32)
    base = [
        np.clip(source.timeline / max_timeline_scale, -1.0, 1.0),
        np.clip(source.turn / max_turn_scale, 0.0, 1.0),
        _color_sign(source.side),
        source.x / 7.0,
        source.y / 7.0,
        np.clip(destination.timeline / max_timeline_scale, -1.0, 1.0),
        np.clip(destination.turn / max_turn_scale, 0.0, 1.0),
        _color_sign(destination.side),
        destination.x / 7.0,
        destination.y / 7.0,
        np.clip(vector.dl / max_timeline_scale, -1.0, 1.0),
        np.clip(vector.dt / max_turn_scale, -1.0, 1.0),
        vector.dx / 7.0,
        vector.dy / 7.0,
        _color_sign(move.piece.color),
        1.0 if move.captured else 0.0,
        1.0 if move.is_castling else 0.0,
        1.0 if move.is_en_passant else 0.0,
        1.0 if move.is_branching else 0.0,
        1.0 if move.is_cross_timeline else 0.0,
        (
            np.clip(move.created_timeline / max_timeline_scale, -1.0, 1.0)
            if move.created_timeline is not None else 0.0
        ),
        1.0 if move.promotion else 0.0,
    ]
    features[:22] = np.asarray(base, dtype=np.float32)
    features[22 + PIECE_INDEX[move.piece.piece_type]] = 1.0
    if move.captured is not None:
        features[28 + PIECE_INDEX[move.captured.piece_type]] = 1.0
    if move.promotion is not None:
        features[34 + PIECE_INDEX[move.promotion]] = 1.0
    return features


def encode_action(
    engine,
    specs: Sequence[MoveSpec],
    config: EncodingConfig = DEFAULT_ENCODING,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Resolve and encode every Move in a complete Action on an engine clone."""
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
    clone = engine.clone_for_simulation()
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


def encode_candidates(
    engine,
    candidates: Iterable[Sequence[MoveSpec]],
    config: EncodingConfig = DEFAULT_ENCODING,
) -> EncodedCandidates:
    candidates = tuple(tuple(candidate) for candidate in candidates)
    if not candidates:
        raise EncodingError("cannot encode an empty candidate set")
    moves = np.zeros(
        (
            len(candidates),
            config.max_moves_per_action,
            config.action_move_feature_dim,
        ),
        dtype=np.float32,
    )
    move_mask = np.zeros(
        (len(candidates), config.max_moves_per_action), dtype=np.bool_
    )
    action_global = np.zeros(
        (len(candidates), config.action_global_dim), dtype=np.float32
    )
    candidate_mask = np.ones((len(candidates),), dtype=np.bool_)
    for index, candidate in enumerate(candidates):
        encoded, mask, global_features = encode_action(engine, candidate, config)
        moves[index] = encoded
        move_mask[index] = mask
        action_global[index] = global_features
    return EncodedCandidates(moves, move_mask, action_global, candidate_mask)


__all__ = [
    "EncodedCandidates",
    "EncodedState",
    "EncodingError",
    "encode_action",
    "encode_candidates",
    "encode_state",
]
