from __future__ import annotations

import json

import pytest

pytest.importorskip("torch")
pytest.importorskip("safetensors")

from src.training.arena import (
    _neural_color_for_game,
    _normalize_game_seeds,
    build_parser as build_arena_parser,
)
from src.training.benchmark import (
    BENCHMARK_SCHEMA_VERSION,
    DEFAULT_BLACK_SEEDS,
    DEFAULT_WHITE_SEEDS,
    aggregate_games,
    determinism_fingerprint,
    merge_benchmark_reports,
    validate_seed_schedule,
)
from src.utils.constants import ChessColor


def _record(
    seed: int,
    color: str,
    result: str,
    *,
    opponent: str = "easy",
    actions: int = 12,
    inference_ms: float = 2.0,
    illegal: int = 0,
    stale: int = 0,
    planning: int = 0,
    unexpected: int = 0,
    budget: int = 0,
):
    winner = None
    if result == "win":
        winner = color
    elif result == "loss" and not any((illegal, stale, planning, unexpected, budget)):
        winner = "black" if color == "white" else "white"
    return {
        "opponent": opponent,
        "seed": seed,
        "model_color": color,
        "result": result,
        "winner": winner,
        "actions": actions,
        "average_inference_ms": inference_ms,
        "inference_observations": 2,
        "candidate_breadth": {
            "all_actions": [4, 6],
            "neural_actions": [5, 7],
            "all_partial_search_count": 1,
            "neural_partial_search_count": 1,
        },
        "budget_termination_count": budget,
        "illegal_action_count": illegal,
        "planning_failure_count": planning,
        "stale_failure_count": stale,
        "unexpected_failure_count": unexpected,
        "first_failure": None,
        "proven_terminal_adjudication_count": 0,
    }


def _balanced_records(opponent="easy"):
    records = []
    for index, seed in enumerate(DEFAULT_WHITE_SEEDS):
        records.append(
            _record(seed, "white", "win" if index < 5 else "draw", opponent=opponent)
        )
    for index, seed in enumerate(DEFAULT_BLACK_SEEDS):
        records.append(
            _record(seed, "black", "loss" if index < 5 else "draw", opponent=opponent)
        )
    return records


def _report(opponent: str):
    games = _balanced_records(opponent)
    summary = aggregate_games(games, expected_games=20)
    return {
        "benchmark_schema_version": BENCHMARK_SCHEMA_VERSION,
        "metadata": {
            "generated_at": "2026-09-05T00:00:00+00:00",
            "git_sha": "abc",
            "checkpoint_source_run": "33347901504",
            "checkpoint_artifact": "local-ai-checkpoint-33347901504",
            "checkpoint": "/tmp/checkpoint/best",
            "checkpoint_epoch": 20,
            "model_config": {"preset": "small"},
            "encoding_config": {"max_relevant_boards": 16},
            "device": "cpu",
            "opponents": [opponent],
            "planner": {
                "max_states": 256,
                "max_actions": 24,
                "max_move_depth": 32,
                "max_seconds": 5.0,
            },
            "max_actions": 120,
            "seed_schedule": {
                "white": list(DEFAULT_WHITE_SEEDS),
                "black": list(DEFAULT_BLACK_SEEDS),
            },
        },
        "games": games,
        "by_opponent": {opponent: summary},
        "overall": summary,
    }


def test_fixed_seed_schedule_is_exact_and_deterministic():
    first = validate_seed_schedule()
    second = validate_seed_schedule()
    assert first == second
    assert first["white"] == DEFAULT_WHITE_SEEDS
    assert first["black"] == DEFAULT_BLACK_SEEDS
    assert len(first["white"]) == len(first["black"]) == 10
    assert len(set(first["white"] + first["black"])) == 20


def test_seed_schedule_rejects_duplicates_and_wrong_size():
    with pytest.raises(ValueError, match="exactly 10"):
        validate_seed_schedule(DEFAULT_WHITE_SEEDS[:-1], DEFAULT_BLACK_SEEDS)
    with pytest.raises(ValueError, match="unique"):
        validate_seed_schedule(DEFAULT_WHITE_SEEDS, DEFAULT_BLACK_SEEDS[:-1] + (101,))


def test_arena_explicit_model_color_and_seed_helpers():
    assert _neural_color_for_game("white", 99) is ChessColor.WHITE
    assert _neural_color_for_game("black", 0) is ChessColor.BLACK
    assert _neural_color_for_game("alternate", 0) is ChessColor.WHITE
    assert _neural_color_for_game("alternate", 1) is ChessColor.BLACK
    assert _normalize_game_seeds((1, 2), games=2) == (1, 2)
    with pytest.raises(ValueError, match="length"):
        _normalize_game_seeds((1,), games=2)
    with pytest.raises(ValueError, match="integers"):
        _normalize_game_seeds((1, True), games=2)


