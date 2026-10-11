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
    from src.engine.move_generator import Move


def fixed_successor_attackers(engine, interrupted):
    """Find enemy pieces whose survival on a successor proves direct check.

    The source is hypothetical, but its royal target and every intervening
    square must already exist on the opponent's phase. Those boards cannot be
    changed in this Action. Advancing the source therefore makes the threat
    irreversible unless that very Move captures the attacker. Optional and
    inactive source boards are included. Pawns are excluded because en passant
    can remove them away from the Move's destination.

    None means interrupted; an empty mapping means no such certificate.
    """
    if interrupted():
        return None
    rules = RoyalRules(engine.timeline_manager.timelines)
    color = engine.current_turn_color
    kings = tuple(square for square in rules.king_squares(color)
                  if square.side == color.opposite())
    result = {}
    movable = ActionRules.movable_boards(
        engine._ensure_current_action(), engine.timeline_manager.timelines,
    )
    for board in movable:
        if interrupted():
            return None
        position = rules.board_view.resolve(board)
        if position is None:
            continue
        targets = set()
        for x, y, piece in position.get_all_pieces(color.opposite()):
            if piece.piece_type == PieceType.PAWN:
                continue
            source = Square5D(board.next(), x, y)
            for king in kings:
                if interrupted():
                    return None
                if rules._attacks_prevalidated_square_with_view(
                    piece, source, king, rules.board_view,
                ):
                    targets.add(Square5D(board, x, y))
                    break
        if targets:
            result[board] = frozenset(targets)
    return None if interrupted() else result


def move_exposes_fixed_attacker(move: "Move", attackers) -> bool:
    """Reject only canonical Moves which materialize a certified attacker.

    Branching advances the original source, but not the historical destination.
    A non-branching cross-timeline Move advances both original boards.
    """
    boards = {move.source.board}
    if move.is_cross_timeline and not move.is_branching:
        boards.add(move.destination.board)
    return any(move.destination != target
               for board in boards for target in attackers.get(board, ()))


@dataclass(frozen=True, slots=True)
class RequiredBoardThreatProof:
    board: BoardCoord
    threat: RoyalThreat
    other_threat: RoyalThreat | None = None


@dataclass(frozen=True, slots=True)
class RequiredBoardMobilityProof:
    board: BoardCoord
    forced_source_threat: RoyalThreat | None = None


def _forced_incoming_source_threat(engine, incoming, interrupted):
    """Certify a sole arrival source which every arrival makes irreparable.

    Only used at full capacity with an immobile required destination. No new
    acting-phase board can appear. Consuming the sole source any other way
    removes every arrival; consuming it by an arrival must expose a direct
    attacker on its successor, against a King/path already immutable here.
    """
    if not incoming or len({move.source.board for move in incoming}) != 1:
        return None
    if hasattr(engine, '_replay_origin'):
        return None
    view = RoyalRules(engine.timeline_manager.timelines).board_view
    first_threat = None
    for move in incoming:
        if interrupted():
            return None
        child = engine.clone_for_simulation()
        if not child.execute_action_move(move) or interrupted():
            return None
        threat = prove_direct_threat(child, interrupted)
        if (
            threat is None
            or threat.attacker.board != move.source.board.next()
            or view.resolve(threat.king.board) is None
        ):
            return None
        if PieceMovementRules.is_slider(threat.piece.piece_type) and any(
            view.resolve(square.board) is None
            for square in PathRules.intermediate_squares(
                threat.piece.piece_type, threat.attacker, threat.king,
            )
        ):
            return None
        first_threat = first_threat or threat
    return None if interrupted() else first_threat


def _branches_cannot_defer_required_boards(engine: "FiveDEngine") -> bool:
    manager = engine.timeline_manager
    timelines = manager.timelines
    color = engine.current_turn_color
    if not timelines:
        return False
    if len(timelines) >= manager.max_timelines:
        # No further branch can be allocated. Existing optional moves only
        # advance their sources/targets, and cannot activate or add a lane.
        return True
    for lane, timeline in timelines.items():
        expected = None if lane == 0 else (
            ChessColor.WHITE if lane > 0 else ChessColor.BLACK
        )
        if TimelineRules._owner(timeline) != expected:
            return False
        if expected == color.opposite() and not TimelineRules.is_active_timeline(timeline, timelines):
            return False
    next_lane = (
        manager._next_positive_id if color == ChessColor.WHITE
        else manager._next_negative_id
    )
    if color == ChessColor.WHITE:
        if next_lane <= max(0, *timelines):
            return False
    elif next_lane >= min(0, *timelines):
        return False
    return abs(next_lane) > TimelineRules.creator_counts(timelines)[color.opposite()] + 1


