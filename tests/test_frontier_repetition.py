"""Returning frontiers are advisory, with no effect on canonical rules."""
from copy import deepcopy

import pytest

from src.ai.action_planner import engine_state_signature
from src.data.archive import GameArchive
from src.engine import ActionRules, FiveDEngine, Position, Timeline
from src.engine.repetition import _frontier_key, detect_frontier_repetition
from src.utils.constants import ChessColor, GameState


def play_cycle(engine, count=1):
    for _ in range(count):
        for source, target in [((6, 7), (5, 5)), ((6, 0), (5, 2)),
                               ((5, 5), (6, 7)), ((5, 2), (6, 0))]:
            for lane in sorted(engine.timeline_manager.timelines):
                timeline = engine.timeline_manager.timelines[lane]
                pos = timeline.positions[timeline.latest_time]
                move = next(m for m in engine.get_legal_moves_from_square(pos, *source)
                            if m.is_spatial and (m.to_x, m.to_y) == target)
                assert engine.execute_action_move(move)
            assert engine.submit_action(evaluate_outcome=False)


@pytest.mark.parametrize('lanes', [1, 2])
def test_three_frontier_occurrences_warn_without_declaring_draw(lanes):
    engine = FiveDEngine()
    if lanes == 2:
        engine.timeline_manager.timelines[1] = Timeline(1, positions={0: Position.initial(1)})
        engine.current_action = ActionRules.begin(ChessColor.WHITE, engine.timeline_manager.timelines)
    play_cycle(engine)
    assert detect_frontier_repetition(engine) is None
    play_cycle(engine)
    before = engine_state_signature(engine)
    repetition = detect_frontier_repetition(engine)
    assert repetition.action_indices == (0, 4, 8)
    assert repetition.occurrences == 3 and repetition.window_actions == 8
    assert repetition.to_dict()['is_draw'] is False
    assert engine.game_state == GameState.PLAYING
    assert engine_state_signature(engine) == before
    assert detect_frontier_repetition(engine, max_actions=4) is None
    assert detect_frontier_repetition(engine.clone_for_simulation()) == repetition
    assert detect_frontier_repetition(GameArchive.restore(GameArchive.capture(engine))) == repetition


def test_partial_action_progress_and_terminal_state_clear_warning():
    engine = FiveDEngine()
    play_cycle(engine, 2)
    move = next(m for m in engine.get_legal_moves() if m.is_spatial and (m.from_x, m.from_y, m.to_y) == (4, 6, 4))
    assert engine.execute_action_move(move)
    assert detect_frontier_repetition(engine) is None
    assert engine.submit_action(evaluate_outcome=False)
    assert detect_frontier_repetition(engine) is None
    play_cycle_engine = FiveDEngine()
    play_cycle(play_cycle_engine, 2)
    play_cycle_engine.game_state = GameState.CHECKMATE
    assert detect_frontier_repetition(play_cycle_engine) is None


@pytest.mark.parametrize('change', ['turn', 'rights', 'en_passant', 'unmoved', 'offset', 'piece', 'lane'])
def test_frontier_identity_preserves_rule_relevant_differences(change):
    timelines = {0: Timeline(0), 1: Timeline(1)}
    frontier = {lane: Position.initial(lane) for lane in timelines}
    original = _frontier_key(timelines, frontier, ChessColor.WHITE)
    modified = deepcopy(frontier)
    color = ChessColor.WHITE
    if change == 'turn': color = ChessColor.BLACK
    elif change == 'rights': modified[0].castling_rights['white_kingside'] = False
    elif change == 'en_passant': modified[0].en_passant_target = (3, 2)
    elif change == 'unmoved': modified[0].unmoved_pawns.remove((0, 6))
    elif change == 'offset': modified[1].time_point += 2
    elif change == 'piece': modified[1].board[0][0] = ''
    elif change == 'lane': del modified[1]
    assert _frontier_key(timelines, modified, color) != original
    translated = deepcopy(frontier)
    for position in translated.values(): position.time_point += 8
    assert _frontier_key(timelines, translated, ChessColor.WHITE) == original


def test_inconsistent_history_never_fabricates_recurrence():
    engine = FiveDEngine()
    play_cycle(engine, 2)
    engine.timeline_manager.timelines[0].positions.pop(3)
    assert detect_frontier_repetition(engine) is None