def test_arena_parser_exposes_model_color_without_changing_default():
    parser = build_arena_parser()
    args = parser.parse_args(["--checkpoint", "x"])
    assert args.model_color == "alternate"
    explicit = parser.parse_args(["--checkpoint", "x", "--model-color", "black"])
    assert explicit.model_color == "black"


def test_aggregate_wdl_score_side_split_and_candidate_stats():
    summary = aggregate_games(_balanced_records(), expected_games=20)
    assert summary["games"] == 20
    assert (summary["wins"], summary["draws"], summary["losses"]) == (5, 10, 5)
    assert summary["win_rate"] == pytest.approx(0.25)
    assert summary["score_rate"] == pytest.approx(0.5)
    assert summary["average_actions"] == pytest.approx(12.0)
    assert summary["median_actions"] == pytest.approx(12.0)
    assert summary["average_inference_ms"] == pytest.approx(2.0)
    assert summary["candidate_breadth"]["neural_actions"] == {
        "observations": 40,
        "minimum": 5,
        "median": 6.0,
        "mean": 6.0,
        "maximum": 7,
    }
    assert summary["candidate_breadth"]["neural_partial_search_count"] == 20
    assert summary["candidate_breadth"]["neural_partial_search_rate"] == pytest.approx(0.5)
    assert summary["side_split"]["white"]["games"] == 10
    assert summary["side_split"]["black"]["games"] == 10


def test_aggregate_reliability_counts_are_not_hidden_by_wins():
    records = _balanced_records()
    records[0] = _record(
        DEFAULT_WHITE_SEEDS[0],
        "white",
        "loss",
        illegal=1,
        planning=2,
        budget=1,
    )
    summary = aggregate_games(records, expected_games=20)
    assert summary["illegal_action_count"] == 1
    assert summary["planner_failure_count"] == 2
    assert summary["budget_termination_count"] == 1


def test_aggregate_rejects_duplicate_missing_and_side_imbalance():
    records = _balanced_records()
    with pytest.raises(ValueError, match="duplicate"):
        aggregate_games(records + [dict(records[0])], require_balanced=False)
    with pytest.raises(ValueError, match="expected 20"):
        aggregate_games(records[:-1], expected_games=20)
    with pytest.raises(ValueError, match="imbalanced"):
        aggregate_games(records[:-1], require_balanced=True)
    malformed = dict(records[0])
    malformed.pop("winner")
    with pytest.raises(ValueError, match="missing keys"):
        aggregate_games([malformed], require_balanced=False)


def test_determinism_fingerprint_ignores_timing_not_semantics():
    first = _record(DEFAULT_WHITE_SEEDS[0], "white", "win", inference_ms=1.0)
    second = dict(first)
    second["average_inference_ms"] = 99.0
    assert determinism_fingerprint(first) == determinism_fingerprint(second)
    changed = dict(second)
    changed["actions"] += 1
    assert determinism_fingerprint(first) != determinism_fingerprint(changed)


def test_merge_reports_requires_compatible_protocol_and_recomputes_overall():
    easy = _report("easy")
    medium = _report("medium")
    merged = merge_benchmark_reports([easy, medium])
    assert merged["metadata"]["opponents"] == ["easy", "medium"]
    assert len(merged["games"]) == 40
    assert merged["overall"]["games"] == 40
    assert set(merged["by_opponent"]) == {"easy", "medium"}

    incompatible = _report("hard")
    incompatible["metadata"]["planner"] = dict(incompatible["metadata"]["planner"])
    incompatible["metadata"]["planner"]["max_seconds"] = 4.0
    with pytest.raises(ValueError, match="different planner"):
        merge_benchmark_reports([easy, incompatible])


def test_benchmark_report_json_round_trip_preserves_seed_protocol():
    report = _report("easy")
    restored = json.loads(json.dumps(report, sort_keys=True))
    assert restored["benchmark_schema_version"] == BENCHMARK_SCHEMA_VERSION
    assert restored["metadata"]["seed_schedule"]["white"] == list(DEFAULT_WHITE_SEEDS)
    assert restored["metadata"]["seed_schedule"]["black"] == list(DEFAULT_BLACK_SEEDS)
    assert restored["overall"]["score_rate"] == pytest.approx(0.5)
