"""Temporary one-game Arena telemetry for the planner ordering experiment.

This test is intentionally removed after telemetry is captured from CI.
It downloads the already-existing Run 33347901504 checkpoint; it does not train.
"""
from __future__ import annotations

import json
from pathlib import Path
import statistics
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

from src.ai.action_planner import ActionPlanner, ActionSearchBudget
from src.engine.engine import FiveDEngine
from src.training.agent import NeuralPolicyValueAgent
from src.training.arena import evaluate_arena

ARTIFACT_URL = "https://api.github.com/repos/Polarzen/5Dchess/actions/artifacts/9748029228/zip"
PLANNER_SECONDS = 0.5


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
            "User-Agent": "5dchess-planner-arena-benchmark",
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
        headers={"User-Agent": "5dchess-planner-arena-benchmark"},
    )
    with urllib.request.urlopen(blob_request, timeout=60) as response, archive.open("wb") as output:
        output.write(response.read())
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(root / "checkpoint")
    best = root / "checkpoint" / "best"
    assert (best / "metadata.json").is_file()
    return best


def test_one_game_arena_candidate_breadth_and_overrun():
    with tempfile.TemporaryDirectory(prefix="planner-ordering-arena-") as temp:
        checkpoint = _download_checkpoint(Path(temp))
        candidate_counts: list[int] = []
        partial_search_count = 0
        planner_wall_ms: list[float] = []
        can_submit_ms: list[float] = []

        original_score = NeuralPolicyValueAgent.score_candidates
        original_search = ActionPlanner.search
        original_can_submit = FiveDEngine.can_submit_action

        def timed_search(self, engine):
            started = time.perf_counter()
            try:
                return original_search(self, engine)
            finally:
                planner_wall_ms.append((time.perf_counter() - started) * 1000.0)

        def timed_can_submit(self):
            started = time.perf_counter()
            try:
                return original_can_submit(self)
            finally:
                can_submit_ms.append((time.perf_counter() - started) * 1000.0)

        def recording_score(self, engine):
            nonlocal partial_search_count
            result, decision = original_score(self, engine)
            candidate_counts.append(len(result.candidates))
            if result.termination_reason is not None and result.candidates:
                partial_search_count += 1
            return result, decision

        ActionPlanner.search = timed_search
        FiveDEngine.can_submit_action = timed_can_submit
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
                    max_seconds=PLANNER_SECONDS,
                ),
                output="json",
            )
        finally:
            NeuralPolicyValueAgent.score_candidates = original_score
            FiveDEngine.can_submit_action = original_can_submit
            ActionPlanner.search = original_search

        breadth = None
        if candidate_counts:
            breadth = {
                "min": min(candidate_counts),
                "median": statistics.median(candidate_counts),
                "mean": statistics.fmean(candidate_counts),
                "max": max(candidate_counts),
            }
        max_planner_wall_ms = max(planner_wall_ms, default=0.0)
        longest_can_submit_ms = max(can_submit_ms, default=0.0)
        telemetry = {
            "run_checkpoint": 33347901504,
            "planner_seconds": PLANNER_SECONDS,
            "arena": arena,
            "partial_search_count": partial_search_count,
            "candidate_breadth": breadth,
            "neural_planning_calls": len(candidate_counts),
            "all_planner_calls": len(planner_wall_ms),
            "max_planner_wall_ms": max_planner_wall_ms,
            "budget_overrun_ms": max(0.0, max_planner_wall_ms - PLANNER_SECONDS * 1000.0),
            "longest_can_submit_ms": longest_can_submit_ms,
        }
        warnings.warn("ARENA_ORDERING_TELEMETRY=" + json.dumps(telemetry, sort_keys=True))

        assert arena["checkpoint_epoch"] == 20
        assert arena["candidate_limit"] == 24
        assert arena["planner_budget_seconds"] == PLANNER_SECONDS
        assert arena["illegal_action_count"] == 0
        assert arena["stale_failure_count"] == 0
        assert arena["unexpected_failure_count"] == 0
