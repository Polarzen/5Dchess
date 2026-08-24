"""
5D Chess - 时间线模块测试
"""
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.engine import TimelineManager, Timeline, Position
from src.utils.constants import ChessColor


def add_initial_position(timeline: Timeline, time_point: int = 0):
    pos = Position.initial(timeline_id=timeline.timeline_id, time_point=time_point)
    pos.turn = ChessColor.WHITE if time_point % 2 == 0 else ChessColor.BLACK
    timeline.add_position(pos)
    return pos


class TestTimeline:
    def test_basic(self):
        tl = Timeline(timeline_id=1, parent_id=0, owner=ChessColor.WHITE)
        assert tl.timeline_id == 1
        assert tl.parent_id == 0
        assert tl.owner == ChessColor.WHITE
        assert tl.is_active
        assert tl.latest_time == 0

    def test_positions(self):
        tl = Timeline(timeline_id=0)
        add_initial_position(tl, 0)
        assert tl.latest_time == 0
        assert tl.get_position(0) is not None

        add_initial_position(tl, 1)
        assert tl.latest_time == 1
        assert tl.turn_count == 2

    def test_rejects_position_from_another_timeline(self):
        tl = Timeline(timeline_id=0)
        pos = Position.initial(timeline_id=2, time_point=0)
        with pytest.raises(ValueError, match="cannot add timeline 2"):
            tl.add_position(pos)


class TestTimelineManager:
    def test_init(self):
        mgr = TimelineManager()
        assert len(mgr.timelines) == 0

    def test_create_initial(self):
        mgr = TimelineManager()
        tl = mgr.create_initial_timeline()
        assert tl.timeline_id == 0
        assert tl.owner is None
        assert mgr.active_timeline_id == 0

    def test_white_and_black_branches_use_opposite_lanes(self):
        mgr = TimelineManager()
        parent = mgr.create_initial_timeline()
        add_initial_position(parent)

        white_1 = mgr.create_branch(0, 1, 1, 0, creator=ChessColor.WHITE)
        black_1 = mgr.create_branch(0, 1, 2, 0, creator=ChessColor.BLACK)
        white_2 = mgr.create_branch(0, 2, 3, 0, creator=ChessColor.WHITE)
        black_2 = mgr.create_branch(0, 2, 4, 0, creator=ChessColor.BLACK)

        assert [white_1.timeline_id, white_2.timeline_id] == [1, 2]
        assert [black_1.timeline_id, black_2.timeline_id] == [-1, -2]
        assert white_1.owner == ChessColor.WHITE
        assert black_1.owner == ChessColor.BLACK

    def test_branch_creation_copies_only_history_through_target(self):
        mgr = TimelineManager()
        parent = mgr.create_initial_timeline()
        for time_point in range(4):
            add_initial_position(parent, time_point)

        branch = mgr.create_branch(
            parent_id=0,
            branch_turn=3,
            branch_move_id=5,
            target_time=1,
            creator=ChessColor.BLACK,
        )
        assert branch is not None
        assert branch.timeline_id == -1
        assert branch.parent_id == 0
        assert branch.branch_turn == 3
        assert sorted(branch.positions) == [0, 1]
        assert all(pos.timeline_id == -1 for pos in branch.positions.values())

    def test_branch_requires_existing_target_board(self):
        mgr = TimelineManager()
        mgr.create_initial_timeline()
        assert mgr.create_branch(0, 1, 1, 0) is None

    def test_active_timelines(self):
        mgr = TimelineManager()
        parent = mgr.create_initial_timeline()
        add_initial_position(parent)
        mgr.create_branch(0, 1, 1, 0, creator=ChessColor.WHITE)
        active = mgr.get_active_timelines()
        assert len(active) == 2

    def test_tree_building_uses_signed_lane_names(self):
        mgr = TimelineManager()
        parent = mgr.create_initial_timeline()
        add_initial_position(parent)
        mgr.create_branch(0, 1, 1, 0, creator=ChessColor.BLACK)
        tree = mgr.build_tree()
        assert tree["id"] == 0
        assert tree["name"] == "L0"
        assert len(tree["children"]) == 1
        assert tree["children"][0]["id"] == -1
        assert tree["children"][0]["name"] == "L-1"
        assert tree["children"][0]["owner"] == "black"

    def test_serialization_preserves_signed_allocators_and_owner(self):
        mgr = TimelineManager()
        parent = mgr.create_initial_timeline()
        add_initial_position(parent)
        mgr.create_branch(0, 1, 1, 0, creator=ChessColor.WHITE)
        mgr.create_branch(0, 1, 2, 0, creator=ChessColor.BLACK)

        restored = TimelineManager.from_dict(mgr.to_dict())
        assert set(restored.timelines) == {-1, 0, 1}
        assert restored.get_timeline(1).owner == ChessColor.WHITE
        assert restored.get_timeline(-1).owner == ChessColor.BLACK

        next_white = restored.create_branch(0, 2, 3, 0, creator=ChessColor.WHITE)
        next_black = restored.create_branch(0, 2, 4, 0, creator=ChessColor.BLACK)
        assert next_white.timeline_id == 2
        assert next_black.timeline_id == -2

    def test_legacy_serialization_without_signed_allocators_still_loads(self):
        mgr = TimelineManager()
        parent = mgr.create_initial_timeline()
        add_initial_position(parent)
        data = mgr.to_dict()
        data.pop("next_positive_id")
        data.pop("next_negative_id")

        restored = TimelineManager.from_dict(data)
        branch = restored.create_branch(0, 1, 1, 0, creator=ChessColor.BLACK)
        assert branch.timeline_id == -1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
