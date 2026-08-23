"""
5D Chess - 引擎单元测试
"""
import pytest
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.engine import FiveDEngine, Position, Piece, piece_from_char, Move, MoveGenerator, MoveValidator, Timeline, TimelineManager, RulesEngine
from src.utils.constants import ChessColor, PieceType, GameState, INITIAL_BOARD


class TestPiece:
    """棋子定义测试"""

    def test_piece_from_char(self):
        assert piece_from_char("K") is not None
        assert piece_from_char("K").piece_type == PieceType.KING
        assert piece_from_char("K").color == ChessColor.WHITE
        assert piece_from_char("k").color == ChessColor.BLACK
        assert piece_from_char("") is None

    def test_piece_value(self):
        king = Piece(PieceType.KING, ChessColor.WHITE)
        assert king.value == 10000
        queen = Piece(PieceType.QUEEN, ChessColor.BLACK)
        assert queen.value == 9

    def test_piece_symbol(self):
        queen = Piece(PieceType.QUEEN, ChessColor.WHITE)
        assert queen.symbol in ("♕", "Q")


class TestPosition:
    """棋盘测试"""

    def test_initial_position(self):
        pos = Position.initial()
        assert pos.turn == ChessColor.WHITE
        assert pos.time_point == 0
        # 白棋在1-2行，黑棋在7-8行
        assert pos.get_piece(0, 6) is not None  # 白兵
        assert pos.get_piece(0, 6).color == ChessColor.WHITE
        assert pos.get_piece(0, 0) is not None  # 黑车
        assert pos.get_piece(0, 0).color == ChessColor.BLACK

    def test_find_king(self):
        pos = Position.initial()
        wk = pos.find_king(ChessColor.WHITE)
        assert wk == (4, 7)  # e1
        bk = pos.find_king(ChessColor.BLACK)
        assert bk == (4, 0)  # e8

    def test_move_piece(self):
        pos = Position.initial()
        # e2-e4
        pos.move_piece(4, 6, 4, 4)
        assert pos.get_piece(4, 4) is not None
        assert pos.get_piece(4, 4).piece_type == PieceType.PAWN
        assert pos.is_empty(4, 6)

    def test_copy(self):
        pos = Position.initial()
        pos2 = pos.copy()
        pos2.move_piece(4, 6, 4, 4)
        assert pos.get_piece(4, 6) is not None  # 原棋盘不受影响
        assert pos2.is_empty(4, 6)


class TestMoveGenerator:
    """走子生成测试"""

    def test_initial_pawn_moves(self):
        pos = Position.initial()
        gen = MoveGenerator(pos)
        moves = gen.generate_all()
        # 初始局面白方应有16个兵走子 + 4个马走子
        pawn_moves = [m for m in moves if m.piece.piece_type == PieceType.PAWN]
        assert len(pawn_moves) == 16  # 8个兵，每个可走1或2格

    def test_knight_moves(self):
        pos = Position.initial()
        gen = MoveGenerator(pos)
        moves = gen.generate_all()
        knight_moves = [m for m in moves if m.piece.piece_type == PieceType.KNIGHT]
        assert len(knight_moves) == 4  # 2个马，每个2个走法

    def test_no_king_moves_initial(self):
        pos = Position.initial()
        gen = MoveGenerator(pos)
        moves = gen.generate_all()
        king_moves = [m for m in moves if m.piece.piece_type == PieceType.KING]
        assert len(king_moves) == 0  # 王被包围，无法移动


class TestMoveValidator:
    """走子校验测试"""

    def test_legal_filter(self):
        pos = Position.initial()
        gen = MoveGenerator(pos)
        validator = MoveValidator()
        all_moves = gen.generate_all()
        legal = validator.filter_legal_moves(pos, all_moves)
        assert len(legal) > 0
        # 初始局面所有伪合法走子都应该是合法的（王未被攻击）
        assert len(legal) == len(all_moves)

    def test_not_in_check_initial(self):
        pos = Position.initial()
        validator = MoveValidator()
        assert not validator.is_king_in_check(pos, ChessColor.WHITE)
        assert not validator.is_king_in_check(pos, ChessColor.BLACK)


class TestRulesEngine:
    """规则引擎测试"""

    def test_initial_not_checkmate(self):
        pos = Position.initial()
        engine = RulesEngine()
        assert not engine.is_checkmate(pos)
        assert not engine.is_stalemate(pos)

    def test_initial_no_result(self):
        pos = Position.initial()
        engine = RulesEngine()
        assert engine.get_game_result(pos) is None

    def test_insufficient_material(self):
        # 只有两王
        board = [["" for _ in range(8)] for _ in range(8)]
        board[0][4] = "k"
        board[7][4] = "K"
        pos = Position(
            board=board,
            turn=ChessColor.WHITE,
            timeline_id=0,
            time_point=0,
        )
        engine = RulesEngine()
        assert engine.is_draw_by_insufficient_material(pos)


class TestTimelineManager:
    """时间线管理测试"""

    def test_create_initial(self):
        mgr = TimelineManager()
        tl = mgr.create_initial_timeline()
        assert tl.timeline_id == 0
        assert tl.parent_id is None

    def test_create_branch(self):
        mgr = TimelineManager()
        mgr.create_initial_timeline()
        tl = mgr.create_branch(parent_id=0, branch_turn=5, branch_move_id=10, target_time=3)
        assert tl is not None
        assert tl.parent_id == 0
        assert tl.branch_turn == 5

    def test_max_timelines(self):
        mgr = TimelineManager(max_timelines=3)
        mgr.create_initial_timeline()
        assert mgr.create_branch(0, 1, 1, 0) is not None
        assert mgr.create_branch(0, 2, 2, 0) is not None
        assert mgr.create_branch(0, 3, 3, 0) is None  # 超过上限


class TestFiveDEngine:
    """核心引擎集成测试"""

    def test_engine_init(self):
        engine = FiveDEngine()
        assert engine.game_state == GameState.PLAYING
        assert engine.current_turn_color == ChessColor.WHITE
        assert engine.move_counter == 0

    def test_initial_legal_moves(self):
        engine = FiveDEngine()
        moves = engine.get_legal_moves()
        assert len(moves) > 0
        assert all(m.piece.color == ChessColor.WHITE for m in moves)

    def test_execute_and_get_moves(self):
        engine = FiveDEngine()
        # 执行 e7-e5 (白方兵从row 6到row 4)
        moves = engine.get_legal_moves()
        e2e4 = [m for m in moves if m.from_x == 4 and m.from_y == 6 and m.to_y == 4]
        assert len(e2e4) > 0
        success = engine.execute_move(e2e4[0])
        assert success
        assert engine.move_counter == 1
        assert engine.current_turn_color == ChessColor.BLACK

    def test_game_summary(self):
        engine = FiveDEngine()
        summary = engine.get_game_summary()
        assert summary["game_state"] == "PLAYING"
        assert summary["total_moves"] == 0
        assert summary["total_timelines"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])