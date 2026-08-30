"""Canonical Action-level planning primitives for the 5D chess AIs.

The engine exposes individual :class:`~src.engine.move_generator.Move`
objects, but a player's turn is a complete ``Action`` which may contain more
than one move.  This module is the small, immutable boundary used by the AI
implementations: search works on deep-copied engines, plans contain only
canonical coordinate specifications, and application resolves every
specification against the live engine immediately before executing it.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
import time
from typing import Any, Mapping, TYPE_CHECKING

from src.engine.action import ActionRules
from src.engine.coordinates import BoardCoord, Square5D
from src.engine.move_generator import Move
from src.utils.constants import ChessColor, GameState, PieceType

if TYPE_CHECKING:
    from src.engine.engine import FiveDEngine


def _enum_value(value: Any) -> Any:
    """Return a stable value for enum-like state fields."""
    return value.value if isinstance(value, Enum) else value


def _board_signature(board: BoardCoord) -> tuple:
    return board.timeline, board.turn, _enum_value(board.side)


def _square_signature(square: Square5D) -> tuple:
    return _board_signature(square.board), square.x, square.y


def _move_signature(move: Move) -> tuple:
    piece = move.piece
    return (
        _enum_value(piece.color),
        _enum_value(piece.piece_type),
        _square_signature(move.source),
        _square_signature(move.destination),
        (
            _enum_value(move.captured.color),
            _enum_value(move.captured.piece_type),
        ) if move.captured else None,
        _enum_value(move.promotion),
        bool(move.is_castling),
        bool(move.is_en_passant),
        bool(move.is_branching),
        move.created_timeline,
    )


def _present_signature(present: Any) -> tuple | None:
    if present is None:
        return None
    return (
        present.legacy_time_point,
        present.turn,
        _enum_value(present.side),
        tuple(_board_signature(board) for board in present.boards),
    )


def _action_signature(action: Any) -> tuple | None:
    if action is None:
        return None
    return (
        _enum_value(action.color),
        bool(action.submitted),
        _present_signature(action.starting_present),
        tuple(_move_signature(move) for move in action.moves),
    )


def _position_signature(position: Any) -> tuple:
    return (
        position.timeline_id,
        position.time_point,
        _enum_value(position.turn),
        position.move_number,
        tuple(tuple(row) for row in position.board),
        tuple(sorted(position.castling_rights.items())),
        tuple(position.en_passant_target) if position.en_passant_target else None,
        tuple(sorted(position.unmoved_pawns or ())),
    )


def engine_state_signature(engine: "FiveDEngine") -> tuple:
    """Return a hashable signature of all rule-relevant engine state.

    The signature deliberately includes timeline history, derived turn/action
    bookkeeping, and the allocation counters used by branching.  It is used
    as a stale-plan guard, not as a position-evaluation cache, so conservative
    inclusion is preferable to accidentally accepting a plan after a caller
    changed a less-visible field.
    """
    manager = engine.timeline_manager
    timelines: list[tuple] = []
    for timeline_id in sorted(manager.timelines):
        timeline = manager.timelines[timeline_id]
        positions = tuple(
            (time_point, _position_signature(timeline.positions[time_point]))
            for time_point in sorted(timeline.positions)
        )
        timelines.append((
            timeline_id,
            timeline.parent_id,
            timeline.branch_move_id,
            timeline.branch_turn,
            bool(timeline.is_active),
            timeline.created_at_turn,
            _enum_value(timeline.owner),
            positions,
        ))

    return (
        _enum_value(engine.game_state),
        _enum_value(engine.current_turn_color),
        engine.move_counter,
        tuple(_move_signature(move) for move in engine.move_history),
        tuple(_action_signature(action) for action in engine.action_history),
        _action_signature(engine.current_action),
        manager.max_timelines,
        getattr(manager, "active_timeline_id", None),
        getattr(manager, "_next_positive_id", None),
        getattr(manager, "_next_negative_id", None),
        engine.max_timelines,
        engine.max_turns,
        tuple(timelines),
    )


@dataclass(frozen=True, slots=True)
class MoveSpec:
    """Immutable canonical source/destination specification for one move."""

    source: Square5D
    destination: Square5D
    promotion: PieceType | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source, Square5D):
            raise TypeError("MoveSpec.source must be a canonical Square5D")
        if not isinstance(self.destination, Square5D):
            raise TypeError("MoveSpec.destination must be a canonical Square5D")
        promotion = self.promotion
        if promotion is not None and not isinstance(promotion, PieceType):
            try:
                promotion = PieceType(promotion)
            except (TypeError, ValueError) as exc:
                raise TypeError("MoveSpec.promotion must be a PieceType") from exc
            object.__setattr__(self, "promotion", promotion)

    @classmethod
    def from_move(cls, move: Move) -> "MoveSpec":
        return cls(move.source, move.destination, move.promotion)

    @property
    def source_coord(self) -> Square5D:
        """Alias retained for callers that spell out the coordinate role."""
        return self.source

    @property
    def destination_coord(self) -> Square5D:
        return self.destination

    @property
    def from_coord(self) -> Square5D:
        return self.source

    @property
    def to_coord(self) -> Square5D:
        return self.destination


@dataclass(frozen=True, slots=True)
class AIActionPlan:
    """Immutable, stale-checkable description of one complete Action."""

    color: ChessColor
    moves: tuple[MoveSpec, ...]
    start_signature: tuple
    score: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    warning: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.color, ChessColor):
            raise TypeError("AIActionPlan.color must be a ChessColor")
        moves = tuple(self.moves)
        if any(not isinstance(move, MoveSpec) for move in moves):
            raise TypeError("AIActionPlan.moves must contain MoveSpec values")
        object.__setattr__(self, "moves", moves)
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata or {})),
        )

    @property
    def move_specs(self) -> tuple[MoveSpec, ...]:
        return self.moves

    @property
    def ordered_moves(self) -> tuple[MoveSpec, ...]:
        return self.moves

    @property
    def specs(self) -> tuple[MoveSpec, ...]:
        return self.moves


class ActionPlanningError(RuntimeError):
    """Planning failed or was inconclusive under an explicit bounded reason."""

    def __init__(
        self,
        reason: str,
        *,
        incomplete: bool = False,
        explored_states: int = 0,
        explored_actions: int = 0,
    ) -> None:
        self.reason = reason
        self.incomplete = bool(incomplete)
        self.explored_states = explored_states
        self.explored_actions = explored_actions
        self.status = "inconclusive" if self.incomplete else "no_action"
        super().__init__(
            f"unable to plan a complete Action: {reason}"
            f" (incomplete={self.incomplete})"
        )


class InvalidActionPlanError(ValueError):
    """The plan is malformed or does not resolve to a legal Action."""


class StaleActionPlanError(InvalidActionPlanError):
    """The engine no longer matches the state from which a plan was made."""


class ActionApplicationError(InvalidActionPlanError):
    """A validly-shaped plan could not be applied safely."""


# Compatibility aliases make the error distinction discoverable without
# forcing callers to depend on one particular historical spelling.
ActionPlanError = InvalidActionPlanError


@dataclass(frozen=True, slots=True)
class ActionSearchBudget:
    """Shared hard limits for bounded Action planning/search."""

    max_states: int | None = 256
    max_actions: int | None = 24
    max_move_depth: int | None = 32
    max_seconds: float | None = 0.5

    def __post_init__(self) -> None:
        for name in ("max_states", "max_actions", "max_move_depth"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, int) or value < 0):
                raise ValueError(f"{name} must be a non-negative int or None")
        if self.max_seconds is not None and self.max_seconds < 0:
            raise ValueError("max_seconds must be non-negative or None")


@dataclass(frozen=True, slots=True)
class ActionSearchResult:
    """Bounded search evidence and complete candidate Action paths."""

    candidates: tuple[tuple[MoveSpec, ...], ...]
    explored_states: int
    termination_reason: str | None = None

    @property
    def has_legal_action(self) -> bool:
        return bool(self.candidates)

    @property
    def exhausted(self) -> bool:
        return self.termination_reason is not None


class _BudgetTracker:
    def __init__(self, budget: ActionSearchBudget):
        self.budget = budget
        self.started_at = time.monotonic()
        self.explored_states = 0
        self.explored_actions = 0
        self.termination_reason: str | None = None

    def check(self, depth: int) -> bool:
        if self.termination_reason is not None:
            return True
        if (
            self.budget.max_seconds is not None
            and time.monotonic() - self.started_at >= self.budget.max_seconds
        ):
            self.termination_reason = "time_budget"
            return True
        if (
            self.budget.max_move_depth is not None
            and depth >= self.budget.max_move_depth
        ):
            self.termination_reason = "move_depth_budget"
            return True
        if (
            self.budget.max_states is not None
            and self.explored_states >= self.budget.max_states
        ):
            self.termination_reason = "state_budget"
            return True
        if (
            self.budget.max_actions is not None
            and self.explored_actions >= self.budget.max_actions
        ):
            self.termination_reason = "action_budget"
            return True
        return False


def _move_sort_key(move: Move) -> tuple:
    return (
        move.source.board.timeline,
        move.source.board.turn,
        _enum_value(move.source.board.side),
        move.source.y,
        move.source.x,
        move.destination.board.timeline,
        move.destination.board.turn,
        _enum_value(move.destination.board.side),
        move.destination.y,
        move.destination.x,
        _enum_value(move.promotion) or "",
        bool(move.is_branching),
        bool(move.is_cross_timeline),
    )


class ActionPlanner:
    """Enumerate complete legal Actions without mutating the caller."""

    def __init__(self, budget: ActionSearchBudget | None = None):
        self.budget = budget or ActionSearchBudget()
        self._tracker: _BudgetTracker | None = None

    def search(self, engine: "FiveDEngine") -> ActionSearchResult:
        """Search all bounded complete Action witnesses from ``engine``."""
        if engine.game_state != GameState.PLAYING:
            return ActionSearchResult((), 0, "game_not_playing")

        state = deepcopy(engine)
        state.timeline_manager.refresh_activity()
        state._ensure_current_action()
        tracker = _BudgetTracker(self.budget)
        self._tracker = tracker
        candidates: list[tuple[MoveSpec, ...]] = []
        self._dfs(state, (), 0, tracker, candidates)
        return ActionSearchResult(
            tuple(candidates),
            tracker.explored_states,
            tracker.termination_reason,
        )

    # Friendly aliases used by older callers and by the AI implementations.
    find_candidates = search
    enumerate = search

    def plan(
        self,
        engine: "FiveDEngine",
        *,
        warning_prefix: str | None = None,
        score: float | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AIActionPlan:
        result = self.search(engine)
        if not result.candidates:
            raise ActionPlanningError(
                result.termination_reason or "no_legal_action",
                incomplete=result.termination_reason is not None,
                explored_states=result.explored_states,
            )

        warning = None
        if result.termination_reason:
            warning = f"bounded search incomplete: {result.termination_reason}"
            if warning_prefix:
                warning = f"{warning_prefix}; {warning}"
        info = dict(metadata or {})
        info.update({
            "explored_states": result.explored_states,
            "candidate_count": len(result.candidates),
            "search_complete": not result.exhausted,
        })
        return AIActionPlan(
            color=engine.current_turn_color,
            moves=result.candidates[0],
            start_signature=engine_state_signature(engine),
            score=score,
            metadata=info,
            warning=warning,
        )

    def _dfs(
        self,
        state: "FiveDEngine",
        path: tuple[MoveSpec, ...],
        depth: int,
        tracker: _BudgetTracker,
        candidates: list[tuple[MoveSpec, ...]],
    ) -> None:
        action = state._ensure_current_action()

        # Completion is checked before the budget so a witness exactly at the
        # configured depth is still accepted.  A submit-capable state is also
        # allowed to continue through optional boards: callers may deliberately
        # include those moves before the one final submission.
        if state.can_submit_action():
            candidates.append(path)
            tracker.explored_actions += 1
            if (
                self.budget.max_actions is not None
                and tracker.explored_actions >= self.budget.max_actions
            ):
                tracker.termination_reason = "action_budget"
                return

        if tracker.check(depth):
            return
        tracker.explored_states += 1

        required = set(ActionRules.required_boards(
            action,
            state.timeline_manager.timelines,
        ))
        movable = ActionRules.movable_boards(
            action,
            state.timeline_manager.timelines,
        )
        if not movable:
            return

        ordered_boards = tuple(
            sorted(
                movable,
                key=lambda board: (
                    board not in required,
                    board.timeline,
                    board.turn,
                    _enum_value(board.side),
                ),
            )
        )

        for board in ordered_boards:
            if tracker.check(depth):
                return
            position = state._resolve_position(board)
            if position is None:
                continue
            # No movement/rule legality is duplicated here.  All generated
            # Move varieties, including branching and cross-timeline moves,
            # are retained and passed through the engine's canonical API.
            legal_moves = sorted(
                state.get_legal_moves(position),
                key=_move_sort_key,
            )
            for move in legal_moves:
                if tracker.check(depth):
                    return
                child = deepcopy(state)
                if not child.execute_action_move(move):
                    continue
                self._dfs(
                    child,
                    path + (MoveSpec.from_move(move),),
                    depth + 1,
                    tracker,
                    candidates,
                )


def enumerate_action_candidates(
    engine: "FiveDEngine",
    budget: ActionSearchBudget | None = None,
) -> ActionSearchResult:
    """Convenience wrapper for bounded complete-Action enumeration."""
    return ActionPlanner(budget).search(engine)


def _spec_matches(move: Move, spec: MoveSpec) -> bool:
    return (
        move.source == spec.source
        and move.destination == spec.destination
        and move.promotion == spec.promotion
    )


def resolve_move_spec(engine: "FiveDEngine", spec: MoveSpec) -> Move:
    """Resolve one spec against the engine's current canonical legal moves."""
    if not isinstance(spec, MoveSpec):
        raise InvalidActionPlanError("move specification has the wrong type")
    if engine.game_state != GameState.PLAYING:
        raise InvalidActionPlanError("engine is not playing")
    position = engine._resolve_position(spec.source.board)
    if position is None:
        raise InvalidActionPlanError(f"source board does not exist: {spec.source.board}")
    legal_moves = engine.get_legal_moves(position)
    matches = [move for move in legal_moves if _spec_matches(move, spec)]
    if len(matches) != 1:
        if not matches:
            raise InvalidActionPlanError(
                "MoveSpec is not an exact current legal move: "
                f"{spec.source} -> {spec.destination}"
            )
        raise InvalidActionPlanError("MoveSpec resolved ambiguously")
    return matches[0]


