"""
5D Chess - 数据层测试
"""
import pytest
import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.models import GameRecord, MoveRecord, PositionRecord, TimelineRecord, GameStats
from src.data.pgn_parser import FiveDPGN
from src.engine import FiveDEngine, MoveGenerator
from src.utils.constants import ChessColor, PieceType


class TestModels:
    def test_game_record(self):
        record = GameRecord(
            mode="pvp",
            player_white="Player1",
            player_black="Player2",
        )
        d = record.to_dict()
        assert d["mode"] == "pvp"
        assert d["player_white"] == "Player1"

    def test_move_record_from_move(self):
        engine = FiveDEngine()
        moves = engine.get_legal_moves()
        move = moves[0]
        record = MoveRecord.from_move(move, game_id=1, turn_number=1)
        assert record.game_id == 1
        assert record.piece_type == move.piece.piece_type.value
        assert record.from_x == move.from_x
        assert record.from_y == move.from_y


class TestFiveDPGN:
    def test_save_and_load(self, tmp_path):
        """测试棋谱保存和加载"""
        engine = FiveDEngine()
        # 走几步
        moves = engine.get_legal_moves()
        engine.execute_move(moves[0])  # 白方
        moves = engine.get_legal_moves()
        engine.execute_move(moves[0])  # 黑方

        filepath = tmp_path / "test.5dpgn"
        success = FiveDPGN.save(str(filepath), engine, {
            "mode": "pvp",
            "white": "TestWhite",
            "black": "TestBlack",
        })
        assert success
        assert filepath.exists()

        loaded_moves, tl_mgr = FiveDPGN.load(str(filepath))
        assert loaded_moves is not None
        assert len(loaded_moves) == 2
        assert tl_mgr is not None

    def test_save_text(self, tmp_path):
        """测试文本格式保存"""
        engine = FiveDEngine()
        moves = engine.get_legal_moves()
        engine.execute_move(moves[0])

        filepath = tmp_path / "test.txt"
        success = FiveDPGN.save_text(str(filepath), engine, {
            "mode": "pvp",
            "white": "TestWhite",
            "black": "TestBlack",
        })
        assert success
        assert filepath.exists()


class TestAsyncWriter:
    def test_singleton(self):
        from src.data.async_writer import AsyncDBWriter
        w1 = AsyncDBWriter()
        w2 = AsyncDBWriter()
        assert w1 is w2

    def test_queue_operations(self):
        from src.data.async_writer import AsyncDBWriter
        writer = AsyncDBWriter()
        writer.write_move({"test": "data"})
        writer.write_position({"test": "data"})
        # 不启动worker，仅测试入队
        assert writer._queue.qsize() >= 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])