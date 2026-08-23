"""
5D Chess - 时间线管理
"""
from __future__ import annotations
from dataclasses import dataclass, field
from src.engine.board import Position
from src.engine.move_generator import Move


@dataclass
class Timeline:
    """时间线 — 一条独立的时间分支"""
    timeline_id: int
    parent_id: int | None = None              # 父时间线
    branch_move_id: int | None = None          # 触发分支的走子
    branch_turn: int | None = None             # 分支发生的回合
    positions: dict[int, Position] = field(default_factory=dict)  # time_point → Position
    is_active: bool = True
    created_at_turn: int = 0

    @property
    def latest_time(self) -> int:
        """最新时间点"""
        return max(self.positions.keys()) if self.positions else 0

    @property
    def turn_count(self) -> int:
        """该时间线的走子数"""
        return len(self.positions)

    def get_position(self, time_point: int) -> Position | None:
        return self.positions.get(time_point)

    def add_position(self, position: Position):
        """添加新的棋盘状态到时间线"""
        self.positions[position.time_point] = position


class TimelineManager:
    """时间线管理器"""

    def __init__(self, max_timelines: int = 32):
        self.timelines: dict[int, Timeline] = {}
        self.max_timelines = max_timelines
        self._next_id = 0
        self.active_timeline_id = 0

    def create_initial_timeline(self) -> Timeline:
        """创建初始时间线"""
        tl = Timeline(timeline_id=self._next_id, parent_id=None)
        self._next_id += 1
        self.timelines[tl.timeline_id] = tl
        self.active_timeline_id = tl.timeline_id
        return tl

    def create_branch(self, parent_id: int, branch_turn: int,
                      branch_move_id: int, target_time: int) -> Timeline | None:
        """创建分支时间线（向过去走子触发）"""
        if len(self.timelines) >= self.max_timelines:
            return None  # 超过最大时间线数

        parent = self.timelines.get(parent_id)
        if parent is None:
            return None

        tl = Timeline(
            timeline_id=self._next_id,
            parent_id=parent_id,
            branch_move_id=branch_move_id,
            branch_turn=branch_turn,
            created_at_turn=branch_turn,
        )
        self._next_id += 1
        self.timelines[tl.timeline_id] = tl

        # 复制父时间线目标时间点之前的棋盘状态
        for t in range(target_time + 1):
            if t in parent.positions:
                copied = parent.positions[t].copy()
                copied.timeline_id = tl.timeline_id
                tl.positions[t] = copied

        return tl

    def get_active_timelines(self) -> list[Timeline]:
        """获取所有活跃时间线"""
        return [tl for tl in self.timelines.values() if tl.is_active]

    def get_active_boards(self) -> list[Position]:
        """获取所有活跃时间线的最新棋盘"""
        boards = []
        for tl in self.get_active_timelines():
            latest = tl.latest_time
            if latest in tl.positions:
                boards.append(tl.positions[latest])
        return boards

    def get_timeline(self, timeline_id: int) -> Timeline | None:
        return self.timelines.get(timeline_id)

    def switch_active(self, timeline_id: int):
        """切换活跃时间线"""
        if timeline_id in self.timelines:
            self.active_timeline_id = timeline_id

    def get_all_boards_at_time(self, time_point: int) -> list[Position]:
        """获取所有时间线指定时间点的棋盘"""
        boards = []
        for tl in self.timelines.values():
            if time_point in tl.positions:
                boards.append(tl.positions[time_point])
        return boards

    def build_tree(self) -> dict:
        """构建时间线树结构（用于可视化）"""
        def build_node(tl_id: int) -> dict | None:
            tl = self.timelines.get(tl_id)
            if tl is None:
                return None
            children = [build_node(cid) for cid, ct in self.timelines.items()
                       if ct.parent_id == tl_id]
            return {
                "id": tl.timeline_id,
                "name": f"T{tl.timeline_id}",
                "parent_id": tl.parent_id,
                "branch_turn": tl.branch_turn,
                "is_active": tl.is_active,
                "turn_count": tl.turn_count,
                "children": [c for c in children if c is not None],
            }

        root = build_node(0)
        return root if root else {}

    def to_dict(self) -> dict:
        """序列化"""
        return {
            "next_id": self._next_id,
            "active_timeline_id": self.active_timeline_id,
            "timelines": {
                tid: {
                    "timeline_id": tl.timeline_id,
                    "parent_id": tl.parent_id,
                    "branch_move_id": tl.branch_move_id,
                    "branch_turn": tl.branch_turn,
                    "is_active": tl.is_active,
                    "created_at_turn": tl.created_at_turn,
                    "positions": {
                        tp: pos.to_dict()
                        for tp, pos in tl.positions.items()
                    },
                }
                for tid, tl in self.timelines.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TimelineManager":
        mgr = cls()
        mgr._next_id = data["next_id"]
        mgr.active_timeline_id = data["active_timeline_id"]
        for tid_str, tl_data in data["timelines"].items():
            tid = int(tid_str)
            tl = Timeline(
                timeline_id=tid,
                parent_id=tl_data["parent_id"],
                branch_move_id=tl_data["branch_move_id"],
                branch_turn=tl_data["branch_turn"],
                is_active=tl_data["is_active"],
                created_at_turn=tl_data["created_at_turn"],
            )
            for tp_str, pos_data in tl_data["positions"].items():
                tp = int(tp_str)
                tl.positions[tp] = Position.from_dict(pos_data)
            mgr.timelines[tid] = tl
        return mgr