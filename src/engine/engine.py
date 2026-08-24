"""
5D Chess - 五维核心引擎
整合棋盘、走子生成、校验、时间线管理、规则判定
"""
from __future__ import annotations
from dataclasses import dataclass, field, replace
from src.config import DEFAULT_MAX_TIMELINES, DEFAULT_MAX_TURNS
from src.utils.constants import ChessColor, PieceType, GameState
from src.utils.logger import logger
from src.engine.piece import Piece
from src.engine.board import Position
from src.engine.move_generator import Move, MoveGenerator
from src.engine.move_validator import MoveValidator
from src.engine.timeline import TimelineManager
from src.engine.rules import RulesEngine


@dataclass
class FiveDEngine:
    """5D国际象棋核心引擎"""
    max_timelines: int = DEFAULT_MAX_TIMELINES
    max_turns: int = DEFAULT_MAX_TURNS
    timeline_manager: TimelineManager = field(default_factory=TimelineManager)
    rules_engine: RulesEngine = field(default_factory=RulesEngine)
    game_state: GameState = GameState.WAITING
    move_history: list[Move] = field(default_factory=list)
    move_counter: int = 0
    current_turn_color: ChessColor = ChessColor.WHITE

    def __post_init__(self):
        self.timeline_manager.max_timelines = self.max_timelines
        self._init_game()

    def _init_game(self):
        """初始化游戏"""
        tl = self.timeline_manager.create_initial_timeline()
        initial_pos = Position.initial(timeline_id=tl.timeline_id, time_point=0)
        tl.add_position(initial_pos)
        self.game_state = GameState.PLAYING
        self.move_history = []
        self.move_counter = 0
        self.current_turn_color = ChessColor.WHITE
        logger.info("游戏初始化完成")

    def get_current_position(self) -> Position:
        """获取当前活跃时间线的最新棋盘"""
        tl = self.timeline_manager.get_timeline(
            self.timeline_manager.active_timeline_id
        )
        if tl is None:
            raise RuntimeError("没有活跃时间线")
        return tl.positions[tl.latest_time]

    def get_legal_moves(self, position: Position = None) -> list[Move]:
        """获取当前局面的合法走子"""
        if position is None:
            position = self.get_current_position()
        if self.game_state != GameState.PLAYING:
            return []
        generator = MoveGenerator(position, self.timeline_manager.timelines)
        validator = MoveValidator(self.timeline_manager.timelines)
        pseudo_moves = generator.generate_all()
        return validator.filter_legal_moves(position, pseudo_moves)

    def execute_move(self, move: Move) -> bool:
        """执行普通、跨棋盘或分支走子。"""
        if self.game_state != GameState.PLAYING:
            logger.warning("游戏已结束，无法走子")
            return False

        try:
            if move.is_branching:
                return self._execute_branching_move(move)
            if move.is_cross_timeline:
                return self._execute_cross_timeline_move(move)
            return self._execute_normal_move(move)
        except Exception as e:
            logger.error(f"走子执行失败: {e}")
            return False

    def _execute_normal_move(self, move: Move) -> bool:
        """执行同一棋盘上的普通空间移动。"""
        current_pos = self.get_current_position()
        new_pos = current_pos.copy()
        new_pos.time_point = current_pos.time_point + 1
        new_pos.turn = current_pos.turn.opposite()
        new_pos.move_number = self.move_counter + 1

        new_pos.move_piece(move.from_x, move.from_y, move.to_x, move.to_y)

        if move.is_castling:
            row = move.to_y
            if move.to_x == 6:
                new_pos.move_piece(7, row, 5, row)
            elif move.to_x == 2:
                new_pos.move_piece(0, row, 3, row)

        if move.is_en_passant:
            direction = -1 if current_pos.turn == ChessColor.WHITE else 1
            new_pos.set_piece(move.to_x, move.to_y - direction, None)

        if move.promotion:
            new_pos.set_piece(move.to_x, move.to_y, Piece(move.promotion, current_pos.turn))

        self._update_castling_rights(new_pos, move)

        tl = self.timeline_manager.get_timeline(move.to_timeline_id)
        if tl is None:
            return False
        tl.add_position(new_pos)

        self.move_counter += 1
        self.move_history.append(move)
        self.current_turn_color = new_pos.turn
        self._check_game_result(new_pos)
        return True

    def _execute_branching_move(self, move: Move) -> bool:
        """执行落到历史棋盘并创建新时间线的走子。"""
        current_pos = self.get_current_position()
        source_tl = self.timeline_manager.get_timeline(move.from_timeline_id)
        target_tl = self.timeline_manager.get_timeline(move.to_timeline_id)
        if source_tl is None or target_tl is None:
            return False
        if move.to_time not in target_tl.positions:
            return False
        if move.to_time >= target_tl.latest_time:
            # Branching is defined by landing on a historical board.
            return False

        new_tl = self.timeline_manager.create_branch(
            parent_id=move.to_timeline_id,
            branch_turn=current_pos.time_point,
            branch_move_id=self.move_counter + 1,
            target_time=move.to_time,
            creator=move.piece.color,
        )
        if new_tl is None:
            logger.warning("无法创建新时间线：已达上限或目标棋盘不存在")
            return False

        past_pos = new_tl.positions[move.to_time]
        new_target_pos = past_pos.copy()
        new_target_pos.time_point = move.to_time + 1
        new_target_pos.turn = past_pos.turn.opposite()
        new_target_pos.move_number = self.move_counter + 1
        new_target_pos.set_piece(move.to_x, move.to_y, move.piece)
        new_tl.add_position(new_target_pos)

        # The source history remains immutable; removal happens in a successor.
        new_source_pos = current_pos.copy()
        new_source_pos.set_piece(move.from_x, move.from_y, None)
        new_source_pos.time_point = current_pos.time_point + 1
        new_source_pos.turn = current_pos.turn.opposite()
        new_source_pos.move_number = self.move_counter + 1
        source_tl.add_position(new_source_pos)

        self.timeline_manager.switch_active(new_tl.timeline_id)

        recorded_move = replace(move, created_timeline=new_tl.timeline_id)
        self.move_counter += 1
        self.move_history.append(recorded_move)
        self.current_turn_color = new_source_pos.turn

        logger.info(
            f"时间线分支: L{new_tl.timeline_id:+d} ← "
            f"L{new_tl.parent_id:+d} @ t={move.to_time}"
        )
        return True

    def _execute_cross_timeline_move(self, move: Move) -> bool:
        """执行两个可走棋盘之间的跨时间线移动。"""
        current_pos = self.get_current_position()
        source_tl = self.timeline_manager.get_timeline(move.from_timeline_id)
        target_tl = self.timeline_manager.get_timeline(move.to_timeline_id)
        if source_tl is None or target_tl is None:
            return False

        target_time = move.to_time
        if target_time not in target_tl.positions:
            return False
        if target_time != target_tl.latest_time:
            # Landing on history must use the branching execution path instead.
            return False

        target_pos = target_tl.positions[target_time]
        if target_pos.turn != current_pos.turn:
            return False

        new_target_pos = target_pos.copy()
        new_target_pos.time_point = target_pos.time_point + 1
        new_target_pos.turn = target_pos.turn.opposite()
        new_target_pos.move_number = self.move_counter + 1
        new_target_pos.set_piece(move.to_x, move.to_y, move.piece)

        # Never mutate the stored source board. Create its successor first.
        new_source_pos = current_pos.copy()
        new_source_pos.set_piece(move.from_x, move.from_y, None)
        new_source_pos.time_point = current_pos.time_point + 1
        new_source_pos.turn = current_pos.turn.opposite()
        new_source_pos.move_number = self.move_counter + 1

        target_tl.add_position(new_target_pos)
        source_tl.add_position(new_source_pos)

        self.move_counter += 1
        self.move_history.append(move)
        self.current_turn_color = new_source_pos.turn
        return True

    def _update_castling_rights(self, position: Position, move: Move):
        """更新王车易位权"""
        rights = position.castling_rights
        piece = move.piece

        if piece.piece_type == PieceType.KING:
            if piece.color == ChessColor.WHITE:
                rights["white_kingside"] = False
                rights["white_queenside"] = False
            else:
                rights["black_kingside"] = False
                rights["black_queenside"] = False

        if piece.piece_type == PieceType.ROOK:
            if piece.color == ChessColor.WHITE:
                if move.from_x == 7 and move.from_y == 7:
                    rights["white_kingside"] = False
                if move.from_x == 0 and move.from_y == 7:
                    rights["white_queenside"] = False
            else:
                if move.from_x == 7 and move.from_y == 0:
                    rights["black_kingside"] = False
                if move.from_x == 0 and move.from_y == 0:
                    rights["black_queenside"] = False

    def _check_game_result(self, position: Position):
        """检查游戏结果"""
        result = self.rules_engine.get_game_result(position)
        if result == "white_win":
            self.game_state = GameState.CHECKMATE
            logger.info("白方获胜！")
        elif result == "black_win":
            self.game_state = GameState.CHECKMATE
            logger.info("黑方获胜！")
        elif result == "draw":
            self.game_state = GameState.DRAW
            logger.info("和棋！")

    def get_game_summary(self) -> dict:
        """获取游戏摘要"""
        tl_mgr = self.timeline_manager
        return {
            "game_state": self.game_state.name,
            "total_moves": self.move_counter,
            "total_timelines": len(tl_mgr.timelines),
            "active_timelines": len(tl_mgr.get_active_timelines()),
            "current_turn": self.current_turn_color.value,
            "active_timeline_id": tl_mgr.active_timeline_id,
            "move_history": [m.to_notation() for m in self.move_history],
        }

    def to_dict(self) -> dict:
        """序列化完整游戏状态"""
        return {
            "max_timelines": self.max_timelines,
            "max_turns": self.max_turns,
            "timeline_manager": self.timeline_manager.to_dict(),
            "game_state": self.game_state.name,
            "move_history": [
                {
                    "piece_type": m.piece.piece_type.value,
                    "piece_color": m.piece.color.value,
                    "from_x": m.from_x, "from_y": m.from_y,
                    "to_x": m.to_x, "to_y": m.to_y,
                    "from_timeline_id": m.from_timeline_id,
                    "to_timeline_id": m.to_timeline_id,
                    "from_time": m.from_time, "to_time": m.to_time,
                    "is_branching": m.is_branching,
                    "created_timeline": m.created_timeline,
                    "is_castling": m.is_castling,
                    "is_en_passant": m.is_en_passant,
                    "promotion": m.promotion.value if m.promotion else None,
                    "captured": m.captured.piece_type.value if m.captured else None,
                    "notation": m.to_notation(),
                }
                for m in self.move_history
            ],
            "move_counter": self.move_counter,
            "current_turn_color": self.current_turn_color.value,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FiveDEngine":
        engine = cls(
            max_timelines=data.get("max_timelines", DEFAULT_MAX_TIMELINES),
            max_turns=data.get("max_turns", DEFAULT_MAX_TURNS),
        )
        engine.timeline_manager = TimelineManager.from_dict(data["timeline_manager"])
        engine.game_state = GameState[data["game_state"]]
        engine.move_counter = data["move_counter"]
        engine.current_turn_color = ChessColor(data["current_turn_color"])
        return engine
