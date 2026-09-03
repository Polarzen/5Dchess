"""Temporary exact-state benchmark for the planner ordering experiment.

This test is intentionally removed after its telemetry is captured from CI.
It downloads the already-existing Run 33347901504 checkpoint; it does not train.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import warnings
import zipfile

import pytest

pytest.importorskip("torch")
pytest.importorskip("safetensors")

import src.ai.action_planner as action_planner
from src.ai.action_planner import (
    ActionPlanner,
    ActionPlanningError,
    ActionSearchBudget,
    apply_action_plan,
)
from src.engine.engine import FiveDEngine
from src.training.agent import NeuralPolicyValueAgent
from src.training.arena import _baseline, _state_signature_sha256
from src.training.checkpoint import load_checkpoint
from src.training.utils import seed_everything
from src.utils.constants import ChessColor, GameState

TARGET_SHA = "03c8c0604a132d66fa1197145805e5fc3fe51579667ff2424a483353ee52bb03"
ARTIFACT_URL = "https://api.github.com/repos/Polarzen/5Dchess/actions/artifacts/9748029228/zip"


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


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _download_checkpoint(root: Path) -> Path:
    extraheader = subprocess.check_output(
        ["git", "config", "--local", "--get", "http.https://github.com/.extraheader"],
        text=True,
    ).strip()
    _, _, auth_value = extraheader.partition(":")
    assert auth_value.strip(), "checkout credential header unavailable"
    request = urllib.request.Request(
        ARTIFACT_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": auth_value.strip(),
            "User-Agent": "5dchess-planner-benchmark",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        opener.open(request, timeout=30)
    except urllib.error.HTTPError as exc:
        assert exc.code in {301, 302, 303, 307, 308}, f"artifact API returned HTTP {exc.code}"
        location = exc.headers.get("Location")
    else:
        pytest.fail("artifact API unexpectedly returned without a redirect")
    assert location, "artifact redirect did not include Location"

    archive = root / "checkpoint.zip"
    blob_request = urllib.request.Request(
        location,
        headers={"User-Agent": "5dchess-planner-benchmark"},
    )
    with urllib.request.urlopen(blob_request, timeout=60) as response, archive.open("wb") as output:
        output.write(response.read())
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
                return deepcopy(engine), action_index, observed, "target_sha"
            if engine.game_state != GameState.PLAYING:
                break
            try:
                if engine.current_turn_color == ChessColor.WHITE:
                    plan = neural.plan_action(engine)
                else:
                    plan = baseline.plan_action(engine)
            except ActionPlanningError as exc:
                if exc.reason == "time_budget" and exc.incomplete:
                    return deepcopy(engine), action_index, observed, "reproduced_time_budget"
                raise
            apply_action_plan(engine, plan)
    finally:
        action_planner._move_sort_key = new_key
    pytest.fail("legacy planning failure was not reproduced; observed=" + json.dumps(observed))


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


def test_failure_state_ordering_ab():
    with tempfile.TemporaryDirectory(prefix="planner-ordering-benchmark-") as temp:
        checkpoint = _download_checkpoint(Path(temp))
        state, action_index, observed, replay_kind = _replay_failure_state(checkpoint)
        replay_sha = _state_signature_sha256(state)
        timeline_count = len(state.timeline_manager.timelines)
        assert 31 <= timeline_count <= 32

        new_key = action_planner._move_sort_key
        budgets = (0.5, 1.0, 2.0, 5.0)
        before = [_benchmark(state, _legacy_move_sort_key, seconds) for seconds in budgets]
        after = [_benchmark(state, new_key, seconds) for seconds in budgets]
        telemetry = {
            "target_action_index": 34,
            "target_sha": TARGET_SHA,
            "replay_action_index": action_index,
            "replay_sha": replay_sha,
            "replay_kind": replay_kind,
            "timeline_count": timeline_count,
            "before": before,
            "after": after,
            "observed_replay": observed,
        }
        warnings.warn("PLANNER_ORDERING_TELEMETRY=" + json.dumps(telemetry, sort_keys=True))
        assert any(row["candidate_count"] > 0 for row in after), telemetry
