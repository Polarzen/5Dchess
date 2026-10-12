"""Exercise file replay and resumption with actual HardAI Actions.

Run sequentially, without other CPU benchmarks. This command binds no server
port and writes only beneath --output-dir. It preserves the full source history.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ai.action_planner import (
    _PRODUCTION_HYBRID_BUDGET, apply_action_plan, engine_state_signature,
)
from src.ai.hard_ai import HardAI
from src.data.archive import GameArchive
from src.data.online_save import OnlineSaveStore
from src.engine import FiveDEngine
from src.modes.replay import ReplayMode
from src.utils.constants import GameState
from src.utils.logger import logger


def fingerprint(engine):
    return hashlib.sha256(OnlineSaveStore._encode(GameArchive.capture(engine))).hexdigest()


def measure(callback):
    start = time.perf_counter()
    result = callback()
    return result, time.perf_counter() - start


def timings(values):
    return {"count": len(values), "total_seconds": sum(values),
            "max_seconds": max(values, default=0.0)}


def reference_frames(engine):
    """Independent canonical execution, retaining hashes instead of snapshots."""
    origin = GameArchive.capture(engine)['replay_origin']
    reference = GameArchive.restore_origin(origin)
    frames = [fingerprint(reference)]
    boundaries = [0]
    for action_index, action in enumerate(engine.action_history):
        for index, move in enumerate(action.moves):
            assert reference.execute_action_move(move), f'reference Move failed: Action {action_index}, Move {index}'
            if index == len(action.moves) - 1:
                assert action.submitted and reference.submit_action(), f'reference submit failed: Action {action_index}'
                boundaries.append(len(frames))
            frames.append(fingerprint(reference))
    for move in engine.current_action.moves if engine.current_action else ():
        assert reference.execute_action_move(move)
        frames.append(fingerprint(reference))
    assert fingerprint(reference) == fingerprint(engine)
    return frames, boundaries


def validate_replay(engine, store, save_id):
    frames, boundaries = reference_frames(engine)
    path = store.directory / f'{save_id}.json'
    before = path.read_bytes()
    (restored, _), read_seconds = measure(lambda: store.load(save_id))
    assert fingerprint(restored) == fingerprint(engine)
    replay = ReplayMode()
    _, load_seconds = measure(lambda: replay.load_from_engine(restored, strict=True))
    replay.start()
    assert fingerprint(replay.engine) == frames[0]
    forward, backward, jumps = [], [], []
    for index in range(1, len(frames)):
        moved, elapsed = measure(replay.step_forward)
        assert moved and replay.current_index == index
        assert fingerprint(replay.engine) == frames[index]
        forward.append(elapsed)
    assert not replay.step_forward()
    for index in range(len(frames) - 2, -1, -1):
        moved, elapsed = measure(replay.step_backward)
        assert moved and fingerprint(replay.engine) == frames[index]
        backward.append(elapsed)
    assert not replay.step_backward()
    order = list(range(len(frames)))
    random.Random(20261012).shuffle(order)
    for index in order:
        _, elapsed = measure(lambda: replay.jump_to(index))
        assert replay.current_index == index and fingerprint(replay.engine) == frames[index]
        jumps.append(elapsed)
    assert path.read_bytes() == before
    # Release the first snapshot set before testing the real HTTP route.
    del replay
    import gc
    gc.collect()
    from src.web.app import app, _game_session
    import src.web.p2p as p2p
    app.config['P2P_SAVE_DIR'] = str(store.directory)
    client = app.test_client()
    response, http_load_seconds = measure(lambda: client.post(
        '/api/p2p/replay', json={'save_id': save_id}))
    assert response.status_code == 200, response.get_json()
    assert response.json['current_index'] == 0
    assert fingerprint(_game_session['mode_instance'].engine) == frames[0]
    http_jumps = []
    for index in sorted(set([0, 1, len(frames) // 2, len(frames) - 1, *boundaries[-4:]])):
        response, elapsed = measure(lambda: client.post('/api/replay/step',
            json={'action': 'jump', 'index': index}))
        assert response.status_code == 200 and response.json['current_index'] == index
        assert fingerprint(_game_session['mode_instance'].engine) == frames[index]
        http_jumps.append(elapsed)
    assert path.read_bytes() == before
    assert client.post('/api/replay/step', json={'action': 'start'}).status_code == 200
    response, http_resume_seconds = measure(lambda: client.post(
        '/api/p2p/restore', json={'save_id': save_id}))
    if engine.game_state == GameState.PLAYING:
        assert response.status_code == 200, response.get_json()
        assert fingerprint(_game_session['mode_instance'].engine) == frames[-1]
        resume_status = 'exact_saved_final_state'
    else:
        assert response.status_code == 409 and response.json['code'] == 'game_finished'
        resume_status = 'finished_game_rejected'
    p2p._room = None
    _game_session.update(mode=None, mode_instance=None, player_color=None)
    assert path.read_bytes() == before
    return {
        'frames_verified': len(frames), 'submitted_actions': len(boundaries) - 1,
        'multi_move_actions': sum(len(action.moves) > 1 for action in engine.action_history),
        'timelines': len(engine.timeline_manager.timelines),
        'positions': sum(len(t.positions) for t in engine.timeline_manager.timelines.values()),
        'archive_bytes': len(before), 'archive_sha256': hashlib.sha256(before).hexdigest(),
        'read_seconds': read_seconds, 'rebuild_seconds': load_seconds,
        'forward': timings(forward), 'backward': timings(backward), 'jump': timings(jumps),
        'http_load_seconds': http_load_seconds, 'http_jumps': timings(http_jumps),
        'http_resume_seconds': http_resume_seconds, 'http_resume': resume_status,
        'file_unchanged': True, 'final_state_sha256': frames[-1],
    }


def run(args):
    logger.setLevel('WARNING')
    if args.source:
        raw = args.source.read_bytes()
        payload = json.loads(gzip.decompress(raw) if args.source.suffix == '.gz' else raw)
        engine = GameArchive.restore(payload.get('payload', {}).get('game', payload))
    else:
        engine = FiveDEngine()
    store = OnlineSaveStore(args.output_dir / 'saves')
    save_id = 'a' * 32
    report = {
        'schema_version': 1, 'created_at': datetime.now(timezone.utc).isoformat(),
        'source': str(args.source) if args.source else 'standard_initial_position',
        'source_actions': len(engine.action_history), 'source_moves': engine.move_counter,
        'ai': 'HardAI vs HardAI', 'profile': args.profile, 'requested_actions': args.actions,
        'actions': [],
    }
    store.save(save_id, engine)
    try:
        for _ in range(args.actions):
            if engine.game_state != GameState.PLAYING:
                break
            ai = (HardAI(engine.current_turn_color, search_depth=2, budget=_PRODUCTION_HYBRID_BUDGET)
                  if args.profile == 'hybrid' else HardAI(engine.current_turn_color))
            before = engine_state_signature(engine)
            try:
                plan, search_seconds = measure(lambda: ai.plan_action(engine))
            finally:
                assert engine_state_signature(engine) == before
                report['last_search_preserved_source'] = True
            # Resumption uses the exact same plan: a second timed search may
            # legitimately select a different move under its remaining budget.
            loaded, _ = store.load(save_id)
            apply_action_plan(engine, plan)
            apply_action_plan(loaded, plan)
            assert fingerprint(engine) == fingerprint(loaded)
            store.save(save_id, engine)
            entry = {
                'action': len(engine.action_history), 'moves': engine.move_counter,
                'timelines': len(engine.timeline_manager.timelines), 'state': engine.game_state.name,
                'search_seconds': search_seconds, 'budget': asdict(ai.budget),
                'metadata': dict(plan.metadata), 'resume_equal': True,
            }
            report['actions'].append(entry)
            print(json.dumps(entry, ensure_ascii=False), flush=True)
        report['replay'] = validate_replay(engine, store, save_id)
        report['status'] = 'passed'
    except Exception as exc:
        report['status'] = 'failed'
        report['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / 'report.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report['replay'], ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--actions', type=int, default=12)
    parser.add_argument('--profile', choices=['web', 'hybrid'], default='hybrid')
    parser.add_argument('--output-dir', type=Path, required=True)
    run(parser.parse_args())
