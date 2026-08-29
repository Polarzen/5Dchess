"""
5D Chess - Alpha-Beta 搜索AI（中等）
"""
import time
from src.utils.constants import ChessColor, AIDifficulty
from src.ai.base import AIPlayer
from src.ai.evaluator import Evaluator
from src.engine.move_generator import Move, MoveGenerator
from src.engine.move_validator import MoveValidator
from src.engine.board import Position
from src.engine.engine import FiveDEngine
from src.config import AI_TIMEOUT


class AlphaBetaAI(AIPlayer):
    """Alpha-Beta 剪枝搜索AI"""

    def __init__(self, color: ChessColor, search_depth: int = 2):
        super().__init__(color, AIDifficulty.MEDIUM)
        self.search_depth = search_depth
        self.evaluator = Evaluator()
        self.validator = MoveValidator()
        self._start_time = 0.0
        self._timeout = AI_TIMEOUT
        self._nodes_searched = 0

    def choose_move(self, engine: FiveDEngine) -> Move | None:
        """Alpha-Beta 搜索选择最佳走子。"""
        self._guard_action_progress(engine)

        # Do not bind the AI to the legacy UI-selected timeline.  In a
        # multi-board Action the previously selected board may already have
        # flipped to the opponent while another Present board is still required.
        # The engine's no-argument selector always falls forward to a required
        # board first, which is exactly what the compatibility-path AI needs in
        # order to finish and submit its Action.
        moves = engine.get_legal_moves()
        if not moves:
            return None

        position = engine._resolve_position(moves[0].source.board)
        if position is None:
            return None

        self._start_time = time.time()
        self._nodes_searched = 0

        best_move = None
        best_score = float("-inf")
        alpha = float("-inf")
        beta = float("inf")

        # 走子排序（吃子优先，提升剪枝效率）
        moves.sort(key=lambda m: self._move_priority(m), reverse=True)

        for move in moves:
            if time.time() - self._start_time > self._timeout:
                break

            new_pos = self._simulate_move(position, move)
            if new_pos is None:
                continue

            score = -self._alpha_beta(new_pos, self.search_depth - 1, -beta, -alpha)

            if score > best_score:
                best_score = score
                best_move = move

            alpha = max(alpha, score)

        return best_move

    def _alpha_beta(self, position: Position, depth: int, alpha: float, beta: float) -> float:
        """Alpha-Beta 递归搜索"""
        self._nodes_searched += 1

        if time.time() - self._start_time > self._timeout:
            return self.evaluator.evaluate(position, self.color)

        if depth == 0:
            return self.evaluator.evaluate(position, self.color)

        gen = MoveGenerator(position)
        moves = gen.generate_all()
        legal = self.validator.filter_legal_moves(position, moves)

        if not legal:
            # 无合法走子 → 将杀或逼和
            if self.validator.is_king_in_check(position, position.turn):
                return float("-inf") if position.turn == self.color else float("inf")
            return 0.0  # 逼和

        # 走子排序
        legal.sort(key=lambda m: self._move_priority(m), reverse=True)

        for move in legal:
            if time.time() - self._start_time > self._timeout:
                break

            new_pos = self._simulate_move(position, move)
            if new_pos is None:
                continue

            score = -self._alpha_beta(new_pos, depth - 1, -beta, -alpha)
            alpha = max(alpha, score)
            if alpha >= beta:
                break  # Beta 剪枝

        return alpha

    def _simulate_move(self, position: Position, move: Move) -> Position | None:
        """模拟走子（简化版，不做时间旅行分支）"""
        if move.is_branching or move.is_cross_timeline:
            return None  # 在搜索中跳过时间旅行

        new_pos = position.copy()
        new_pos.move_piece(move.from_x, move.from_y, move.to_x, move.to_y)

        if move.is_castling:
            row = move.to_y
            if move.to_x == 6:
                new_pos.move_piece(7, row, 5, row)
            elif move.to_x == 2:
                new_pos.move_piece(0, row, 3, row)

        if move.is_en_passant:
            direction = -1 if position.turn == ChessColor.WHITE else 1
            new_pos.set_piece(move.to_x, move.to_y - direction, None)

        if move.promotion:
            from src.engine.piece import Piece
            new_pos.set_piece(move.to_x, move.to_y, Piece(move.promotion, position.turn))

        # Match the real engine transition: every local move advances the legacy
        # half-move index and flips the side together. Keeping these two fields
        # synchronized is required by canonical BoardCoord conversion.
        new_pos.time_point = position.time_point + 1
        new_pos.turn = position.turn.opposite()
        return new_pos

    @staticmethod
    def _move_priority(move: Move) -> float:
        """走子优先级（用于排序）"""
        priority = 0.0
        if move.captured:
            priority += move.captured.value - move.piece.value * 0.1  # MVV-LVA
        if move.promotion:
            priority += 9.0  # 升变
        if move.is_castling:
            priority += 1.0
        if move.is_branching:
            priority += 2.0
        return priority

    @property
    def nodes_searched(self) -> int:
        return self._nodes_searched
