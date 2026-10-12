"""Exercise a fresh P2P host through its real HTTP(S) address, then close the room."""
from __future__ import annotations

import argparse
import json
import threading
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def check(origin: str) -> None:
    parsed = urlsplit(origin)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("Use an HTTP(S) site address without credentials")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("Use the site address, without a room code, path or query")
    origin = origin.rstrip("/")

    def post(path: str, body: dict, expected: int = 200) -> dict:
        request = Request(origin + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
        try:
            response = urlopen(request, timeout=15)
        except HTTPError as error:
            response = error
        with response:
            status = response.status
            payload = json.load(response)
        if status != expected:
            # Never include bearer tokens or raw request/response bodies in logs.
            raise RuntimeError(f"{path}: HTTP {status}, expected {expected}")
        return payload

    credentials: list[dict] = []
    lock = threading.Lock()
    done = threading.Event()
    heartbeat_errors: list[str] = []

    def heartbeat() -> None:
        while not done.wait(1.2):
            with lock:
                players = list(credentials)
            for auth in players:
                try:
                    post('/api/p2p/state', auth)
                except Exception as error:
                    heartbeat_errors.append(type(error).__name__)

    worker = threading.Thread(target=heartbeat, daemon=True)
    worker.start()
    try:
        with urlopen(origin, timeout=15) as response:
            if response.status != 200 or '创建在线房间' not in response.read().decode('utf-8'):
                raise RuntimeError('Game homepage unavailable')
        created = post('/api/p2p/create', {})
        host = {key: created[key] for key in ('room_code', 'player_token')}
        with lock:
            credentials.append(host)
        assert created['player_color'] == 'white'
        joined = post('/api/p2p/join', {'room_code': host['room_code']})
        guest = {key: joined[key] for key in ('room_code', 'player_token')}
        with lock:
            credentials.append(guest)
        assert joined['player_color'] == 'black'
        assert len(host['room_code']) == 6 and host['player_token'] != guest['player_token']
        assert post('/api/p2p/join', {'room_code': host['room_code']}, 409)['code'] == 'room_full'
        assert post('/api/p2p/state', {**host, 'player_token': 'invalid'}, 401)['code'] == 'invalid_token'
        assert post('/api/p2p/legal_moves', {**guest, 'board': joined['boards'][0]['coord'], 'x': 4, 'y': 1}, 409)['code'] == 'not_your_turn'

        for auth, from_y, to_y, next_color in ((host, 6, 4, 'black'), (guest, 1, 3, 'white')):
            state = post('/api/p2p/state', auth)
            board = next(board for board in state['boards'] if board['is_movable'])
            moves = post('/api/p2p/legal_moves', {**auth, 'board': board['coord'], 'x': 4, 'y': from_y})['moves']
            move = next(move for move in moves if move['destination']['y'] == to_y)
            post('/api/p2p/move', {**auth, **move})
            assert post('/api/p2p/submit', auth)['turn'] == next_color

        rejoined = post('/api/p2p/join', guest)
        assert rejoined['reconnected'] and rejoined['player_color'] == 'black'
        states = [post('/api/p2p/state', auth) for auth in (host, guest)]
        assert states[0]['boards'] == states[1]['boards']
        assert states[0]['move_counter'] == states[1]['move_counter'] == 2
        assert states[0]['action_counter'] == states[1]['action_counter'] == 2
        if heartbeat_errors:
            raise RuntimeError(f'{len(heartbeat_errors)} heartbeat requests failed')
        print('PASS: homepage, create/join, room-full/auth/turn guards, two moves and submissions, reconnect, identical boards')
    finally:
        done.set()
        worker.join(timeout=35)
        if credentials:
            post('/api/p2p/leave', credentials[0])
            print('Test room closed')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True, help='Fresh test server origin; do not use an in-progress game')
    parser.add_argument('--exercise-room', action='store_true', help='Create a temporary room, play two moves and close it')
    args = parser.parse_args()
    if not args.exercise_room:
        parser.error('Pass --exercise-room to explicitly authorize the test room')
    check(args.url)


if __name__ == '__main__':
    main()
