"""Isolated, canonical practice positions; never modify the live game session."""
from src.engine import ActionRules, BoardCoord, FiveDEngine, Position, Timeline
from src.utils.constants import ChessColor


def _position(lane, time, rook=None):
    board = [["" for _ in range(8)] for _ in range(8)]
    board[7][0], board[0][7] = 'K', 'k'
    if rook is not None:
        board[rook[1]][rook[0]] = 'R'
    return Position(board=board, timeline_id=lane, time_point=time,
                    turn=BoardCoord.legacy_side_for_time_point(time), unmoved_pawns=set())


def _engine(positions):
    engine = FiveDEngine()
    engine.timeline_manager.timelines = {}
    for pos in positions:
        engine.timeline_manager.timelines.setdefault(pos.timeline_id, Timeline(pos.timeline_id)).add_position(pos)
    engine.current_action = ActionRules.begin(ChessColor.WHITE, engine.timeline_manager.timelines)
    return engine


def build_lessons(serialize, move_payload):
    """All displayed transitions are generated, executed and submitted by the engine."""
    ordinary = FiveDEngine()
    crossing = _engine([_position(0, 0, (3, 4)), _position(1, 0)])
    branching = _engine([_position(0, 0), _position(0, 1), _position(0, 2, (3, 4))])
    specs = [
        ('first-turn', ordinary, (0, 0, 4, 6), (0, 0, 4, 4)),
        ('cross-board', crossing, (0, 0, 3, 4), (1, 0, 3, 4)),
        ('history', branching, (0, 2, 3, 4), (0, 0, 3, 4)),
    ]
    lessons = []
    for key, engine, source, destination in specs:
        pos = engine.timeline_manager.timelines[source[0]].positions[source[1]]
        moves = engine.get_legal_moves_from_square(pos, source[2], source[3])
        move = next(m for m in moves if (m.destination.timeline, m.destination.board.legacy_time_point,
                                        m.to_x, m.to_y) == destination)
        before = serialize(engine)
        if not engine.execute_action_move(move):
            raise RuntimeError(f'Tutorial move rejected: {key}')
        recorded = engine.move_history[-1]
        after_move = serialize(engine)
        if not engine.submit_action():
            raise RuntimeError(f'Tutorial submission rejected: {key}')
        lessons.append(dict(id=key, move=move_payload(recorded), before=before,
                            after_move=after_move, after_submit=serialize(engine)))
    return lessons
