"""Temporary Arena probe for witness-first ActionPlanner seeding.

This does not change canonical rules or production planner code. It monkeypatches
ActionPlanner.search only for the diagnostic process so we can measure whether
using the existing canonical ActionSearch to secure one complete witness before
bounded candidate enumeration removes zero-candidate planning failures.

For a planning failure the probe also records every previously submitted
canonical Action in that game.  The trace is sufficient to reconstruct the
failure state deterministically without relying on model/RNG/wall-clock replay.
"""
from __future__ import annotations

from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import src.ai.action_planner as planner_mod
from src.ai.action_planner import ActionPlanner, ActionSearchBudget, MoveSpec
from src.engine.action_search import ActionSearch
from src.training import arena


_ORIGINAL_SEARCH = ActionPlanner.search
_ORIGINAL_APPLY = arena.apply_action_plan
_ORIGINAL_FAILURE_RECORD = arena._failure_record
_TRACE_BY_ENGINE: dict[int, dict] = {}


def _candidate_key(candidate):
    return tuple((spec.source, spec.destination, spec.promotion) for spec in candidate)


def _spec_json(spec: MoveSpec) -> dict:
    return {
        "source": [
            spec.source.board.timeline,
            spec.source.board.turn,
            spec.source.board.side.value,
            spec.source.x,
            spec.source.y,
        ],
        "destination": [
            spec.destination.board.timeline,
            spec.destination.board.turn,
            spec.destination.board.side.value,
            spec.destination.x,
            spec.destination.y,
        ],
        "promotion": spec.promotion.value if spec.promotion else None,
    }


def _trace_entry(engine):
    key = id(engine)
    entry = _TRACE_BY_ENGINE.get(key)
    if entry is None:
        # Keep the engine alive so Python cannot reuse its id for a later game.
        entry = {"engine": engine, "actions": []}
        _TRACE_BY_ENGINE[key] = entry
    return entry


def _tracing_apply(engine, plan):
    applied = _ORIGINAL_APPLY(engine, plan)
    _trace_entry(engine)["actions"].append([
        _spec_json(spec) for spec in tuple(plan.moves)
    ])
    return applied


def _tracing_failure_record(**kwargs):
    record = _ORIGINAL_FAILURE_RECORD(**kwargs)
    actions = list(_trace_entry(kwargs["engine"])["actions"])
    record["canonical_action_trace_length"] = len(actions)
    record["canonical_action_trace"] = actions
    return record


def _witness_first_search(self, engine):
    budget = self.budget
    started = time.monotonic()

    witness_search = ActionSearch(
        max_states=budget.max_states,
        max_depth=budget.max_move_depth,
        max_seconds=budget.max_seconds,
    )
    witness_result = witness_search.find_legal_completion(engine)
    elapsed = time.monotonic() - started

    if not witness_result.has_legal_action:
        return planner_mod.ActionSearchResult(
            (),
            witness_result.explored_states,
            witness_result.termination_reason,
        )

    seed = tuple(MoveSpec.from_move(move) for move in witness_result.witness)
    candidates = [seed]
    seen = {_candidate_key(seed)}

    if budget.max_actions is not None and budget.max_actions <= 1:
        return planner_mod.ActionSearchResult(
            tuple(candidates),
            witness_result.explored_states,
            "action_budget" if budget.max_actions == 1 else None,
        )

    remaining_seconds = None
    if budget.max_seconds is not None:
        remaining_seconds = max(0.0, budget.max_seconds - elapsed)
        if remaining_seconds <= 0.0:
            return planner_mod.ActionSearchResult(
                tuple(candidates),
                witness_result.explored_states,
                "time_budget",
            )

    remaining_states = None
    if budget.max_states is not None:
        remaining_states = max(0, budget.max_states - witness_result.explored_states)

    remaining_actions = None
    if budget.max_actions is not None:
        remaining_actions = max(0, budget.max_actions - 1)

    enumeration_budget = ActionSearchBudget(
        max_states=remaining_states,
        max_actions=remaining_actions,
        max_move_depth=budget.max_move_depth,
        max_seconds=remaining_seconds,
    )
    extra = _ORIGINAL_SEARCH(ActionPlanner(enumeration_budget), engine)

    for candidate in extra.candidates:
        key = _candidate_key(candidate)
        if key in seen:
            continue
        candidates.append(candidate)
        seen.add(key)
        if budget.max_actions is not None and len(candidates) >= budget.max_actions:
            break

    termination_reason = extra.termination_reason
    if budget.max_actions is not None and len(candidates) >= budget.max_actions:
        termination_reason = "action_budget"

    return planner_mod.ActionSearchResult(
        tuple(candidates),
        witness_result.explored_states + extra.explored_states,
        termination_reason,
    )


def main() -> int:
    ActionPlanner.search = _witness_first_search
    arena.apply_action_plan = _tracing_apply
    arena._failure_record = _tracing_failure_record
    return arena.main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
