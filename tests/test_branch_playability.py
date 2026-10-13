"""Past branches remain playable by their side, without rewriting history."""
from copy import deepcopy

from src.data.archive import GameArchive
from src.engine import BoardCoord, FiveDEngine, TimelineRules
from src.modes.replay import ReplayMode
from src.utils.constants import ChessColor, GameState


# Anonymous move coordinates only; no uploaded archive, identity or file path.
# Each row is one submitted Action. T here is the legacy half-move index.
ACTIONS = [
    [(0, 0, 6, 7, 0, 0, 5, 5)],
    [(0, 1, 4, 1, 0, 1, 4, 3)],
    [(0, 2, 5, 5, 0, 0, 5, 3)],
    [(1, 1, 4, 1, 1, 1, 4, 2)],
    [(1, 2, 5, 3, 1, 0, 5, 1)],
    [(0, 3, 5, 0, 0, 3, 2, 3), (1, 3, 5, 0, 1, 3, 2, 3)],
    [(1, 4, 4, 6, 1, 4, 4, 4), (0, 4, 1, 7, 0, 4, 2, 5)],
    [(0, 5, 3, 0, 0, 5, 7, 4), (1, 5, 3, 0, 1, 5, 7, 4)],
    [(1, 6, 6, 7, 1, 6, 5, 5), (0, 6, 2, 5, 0, 4, 2, 3)],
    [(1, 7, 7, 4, 1, 7, 5, 6), (0, 7, 7, 4, 0, 7, 5, 6)],
]


def branch_game(actions=10):
    engine = FiveDEngine()
    for action in ACTIONS[:actions]:
        for source_l, source_t, sx, sy, target_l, target_t, tx, ty in action:
            position = engine.timeline_manager.timelines[source_l].positions[source_t]
            target = BoardCoord.from_legacy_time_point(target_l, target_t)
            moves = engine.get_legal_moves_from_square_to_boards(position, sx, sy, {target})
            move = next(m for m in moves if (m.destination.x, m.destination.y) == (tx, ty))
            assert engine.execute_action_move(move)
        assert engine.submit_action()
    return engine


def test_old_optional_branch_can_be_played_before_submitting_required_boards():
    engine = branch_game(5)
    timelines = engine.timeline_manager.timelines
    assert engine.current_turn_color == ChessColor.BLACK
    assert not timelines[2].is_active
    assert {b.timeline for b in engine.get_required_action_boards()} == {0, 1}
    assert {b.timeline for b in TimelineRules.movable_boards(timelines, ChessColor.BLACK)} == {0, 1, 2}
    assert TimelineRules.movable_boards(timelines, ChessColor.WHITE) == ()
    old_history = deepcopy(timelines[1].positions[0].board)
    assert old_history[1][5] == 'p'
    assert timelines[2].positions[1].board[1][5] == 'N'
    # Black may advance the much older inactive branch; activity is not a gate.
    position = timelines[2].positions[1]
    moves = engine.get_legal_moves_from_square_to_boards(position, 4, 1, {BoardCoord.from_legacy_time_point(2, 1)})
    move = next(m for m in moves if (m.to_x, m.to_y) == (4, 2))
    assert engine.execute_action_move(move)
    assert timelines[2].latest_time == 2
    assert timelines[1].positions[0].board == old_history
    assert {b.timeline for b in engine.get_required_action_boards()} == {0, 1}
    assert not engine.can_submit_action()
    for source_l, source_t, sx, sy, target_l, target_t, tx, ty in ACTIONS[5]:
        position = timelines[source_l].positions[source_t]
        target = BoardCoord.from_legacy_time_point(target_l, target_t)
        moves = engine.get_legal_moves_from_square_to_boards(position, sx, sy, {target})
        assert engine.execute_action_move(next(m for m in moves if (m.to_x, m.to_y) == (tx, ty)))
    assert engine.submit_action()
    assert engine.current_turn_color == ChessColor.WHITE
    assert 2 in {b.timeline for b in TimelineRules.movable_boards(timelines, ChessColor.WHITE)}
    # After Black advances that branch and finishes the global Action, the
    # knight that travelled into the past can move again on its own timeline.
    assert engine.get_legal_moves_from_square_to_boards(
        timelines[2].positions[2], 5, 1, {BoardCoord.from_legacy_time_point(2, 2)},
    )


def test_capturing_past_bishop_only_changes_new_branch_and_terminal_save_replays():
    engine = branch_game(9)
    timelines = engine.timeline_manager.timelines
    assert timelines[3].positions[5].board[3][2] == 'N'
    assert timelines[0].positions[4].board[3][2] == 'b'
    assert timelines[0].positions[7].board[3][2] == 'b'
    assert {b.timeline for b in TimelineRules.movable_boards(timelines, ChessColor.BLACK)} == {0, 1, 2, 3}
    final = branch_game()
    assert final.game_state == GameState.CHECKMATE
    assert final.current_turn_color == ChessColor.WHITE
    replay = ReplayMode()
    replay.load_from_engine(final, strict=True)
    assert replay.snapshots[-1] == GameArchive.capture(final)
