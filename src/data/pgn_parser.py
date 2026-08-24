"""
5D Chess - .5dpgn 棋谱文件解析器
扩展PGN格式，支持时间线和分支信息
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from src.utils.logger import logger
from src.engine.move_generator import Move
from src.engine.timeline import TimelineManager


class FiveDPGN:
    """.5dpgn 棋谱文件格式解析/导出"""

    HEADER_PATTERN = re.compile(r'\[(\w+)\s+"([^"]*)"\]')

    @classmethod
    def save(cls, filepath: str, engine, game_metadata: dict = None) -> bool:
        """
        导出游戏为 .5dpgn 文件
        格式：JSON文件（便于程序解析）+ 人类可读的文本
        """
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            engine_data = engine.to_dict()
            metadata = {
                "format": "5dpgn",
                "version": "1.0",
                "date": __import__("datetime").datetime.now().isoformat(),
                **(game_metadata or {}),
            }

            data = {
                "metadata": metadata,
                "game": engine_data,
            }

            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            logger.info(f"棋谱已保存: {filepath}")
            return True
        except Exception as e:
            logger.error(f"棋谱保存失败: {e}")
            return False

    @classmethod
    def save_text(cls, filepath: str, engine, game_metadata: dict = None) -> bool:
        """
        导出为人类可读的文本格式 .5dpgn
        """
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            lines = []
            meta = game_metadata or {}

            lines.append('[Game "5D Chess"]')
            lines.append(f'[Mode "{meta.get("mode", "pvp")}"]')
            lines.append(f'[Date "{meta.get("date", "")}"]')
            lines.append(f'[White "{meta.get("white", "Player1")}"]')
            lines.append(f'[Black "{meta.get("black", "Player2")}"]')
            lines.append(f'[Result "{meta.get("result", "ongoing")}"]')
            lines.append(f'[TotalTimelines "{len(engine.timeline_manager.timelines)}"]')
            lines.append(f'[TotalMoves "{engine.move_counter}"]')
            lines.append("")

            current_turn = 0
            current_timeline = 0
            for move in engine.move_history:
                if move.from_time != current_turn or move.from_timeline_id != current_timeline:
                    current_turn = move.from_time
                    current_timeline = move.from_timeline_id
                    lines.append(f"{current_turn + 1}. (T{current_timeline})")

                notation = move.to_notation()
                if move.is_branching:
                    lines.append(f"  {notation} [BRANCH → T{move.to_timeline_id}]")
                elif move.is_cross_timeline:
                    lines.append(f"  {notation} [CROSS]")
                else:
                    lines.append(f"  {notation}")

            lines.append("")
            lines.append(f"# Result: {meta.get('result', '?')}")

            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

            logger.info(f"文本棋谱已保存: {filepath}")
            return True
        except Exception as e:
            logger.error(f"文本棋谱保存失败: {e}")
            return False

    @classmethod
    def load(cls, filepath: str) -> tuple[list[Move] | None, TimelineManager | None]:
        """
        从 .5dpgn 文件加载棋谱
        返回 (moves, timeline_manager)
        """
        path = Path(filepath)
        if not path.exists():
            logger.error(f"棋谱文件不存在: {filepath}")
            return None, None

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            game_data = data.get("game", {})
            tl_mgr = TimelineManager.from_dict(game_data.get("timeline_manager", {}))

            moves = []
            for m_data in game_data.get("move_history", []):
                from src.engine.coordinates import BoardCoord, Square5D
                from src.engine.piece import Piece
                from src.utils.constants import PieceType, ChessColor

                piece = Piece(
                    PieceType(m_data["piece_type"]),
                    ChessColor(m_data["piece_color"]),
                )
                captured = None
                if m_data.get("captured"):
                    captured = Piece(
                        PieceType(m_data["captured"]),
                        piece.color.opposite(),
                    )
                promotion = None
                if m_data.get("promotion"):
                    promotion = PieceType(m_data["promotion"])

                # Legacy .5dpgn files do not store the board half-move side.
                # Existing move history always belongs to the moving piece's
                # side, so use that as the migration adapter.
                source_board = BoardCoord(
                    timeline=m_data["from_timeline_id"],
                    turn=m_data["from_time"],
                    side=piece.color,
                )
                destination_board = BoardCoord(
                    timeline=m_data["to_timeline_id"],
                    turn=m_data["to_time"],
                    side=piece.color,
                )

                move = Move(
                    piece=piece,
                    source=Square5D(source_board, m_data["from_x"], m_data["from_y"]),
                    destination=Square5D(destination_board, m_data["to_x"], m_data["to_y"]),
                    is_branching=m_data.get("is_branching", False),
                    is_castling=m_data.get("is_castling", False),
                    is_en_passant=m_data.get("is_en_passant", False),
                    captured=captured,
                    promotion=promotion,
                    created_timeline=m_data.get("created_timeline"),
                )
                moves.append(move)

            logger.info(f"棋谱已加载: {filepath} ({len(moves)} 步)")
            return moves, tl_mgr
        except Exception as e:
            logger.error(f"棋谱加载失败: {e}")
            return None, None
