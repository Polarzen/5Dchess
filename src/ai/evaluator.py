"""
5D Chess - 评估函数
五维扩展：考虑时间线控制和跨时间线威胁
"""
from src.utils.constants import ChessColor, PieceType, PIECE_VALUES, BOARD_SIZE
from src.engine.board import Position
from src.engine.action import ActionRules
from src.engine.multiverse import MultiverseBoardView
from src.engine.royal_rules import RoyalRules
from src.engine.timeline_rules import TimelineRules
from src.engine.move_validator import MoveValidator


# 位置价值表（白方视角，黑方需翻转）
PAWN_TABLE = [
    [0,  0,  0,  0,  0,  0,  0,  0],
    [50, 50, 50, 50, 50, 50, 50, 50],
    [10, 10, 20, 30, 30, 20, 10, 10],
    [5,  5, 10, 25, 25, 10,  5,  5],
    [0,  0,  0, 20, 20,  0,  0,  0],
    [5, -5,-10,  0,  0,-10, -5,  5],
    [5, 10, 10,-20,-20, 10, 10,  5],
    [0,  0,  0,  0,  0,  0,  0,  0],
]

KNIGHT_TABLE = [
    [-50,-40,-30,-30,-30,-30,-40,-50],
    [-40,-20,  0,  0,  0,  0,-20,-40],
    [-30,  0, 10, 15, 15, 10,  0,-30],
    [-30,  5, 15, 20, 20, 15,  5,-30],
    [-30,  0, 15, 20, 20, 15,  0,-30],
    [-30,  5, 10, 15, 15, 10,  5,-30],
    [-40,-20,  0,  5,  5,  0,-20,-40],
    [-50,-40,-30,-30,-30,-30,-40,-50],
]

BISHOP_TABLE = [
    [-20,-10,-10,-10,-10,-10,-10,-20],
    [-10,  0,  0,  0,  0,  0,  0,-10],
    [-10,  0,  5, 10, 10,  5,  0,-10],
    [-10,  5,  5, 10, 10,  5,  5,-10],
    [-10,  0, 10, 10, 10, 10,  0,-10],
    [-10, 10, 10, 10, 10, 10, 10,-10],
    [-10,  5,  0,  0,  0,  0,  5,-10],
    [-20,-10,-10,-10,-10,-10,-10,-20],
]

ROOK_TABLE = [
    [0,  0,  0,  0,  0,  0,  0,  0],
    [5, 10, 10, 10, 10, 10, 10,  5],
    [-5,  0,  0,  0,  0,  0,  0, -5],
    [-5,  0,  0,  0,  0,  0,  0, -5],
    [-5,  0,  0,  0,  0,  0,  0, -5],
    [-5,  0,  0,  0,  0,  0,  0, -5],
    [-5,  0,  0,  0,  0,  0,  0, -5],
    [0,  0,  0,  5,  5,  0,  0,  0],
]

QUEEN_TABLE = [
    [-20,-10,-10, -5, -5,-10,-10,-20],
    [-10,  0,  0,  0,  0,  0,  0,-10],
    [-10,  0,  5,  5,  5,  5,  0,-10],
    [-5,  0,  5,  5,  5,  5,  0, -5],
    [0,  0,  5,  5,  5,  5,  0, -5],
    [-10,  5,  5,  5,  5,  5,  0,-10],
    [-10,  0,  5,  0,  0,  0,  0,-10],
    [-20,-10,-10, -5, -5,-10,-10,-20],
]

KING_MIDDLE_TABLE = [
    [-30,-40,-40,-50,-50,-40,-40,-30],
    [-30,-40,-40,-50,-50,-40,-40,-30],
    [-30,-40,-40,-50,-50,-40,-40,-30],
    [-30,-40,-40,-50,-50,-40,-40,-30],
    [-20,-30,-30,-40,-40,-30,-30,-20],
    [-10,-20,-20,-20,-20,-20,-20,-10],
    [20, 20,  0,  0,  0,  0, 20, 20],
    [20, 30, 10,  0,  0, 10, 30, 20],
]

POSITION_TABLES = {
    PieceType.PAWN: PAWN_TABLE,
    PieceType.KNIGHT: KNIGHT_TABLE,
    PieceType.BISHOP: BISHOP_TABLE,
    PieceType.ROOK: ROOK_TABLE,
    PieceType.QUEEN: QUEEN_TABLE,
    PieceType.KING: KING_MIDDLE_TABLE,
}


