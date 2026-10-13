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
    assert response.json['version'] == 2
    lessons = {row['id']: row for row in response.json['lessons']}
    assert list(lessons) == ['welcome', 'read-boards', 'first-turn', 'pieces', 'many-moves',
                             'cross-board', 'history', 'bishop', 'knight', 'pawn', 'present',
                             'king-safety', 'challenge']
    for lesson in lessons.values():
        assert lesson['quiz']['explanation']
        assert 0 <= lesson['quiz']['correct'] < len(lesson['quiz']['answers'])
        for plan in lesson.get('plans', []):
            for i, step in enumerate(plan['steps']):
                assert step['before']['turn'] == step['after_move']['turn'] == 'white'
                assert not step['before']['can_submit']
                assert step['after_move']['can_submit'] == (i == len(plan['steps']) - 1)
                if i:
                    assert step['before'] == plan['steps'][i-1]['after_move']
            assert plan['steps'][-1]['after_move']['required_count'] == 0
            assert plan['after_submit']['turn'] == 'black'
            assert not plan['after_submit']['can_submit']
    assert lessons['cross-board']['plans'][0]['steps'][0]['before']['required_count'] == 2
    branch = lessons['history']['plans'][0]['steps'][0]
    assert branch['move']['created_timeline'] == 1
    assert branch['move']['result_destination_board']['key'] == '1:1'
    old = next(b for b in branch['before']['boards'] if b['key'] == '0:0')
    preserved = next(b for b in branch['after_move']['boards'] if b['key'] == '0:0')
    assert old['board'] == preserved['board']
    assert _game_session['mode_instance'] is instance
    assert instance.engine.to_dict() == before


def test_curriculum_teaches_multiple_moves_piece_geometry_and_submission_blockers(client):
    lessons = {row['id']: row for row in client.get('/api/tutorial').json['lessons']}
    multi = lessons['many-moves']['plans'][0]
    assert [multi['steps'][0]['before']['required_count']] + [step['after_move']['required_count'] for step in multi['steps']] == [2, 1, 0]
    bishop = lessons['bishop']['plans'][0]['steps'][0]['move']
    knight = lessons['knight']['plans'][0]['steps'][0]['move']
    assert bishop['to_timeline'] - bishop['from_timeline'] == 1
    assert bishop['to'][0] - bishop['from'][0] == 1
    assert knight['to_timeline'] - knight['from_timeline'] == 1
    assert knight['to'][0] - knight['from'][0] == 2
    assert lessons['pawn']['plans'][0]['steps'][0]['move']['captured'] == 'P'
    present = lessons['present']['snapshot']
    assert [b['coord']['timeline'] for b in present['boards'] if b['is_required']] == [1]
    assert not next(b for b in present['boards'] if b['coord']['timeline'] == 2)['timeline_active']
    unsafe = lessons['king-safety']['snapshot']
    assert unsafe['required_count'] == 0 and not unsafe['can_submit']
    # Independent check of the diagram's attack, rather than just a false button.
    from src.engine.royal_rules import RoyalRules
    from src.web.tutorial import _engine, _position
    from src.utils.constants import ChessColor
    assert RoyalRules(_engine(_position(0, 1, {(7, 7): 'r'})).timeline_manager.timelines).is_in_check(ChessColor.WHITE)


def test_quick_guide_examples_match_engine_practice_and_do_not_touch_game(client):
    import re

    engine = _game_session['mode_instance'].engine
    before = deepcopy(engine.to_dict())
    html = client.get('/').get_data(as_text=True)
    lessons = {row['id']: row for row in client.get('/api/tutorial').json['lessons']}
    assert html.count('onclick="openCrossBoardGuide()"') == 2
    assert 'id="cross-board-guide"' in html
    assert '过去的自己也会占格' in html
    assert '没有红框不代表一定能提交' in html
    assert 'T0 · 白方' in html and 'T0 · 黑方' in html and 'T1 · 白方' in html
    for example, lesson, x in [('rook', 'cross-board', 3), ('bishop', 'bishop', 4), ('knight', 'knight', 5)]:
        panel = html.split(f'id="guide-example-{example}"', 1)[1].split('亲手试这一步', 1)[0]
        assert f"practiceCrossBoardGuide('{lesson}')" in panel
        markers = re.findall(r'--file: (\d); --row: (\d)', panel)
        assert markers == [('3', '4'), (str(x), '4')]
        move = lessons[lesson]['plans'][0]['steps'][0]['move']
        assert move['from'] == [3, 4] and move['to'] == [x, 4]
        assert move['from_timeline'] == 0 and move['to_timeline'] == 1
        assert move['created_timeline'] is None
    assert "practiceCrossBoardGuide('history')" in html
    assert lessons['history']['plans'][0]['steps'][0]['move']['created_timeline'] == 1
    # The short guide is inline HTML/CSS and needs no additional asset request.
    assert len(set(re.findall(r'(?:src|href)=[\"\'](/static/[^\"\']+)', html))) == 7
    assert engine.to_dict() == before


def test_final_practice_supports_both_board_orders_and_pawn_distances(client):
    lesson = client.get('/api/tutorial').json['lessons'][-1]
    assert lesson['independent']
    choices = set()
    for plan in lesson['plans']:
        steps = plan['steps']
        choices.add(tuple((step['move']['from_timeline'], step['move']['to'][1]) for step in steps))
        assert len(steps) == 2
        assert steps[0]['after_move']['required_count'] == 1
        assert not steps[0]['after_move']['can_submit']
        assert plan['after_submit']['turn'] == 'black'
    assert len(choices) == 8
    assert {choice[0][0] for choice in choices} == {0, 1}
    assert {move[1] for choice in choices for move in choice} == {4, 5}


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
