"""Royal-piece safety across the complete 5D multiverse.

This layer answers whether an opponent can capture any historical instance of a
standard King.  It intentionally sits above Move geometry/validation and below
checkmate search: individual Moves may be accumulated inside an Action, while
RoyalRules decides whether the resulting Action may safely be submitted.
"""
from __future__ import annotations

from copy import copy, deepcopy
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterator, Mapping

from src.engine.coordinates import BoardCoord, Square5D
from src.engine.board import Position
from src.engine.multiverse import MultiverseBoardView
from src.engine.path_rules import PathRules
from src.engine.piece import Piece
from src.engine.piece_movement import PieceMovementRules
from src.engine.timeline_rules import TimelineRules
from src.engine.timeline import Timeline
from src.utils.constants import ChessColor, PieceType

@dataclass(frozen=True, slots=True)
class RoyalThreat:
    """One legal capture relation from an attacker to a royal King instance."""

    piece: Piece
    attacker: Square5D
    king: Square5D


class RoyalRules:
    """Canonical 4D attack/check rules for standard royal Kings."""

    def __init__(self, timelines: Mapping[int, "Timeline"] | None = None):
        self.timelines = timelines or {}
        self.board_view = MultiverseBoardView(self.timelines)

    @staticmethod
    def _king_squares_in(
        timelines: Mapping[int, "Timeline"],
        color: ChessColor,
    ) -> tuple[Square5D, ...]:
        view = MultiverseBoardView(timelines)
        kings: list[Square5D] = []
        for board in view.iter_boards():
            for x, y in board.position.find_kings(color):
                kings.append(Square5D(board.coord, x, y))
        return tuple(kings)

    def king_squares(self, color: ChessColor) -> tuple[Square5D, ...]:
        """Return every stored historical/playable instance of ``color``'s King."""
        return self._king_squares_in(self.timelines, color)

    @staticmethod
    def _attack_delta_matches(
        piece_type: PieceType,
        color: ChessColor,
        dx: int,
        dy: int,
        dt: int,
        dl: int,
    ) -> bool:
        return RoyalRules._attack_delta_values_match(
            piece_type.value, color == ChessColor.WHITE, dx, dy, dt, dl,
        )

    @staticmethod
    @lru_cache(maxsize=262_144)
    def _attack_delta_values_match(
        piece_type: str,
        white: bool,
        dx: int,
        dy: int,
        dt: int,
        dl: int,
    ) -> bool:
        """Pure 4D capture geometry keyed by reusable relative displacement.

        Planner DFS visits many cloned states that repeat the same piece type and
        source→King displacement.  Caching only this occupancy-independent part
        avoids recomputing millions of identical integer predicates while path
        blocking remains validated against the current multiverse below.
        Primitive keys avoid repeated Enum hashing in the attacker/King product.
        """
        if piece_type == PieceType.PAWN.value:
            spatial_forward = -1 if white else 1
            timeline_forward = -1 if white else 1
            return (
                (
                    abs(dx) == 1
                    and dy == spatial_forward
                    and dt == 0
                    and dl == 0
                )
                or (
                    dx == 0
                    and dy == 0
                    and abs(dt) == 1
                    and dl == timeline_forward
                )
            )

        adx = abs(dx)
        ady = abs(dy)
        adt = abs(dt)
        adl = abs(dl)
        dimensions = (
            int(dx != 0)
            + int(dy != 0)
            + int(dt != 0)
            + int(dl != 0)
        )
        if dimensions == 0:
            return False

        max_magnitude = max(adx, ady, adt, adl)
        magnitude_sum = adx + ady + adt + adl

        if piece_type == PieceType.ROOK.value:
            return dimensions == 1
        if piece_type == PieceType.BISHOP.value:
            return dimensions == 2 and magnitude_sum == 2 * max_magnitude
        if piece_type == PieceType.QUEEN.value:
            return magnitude_sum == dimensions * max_magnitude
        if piece_type == PieceType.KING.value:
            return max_magnitude == 1
        if piece_type == PieceType.KNIGHT.value:
            return (
                dimensions == 2
                and max_magnitude == 2
                and magnitude_sum == 3
            )
        return False

    @staticmethod
    def _attack_geometry_matches(
        piece: Piece,
        source: Square5D,
        target: Square5D,
    ) -> bool:
        """Fast exact capture geometry without allocating a Vector4D per pair.

        Royal safety evaluates a very large attacker × historical-King product.
        Constructing ``Vector4D`` objects and repeatedly materializing their
        derived tuples dominates safe-position scans.  These integer predicates
        are algebraically equivalent to ``PieceMovementRules`` / pawn capture
        geometry and leave slider path validation to ``PathRules`` below.
        """
        if source.side != target.side:
            return False

        return RoyalRules._attack_delta_matches(
            piece.piece_type,
            piece.color,
            target.x - source.x,
            target.y - source.y,
            target.turn - source.turn,
            target.timeline - source.timeline,
        )

    @staticmethod
    @lru_cache(maxsize=4096)
    def _spatial_delta_can_attack(piece_code: str, white: bool, dx: int, dy: int) -> bool:
        """Necessary spatial condition, using the canonical 4D geometry.

        Equal-step sliders need only the existing spatial magnitudes, or one
        when both are zero. King/Pawn use one and Knight uses one/two. These
        representatives therefore cover every possible temporal/lane completion.
        Actual displacements and occupancy are still checked for each target.
        """
        steps = {0, -1, 1, -2, 2, dx, -dx, dy, -dy}
        return any(RoyalRules._attack_delta_values_match(piece_code, white, dx, dy, dt, dl)
                   for dt in steps for dl in steps)

    @staticmethod
    def _attacks_prevalidated_square_with_view(
        piece: Piece,
        source: Square5D,
        target: Square5D,
        view: MultiverseBoardView,
    ) -> bool:
        """Attack geometry/path after caller has validated source and target."""
        if not RoyalRules._attack_geometry_matches(piece, source, target):
            return False

        if PieceMovementRules.is_slider(piece.piece_type):
            return PathRules.is_clear(
                piece.piece_type,
                source,
                target,
                view.resolve,
            )
        return True

    @staticmethod
    def _attacks_square_with_view(
        piece: Piece,
        source: Square5D,
        target: Square5D,
        view: MultiverseBoardView,
    ) -> bool:
        """Return whether ``piece`` can capture ``target`` by 5D geometry/path."""
        source_position = view.resolve(source.board)
        target_position = view.resolve(target.board)
        if source_position is None or target_position is None:
            return False
        if source_position.get_piece(source.x, source.y) != piece:
            return False
        if source.side != piece.color or target.side != piece.color:
            return False

        target_piece = target_position.get_piece(target.x, target.y)
        if target_piece is not None and target_piece.color == piece.color:
            return False

        return RoyalRules._attacks_prevalidated_square_with_view(
            piece,
            source,
            target,
            view,
        )

    def attacks_square(
        self,
        piece: Piece,
        source: Square5D,
        target: Square5D,
    ) -> bool:
        """Public attack predicate on the current multiverse."""
        return self._attacks_square_with_view(
            piece,
            source,
            target,
            self.board_view,
        )

    @classmethod
    def _iter_direct_threats_in(
        cls,
        timelines: Mapping[int, "Timeline"],
        color: ChessColor,
    ) -> Iterator[RoyalThreat]:
        """Yield opponent captures from currently playable boards.

        Enumeration callers still receive every threat. Boolean safety queries
        consume only the first yielded threat, avoiding a full multiverse scan
        once royal exposure has already been proved.
        """
        if not timelines:
            return

        by_color = color.opposite()
        view = MultiverseBoardView(timelines)

        # Attack source and target boards must both be on the attacker's phase.
        # iter_boards already validates each stored Position, and find_kings()
        # proves the exact royal piece in that Position. Filtering by side here
        # avoids constructing a second board view, scanning the opposite phase,
        # then resolving and validating every King board a second time.
        kings = []
        for board in view.iter_boards(side=by_color):
            for x, y in board.position.find_kings(color):
                kings.append((Square5D(board.coord, x, y),
                              x, y, board.coord.turn, board.coord.timeline))

        if not kings:
            return

        # Many historical Kings share a square. Reuse only a query-local list
        # of spatially possible targets across equal pieces on different lanes;
        # preserve exact original target order and recheck time/lane/path below.
        # Extended rule classes retain their unfiltered geometry contract.
        spatial_squares = {(entry[1], entry[2]) for entry in kings}
        target_lists = {}
        white = by_color == ChessColor.WHITE

        # Playable boards on inactive timelines are included deliberately: they
        # are optional moves and therefore can still be used to capture a King.
        # ``get_all_pieces`` validates each source against exactly this board,
        # and ``kings`` above validates each target once, so the hot cross-product
        # can reuse the canonical geometry/path predicate without re-resolving
        # the same endpoints millions of times.
        for board in view.iter_boards(side=by_color, playable_only=True):
            turn, lane = board.coord.turn, board.coord.timeline
            for x, y, piece in board.position.get_all_pieces(by_color):
                source = Square5D(board.coord, x, y)
                piece_code = piece.piece_type.value
                targets = kings
                if cls is RoyalRules:
                    target_key = (piece_code, x, y)
                    if target_key not in target_lists:
                        possible = {(kx, ky) for kx, ky in spatial_squares
                                    if cls._spatial_delta_can_attack(piece_code, white, kx-x, ky-y)}
                        target_lists[target_key] = tuple(
                            entry for entry in kings if (entry[1], entry[2]) in possible)
                    targets = target_lists[target_key]
                for king, king_x, king_y, king_turn, king_lane in targets:
                    # Both endpoints already have the attacker's phase. Use the
                    # same exact geometry predicate on pre-extracted integers;
                    # most pairs fail without repeated Square5D property calls.
                    # Surviving pairs still use the canonical path predicate.
                    if not cls._attack_delta_values_match(
                        piece_code, white, king_x - x, king_y - y,
                        king_turn - turn, king_lane - lane,
                    ):
                        continue
                    if cls._attacks_prevalidated_square_with_view(
                        piece,
                        source,
                        king,
                        view,
                    ):
                        yield RoyalThreat(piece, source, king)

    @classmethod
    def _direct_threats_in(
        cls,
        timelines: Mapping[int, "Timeline"],
        color: ChessColor,
    ) -> tuple[RoyalThreat, ...]:
        """Find every capture available to the opponent from playable boards."""
        return tuple(cls._iter_direct_threats_in(timelines, color))

    @classmethod
    def _has_direct_threat_in(
        cls,
        timelines: Mapping[int, "Timeline"],
        color: ChessColor,
    ) -> bool:
        """Return as soon as one canonical direct royal threat is found."""
        return next(cls._iter_direct_threats_in(timelines, color), None) is not None

    def direct_threats_against(self, color: ChessColor) -> tuple[RoyalThreat, ...]:
        """Threats available in the already-materialized current state."""
        return self._direct_threats_in(self.timelines, color)

    def _after_virtual_present_pass(
        self,
        color: ChessColor,
        *,
        copy_history: bool = True,
    ) -> Mapping[int, "Timeline"]:
        """Copy the multiverse and pass every active board currently in Present.

        The official check definition asks what the opponent could capture if the
        player passed on all active Present boards.  A virtual pass therefore
        creates the next half-move board with identical occupancy and opposite
        side-to-move, without mutating real game history.

        The default retains an isolated copy. Internal threat queries may borrow
        unchanged history: they only read it and return frozen threats or a bool.
        Only touched Timeline containers and new successor Positions then need
        copying. Subclasses and dynamic attributes retain generic deepcopy.
        """
        present = TimelineRules.present(self.timelines)
        if present is None or present.side != color:
            return self.timelines

        canonical = not copy_history and type(self) is RoyalRules and all(
            type(timeline) is Timeline
            and type(timeline.positions) is dict
            and set(vars(timeline)) == set(Timeline.__dataclass_fields__)
            and all(type(position) is Position
                    and set(vars(position)) == set(Position.__dataclass_fields__)
                    for position in timeline.positions.values())
            for timeline in self.timelines.values()
        )
        if canonical:
            simulated = dict(self.timelines)
            for coord in present.boards:
                timeline = copy(self.timelines[coord.timeline])
                timeline.positions = dict(timeline.positions)
                simulated[coord.timeline] = timeline
        else:
            simulated = deepcopy(dict(self.timelines))
        for coord in present.boards:
            timeline = simulated.get(coord.timeline)
            if timeline is None:
                continue
            position = timeline.positions.get(coord.legacy_time_point)
            if position is None:
                continue

            next_coord = coord.next()
            successor = position.copy()
            successor.time_point = next_coord.legacy_time_point
            successor.turn = next_coord.side
            # Passing ends any same-board en-passant opportunity.
            successor.en_passant_target = None
            timeline.add_position(successor)

        return simulated

    def threats_against(self, color: ChessColor) -> tuple[RoyalThreat, ...]:
        """Return check threats using the official virtual-Present-pass semantics."""
        simulated = self._after_virtual_present_pass(color, copy_history=False)
        return self._direct_threats_in(simulated, color)

    def is_in_check(self, color: ChessColor) -> bool:
        """Whether ``color`` is in 5D check under the Present-pass definition."""
        simulated = self._after_virtual_present_pass(color, copy_history=False)
        return self._has_direct_threat_in(simulated, color)

    def is_action_safe(self, color: ChessColor) -> bool:
        """Whether a completed Action can be submitted without exposing a King.

        At submission The Present must already belong to the opponent, so no
        hypothetical pass is needed: the opponent's playable source boards are
        materialized in the real state and direct capture threats are decisive.
        """
        present = TimelineRules.present(self.timelines)
        if present is None or present.side == color:
            return False
        return not self._has_direct_threat_in(self.timelines, color)
