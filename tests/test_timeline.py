"""
5D Chess - 时间线模块测试
"""
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.engine import TimelineManager, Timeline, Position
from src.utils.constants import ChessColor


class TestTimeline:
    def test_basic(self):
        tl = Timeline(timeline_id=1, parent_id=0)
        assert tl.timeline_id == 1
        assert tl.parent_id == 0
        assert tl.is_active
        assert tl.latest_time == 0

    def test_positions(self):
        tl = Timeline(timeline_id=0)
        pos = Position.initial(timeline_id=0, time_point=0)
        tl.add_position(pos)
        assert tl.latest_time == 0
        assert tl.get_position(0) is not None

        pos2 = Position.initial(timeline_id=0, time_point=1)
        pos2.turn = ChessColor.BLACK
        tl.add_position(pos2)
        assert tl.latest_time == 1
        assert tl.turn_count == 2


class TestTimelineManager:
    def test_init(self):
        mgr = TimelineManager()
        assert len(mgr.timelines) == 0

    def test_create_initial(self):
        mgr = TimelineManager()
        tl = mgr.create_initial_timeline()
        assert tl.timeline_id == 0
        assert mgr.active_timeline_id == 0

    def test_branch_creation(self):
        mgr = TimelineManager()
        parent = mgr.create_initial_timeline()
        parent.add_position(Position.initial(timeline_id=0, time_point=0))
        parent.add_position(Position.initial(timeline_id=0, time_point=1))

        branch = mgr.create_branch(
            parent_id=0, branch_turn=1, branch_move_id=5, target_time=0
        )
        assert branch is not None
        assert branch.parent_id == 0
        assert branch.branch_turn == 1
        # 分支应复制目标时间点的棋盘
        assert 0 in branch.positions

    def test_active_timelines(self):
        mgr = TimelineManager()
        mgr.create_initial_timeline()
        mgr.create_branch(0, 1, 1, 0)
        active = mgr.get_active_timelines()
        assert len(active) == 2

    def test_tree_building(self):
        mgr = TimelineManager()
        mgr.create_initial_timeline()
        mgr.create_branch(0, 1, 1, 0)
        tree = mgr.build_tree()
        assert tree["id"] == 0
        assert len(tree["children"]) == 1
        assert tree["children"][0]["id"] == 1

    def test_serialization(self):
        mgr = TimelineManager()
        tl = mgr.create_initial_timeline()
        tl.add_position(Position.initial(timeline_id=0, time_point=0))
        data = mgr.to_dict()
        restored = TimelineManager.from_dict(data)
        assert len(restored.timelines) == 1
        assert restored.get_timeline(0).turn_count == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])