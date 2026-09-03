"""Temporary exact-state benchmark for the planner ordering experiment.

This test is intentionally removed after its telemetry is captured from CI.
It downloads the already-existing Run 33347901504 checkpoint; it does not train.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import statistics
import tempfile
import time
import urllib.request
import warnings
import zipfile

import pytest

pytest.importorskip("torch")
pytest.importorskip("safetensors")

import src.ai.action_planner as action_planner
from src.ai.action_planner import ActionPlanner, ActionSearchBudget, apply_action_plan
from src.engine.engine import FiveDEngine
from src.training.agent import NeuralPolicyValueAgent
from src.training.arena import _baseline, _state_signature_sha256, evaluate_arena
from src.training.checkpoint import load_checkpoint
from src.training.utils import seed_everything
from src.utils.constants import ChessColor, GameState

TARGET_SHA = "03c8c0604a132d66fa1197145805e5fc3fe51579667ff2424a483353ee52bb03"
COMMENT_MARKER = "<!-- planner-benchmark-checkpoint -->"
COMMENTS_URL = "https://api.github.com/repos/Polarzen/5Dchess/issues/24/comments?per_page=100"


def _legacy_move_sort_key(move):
    return (
        move.source.board.timeline,
        move.source.board.turn,
        move.source.board.side.value,
        move.source.y,
        move.source.x,
        move.destination.board.timeline,
        move.destination.board.turn,
        move.destination.board.side.value,
        move.destination.y,
        move.destination.x,
        move.promotion.value if move.promotion else "",
        bool(move.is_branching),
        bool(move.is_cross_timeline),
    )


def _checkpoint_from_pr_comment(root: Path) -> Path:
    request = urllib.request.Request(COMMENTS_URL, headers={"User-Agent": "5dchess-planner-benchmark"})
    with urllib.request.urlopen(request, timeout=30) as response:
        comments = json.load(response)
    body = next(
        item["body"] for item in reversed(comments)
        if COMMENT_MARKER in (item.get("body") or "")
    )
    url = next(line.strip() for line in body.splitlines() if line.startswith("https://"))
    archive = root / "checkpoint.zip"
    urllib.request.urlretrieve(url, archive)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(root / "checkpoint")
    best = root / "checkpoint" / "best"
    assert (best / "metadata.json").is_file()
    return best


def _replay_failure_state(checkpoint: Path):
    seed_everything(42)
    model, _ = load_checkpoint(checkpoint, device="cpu")
    budget = ActionSearchBudget(max_states=256, max_actions=24, max_move_depth=32, max_seconds=0.5)
    engine = FiveDEngine()
    neural = NeuralPolicyValueAgent(model, ChessColor.WHITE, device="cpu", budget=budget)
    baseline = _baseline("easy", ChessColor.BLACK, 43, budget)
    observed = []

    new_key = action_planner._move_sort_key
    action_planner._move_sort_key = _legacy_move_sort_key
    try:
        for action_index in range(120):
            state_sha = _state_signature_sha256(engine)
            if 28 <= action_index <= 40:
                observed.append((action_index, state_sha, len(engine.timeline_manager.timelines), engine.move_counter))
            if state_sha == TARGET_SHA:
                return deepcopy(engine), action_index, observed
            if engine.game_state != GameState.PLAYING:
                break
            if engine.current_turn_color == ChessColor.WHITE:
                plan = neural.plan_action(engine)
            else:
                plan = baseline.plan_action(engine)
            apply_action_plan(engine, plan)
    finally:
        action_planner._move_sort_key = new_key
    pytest.fail("target failure state was not reproduced; observed=" + json.dumps(observed))


def _benchmark(state, key, seconds: float):
    old_key = action_planner._move_sort_key
    original_can_submit = FiveDEngine.can_submit_action
    first_candidate_ms = None
    started = time.perf_counter()

    def timed_can_submit(self):
        nonlocal first_candidate_ms
        result = original_can_submit(self)
        if result and first_candidate_ms is None:
            first_candidate_ms = (time.perf_counter() - started) * 1000.0
        return result

    action_planner._move_sort_key = key
    FiveDEngine.can_submit_action = timed_can_submit
    try:
        result = ActionPlanner(ActionSearchBudget(
            max_states=256,
            max_actions=24,
            max_move_depth=32,
            max_seconds=seconds,
        )).search(deepcopy(state))
        wall_ms = (time.perf_counter() - started) * 1000.0
    finally:
        FiveDEngine.can_submit_action = original_can_submit
        action_planner._move_sort_key = old_key
    return {
        "budget": seconds,
        "first_candidate_ms": first_candidate_ms,
        "candidate_count": len(result.candidates),
        "explored_states": result.explored_states,
        "termination": result.termination_reason,
        "wall_ms": wall_ms,
    }


def test_exact_failure_state_ordering_ab_and_one_game_arena():
    with tempfile.TemporaryDirectory(prefix="planner-ordering-benchmark-") as temp:
        checkpoint = _checkpoint_from_pr_comment(Path(temp))
        state, action_index, observed = _replay_failure_state(checkpoint)
        assert action_index == 34
        assert _state_signature_sha256(state) == TARGET_SHA
        assert len(state.timeline_manager.timelines) == 32

        new_key = action_planner._move_sort_key
        budgets = (0.5, 1.0, 2.0, 5.0)
        before = [_benchmark(state, _legacy_move_sort_key, seconds) for seconds in budgets]
        after = [_benchmark(state, new_key, seconds) for seconds in budgets]
        successful = [row for row in after if row["candidate_count"] > 0]

        telemetry = {
            "target_action_index": action_index,
            "target_sha": TARGET_SHA,
            "before": before,
            "after": after,
            "observed_replay": observed,
        }

        if successful:
            selected = min(successful, key=lambda row: row["budget"])["budget"]
            candidate_counts = []
            partial_searches = 0
            original_score = NeuralPolicyValueAgent.score_candidates

            def recording_score(self, engine):
                nonlocal partial_searches
                result, decision = original_score(self, engine)
                candidate_counts.append(len(result.candidates))
                if result.termination_reason is not None and result.candidates:
                    partial_searches += 1
                return result, decision

            NeuralPolicyValueAgent.score_candidates = recording_score
            try:
                arena = evaluate_arena(
                    checkpoint=checkpoint,
                    opponent="easy",
                    games=1,
                    device_name="cpu",
                    seed=42,
                    max_actions=120,
                    budget=ActionSearchBudget(
                        max_states=256,
                        max_actions=24,
                        max_move_depth=32,
                        max_seconds=selected,
                    ),
                    output="json",
                )
            finally:
                NeuralPolicyValueAgent.score_candidates = original_score

            telemetry["selected_budget"] = selected
            telemetry["arena"] = arena
            telemetry["partial_searches"] = partial_searches
            if candidate_counts:
                telemetry["candidate_breadth"] = {
                    "min": min(candidate_counts),
                    "median": statistics.median(candidate_counts),
                    "mean": statistics.fmean(candidate_counts),
                    "max": max(candidate_counts),
                }
            assert arena["illegal_action_count"] == 0
            assert arena["stale_failure_count"] == 0
            assert arena["unexpected_failure_count"] == 0
            assert arena["planning_failure_count"] == 0

        warnings.warn("PLANNER_ORDERING_TELEMETRY=" + json.dumps(telemetry, sort_keys=True))
        assert successful, telemetry
