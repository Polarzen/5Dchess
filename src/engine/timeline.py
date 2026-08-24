"""
5D Chess - 时间线管理
"""
from __future__ import annotations
from dataclasses import dataclass, field

from src.engine.board import Position
from src.utils.constants import ChessColor


@dataclass
class Timeline:
    """时间线 — 一条独立的时间分支。

    ``timeline_id`` is also the canonical L-axis coordinate:
    main timeline = 0, white-created timelines = positive, black-created
    timelines = negative.
    """

    timeline_id: int
    parent_id: int | None = None
    branch_move_id: int | None = None
    branch_turn: int | None = None
    positions: dict[int, Position] = field(default_factory=dict)
    is_active: bool = True
    created_at_turn: int = 0
    owner: ChessColor | None = None

    @property
    def latest_time(self) -> int:
        """最新 legacy half-move 时间点。"""
        return max(self.positions.keys()) if self.positions else 0

    @property
    def turn_count(self) -> int:
        return len(self.positions)

    def get_position(self, time_point: int) -> Position | None:
        return self.positions.get(time_point)

    def add_position(self, position: Position):
        if position.timeline_id != self.timeline_id:
            raise ValueError(
                f"cannot add timeline {position.timeline_id} position to "
                f"timeline {self.timeline_id}"
            )
        self.positions[position.time_point] = position


class TimelineManager:
    """时间线管理器，使用有符号整数作为 canonical L 轴。"""

    def __init__(self, max_timelines: int = 32):
        self.timelines: dict[int, Timeline] = {}
        self.max_timelines = max_timelines
        self._next_positive_id = 1
        self._next_negative_id = -1
        self.active_timeline_id = 0

    def create_initial_timeline(self) -> Timeline:
        """创建主时间线 L0。"""
        if 0 in self.timelines:
            return self.timelines[0]
        tl = Timeline(timeline_id=0, parent_id=None, owner=None)
        self.timelines[0] = tl
        self.active_timeline_id = 0
        return tl

    def _allocate_timeline_id(self, creator: ChessColor) -> int:
        if creator == ChessColor.WHITE:
            timeline_id = self._next_positive_id
            while timeline_id in self.timelines:
                timeline_id += 1
            self._next_positive_id = timeline_id + 1
            return timeline_id

        timeline_id = self._next_negative_id
        while timeline_id in self.timelines:
            timeline_id -= 1
        self._next_negative_id = timeline_id - 1
        return timeline_id

    def create_branch(
        self,
        parent_id: int,
        branch_turn: int,
        branch_move_id: int,
        target_time: int,
        creator: ChessColor = ChessColor.WHITE,
    ) -> Timeline | None:
        """从历史棋盘创建分支时间线。

        White branches occupy +L lanes and Black branches occupy -L lanes.
        ``creator`` defaults to WHITE only for compatibility with older direct
        callers; engine execution always supplies the moving piece's color.
        """
        if len(self.timelines) >= self.max_timelines:
            return None

        parent = self.timelines.get(parent_id)
        if parent is None or target_time not in parent.positions:
            return None

        timeline_id = self._allocate_timeline_id(creator)
        tl = Timeline(
            timeline_id=timeline_id,
            parent_id=parent_id,
            branch_move_id=branch_move_id,
            branch_turn=branch_turn,
            created_at_turn=branch_turn,
            owner=creator,
        )
        self.timelines[timeline_id] = tl

        # Preserve immutable history by copying parent boards through the target.
        for time_point in sorted(parent.positions):
            if time_point > target_time:
                break
            copied = parent.positions[time_point].copy()
            copied.timeline_id = timeline_id
            tl.positions[time_point] = copied

        return tl

    def get_active_timelines(self) -> list[Timeline]:
        return [tl for tl in self.timelines.values() if tl.is_active]

    def get_active_boards(self) -> list[Position]:
        boards = []
        for tl in self.get_active_timelines():
            latest = tl.latest_time
            if latest in tl.positions:
                boards.append(tl.positions[latest])
        return boards

    def get_timeline(self, timeline_id: int) -> Timeline | None:
        return self.timelines.get(timeline_id)

    def switch_active(self, timeline_id: int):
        if timeline_id in self.timelines:
            self.active_timeline_id = timeline_id

    def get_all_boards_at_time(self, time_point: int) -> list[Position]:
        boards = []
        for tl in self.timelines.values():
            if time_point in tl.positions:
                boards.append(tl.positions[time_point])
        return boards

    def build_tree(self) -> dict:
        """构建时间线树（timeline_id 同时是可显示的 L 坐标）。"""
        def build_node(tl_id: int) -> dict | None:
            tl = self.timelines.get(tl_id)
            if tl is None:
                return None
            children = [
                build_node(child_id)
                for child_id, child in self.timelines.items()
                if child.parent_id == tl_id
            ]
            lane_name = "L0" if tl.timeline_id == 0 else f"L{tl.timeline_id:+d}"
            return {
                "id": tl.timeline_id,
                "name": lane_name,
                "parent_id": tl.parent_id,
                "branch_turn": tl.branch_turn,
                "is_active": tl.is_active,
                "owner": tl.owner.value if tl.owner else None,
                "turn_count": tl.turn_count,
                "children": [c for c in children if c is not None],
            }

        root = build_node(0)
        return root if root else {}

    def to_dict(self) -> dict:
        return {
            "max_timelines": self.max_timelines,
            # Keep next_id as a compatibility hint for old readers.
            "next_id": self._next_positive_id,
            "next_positive_id": self._next_positive_id,
            "next_negative_id": self._next_negative_id,
            "active_timeline_id": self.active_timeline_id,
            "timelines": {
                tid: {
                    "timeline_id": tl.timeline_id,
                    "parent_id": tl.parent_id,
                    "branch_move_id": tl.branch_move_id,
                    "branch_turn": tl.branch_turn,
                    "is_active": tl.is_active,
                    "created_at_turn": tl.created_at_turn,
                    "owner": tl.owner.value if tl.owner else None,
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
        mgr = cls(max_timelines=data.get("max_timelines", 32))
        mgr.active_timeline_id = data.get("active_timeline_id", 0)

        for tid_str, tl_data in data.get("timelines", {}).items():
            tid = int(tid_str)
            owner_value = tl_data.get("owner")
            owner = ChessColor(owner_value) if owner_value else None
            tl = Timeline(
                timeline_id=tid,
                parent_id=tl_data.get("parent_id"),
                branch_move_id=tl_data.get("branch_move_id"),
                branch_turn=tl_data.get("branch_turn"),
                is_active=tl_data.get("is_active", True),
                created_at_turn=tl_data.get("created_at_turn", 0),
                owner=owner,
            )
            for tp_str, pos_data in tl_data.get("positions", {}).items():
                tp = int(tp_str)
                position = Position.from_dict(pos_data)
                # Old save files may carry the same id already; normalize to the
                # dictionary lane so resolver validation remains deterministic.
                position.timeline_id = tid
                tl.positions[tp] = position
            mgr.timelines[tid] = tl

        if "next_positive_id" in data:
            mgr._next_positive_id = int(data["next_positive_id"])
        else:
            positives = [tid for tid in mgr.timelines if tid > 0]
            legacy_hint = int(data.get("next_id", 1))
            mgr._next_positive_id = max([legacy_hint, *(tid + 1 for tid in positives)], default=1)

        if "next_negative_id" in data:
            mgr._next_negative_id = int(data["next_negative_id"])
        else:
            negatives = [tid for tid in mgr.timelines if tid < 0]
            mgr._next_negative_id = min([*(tid - 1 for tid in negatives), -1])

        return mgr
