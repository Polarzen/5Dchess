"""Reproducible long-game audit using unchanged production Arena planning.

Run serially (not alongside CPU-heavy tests). Observers only inspect completed
Actions; they do not select moves, change budgets or adjudicate repetition.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
import logging
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ai.action_planner import _PRODUCTION_HYBRID_BUDGET
from src.data.archive import GameArchive
from src.engine import FiveDEngine
from src.engine.repetition import detect_frontier_repetition
from src.utils.constants import GameState


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def position_key(position):
    return (tuple(tuple(row) for row in position.board), position.turn,
            position.timeline_id, position.time_point, position.move_number,
            tuple(sorted(position.castling_rights.items())), position.en_passant_target,
            frozenset(position.unmoved_pawns))


def history_keys(engine):
    return {(lane, point): position_key(pos)
            for lane, timeline in engine.timeline_manager.timelines.items()
            for point, pos in timeline.positions.items()}


def assert_history_preserved(before, engine):
    for (lane, point), key in before.items():
        assert position_key(engine.timeline_manager.timelines[lane].positions[point]) == key


def sustained_recurrence(actions=200):
    """Actual canonical move+submit stress, intentionally repeated Knight play."""
    engine = FiveDEngine()
    cycle = [((6, 7), (5, 5)), ((6, 0), (5, 2)),
             ((5, 5), (6, 7)), ((5, 2), (6, 0))]
    warnings = 0
    for index in range(actions):
        source, target = cycle[index % 4]
        before = history_keys(engine)
        pos = engine.get_current_position()
        move = next(m for m in engine.get_legal_moves_from_square(pos, *source)
                    if m.is_spatial and (m.to_x, m.to_y) == target)
        assert engine.execute_action_move(move)
        assert engine.submit_action()  # Include normal global outcome evaluation.
        assert_history_preserved(before, engine)
        assert engine.game_state == GameState.PLAYING
        repeat = detect_frontier_repetition(engine)
        if index >= 7:
            assert repeat is not None
            warnings += 1
    # A genuine change clears the advisory without any special reset API.
    pos = engine.get_current_position()
    pawn = next(m for m in engine.get_legal_moves_from_square(pos, 4, 6)
                if m.is_spatial and (m.to_x, m.to_y) == (4, 4))
    assert engine.execute_action_move(pawn) and engine.submit_action()
    assert detect_frontier_repetition(engine) is None
    return {'scripted_actions': actions, 'warning_boundaries': warnings,
            'state': engine.game_state.name, 'progress_clears_warning': True,
            'history_preserved': True}


def run_tier(opponent, args, output):
    import src.training.arena as arena
    original_engine, original_apply = arena.FiveDEngine, arena.apply_action_plan
    original_record_failure = arena._record_first_failure
    games, active = [], [None]

    def create_engine():
        if active[0] is not None:
            games[-1]['state'] = active[0].game_state.name
        engine = original_engine()
        active[0] = engine
        games.append({'game': len(games) + 1, 'actions': 0, 'moves': 0,
                      'max_timelines': 1, 'branches': 0, 'castles': 0,
                      'repetition_actions': [], 'rule_warning_actions': []})
        print(json.dumps({'opponent': opponent, 'starting_game': len(games)}), flush=True)
        return engine

    def observe_apply(engine, plan):
        before = history_keys(engine)
        prior_actions = len(engine.action_history)
        result = original_apply(engine, plan)
        assert_history_preserved(before, engine)
        assert len(engine.action_history) == prior_actions + 1
        action = engine.action_history[-1]
        assert action.submitted and engine.current_turn_color == action.color.opposite()
        row = games[-1]
        row.update(actions=len(engine.action_history), moves=engine.move_counter,
                   state=engine.game_state.name)
        row['max_timelines'] = max(row['max_timelines'], len(engine.timeline_manager.timelines))
        row['branches'] += sum(m.is_branching for m in action.moves)
        row['castles'] += sum(m.is_castling for m in action.moves)
        repetition = detect_frontier_repetition(engine)
        if repetition:
            row['repetition_actions'].append(row['actions'])
        if getattr(engine, 'rule_warning', None):
            row['rule_warning_actions'].append(row['actions'])
        if row['actions'] % 20 == 0 or engine.game_state != GameState.PLAYING:
            print(json.dumps({'opponent': opponent, **row}), flush=True)
            write_json(output / 'progress.json', {'opponent': opponent, 'games': games})
        return result

    def observe_failure(first_failure, **kwargs):
        recorded = original_record_failure(first_failure, **kwargs)
        if first_failure is None:
            # Capture at the failure boundary, before the next game replaces
            # the active engine. A seed alone cannot replay timed searches.
            snapshot = output / f'{opponent}-first-failure.json.gz'
            snapshot.write_bytes(gzip.compress(
                json.dumps(GameArchive.capture(kwargs['engine'])).encode(), mtime=0))
        return recorded

    arena.FiveDEngine, arena.apply_action_plan = create_engine, observe_apply
    arena._record_first_failure = observe_failure
    started = time.monotonic()
    try:
        result = arena.evaluate_arena(checkpoint=args.checkpoint, opponent=opponent,
            games=args.games, device_name='cpu', seed=args.seed, max_actions=args.max_actions,
            budget=_PRODUCTION_HYBRID_BUDGET, output='json', model_color='alternate')
    finally:
        arena.FiveDEngine, arena.apply_action_plan = original_engine, original_apply
        arena._record_first_failure = original_record_failure
    if active[0] is not None:
        games[-1]['state'] = active[0].game_state.name
    payload = {'seconds': time.monotonic() - started, 'arena': result, 'game_details': games}
    write_json(output / f'{opponent}.json', payload)
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--games', type=int, default=20)
    parser.add_argument('--max-actions', type=int, default=120)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--opponents', nargs='+', choices=['easy', 'medium', 'hard'],
                        default=['easy', 'medium', 'hard'])
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    logging.disable(logging.CRITICAL)
    paths = sorted((ROOT / 'src').rglob('*.py')) + [Path(__file__).resolve()]
    source = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    metadata = {'started_utc': datetime.now(timezone.utc).isoformat(), 'source_sha256': source,
                'model_sha256': hashlib.sha256((args.checkpoint / 'model.safetensors').read_bytes()).hexdigest(),
                'budget': asdict(_PRODUCTION_HYBRID_BUDGET), 'games_per_tier': args.games,
                'max_actions': args.max_actions, 'seed': args.seed, 'color': 'alternate'}
    write_json(args.output / 'source.json', metadata)
    scripted = sustained_recurrence()
    write_json(args.output / 'sustained-recurrence.json', scripted)
    tiers = {tier: run_tier(tier, args, args.output) for tier in args.opponents}
    failures = sum(t['arena'][key] for t in tiers.values() for key in
                   ('illegal_action_count', 'stale_failure_count', 'planning_failure_count', 'unexpected_failure_count'))
    summary = {'metadata': metadata, 'scripted': scripted, 'tiers': tiers,
               'execution_failures': failures,
               'source_unchanged': all(hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == sha
                                       for p, sha in source.items())}
    write_json(args.output / 'result.json', summary)
    print(json.dumps({'execution_failures': failures, 'source_unchanged': summary['source_unchanged']}), flush=True)
    return int(bool(failures) or not summary['source_unchanged'])


if __name__ == '__main__':
    raise SystemExit(main())
