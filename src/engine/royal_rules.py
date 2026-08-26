"""Royal-piece safety across the complete 5D multiverse.

This layer answers whether an opponent can capture any historical instance of a
standard King.  It intentionally sits above Move geometry/validation and below
checkmate search: individual Moves may be accumulated inside an Action, while
RoyalRules decides whether the resulting Action may safely be submitted.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Mapping, TYPE_CHECKING

from src.engine.coordinates import BoardCoord, Square5D
from src.engine.multiverse import MultiverseBoardView
from src.engine.path_rules import PathRules
from src.engine.pawn_rules import PawnRules
from src.engine.piece import Piece
from src.engine.piece_movement import PieceMovementRules
from src.engine.timeline_rules import TimelineRules
from src.utils.constants import ChessColor, PieceType

if TYPE_CHECKING:
    from src.engine.timeline import Timeline


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
            king = board.position.find_king(color)
            if king is None:
                continue
            kings.append(Square5D(board.coord, king[0], king[1]))
        return tuple(kings)

    def king_squares(self, color: ChessColor) -> tuple[Square5D, ...]:
        """Return every stored historical/playable instance of ``color``'s King."""
        return self._king_squares_in(self.timelines, color)

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

        try:
            vector = source.vector_to(target)
        except ValueError:
            return False

        if piece.piece_type == PieceType.PAWN:
            # Pawn attack geometry is independent of first-move state.
            return PawnRules.is_valid_vector(
                piece.color,
                vector,
                capture=True,
                unmoved=False,
            )

        try:
            if not PieceMovementRules.is_valid(piece.piece_type, vector):
                return False
        except (ValueError, NotImplementedError):
            return False

        if PieceMovementRules.is_slider(piece.piece_type):
            return PathRules.is_clear(
                piece.piece_type,
                source,
                target,
                view.resolve,
            )
        return True

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
    def _direct_threats_in(
        cls,
        timelines: Mapping[int, "Timeline"],
        color: ChessColor,
    ) -> tuple[RoyalThreat, ...]:
        """Find captures available to the opponent from currently playable boards."""
        if not timelines:
            return ()

        by_color = color.opposite()
        view = MultiverseBoardView(timelines)
        kings = cls._king_squares_in(timelines, color)
        threats: list[RoyalThreat] = []

        # Playable boards on inactive timelines are included deliberately: they
        # are optional moves and therefore can still be used to capture a King.
        for board in view.iter_boards(side=by_color, playable_only=True):
            for x, y, piece in board.position.get_all_pieces(by_color):
                source = Square5D(board.coord, x, y)
                for king in kings:
                    if king.side != by_color:
                        continue
                    target_piece = view.resolve(king.board)
                    if target_piece is None:
                        continue
                    king_piece = target_piece.get_piece(king.x, king.y)
                    if (
                        king_piece is None
                        or king_piece.color != color
                        or king_piece.piece_type != PieceType.KING
                    ):
                        continue
                    if cls._attacks_square_with_view(piece, source, king, view):
                        threats.append(RoyalThreat(piece, source, king))

        return tuple(threats)

    def direct_threats_against(self, color: ChessColor) -> tuple[RoyalThreat, ...]:
        """Threats available in the already-materialized current state."""
        return self._direct_threats_in(self.timelines, color)

    def _after_virtual_present_pass(
        self,
        color: ChessColor,
    ) -> Mapping[int, "Timeline"]:
        """Copy the multiverse and pass every active board currently in Present.

        The official check definition asks what the opponent could capture if the
        player passed on all active Present boards.  A virtual pass therefore
        creates the next half-move board with identical occupancy and opposite
        side-to-move, without mutating real game history.
        """
        present = TimelineRules.present(self.timelines)
        if present is None or present.side != color:
            return self.timelines

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
        simulated = self._after_virtual_present_pass(color)
        return self._direct_threats_in(simulated, color)

    def is_in_check(self, color: ChessColor) -> bool:
        """Whether ``color`` is in 5D check under the Present-pass definition."""
        return bool(self.threats_against(color))

    def is_action_safe(self, color: ChessColor) -> bool:
        """Whether a completed Action can be submitted without exposing a King.

        At submission The Present must already belong to the opponent, so no
        hypothetical pass is needed: the opponent's playable source boards are
        materialized in the real state and direct capture threats are decisive.
        """
        present = TimelineRules.present(self.timelines)
        if present is None or present.side == color:
            return False
        return not self.direct_threats_against(color)
