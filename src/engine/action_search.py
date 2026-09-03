"""Search complete 5D Actions for checkmate/stalemate detection.

Checkmate in 5D Chess is an Action-level property: a player is only lost when
there is no sequence of legal Moves that can advance The Present to the
opponent while leaving every royal King safe.  This module performs that search
without submitting or mutating the caller's real engine state.

The search is intentionally bounded.  A complex multiverse can have an
extremely large Action tree even though every individual Move is legal.  Search
budget exhaustion is therefore reported as *unknown*, never as "no legal
Action", so callers cannot accidentally turn a performance guard into a false
checkmate/stalemate result.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import time
from typing import TYPE_CHECKING

from src.engine.action import ActionRules
from src.engine.move_generator import Move
from src.utils.constants import ChessColor, GameState

if TYPE_CHECKING:
    from src.engine.engine import FiveDEngine


DEFAULT_ACTION_SEARCH_MAX_STATES = 4096
DEFAULT_ACTION_SEARCH_MAX_DEPTH = 64
DEFAULT_ACTION_SEARCH_MAX_SECONDS = 3.0


@dataclass(frozen=True, slots=True)
class ActionSearchResult:
    """Result of searching for one legal Action completion.

    ``termination_reason`` is ``None`` only when the search completed normally
    (either a witness was found or the reachable state space was exhausted).
    Any non-``None`` value means the result is intentionally inconclusive.
    """

    has_legal_action: bool
    explored_states: int
    witness: tuple[Move, ...] = ()
    termination_reason: str | None = None

    @property
    def exhausted(self) -> bool:
        """Whether a safety budget stopped the search before completion."""
        return self.termination_reason is not None


class ActionSearch:
    """Depth-first search over legal Move sequences inside one Action.

    The search deliberately stops as soon as a royal-safe Submit state is
    reached.  Optional future/inactive-board Moves are still explored when they
    are needed to make such a state reachable.  Failed states are memoized by a
    rule-relevant multiverse signature so equivalent Move orderings are not
    searched repeatedly.

    State, depth, and wall-clock budgets protect production gameplay from
    combinatorial Action trees.  Budget exhaustion is surfaced explicitly in
    ``ActionSearchResult`` and must not be interpreted as a terminal position.
    """

    def __init__(
        self,
        *,
        max_states: int | None = DEFAULT_ACTION_SEARCH_MAX_STATES,
        max_depth: int | None = DEFAULT_ACTION_SEARCH_MAX_DEPTH,
        max_seconds: float | None = DEFAULT_ACTION_SEARCH_MAX_SECONDS,
    ):
        self.max_states = max_states
        self.max_depth = max_depth
        self.max_seconds = max_seconds
        self._failed_states: set[tuple] = set()
        self._explored_states = 0
        self._started_at = 0.0
        self._termination_reason: str | None = None

    def find_legal_action(
        self,
        engine: "FiveDEngine",
        color: ChessColor | None = None,
    ) -> ActionSearchResult:
        """Search from the start of ``color``'s Action.

        ``engine`` is deep-copied.  Move history, UI selection and the caller's
        real Timeline objects therefore remain untouched.
        """
        state = deepcopy(engine)
        state.game_state = GameState.PLAYING
        if color is None:
            color = state.current_turn_color
        state.current_turn_color = color
        state.timeline_manager.refresh_activity()
        state.current_action = ActionRules.begin(
            color,
            state.timeline_manager.timelines,
        )

        self._reset_search()
        witness = self._dfs(state, depth=0)
        return ActionSearchResult(
            has_legal_action=witness is not None,
            explored_states=self._explored_states,
            witness=witness or (),
            termination_reason=self._termination_reason,
        )

    def find_legal_completion(
        self,
        engine: "FiveDEngine",
    ) -> ActionSearchResult:
        """Search from the caller's current partially-built Action."""
        state = deepcopy(engine)
        state.game_state = GameState.PLAYING
        state.timeline_manager.refresh_activity()
        state._ensure_current_action()

        self._reset_search()
        witness = self._dfs(state, depth=0)
        return ActionSearchResult(
            has_legal_action=witness is not None,
            explored_states=self._explored_states,
            witness=witness or (),
            termination_reason=self._termination_reason,
        )

    def _reset_search(self) -> None:
        self._failed_states.clear()
        self._explored_states = 0
        self._started_at = time.monotonic()
        self._termination_reason = None

    def _budget_exhausted(self, depth: int) -> bool:
        if self._termination_reason is not None:
            return True

        if self.max_depth is not None and depth >= self.max_depth:
            self._termination_reason = "depth_limit"
            return True

        if self.max_states is not None and self._explored_states >= self.max_states:
            self._termination_reason = "state_budget"
            return True

        if (
            self.max_seconds is not None
            and time.monotonic() - self._started_at >= self.max_seconds
        ):
            self._termination_reason = "time_budget"
            return True

        return False

    def _dfs(
        self,
        state: "FiveDEngine",
        depth: int,
    ) -> tuple[Move, ...] | None:
        action = state._ensure_current_action()
        required = set(ActionRules.required_boards(
            action,
            state.timeline_manager.timelines,
        ))

        # A non-empty required set proves that The Present still belongs to the
        # acting color, so ActionRules.can_submit() must be false. Avoid the
        # expensive royal-safety scan until Present progress is complete. This
        # is only a predicate short-circuit: no Move, state, or legal completion
        # is pruned. Completion remains checked before budgets so a witness
        # exactly at the configured depth is accepted.
        if (
            not required
            and ActionRules.can_submit(action, state.timeline_manager.timelines)
        ):
            return tuple(action.moves)

        if self._budget_exhausted(depth):
            return None

        key = self._state_key(state)
        if key in self._failed_states:
            return None

        self._explored_states += 1

        movable = ActionRules.movable_boards(
            action,
            state.timeline_manager.timelines,
        )
        if not movable:
            self._failed_states.add(key)
            return None

        # Required Present boards first is only an ordering heuristic. Optional
        # boards remain in the list, so rewind/blocking resources are not lost.
        ordered_boards = tuple(
            sorted(
                movable,
                key=lambda board: (
                    board not in required,
                    board.timeline,
                    board.turn,
                    board.side.value,
                ),
            )
        )

        for board in ordered_boards:
            if self._termination_reason is not None:
                return None

            position = state._resolve_position(board)
            if position is None:
                continue

            moves = state.get_legal_moves(position)
            # Prefer non-branching transitions first.  Branching is still fully
            # searched and can be the only way to rewind The Present out of a
            # board-local mate/stalemate.
            moves = sorted(
                moves,
                key=lambda move: (
                    move.is_branching,
                    move.destination.timeline,
                    move.destination.turn,
                    move.destination.y,
                    move.destination.x,
                    move.source.y,
                    move.source.x,
                ),
            )

            for move in moves:
                if self._termination_reason is not None:
                    return None

                child = deepcopy(state)
                if not child.execute_action_move(move):
                    continue
                witness = self._dfs(child, depth=depth + 1)
                if witness is not None:
                    return witness

        # Never memoize a state as failed when a safety limit interrupted its
        # descendants; the state space was not fully proved unsatisfiable.
        if self._termination_reason is None:
            self._failed_states.add(key)
        return None

    @staticmethod
    def _state_key(state: "FiveDEngine") -> tuple:
        """Hash rule-relevant multiverse state, ignoring bookkeeping order.

        ``move_number`` and Action Move ordering are intentionally excluded:
        neither changes future geometry, activity, Pawn state, castling rights,
        en-passant state, branching capacity or royal safety.
        """
        manager = state.timeline_manager
        timeline_parts: list[tuple] = []

        for timeline_id in sorted(manager.timelines):
            timeline = manager.timelines[timeline_id]
            position_parts: list[tuple] = []
            for time_point in sorted(timeline.positions):
                position = timeline.positions[time_point]
                position_parts.append((
                    time_point,
                    position.turn.value,
                    tuple(tuple(row) for row in position.board),
                    tuple(sorted(position.castling_rights.items())),
                    position.en_passant_target,
                    tuple(sorted(position.unmoved_pawns)),
                ))

            timeline_parts.append((
                timeline_id,
                timeline.parent_id,
                timeline.owner.value if timeline.owner else None,
                tuple(position_parts),
            ))

        return (
            state.current_turn_color.value,
            manager.max_timelines,
            getattr(manager, "_next_positive_id", None),
            getattr(manager, "_next_negative_id", None),
            tuple(timeline_parts),
        )
