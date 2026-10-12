"""Compare terminal decisions against a pinned repository implementation.

Run sequentially without other CPU benchmarks. This proves local tactical
improvements, not a general win-rate or Elo increase. No model is retrained.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ai import (ActionPlanner, ActionSearchBudget, AlphaBetaAI, HardAI,
                    apply_action_plan, engine_state_signature)
from src.utils.constants import ChessColor, GameState
from src.utils.logger import logger
from tests.test_ai_terminal_scoring import tactical_position, defense_position


def coordinates(plan):
    return [[spec.source.x, spec.source.y, spec.destination.x, spec.destination.y]
            for spec in plan.moves]


def compare(baseline_ref):
    # Load only the explicitly selected, locally available Git baseline.
    source = subprocess.check_output(
        ['git', 'show', f'{baseline_ref}:src/ai/alpha_beta.py'], cwd=ROOT,
    )
    old = types.ModuleType('terminal_scoring_baseline')
    exec(compile(source, f'{baseline_ref}:src/ai/alpha_beta.py', 'exec'), old.__dict__)
    rows = []
    for version in ['before', 'after']:
        for ai_type in [AlphaBetaAI, HardAI]:
            for color in ChessColor:
                for mirrored in [False, True]:
                    for depth in [1, 2]:
                        engine = tactical_position(color, mirrored)
                        ai = ai_type(color, search_depth=depth)
                        if version == 'before':
                            ai._search_state = types.MethodType(old.AlphaBetaAI._search_state, ai)
                        before = engine_state_signature(engine)
                        started = time.monotonic()
                        plan = ai.plan_action(engine)
                        elapsed = time.monotonic() - started
                        assert engine_state_signature(engine) == before
                        apply_action_plan(engine, plan)
                        won = (engine.game_state == GameState.CHECKMATE
                               and engine.current_turn_color == color.opposite())
                        if version == 'after':
                            assert won
                        rows.append(dict(version=version, kind='mate_choice',
                            ai=ai_type.__name__, color=color.value, mirrored=mirrored,
                            depth=depth, move=coordinates(plan), score=plan.score,
                            state=engine.game_state.name, won=won, seconds=elapsed,
                            metadata=dict(plan.metadata), budget=asdict(ai.budget)))

        for mirrored in [False, True]:
            engine = defense_position(mirrored)
            ai = AlphaBetaAI(ChessColor.BLACK)
            if version == 'before':
                ai._search_state = types.MethodType(old.AlphaBetaAI._search_state, ai)
            before = engine_state_signature(engine)
            started = time.monotonic()
            plan = ai.plan_action(engine)
            elapsed = time.monotonic() - started
            assert engine_state_signature(engine) == before
            apply_action_plan(engine, plan)
            # Independent exhaustive replies establish actual mate, not just a
            # heuristic score. This diagnostic work is outside the AI budget.
            replies = ActionPlanner(ActionSearchBudget(None, None, 8, None)).search(engine)
            assert replies.candidates and replies.termination_reason is None
            mates = []
            for specs in replies.candidates:
                child = ai._apply_candidate(engine, specs)
                if child.game_state == GameState.CHECKMATE:
                    assert child.current_turn_color == ChessColor.BLACK
                    mates.append(coordinates(ai._candidate_plan(engine, specs)))
            if version == 'after':
                assert not mates
            rows.append(dict(version=version, kind='avoid_mate', ai='AlphaBetaAI',
                color='black', mirrored=mirrored, depth=2, move=coordinates(plan),
                score=plan.score, losing_replies=mates, reply_count=len(replies.candidates),
                seconds=elapsed, metadata=dict(plan.metadata), budget=asdict(ai.budget)))

    return dict(schema_version=1, created_at=datetime.now(timezone.utc).isoformat(),
        baseline_ref=baseline_ref, baseline_sha256=hashlib.sha256(source).hexdigest(),
        current_sha256=hashlib.sha256((ROOT/'src/ai/alpha_beta.py').read_bytes()).hexdigest(),
        shared_source_sha256={name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
            for name in ['src/ai/action_planner.py', 'src/ai/evaluator.py',
                         'src/engine/royal_rules.py', 'src/engine/outcome_rules.py']},
        constraints='Same candidates, default Medium/Hard budgets, depth1/2; no training or rule changes',
        limitations='Four constructed mating nets and two defense positions; not an Elo or full-game win-rate estimate. Candidate caps may omit other tactics.',
        results=rows,
        summary={version: dict(
            immediate_mates=sum(r.get('won', False) for r in rows if r['version']==version),
            mate_cases=16,
            avoided_immediate_losses=sum(not r['losing_replies'] for r in rows if r['version']==version and r['kind']=='avoid_mate'),
            defense_cases=2,
        ) for version in ['before','after']})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-ref', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    logger.disabled = True
    result = compare(args.baseline_ref)
    args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf8')
    print(json.dumps(result['summary']))


if __name__ == '__main__':
    main()
