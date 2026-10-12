"""Read-only frontier recurrence detection, deliberately NOT a draw rule.

Absolute time and accumulated history change in 5D chess. We recognize a
returning frontier up to a uniform time translation, while preserving relative
board times, every lane and special-move rights. This is a player advisory;
move legality and game outcomes never depend on it. AIs may use the same
identity as a soft selection preference, never as a transposition/draw rule.
"""
from collections import Counter
from dataclasses import dataclass

from src.engine.timeline_rules import TimelineRules
from src.utils.constants import GameState


@dataclass(frozen=True)
class FrontierRepetition:
    occurrences: int
    action_indices: tuple[int, ...]
    window_actions: int

    def to_dict(self):
        return {
            'kind': 'frontier_repetition',
            'occurrences': self.occurrences,
            'action_indices': list(self.action_indices),
            'window_actions': self.window_actions,
            'is_draw': False,
            'message': (f'检测到往返走棋：最近 {self.window_actions} 个已提交行动中，'
                        f'所有时间线的最新布局及走子权已出现 {self.occurrences} 次相同配置。'
                        '历史棋盘仍不同，这不是自动和棋；可尝试不同走法。'),
        }


def _frontier_key(timelines, frontier, color):
    # `frontier` borrows immutable stored Positions; its mapping is local.
    lanes = {lane: timelines[lane] for lane in frontier}
    activity = TimelineRules.activity_map(lanes)
    present = min(p.time_point for lane, p in frontier.items() if activity[lane])
    return (color, tuple(
        (lane, TimelineRules._owner(lanes[lane]), lanes[lane].parent_id,
         activity[lane], pos.time_point - present, pos.turn,
         tuple(tuple(row) for row in pos.board),
         tuple(sorted(pos.castling_rights.items())), pos.en_passant_target,
         tuple(sorted(pos.unmoved_pawns)))
        for lane, pos in sorted(frontier.items())
    ))


def frontier_key(engine, color=None):
    """Identity of the latest boards; color can project a canonical submission."""
    timelines = engine.timeline_manager.timelines
    frontier = {lane: timeline.positions[timeline.latest_time]
                for lane, timeline in timelines.items()}
    return _frontier_key(timelines, frontier, color or engine.current_turn_color)


def _recent_frontiers(engine, max_actions, should_stop=None):
    """Read submitted boundaries once; discard incomplete or interrupted scans."""
    if (engine.game_state != GameState.PLAYING
            or (engine.current_action and engine.current_action.moves)):
        return ()
    timelines = engine.timeline_manager.timelines
    if not timelines or any(not lane.positions for lane in timelines.values()):
        return ()
    frontier = {lane: timeline.positions[timeline.latest_time] for lane, timeline in timelines.items()}
    count = len(engine.action_history)
    boundaries = [(count, _frontier_key(timelines, frontier, engine.current_turn_color))]
    for index in range(count - 1, max(-1, count - max_actions - 1), -1):
        if should_stop is not None and should_stop():
            return ()
        action = engine.action_history[index]
        if not action.submitted or not action.moves:
            return ()
        # A newly-created lane is genuine frontier change, not a cycle.
        if any(move.is_branching for move in action.moves):
            break
        for move in reversed(action.moves):
            if should_stop is not None and should_stop():
                return ()
            boards = [move.source.board]
            if move.is_cross_timeline:
                boards.append(move.destination.board)
            for board in boards:
                latest = frontier.get(board.timeline)
                timeline = timelines.get(board.timeline)
                previous = timeline.positions.get(board.legacy_time_point) if timeline else None
                if (latest is None or previous is None
                        or latest.time_point != board.next().legacy_time_point
                        or latest.turn != board.next().side):
                    return ()
                frontier[board.timeline] = previous
        boundaries.append((index, _frontier_key(timelines, frontier, action.color)))
    return tuple(boundaries)


def repeated_frontier_counts(engine, *, max_actions=64, should_stop=None):
    """Only frontiers seen at least twice can trigger an AI repetition cost.

    The optional cooperative stop shares the caller's existing planning budget.
    This borrows immutable Positions and never clones/replays an engine.
    """
    if max_actions < 1:
        raise ValueError('repetition window must be positive')
    if len(engine.action_history) < 2:
        return {}
    counts = Counter(key for _, key in _recent_frontiers(engine, max_actions, should_stop))
    return {key: count for key, count in counts.items() if count >= 2}


def detect_frontier_repetition(engine, *, max_actions=64, threshold=3):
    """Compare submitted boundaries by reversing recorded frontier transitions.

    Uses existing Action/history storage, so archive restore and simulation
    clones need no new mutable counters or schema. Partial Actions, terminal
    games and incomplete/inconsistent history do not produce a warning.
    Work is bounded by the last `max_actions` submitted Actions. A new branch
    ends the comparable segment because the lane set can never shrink in play.
    """
    if max_actions < 1 or threshold < 2:
        raise ValueError('repetition window must be positive and threshold >= 2')
    if len(engine.action_history) < threshold - 1:
        return None
    boundaries = _recent_frontiers(engine, max_actions)
    if not boundaries:
        return None
    target = boundaries[0][1]
    indices = [index for index, key in boundaries if key == target]
    if len(indices) < threshold:
        return None
    return FrontierRepetition(len(indices), tuple(reversed(indices)), len(boundaries) - 1)
