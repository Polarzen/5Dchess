"""
5D Chess - Replay 棋谱回放模式（答辩核心）
支持：逐步回放、时间线树交互、快进/快退、统计面板
"""
from __future__ import annotations
from src.engine.move_generator import Move
from src.engine.engine import FiveDEngine
from src.engine.timeline import TimelineManager
from src.modes.base import GameModeBase
from src.utils.constants import ChessColor, GameState
from src.utils.logger import logger


class ReplayMode(GameModeBase):
    """棋谱回放模式"""

    def __init__(self, engine: FiveDEngine = None):
        super().__init__(engine)
        self.current_index: int = 0          # 当前走子索引
        self.move_list: list[Move] = []      # 完整的走子列表
        self.snapshots: list[dict] = []      # 快照历史
        self.is_playing: bool = False        # 自动播放
        self.play_speed: float = 1.0         # 播放速度(步/秒)
        self.selected_timeline_id: int = 0    # 当前查看的时间线
        self._play_timer: float = 0.0

    # ─── 加载棋谱 ──────────────────────────────────────

    def load_from_engine(self, engine: FiveDEngine):
        """从已结束的游戏加载棋谱"""
        self.move_list = list(engine.move_history)
        self.current_index = len(self.move_list)
        self._rebuild_snapshots()
        logger.info(f"加载棋谱: {len(self.move_list)} 步, {len(engine.timeline_manager.timelines)} 条时间线")

    def load_from_moves(self, moves: list[Move], timeline_manager: TimelineManager):
        """从走子列表和时间线管理器加载"""
        self.move_list = list(moves)
        self.engine.timeline_manager = timeline_manager
        self.current_index = len(self.move_list)
        self._rebuild_snapshots()
        logger.info(f"加载棋谱: {len(self.move_list)} 步")

    def load_from_pgn(self, filepath: str):
        """从 .5dpgn 文件加载"""
        from src.data.pgn_parser import FiveDPGN
        moves, tl_mgr = FiveDPGN.load(filepath)
        if moves is not None:
            self.load_from_moves(moves, tl_mgr)

    # ─── 回放控制 ──────────────────────────────────────

    def start(self):
        """启动回放模式"""
        self.current_index = 0
        self.is_playing = False
        self.selected_timeline_id = 0
        logger.info("Replay模式启动")
        self.emit("replay_started", {"total_moves": len(self.move_list)})

    def step_forward(self) -> bool:
        """前进一步"""
        if self.current_index < len(self.move_list):
            move = self.move_list[self.current_index]
            self.engine.execute_move(move)
            self.current_index += 1
            self._update_timeline_view(move)
            self.emit("step_changed", {"index": self.current_index, "move": move})
            return True
        return False

    def step_backward(self) -> bool:
        """后退一步"""
        if self.current_index > 0:
            self.current_index -= 1
            self._restore_to_index(self.current_index)
            self.emit("step_changed", {"index": self.current_index})
            return True
        return False

    def jump_to(self, index: int):
        """跳转到指定步数"""
        index = max(0, min(index, len(self.move_list)))
        self.current_index = index
        self._restore_to_index(index)
        self.emit("step_changed", {"index": self.current_index})

    def jump_to_start(self):
        """跳到开头"""
        self.jump_to(0)

    def jump_to_end(self):
        """跳到末尾"""
        self.jump_to(len(self.move_list))

    def toggle_play(self):
        """切换自动播放"""
        self.is_playing = not self.is_playing
        self.emit("play_toggled", {"playing": self.is_playing})

    def set_speed(self, speed: float):
        """设置播放速度"""
        self.play_speed = max(0.25, min(4.0, speed))

    def update(self, dt: float):
        """每帧更新（用于自动播放）"""
        if self.is_playing:
            self._play_timer += dt
            steps = int(self._play_timer * self.play_speed)
            if steps > 0:
                self._play_timer -= steps / self.play_speed
                for _ in range(steps):
                    if not self.step_forward():
                        self.is_playing = False
                        self.emit("play_completed", {})
                        break

    # ─── 时间线树交互 ──────────────────────────────────

    def select_timeline(self, timeline_id: int):
        """切换查看的时间线"""
        tl = self.engine.timeline_manager.get_timeline(timeline_id)
        if tl:
            self.selected_timeline_id = timeline_id
            self.emit("timeline_changed", {"timeline_id": timeline_id})

    def get_timeline_tree(self) -> dict:
        """获取时间线树结构"""
        return self.engine.timeline_manager.build_tree()

    def get_timeline_board(self, timeline_id: int, time_point: int = None) -> list[list[str]] | None:
        """获取指定时间线指定时间点的棋盘"""
        tl = self.engine.timeline_manager.get_timeline(timeline_id)
        if tl is None:
            return None
        if time_point is None:
            time_point = tl.latest_time
        pos = tl.get_position(time_point)
        return pos.board if pos else None

    # ─── 统计面板 ──────────────────────────────────────

    def get_statistics(self) -> dict:
        """获取对局统计"""
        tl_mgr = self.engine.timeline_manager
        timelines = tl_mgr.timelines

        white_time_travels = sum(
            1 for m in self.move_list
            if m.piece.color == ChessColor.WHITE and (m.is_branching or m.is_time_travel)
        )
        black_time_travels = sum(
            1 for m in self.move_list
            if m.piece.color == ChessColor.BLACK and (m.is_branching or m.is_time_travel)
        )

        branching_moves = sum(1 for m in self.move_list if m.is_branching)
        cross_timeline_moves = sum(1 for m in self.move_list if m.is_cross_timeline)

        # 计算平均分支深度
        depths = []
        for tl in timelines.values():
            depth = 0
            current = tl
            while current.parent_id is not None:
                depth += 1
                current = timelines.get(current.parent_id)
                if current is None:
                    break
            depths.append(depth)

        return {
            "total_moves": len(self.move_list),
            "current_index": self.current_index,
            "total_timelines": len(timelines),
            "active_timelines": len(tl_mgr.get_active_timelines()),
            "branching_moves": branching_moves,
            "cross_timeline_moves": cross_timeline_moves,
            "white_time_travels": white_time_travels,
            "black_time_travels": black_time_travels,
            "max_branch_depth": max(depths) if depths else 0,
            "avg_branch_depth": sum(depths) / len(depths) if depths else 0,
            "result": self.engine.game_state.name,
        }

    def get_overview(self) -> dict:
        """获取整体预览（所有时间线最终状态）"""
        overview = {}
        for tid, tl in self.engine.timeline_manager.timelines.items():
            if tl.is_active:
                latest = tl.latest_time
                pos = tl.get_position(latest)
                if pos:
                    overview[tid] = {
                        "board": pos.board,
                        "time_point": latest,
                        "parent_id": tl.parent_id,
                        "branch_turn": tl.branch_turn,
                    }
        return overview

    # ─── 内部方法 ──────────────────────────────────────

    def _rebuild_snapshots(self):
        """重建快照（通过重放所有走子）"""
        self.snapshots = []
        temp_engine = FiveDEngine()
        for move in self.move_list:
            temp_engine.execute_move(move)
            self.snapshots.append({
                "index": len(self.snapshots),
                "move": move,
                "summary": temp_engine.get_game_summary(),
            })

    def _restore_to_index(self, index: int):
        """恢复到指定步数"""
        self.engine._init_game()
        for i in range(index):
            if i < len(self.move_list):
                self.engine.execute_move(self.move_list[i])

    def _update_timeline_view(self, move: Move):
        """更新当前查看的时间线"""
        if move.is_branching or move.is_cross_timeline:
            self.selected_timeline_id = move.to_timeline_id

    def handle_move(self, move: Move) -> bool:
        """Replay模式不接受外部走子"""
        return False

    def get_current_board(self) -> list[list[str]]:
        """获取当前查看的棋盘"""
        return self.get_timeline_board(self.selected_timeline_id) or [[]]