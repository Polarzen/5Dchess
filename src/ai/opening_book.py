"""
5D Chess - 开局库
"""
import json
from pathlib import Path
from src.utils.constants import ChessColor
from src.engine.move_generator import Move
from src.engine.board import Position
from src.config import ROOT_DIR


class OpeningBook:
    """开局库管理器"""

    def __init__(self, book_path: Path = None):
        self.book_path = book_path or ROOT_DIR / "data" / "openings.json"
        self.openings: list[dict] = []
        self._load()

    def _load(self):
        """加载开局库"""
        if self.book_path.exists():
            try:
                with open(self.book_path, "r", encoding="utf-8") as f:
                    self.openings = json.load(f)
            except (json.JSONDecodeError, IOError):
                self.openings = []

    def save(self):
        """保存开局库"""
        self.book_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.book_path, "w", encoding="utf-8") as f:
            json.dump(self.openings, f, ensure_ascii=False, indent=2)

    def lookup(self, move_history: list[Move]) -> list[Move] | None:
        """
        查找当前局面匹配的开局走法
        返回推荐的走法列表（或None表示无匹配）
        """
        if not self.openings:
            return None

        # 构建当前走子序列
        current_sequence = [
            f"{m.from_x},{m.from_y}->{m.to_x},{m.to_y}"
            for m in move_history
        ]

        best_match = None
        best_match_len = 0

        for opening in self.openings:
            opening_seq = opening.get("moves", [])
            if len(opening_seq) <= len(current_sequence):
                continue

            # 检查前N步是否匹配
            match = True
            for i, (expected, actual) in enumerate(zip(opening_seq, current_sequence)):
                if expected != actual:
                    match = False
                    break

            if match and len(current_sequence) > best_match_len:
                best_match = opening
                best_match_len = len(current_sequence)

        if best_match and best_match_len < len(best_match.get("moves", [])):
            # 返回下一步走法（需要解析为Move对象 — 由调用者处理）
            next_move_str = best_match["moves"][best_match_len]
            # 返回字符串表示，由调用者匹配
            return None  # 在五维环境下，返回None让AI自行搜索

        return None

    def add_opening(self, name: str, moves: list[str], win_rate: float = 0.5):
        """添加开局"""
        self.openings.append({
            "name": name,
            "moves": moves,
            "win_rate_white": win_rate,
            "total_games": 0,
        })