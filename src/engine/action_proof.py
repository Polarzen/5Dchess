"""Conservative certificates, independent of bounded search exhaustion."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, TYPE_CHECKING

from src.engine.action import ActionRules
from src.engine.coordinates import BoardCoord, Square5D
from src.engine.path_rules import PathRules
from src.engine.piece_movement import PieceMovementRules
from src.engine.royal_rules import RoyalRules, RoyalThreat
from src.engine.timeline_rules import TimelineRules
from src.utils.constants import ChessColor, PieceType

if TYPE_CHECKING:
    from src.engine.engine import FiveDEngine


@dataclass(frozen=True, slots=True)
class RequiredBoardThreatProof:
    board: BoardCoord
    threat: RoyalThreat


def prove_direct_threat(
    engine: "FiveDEngine",
    interrupted: Callable[[], bool],
) -> RoyalThreat | None:
    """An already-materialized royal threat cannot be repaired in this Action.

    Its playable attacker, historical King and clear ray all lie on the
    opponent's phase. Acting-color moves cannot advance those boards or
    overwrite their history. Branches only add boards, and inactive attack
    sources are included by the canonical predicate. This does NOT use virtual
    pass threats or the unsafe-while-Present-is-ours submission predicate.
    """
    if interrupted() or not engine.timeline_manager.timelines:
        return None
    threat = next(RoyalRules._iter_direct_threats_in(
        engine.timeline_manager.timelines, engine.current_turn_color,
    ), None)
    return None if interrupted() else threat


def prove_required_board_threat(
    engine: "FiveDEngine",
    interrupted: Callable[[], bool],
) -> RequiredBoardThreatProof | None:
    """Prove an uncapturable attacker must appear on a required successor.

    None means unproven, never no legal Action. The certificate requires:
    * branching cannot introduce or activate an earlier active Present;
    * the King and entire attack path already exist on the opponent's phase;
    * no piece on ANY movable board can legally capture the attacker.

    Every new playable successor during this Action belongs to the opponent,
    including on new branches. Thus acting-color capture sources can only
    disappear. Source/target occupancy and board-local King safety stay fixed
    until either board advances (which consumes the capture opportunity).
    Capture rays between original boards stay inside existing lane extrema;
    guarded allocation outside those extrema cannot fill a missing ray board.
    Existing opponent-phase boards are immutable. A virtual pass threat alone
    is NEVER sufficient evidence for this certificate.
    """
    if interrupted():
        return None
    manager = engine.timeline_manager
    timelines = manager.timelines
    if not timelines:
        return None
    color = engine.current_turn_color
    action = engine._ensure_current_action()
    required = ActionRules.required_boards(action, timelines)
    if not required:
        return None

    # Future actor branches must remain outside existing lanes and inactive.
    # Existing opponent lanes must already be active: increasing actor count
    # could otherwise activate one at an earlier opponent-side Present.
    for lane, timeline in timelines.items():
        expected = None if lane == 0 else (
            ChessColor.WHITE if lane > 0 else ChessColor.BLACK
        )
        if TimelineRules._owner(timeline) != expected:
            return None
        if expected == color.opposite() and not TimelineRules.is_active_timeline(timeline, timelines):
            return None
    next_lane = (
        manager._next_positive_id if color == ChessColor.WHITE
        else manager._next_negative_id
    )
    if color == ChessColor.WHITE:
        if next_lane <= max(0, *timelines):
            return None
    elif next_lane >= min(0, *timelines):
        return None
    opponent_count = TimelineRules.creator_counts(timelines)[color.opposite()]
    if abs(next_lane) <= opponent_count + 1:
        return None

    required_successors = {board.next(): board for board in required}
    rules = RoyalRules(timelines)
    threats = rules.threats_against(color)
    if interrupted():
        return None
    movable = ActionRules.movable_boards(action, timelines)
    for threat in threats:
        if interrupted():
            return None
        board = required_successors.get(threat.attacker.board)
        if board is None or threat.piece.piece_type == PieceType.PAWN:
            # En passant removes a pawn off the landing square; do not use
            # this proof for that additional capture form.
            continue
        if rules.board_view.resolve(threat.king.board) is None:
            continue
        if PieceMovementRules.is_slider(threat.piece.piece_type):
            path = PathRules.intermediate_squares(
                threat.piece.piece_type, threat.attacker, threat.king,
            )
            if any(rules.board_view.resolve(square.board) is None for square in path):
                # Virtual-pass path boards are still mutable in reality.
                continue
        target = Square5D(board, threat.attacker.x, threat.attacker.y)
        capturable = False
        for source_board in movable:
            if interrupted():
                return None
            position = rules.board_view.resolve(source_board)
            if position is None:
                return None
            for x, y, piece in position.get_all_pieces(color):
                if not RoyalRules._attack_geometry_matches(
                    piece, Square5D(source_board, x, y), target,
                ):
                    continue
                moves = engine.get_legal_moves_from_square(position, x, y)
                if interrupted():
                    return None
                if any(move.destination == target for move in moves):
                    capturable = True
                    break
            if capturable:
                break
        if not capturable and not interrupted():
            return RequiredBoardThreatProof(board, threat)
    return None
