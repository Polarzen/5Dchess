"""Tutorial isolation and actual Web branching/submission contracts."""
from copy import deepcopy

import pytest

from src.modes import PvPMode
from src.web.app import _game_session, app
from tests.test_travelling_kings import engine_with, position


@pytest.fixture()
def client():
    saved = _game_session.copy()
    _game_session.update(mode='pvp', mode_instance=PvPMode(), player_color=None)
    with app.test_client() as client:
        yield client
    _game_session.clear()
    _game_session.update(saved)


def test_tutorial_uses_canonical_transitions_and_never_mutates_live_game(client):
    instance = _game_session['mode_instance']
    before = deepcopy(instance.engine.to_dict())
    response = client.get('/api/tutorial')
    assert response.status_code == 200
    lessons = response.json['lessons']
    assert [row['id'] for row in lessons] == ['first-turn', 'cross-board', 'history']
    for lesson in lessons:
        assert lesson['before']['turn'] == lesson['after_move']['turn'] == 'white'
        assert not lesson['before']['can_submit']
        assert lesson['after_move']['can_submit']
        assert lesson['after_move']['required_count'] == 0
        assert lesson['after_submit']['turn'] == 'black'
        assert not lesson['after_submit']['can_submit']
    assert lessons[1]['before']['required_count'] == 2
    branch = lessons[2]
    assert branch['move']['created_timeline'] == 1
    assert branch['move']['result_destination_board']['key'] == '1:1'
    old = next(b for b in branch['before']['boards'] if b['key'] == '0:0')
    preserved = next(b for b in branch['after_move']['boards'] if b['key'] == '0:0')
    assert old['board'] == preserved['board']
    assert _game_session['mode_instance'] is instance
    assert instance.engine.to_dict() == before


def test_branch_response_points_to_arrival_and_requires_explicit_submit(client):
    pieces = {(0, 7): 'K', (7, 0): 'k'}
    engine = engine_with(position(0, 0, pieces), position(0, 1, pieces),
                         position(0, 2, {**pieces, (3, 4): 'R'}))
    _game_session['mode_instance'].engine = engine
    state = client.get('/api/game/state').json
    assert state['action']['submit_blocker'] == 'required_boards'
    source = next(b['coord'] for b in state['boards'] if b['key'] == '0:2')
    moves = client.post('/api/game/legal_moves_5d', json={'board': source, 'x': 3, 'y': 4}).json['moves']
    move = next(m for m in moves if m['destination']['board']['key'] == '0:0')
    result = client.post('/api/game/move_5d', json=move)
    assert result.status_code == 200
    state = result.json
    assert state['move']['created_timeline'] == 1
    assert state['move'] == state['last_move']
    assert state['move']['result_source_board']['key'] == '0:3'
    assert state['move']['result_destination_board']['key'] == '1:1'
    assert state['move']['display_notation'] == 'L0 · T1 白方：d4 → L0 · T0 白方 d4（新分支 L+1）'
    assert state['turn'] == 'white'
    assert state['action']['can_submit'] and state['action']['submit_blocker'] is None
    assert next(b for b in state['boards'] if b['key'] == '1:1')['board'][4][3] == 'R'
    assert next(b for b in state['boards'] if b['key'] == '0:0')['board'][4][3] == ''
    result = client.post('/api/game/submit_action', json={})
    assert result.status_code == 200
    assert result.json['turn'] == 'black'


def test_action_counter_changes_only_on_submission_and_display_matches_tutorial(client):
    pieces = {(0, 7): 'K', (7, 0): 'k', (4, 6): 'P'}
    engine = engine_with(position(0, 0, pieces), position(1, 0, pieces))
    for timeline in engine.timeline_manager.timelines.values():
        timeline.positions[0].unmoved_pawns.add((4, 6))
    _game_session['mode_instance'].engine = engine
    initial = client.get('/api/game/state').json
    assert initial['action_counter'] == initial['move_counter'] == 0
    for lane in (0, 1):
        state = client.get('/api/game/state').json
        source = next(b['coord'] for b in state['boards'] if b['key'] == f'{lane}:0')
        moves = client.post('/api/game/legal_moves_5d', json={'board': source, 'x': 4, 'y': 6}).json['moves']
        move = next(m for m in moves if m['destination']['board']['key'] == f'{lane}:0'
                    and m['to'] == [4, 4])
        response = client.post('/api/game/move_5d', json=move)
        assert response.status_code == 200
        state = response.json
        assert state['action_counter'] == 0
        assert state['move_counter'] == state['action']['move_count'] == lane + 1
        label = 'L0' if lane == 0 else 'L+1'
        assert state['move']['display_notation'] == f'{label} · T0 白方：e2 → e4'
        assert state['move_history_display'][-1] == state['move']['display_notation']
        # The new presentation must not rewrite the legacy storage/API notation.
        assert state['move']['notation'] == state['move_history'][-1] == engine.move_history[-1].to_notation()
        assert state['move']['notation'].endswith('e7-e5')
    submitted = client.post('/api/game/submit_action', json={})
    assert submitted.status_code == 200
    assert submitted.json['action_counter'] == 1
    assert submitted.json['move_counter'] == 2
    assert submitted.json['action']['move_count'] == 0


def test_submit_blocker_explains_second_king_in_check(client):
    pos = position(0, 0, {(0, 0): 'K', (4, 6): 'K', (4, 2): 'r', (7, 7): 'k'})
    engine = engine_with(pos)
    engine.timeline_manager.timelines[0].add_position(engine._build_successor(pos))
    _game_session['mode_instance'].engine = engine
    state = client.get('/api/game/state').json
    assert state['action']['required_boards'] == []
    assert not state['action']['can_submit']
    assert state['action']['submit_blocker'] == 'royal_safety'
    assert client.post('/api/game/submit_action', json={}).status_code == 400