def _verify_plan_start(engine: "FiveDEngine", plan: AIActionPlan) -> None:
    if not isinstance(plan, AIActionPlan):
        raise InvalidActionPlanError("plan has the wrong type")
    if engine.current_turn_color != plan.color:
        raise StaleActionPlanError(
            "plan color does not match the engine's current turn"
        )
    if engine_state_signature(engine) != plan.start_signature:
        raise StaleActionPlanError("engine state changed since the plan was made")


def _apply_specs_once(
    engine: "FiveDEngine",
    plan: AIActionPlan,
) -> tuple[Move, ...]:
    applied: list[Move] = []
    for index, spec in enumerate(plan.moves):
        try:
            move = resolve_move_spec(engine, spec)
        except InvalidActionPlanError as exc:
            raise ActionApplicationError(
                f"plan move {index} failed exact legal resolution: {exc}"
            ) from exc
        if not engine.execute_action_move(move):
            raise ActionApplicationError(f"plan move {index} was rejected by engine")
        applied.append(move)

    if not engine.can_submit_action():
        raise ActionApplicationError("plan does not reach a submit-capable Action")
    if not engine.submit_action():
        raise ActionApplicationError("engine rejected Action submission")
    return tuple(applied)


def apply_action_plan(engine: "FiveDEngine", plan: AIActionPlan) -> tuple[Move, ...]:
    """Preflight and apply a complete plan, submitting exactly once.

    The preflight runs all exact resolutions and the single submission on a
    deep copy.  The real engine is then resolved afresh for every step and is
    submitted once only after all steps succeed. The canonical Move objects
    actually applied to the live engine are returned in execution order.
    """
    _verify_plan_start(engine, plan)

    preflight = deepcopy(engine)
    try:
        _apply_specs_once(preflight, plan)
    except InvalidActionPlanError:
        raise
    except Exception as exc:
        raise ActionApplicationError(f"plan preflight failed: {exc}") from exc

    # The signature was checked before preflight; this second check catches a
    # concurrent caller changing state while the copy was being validated.
    _verify_plan_start(engine, plan)
    return _apply_specs_once(engine, plan)


__all__ = [
    "ActionApplicationError",
    "ActionPlanError",
    "ActionPlanner",
    "ActionPlanningError",
    "ActionSearchBudget",
    "ActionSearchResult",
    "AIActionPlan",
    "InvalidActionPlanError",
    "MoveSpec",
    "StaleActionPlanError",
    "apply_action_plan",
    "engine_state_signature",
    "enumerate_action_candidates",
    "resolve_move_spec",
]