class Evaluator:
    """局面评估器"""

    def __init__(self):
        self.validator = MoveValidator()

    def evaluate(self, position: Position, perspective: ChessColor = ChessColor.WHITE) -> float:
        """
        评估局面分数（从perspective视角）
        正值 = 对perspective有利
        """
        score = 0.0

        # 1. 子力价值
        score += self._material_score(position)

        # 2. 位置价值
        score += self._positional_score(position)

        # 3. 机动性（合法走子数）
        score += self._mobility_score(position)

        # 4. 将军/将杀
        score += self._check_score(position)

        # 返回从perspective视角的分数
        if perspective == ChessColor.BLACK:
            score = -score
        return score

    def evaluate_engine(self, engine, perspective: ChessColor = ChessColor.WHITE) -> float:
        """Evaluate the current multiverse at the Action boundary.

        Only playable/frontier boards contribute material and positional value;
        historical boards are intentionally excluded from the ordinary board
        score.  Timeline activity, the current Present, Action progress,
        canonical mobility, and RoyalRules check state provide the small
        multiverse terms around that frontier score.
        """
        timelines = engine.timeline_manager.timelines
        view = MultiverseBoardView(timelines)
        frontiers = tuple(view.iter_boards(playable_only=True))
        score = 0.0

        for board in frontiers:
            score += self._material_score(board.position)
            score += self._positional_score(board.position)

        # The creator count is a compact, deterministic measure of active
        # timeline control.  It is deliberately small beside material.
        active_frontiers = tuple(view.iter_boards(
            active_only=True,
            playable_only=True,
        ))
        counts = TimelineRules.creator_counts(timelines)
        score += (counts[ChessColor.WHITE] - counts[ChessColor.BLACK]) * 0.15
        for frontier in active_frontiers:
            owner = timelines[frontier.coord.timeline].owner
            if owner == ChessColor.WHITE:
                score += 0.05
            elif owner == ChessColor.BLACK:
                score -= 0.05

        # Mobility is obtained through the engine's canonical board/action API
        # rather than by creating a second legality implementation.
        action = engine._ensure_current_action()
        movable = ActionRules.movable_boards(action, timelines)
        current_mobility = 0
        for board in movable:
            position = engine._resolve_position(board)
            if position is None:
                continue
            current_mobility += len(engine.get_legal_moves(position))
        if engine.current_turn_color == ChessColor.WHITE:
            score += current_mobility * 0.05
        else:
            score -= current_mobility * 0.05

        present = engine.get_present()
        if present is not None:
            score += 0.15 if present.side == ChessColor.WHITE else -0.15
        if action.moves:
            score += 0.02 * len(action.moves) * (
                1 if action.color == ChessColor.WHITE else -1
            )

        royal = RoyalRules(timelines)
        if royal.is_in_check(ChessColor.BLACK):
            score += 0.5
        if royal.is_in_check(ChessColor.WHITE):
            score -= 0.5

        if perspective == ChessColor.BLACK:
            score = -score
        return score

    def _material_score(self, position: Position) -> float:
        """子力价值分数（白方视角）"""
        score = 0.0
        for y in range(BOARD_SIZE):
            for x in range(BOARD_SIZE):
                piece = position.get_piece(x, y)
                if piece:
                    val = piece.value
                    if piece.color == ChessColor.WHITE:
                        score += val
                    else:
                        score -= val
        return score

    def _positional_score(self, position: Position) -> float:
        """位置价值分数"""
        score = 0.0
        for y in range(BOARD_SIZE):
            for x in range(BOARD_SIZE):
                piece = position.get_piece(x, y)
                if piece is None:
                    continue
                table = POSITION_TABLES.get(piece.piece_type)
                if table is None:
                    continue
                if piece.color == ChessColor.WHITE:
                    score += table[y][x] * 0.1
                else:
                    score -= table[7 - y][x] * 0.1
        return score

    def _mobility_score(self, position: Position) -> float:
        """机动性分数"""
        from src.engine.move_generator import MoveGenerator
        gen = MoveGenerator(position)
        moves = gen.generate_all()
        legal = self.validator.filter_legal_moves(position, moves)
        white_moves = sum(1 for m in legal if m.piece.color == ChessColor.WHITE)
        black_moves = len(legal) - white_moves
        return (white_moves - black_moves) * 0.05

    def _check_score(self, position: Position) -> float:
        """将军/将杀分数"""
        score = 0.0
        if self.validator.is_king_in_check(position, ChessColor.BLACK):
            score += 0.5
        if self.validator.is_king_in_check(position, ChessColor.WHITE):
            score -= 0.5
        return score


def evaluate_engine(engine, perspective: ChessColor = ChessColor.WHITE) -> float:
    """Module-level convenience wrapper for multiverse evaluation."""
    return Evaluator().evaluate_engine(engine, perspective)


__all__ = ["Evaluator", "evaluate_engine"]
