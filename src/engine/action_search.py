"""Search complete 5D Actions for checkmate/stalemate detection.

Checkmate in 5D Chess is an Action-level property: a player is only lost when
there is no sequence of legal Moves that can advance The Present to the
opponent while leaving every royal King safe.  This module performs that search
without submitting or mutating the caller's real engine state.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.engine.action import ActionRules
from src.engine.move_generator import Move
from src.utils.constants import ChessColor, GameState

if TYPE_CHECKING:
    from src.engine.engine import FiveDEngine


@dataclass(frozen=True, slots=True)
class ActionSearchResult:
    """Result of searching for one legal Action completion."""

    has_legal_action: bool
    explored_states: int
    witness: tuple[Move, ...] = ()


class ActionSearch:
    """Depth-first search over legal Move sequences inside one Action.

    The search deliberately stops as soon as a royal-safe Submit state is
    reached.  Optional future/inactive-board Moves are still explored when they
    are needed to make such a state reachable.  Failed states are memoized by a
    rule-relevant multiverse signature so equivalent Move orderings are not
    searched repeatedly.
    """

    def __init__(self):
        self._failed_states: set[tuple] = set()
        self._explored_states = 0

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

        self._failed_states.clear()
        self._explored_states = 0
        witness = self._dfs(state)
        return ActionSearchResult(
            has_legal_action=witness is not None,
            explored_states=self._explored_states,
            witness=witness or (),
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

        self._failed_states.clear()
        self._explored_states = 0
        witness = self._dfs(state)
        return ActionSearchResult(
            has_legal_action=witness is not None,
            explored_states=self._explored_states,
            witness=witness or (),
        )

    def _dfs(self, state: "FiveDEngine") -> tuple[Move, ...] | None:
        action = state._ensure_current_action()

        # This is the actual legal-Action terminal condition: The Present has
        # shifted to the opponent and RoyalRules accepts the final state.
        if ActionRules.can_submit(action, state.timeline_manager.timelines):
            return tuple(action.moves)

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
        required = set(ActionRules.required_boards(
            action,
            state.timeline_manager.timelines,
        ))
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
                child = deepcopy(state)
                if not child.execute_action_move(move):
                    continue
                witness = self._dfs(child)
                if witness is not None:
                    return witness

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