def prove_required_board_immobile(
    engine: "FiveDEngine",
    interrupted: Callable[[], bool],
) -> RequiredBoardMobilityProof | None:
    """Prove a required board has no safe present or future advancement.

    Current incoming/outgoing moves are checked canonically. Original acting-
    phase boards and local safety remain fixed until consumed. New playable
    boards have the opponent's phase, so no new incoming source can appear;
    new lanes outside existing extrema cannot open a path between old boards.

    Future historical destinations on new lanes need a separate guard. This
    certificate admits only Pawns (new own lanes lie behind their L movement)
    and Rooks whose first L-ray square toward new lanes is already blocked or
    missing on an original lane. At full timeline capacity there can be no new
    destinations, so all piece types may be checked. Otherwise other pieces
    conservatively reject the certificate. At capacity, a sole incoming source
    can also be rejected if every arrival creates an independently proved
    irreversible threat with a King/path already immutable in this state.
    """
    if interrupted() or not engine.timeline_manager.timelines:
        return None
    if not _branches_cannot_defer_required_boards(engine):
        return None
    manager = engine.timeline_manager
    color = engine.current_turn_color
    action = engine._ensure_current_action()
    required = ActionRules.required_boards(action, manager.timelines)
    if not required:
        return None
    direction = 1 if color == ChessColor.WHITE else -1
    next_lane = manager._next_positive_id if direction == 1 else manager._next_negative_id
    rules = RoyalRules(manager.timelines)
    legal_by_board = {}
    for board in required:
        if interrupted():
            return None
        position = rules.board_view.resolve(board)
        if position is None:
            return None
        future_destination_possible = False
        pieces = (position.get_all_pieces(color)
                  if len(manager.timelines) < manager.max_timelines else ())
        for x, y, piece in pieces:
            if piece.piece_type == PieceType.PAWN:
                continue
            if piece.piece_type == PieceType.ROOK and abs(next_lane - board.timeline) > 1:
                intermediate = rules.board_view.resolve(BoardCoord(
                    board.timeline + direction, board.turn, board.side,
                ))
                if intermediate is None or intermediate.get_piece(x, y) is not None:
                    continue
            future_destination_possible = True
            break
        if future_destination_possible:
            continue
        if board not in legal_by_board:
            legal_by_board[board] = engine.get_legal_moves(position)
        if interrupted():
            return None
        if legal_by_board[board]:
            continue
        incoming = []
        at_capacity = len(manager.timelines) >= manager.max_timelines
        for source in ActionRules.movable_boards(action, manager.timelines):
            if interrupted():
                return None
            if source in legal_by_board:
                source_moves = legal_by_board[source]
            else:
                source_position = rules.board_view.resolve(source)
                if source_position is None:
                    return None
                targeted = getattr(engine, 'get_legal_moves_to_boards', None)
                source_moves = (
                    targeted(source_position, {board}) if targeted is not None
                    else engine.get_legal_moves(source_position)
                )
            if interrupted():
                return None
            incoming.extend(move for move in source_moves if move.destination.board == board)
            if incoming and not at_capacity:
                break
        if not incoming and not interrupted():
            return RequiredBoardMobilityProof(board)
        if at_capacity:
            threat = _forced_incoming_source_threat(engine, incoming, interrupted)
            if threat is not None:
                return RequiredBoardMobilityProof(board, threat)
    return None


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
    """Prove a surviving attacker must appear on a required successor.

    None means unproven, never no legal Action. The certificate requires:
    * branching cannot introduce or activate an earlier active Present;
    * the King and entire attack path already exist on the opponent's phase;
    * no piece on ANY movable board can legally capture the attacker, or two
      distinct non-Pawn attackers on this board each have a fixed royal target.

    Every new playable successor during this Action belongs to the opponent,
    including on new branches. Thus acting-color capture sources can only
    disappear. Source/target occupancy and board-local King safety stay fixed
    until either board advances (which consumes the capture opportunity).
    Capture rays between original boards stay inside existing lane extrema;
    guarded allocation outside those extrema cannot fill a missing ray board.
    Existing opponent-phase boards are immutable. A virtual pass threat alone
    is NEVER sufficient evidence for this certificate.

    One advancement can remove at most one enemy non-Pawn from a board. Two
    distinct fixed attackers on the same required board therefore suffice even
    when each is individually capturable; at least one must survive.
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

    # At capacity no branches are possible. Otherwise future actor branches
    # must remain outside existing lanes and inactive; existing opponent lanes
    # must already be active so increasing actor count cannot rewind Present.
    if not _branches_cannot_defer_required_boards(engine):
        return None

    required_successors = {board.next(): board for board in required}
    rules = RoyalRules(timelines)
    threats = rules.threats_against(color)
    if interrupted():
        return None
    movable = ActionRules.movable_boards(action, timelines)
    fixed_attackers: dict[BoardCoord, RoyalThreat] = {}
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
        previous = fixed_attackers.get(board)
        if previous is not None and previous.attacker != threat.attacker:
            if interrupted():
                return None
            return RequiredBoardThreatProof(board, previous, threat)
        fixed_attackers[board] = threat
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
                targeted = getattr(engine, 'get_legal_moves_from_square_to_boards', None)
                moves = (
                    targeted(position, x, y, {target.board}) if targeted is not None
                    else engine.get_legal_moves_from_square(position, x, y)
                )
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
