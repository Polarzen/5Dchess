"""Fixed-seed, side-balanced model-quality benchmark built on canonical Arena."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping, Sequence

from src.ai.action_planner import ActionSearchBudget
from src.training.arena import evaluate_arena
from src.training.checkpoint import validate_checkpoint_metadata
from src.training.config import DEFAULT_PLANNER_CANDIDATE_LIMIT
from src.training.utils import read_json, write_json
from src.utils.constants import ChessColor

BENCHMARK_SCHEMA_VERSION = 1
DEFAULT_OPPONENTS = ("easy", "medium", "hard")
DEFAULT_WHITE_SEEDS = (101, 103, 107, 109, 113, 127, 131, 137, 139, 149)
DEFAULT_BLACK_SEEDS = (151, 157, 163, 167, 173, 179, 181, 191, 193, 197)

_REQUIRED_FAILURE_KEYS = (
    "illegal_action_count",
    "stale_failure_count",
    "planning_failure_count",
    "unexpected_failure_count",
    "budget_termination_count",
)


def validate_seed_schedule(
    white_seeds: Sequence[int] = DEFAULT_WHITE_SEEDS,
    black_seeds: Sequence[int] = DEFAULT_BLACK_SEEDS,
) -> dict[str, tuple[int, ...]]:
    """Validate the published benchmark schedule and reject cherry-pickable gaps."""
    white = tuple(white_seeds)
    black = tuple(black_seeds)
    if len(white) != 10 or len(black) != 10:
        raise ValueError("benchmark requires exactly 10 White and 10 Black seeds")
    combined: list[int] = []
    for label, values in (("white", white), ("black", black)):
        for value in values:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{label} benchmark seeds must be integers")
            combined.append(int(value))
    if len(set(combined)) != len(combined):
        raise ValueError("benchmark seeds must be unique across both model colors")
    return {"white": white, "black": black}


def _candidate_summary(values: Sequence[int]) -> dict[str, int | float]:
    normalized = [int(value) for value in values]
    if not normalized:
        return {
            "observations": 0,
            "minimum": 0,
            "median": 0.0,
            "mean": 0.0,
            "maximum": 0,
        }
    return {
        "observations": len(normalized),
        "minimum": min(normalized),
        "median": float(median(normalized)),
        "mean": float(sum(normalized) / len(normalized)),
        "maximum": max(normalized),
    }


def _validate_game_record(record: Mapping[str, Any]) -> None:
    required = {
        "opponent",
        "seed",
        "model_color",
        "result",
        "winner",
        "actions",
        "average_inference_ms",
        "inference_observations",
        "candidate_breadth",
        "first_failure",
        "proven_terminal_adjudication_count",
        *_REQUIRED_FAILURE_KEYS,
    }
    missing = sorted(required.difference(record))
    if missing:
        raise ValueError("benchmark game record missing keys: " + ", ".join(missing))
    if record["opponent"] not in DEFAULT_OPPONENTS:
        raise ValueError("benchmark game opponent must be easy, medium, or hard")
    if record["model_color"] not in {"white", "black"}:
        raise ValueError("benchmark game model_color must be white or black")
    if record["result"] not in {"win", "draw", "loss"}:
        raise ValueError("benchmark game result must be win, draw, or loss")
    if isinstance(record["seed"], bool) or not isinstance(record["seed"], int):
        raise ValueError("benchmark game seed must be an integer")
    if isinstance(record["actions"], bool) or not isinstance(record["actions"], int):
        raise ValueError("benchmark game actions must be an integer")
    if record["actions"] < 0:
        raise ValueError("benchmark game actions must be non-negative")
    for key in _REQUIRED_FAILURE_KEYS:
        value = record[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"benchmark game {key} must be a non-negative integer")


def _game_record(
    *,
    opponent: str,
    seed: int,
    model_color: str,
    arena_result: Mapping[str, Any],
) -> dict[str, Any]:
    games = int(arena_result.get("games", 0))
    if games != 1 or int(arena_result.get("games_requested", 0)) != 1:
        raise ValueError("benchmark single-game Arena call did not return exactly one game")
    outcome_counts = {
        "win": int(arena_result.get("wins", 0)),
        "draw": int(arena_result.get("draws", 0)),
        "loss": int(arena_result.get("losses", 0)),
    }
    if sum(outcome_counts.values()) != 1:
        raise ValueError("benchmark Arena result does not contain exactly one W/D/L outcome")
    result = next(label for label, count in outcome_counts.items() if count == 1)
    has_failure = any(int(arena_result.get(key, 0)) > 0 for key in _REQUIRED_FAILURE_KEYS)
    if result == "win":
        winner: str | None = model_color
    elif result == "loss" and not has_failure:
        winner = "black" if model_color == "white" else "white"
    else:
        winner = None

    breadth = arena_result.get("candidate_breadth")
    if not isinstance(breadth, Mapping):
        raise ValueError("benchmark Arena result is missing candidate breadth")
    samples = breadth.get("samples")
    if not isinstance(samples, Mapping):
        raise ValueError("benchmark Arena result is missing candidate breadth samples")
    neural_samples = samples.get("neural_actions")
    all_samples = samples.get("all_actions")
    if not isinstance(neural_samples, list) or not isinstance(all_samples, list):
        raise ValueError("benchmark Arena candidate breadth samples are malformed")

    record = {
        "opponent": opponent,
        "seed": int(seed),
        "model_color": model_color,
        "result": result,
        "winner": winner,
        "actions": int(round(float(arena_result.get("average_actions", 0.0)))),
        "average_inference_ms": float(arena_result.get("average_inference_ms", 0.0)),
        "inference_observations": len(neural_samples),
        "candidate_breadth": {
            "all_actions": [int(value) for value in all_samples],
            "neural_actions": [int(value) for value in neural_samples],
            "all_partial_search_count": int(
                breadth.get("all_partial_search_count", 0)
            ),
            "neural_partial_search_count": int(
                breadth.get("neural_partial_search_count", 0)
            ),
        },
        "budget_termination_count": int(
            arena_result.get("budget_termination_count", 0)
        ),
        "illegal_action_count": int(arena_result.get("illegal_action_count", 0)),
        "planning_failure_count": int(
            arena_result.get("planning_failure_count", 0)
        ),
        "stale_failure_count": int(arena_result.get("stale_failure_count", 0)),
        "unexpected_failure_count": int(
            arena_result.get("unexpected_failure_count", 0)
        ),
        "first_failure": arena_result.get("first_failure"),
        "proven_terminal_adjudication_count": int(
            arena_result.get("proven_terminal_adjudication_count", 0)
        ),
    }
    _validate_game_record(record)
    return record


def _weighted_inference_ms(records: Sequence[Mapping[str, Any]]) -> float:
    total_weight = sum(int(record["inference_observations"]) for record in records)
    if total_weight <= 0:
        return 0.0
    total = sum(
        float(record["average_inference_ms"]) * int(record["inference_observations"])
        for record in records
    )
    return float(total / total_weight)


def aggregate_games(
    records: Sequence[Mapping[str, Any]],
    *,
    require_balanced: bool = True,
    expected_games: int | None = None,
) -> dict[str, Any]:
    """Aggregate per-game records and fail closed on duplicates/side imbalance."""
    games = list(records)
    if expected_games is not None and len(games) != expected_games:
        raise ValueError(f"expected {expected_games} benchmark games, got {len(games)}")
    if not games:
        raise ValueError("benchmark aggregation requires at least one game")
    for record in games:
        _validate_game_record(record)

    identities = [
        (str(record["opponent"]), str(record["model_color"]), int(record["seed"]))
        for record in games
    ]
    if len(set(identities)) != len(identities):
        raise ValueError("benchmark contains a duplicate opponent/color/seed game")

    white = [record for record in games if record["model_color"] == "white"]
    black = [record for record in games if record["model_color"] == "black"]
    if require_balanced and len(white) != len(black):
        raise ValueError("benchmark model sides are imbalanced")

    wins = sum(record["result"] == "win" for record in games)
    draws = sum(record["result"] == "draw" for record in games)
    losses = sum(record["result"] == "loss" for record in games)
    action_values = [int(record["actions"]) for record in games]
    neural_candidates = [
        value
        for record in games
        for value in record["candidate_breadth"]["neural_actions"]
    ]
    all_candidates = [
        value
        for record in games
        for value in record["candidate_breadth"]["all_actions"]
    ]
    neural_partial = sum(
        int(record["candidate_breadth"]["neural_partial_search_count"])
        for record in games
    )
    all_partial = sum(
        int(record["candidate_breadth"]["all_partial_search_count"])
        for record in games
    )
    neural_stats = _candidate_summary(neural_candidates)
    all_stats = _candidate_summary(all_candidates)

    summary: dict[str, Any] = {
        "games": len(games),
        "wins": int(wins),
        "draws": int(draws),
        "losses": int(losses),
        "win_rate": float(wins / len(games)),
        "score_rate": float((wins + 0.5 * draws) / len(games)),
        "average_actions": float(sum(action_values) / len(action_values)),
        "median_actions": float(median(action_values)),
        "average_inference_ms": _weighted_inference_ms(games),
        "planner_failure_count": sum(
            int(record["planning_failure_count"]) for record in games
        ),
        "budget_termination_count": sum(
            int(record["budget_termination_count"]) for record in games
        ),
        "illegal_action_count": sum(
            int(record["illegal_action_count"]) for record in games
        ),
        "stale_failure_count": sum(
            int(record["stale_failure_count"]) for record in games
        ),
        "unexpected_failure_count": sum(
            int(record["unexpected_failure_count"]) for record in games
        ),
        "proven_terminal_adjudication_count": sum(
            int(record["proven_terminal_adjudication_count"]) for record in games
        ),
        "candidate_breadth": {
            "all_actions": all_stats,
            "neural_actions": neural_stats,
            "all_partial_search_count": int(all_partial),
            "all_partial_search_rate": (
                float(all_partial / all_stats["observations"])
                if all_stats["observations"]
                else 0.0
            ),
            "neural_partial_search_count": int(neural_partial),
            "neural_partial_search_rate": (
                float(neural_partial / neural_stats["observations"])
                if neural_stats["observations"]
                else 0.0
            ),
        },
    }
    if require_balanced:
        summary["side_split"] = {
            "white": aggregate_games(white, require_balanced=False),
            "black": aggregate_games(black, require_balanced=False),
        }
    return summary


def determinism_fingerprint(record: Mapping[str, Any]) -> tuple[Any, ...]:
    """Stable semantic fingerprint which intentionally excludes wall-clock inference time."""
    _validate_game_record(record)
    return (
        record["opponent"],
        record["seed"],
        record["model_color"],
        record["result"],
        record["winner"],
        record["actions"],
        tuple(record["candidate_breadth"]["all_actions"]),
        tuple(record["candidate_breadth"]["neural_actions"]),
        record["candidate_breadth"]["all_partial_search_count"],
        record["candidate_breadth"]["neural_partial_search_count"],
        *(record[key] for key in _REQUIRED_FAILURE_KEYS),
        record["proven_terminal_adjudication_count"],
    )


def _checkpoint_metadata(checkpoint: Path) -> dict[str, Any]:
    metadata_path = checkpoint.expanduser().resolve() / "metadata.json"
    metadata = read_json(metadata_path)
    validate_checkpoint_metadata(metadata)
    return metadata


def run_single_game(
    *,
    checkpoint: str | Path,
    opponent: str,
    seed: int,
    model_color: str,
    device: str,
    budget: ActionSearchBudget,
    max_actions: int,
) -> dict[str, Any]:
    if model_color not in {"white", "black"}:
        raise ValueError("benchmark single game model_color must be white or black")
    arena_result = evaluate_arena(
        checkpoint=checkpoint,
        opponent=opponent,
        games=1,
        device_name=device,
        seed=seed,
        max_actions=max_actions,
        budget=budget,
        max_wall_seconds=None,
        output="json",
        model_color=model_color,
        game_seeds=(seed,),
    )
    return _game_record(
        opponent=opponent,
        seed=seed,
        model_color=model_color,
        arena_result=arena_result,
    )


def run_benchmark(
    *,
    checkpoint: str | Path,
    checkpoint_source_run: str,
    checkpoint_artifact: str,
    git_sha: str,
    opponents: Sequence[str] = DEFAULT_OPPONENTS,
    device: str = "cpu",
    planner_states: int = 256,
    planner_actions: int = DEFAULT_PLANNER_CANDIDATE_LIMIT,
    planner_moves: int = 32,
    planner_seconds: float = 5.0,
    max_actions: int = 120,
    white_seeds: Sequence[int] = DEFAULT_WHITE_SEEDS,
    black_seeds: Sequence[int] = DEFAULT_BLACK_SEEDS,
) -> dict[str, Any]:
    schedule = validate_seed_schedule(white_seeds, black_seeds)
    normalized_opponents = tuple(str(value).lower() for value in opponents)
    if not normalized_opponents:
        raise ValueError("benchmark requires at least one opponent")
    if len(set(normalized_opponents)) != len(normalized_opponents):
        raise ValueError("benchmark opponents must be unique")
    if any(value not in DEFAULT_OPPONENTS for value in normalized_opponents):
        raise ValueError("benchmark opponent must be easy, medium, or hard")
    if not str(git_sha).strip():
        raise ValueError("benchmark git_sha is required")
    if not str(checkpoint_source_run).strip():
        raise ValueError("benchmark checkpoint_source_run is required")
    if not str(checkpoint_artifact).strip():
        raise ValueError("benchmark checkpoint_artifact is required")

    checkpoint_path = Path(checkpoint).expanduser().resolve()
    checkpoint_metadata = _checkpoint_metadata(checkpoint_path)
    budget = ActionSearchBudget(
        max_states=int(planner_states),
        max_actions=int(planner_actions),
        max_move_depth=int(planner_moves),
        max_seconds=float(planner_seconds),
    )

    game_records: list[dict[str, Any]] = []
    for opponent in normalized_opponents:
        for model_color, seeds in schedule.items():
            for seed in seeds:
                game_records.append(
                    run_single_game(
                        checkpoint=checkpoint_path,
                        opponent=opponent,
                        seed=seed,
                        model_color=model_color,
                        device=device,
                        budget=budget,
                        max_actions=max_actions,
                    )
                )

    by_opponent: dict[str, Any] = {}
    for opponent in normalized_opponents:
        opponent_games = [
            record for record in game_records if record["opponent"] == opponent
        ]
        by_opponent[opponent] = aggregate_games(
            opponent_games,
            require_balanced=True,
            expected_games=20,
        )

    report = {
        "benchmark_schema_version": BENCHMARK_SCHEMA_VERSION,
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "git_sha": str(git_sha),
            "checkpoint_source_run": str(checkpoint_source_run),
            "checkpoint_artifact": str(checkpoint_artifact),
            "checkpoint": str(checkpoint_path),
            "checkpoint_epoch": checkpoint_metadata.get("epoch"),
            "model_config": checkpoint_metadata.get("model_config"),
            "encoding_config": checkpoint_metadata.get("encoding_config"),
            "device": str(device),
            "opponents": list(normalized_opponents),
            "planner": {
                "max_states": budget.max_states,
                "max_actions": budget.max_actions,
                "max_move_depth": budget.max_move_depth,
                "max_seconds": budget.max_seconds,
            },
            "max_actions": int(max_actions),
            "seed_schedule": {
                "white": list(schedule["white"]),
                "black": list(schedule["black"]),
            },
        },
        "games": game_records,
        "by_opponent": by_opponent,
        "overall": aggregate_games(
            game_records,
            require_balanced=True,
            expected_games=20 * len(normalized_opponents),
        ),
    }
    return report


def merge_benchmark_reports(reports: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Merge disjoint opponent reports and recompute all aggregates from raw games."""
    values = list(reports)
    if not values:
        raise ValueError("at least one benchmark report is required")
    for report in values:
        if int(report.get("benchmark_schema_version", -1)) != BENCHMARK_SCHEMA_VERSION:
            raise ValueError("benchmark schema version mismatch")
        if not isinstance(report.get("metadata"), Mapping):
            raise ValueError("benchmark report metadata is missing")
        if not isinstance(report.get("games"), list):
            raise ValueError("benchmark report games are missing")

    baseline_metadata = dict(values[0]["metadata"])
    comparable_keys = (
        "git_sha",
        "checkpoint_source_run",
        "checkpoint_artifact",
        "checkpoint_epoch",
        "model_config",
        "encoding_config",
        "device",
        "planner",
        "max_actions",
        "seed_schedule",
    )
    for report in values[1:]:
        metadata = report["metadata"]
        for key in comparable_keys:
            if metadata.get(key) != baseline_metadata.get(key):
                raise ValueError(f"cannot merge benchmark reports with different {key}")

    games = [record for report in values for record in report["games"]]
    opponents = sorted({str(record["opponent"]) for record in games})
    if len(games) != 20 * len(opponents):
        raise ValueError("merged benchmark is missing games")
    by_opponent = {
        opponent: aggregate_games(
            [record for record in games if record["opponent"] == opponent],
            require_balanced=True,
            expected_games=20,
        )
        for opponent in opponents
    }
    baseline_metadata["generated_at"] = datetime.now(timezone.utc).isoformat()
    baseline_metadata["opponents"] = opponents
    return {
        "benchmark_schema_version": BENCHMARK_SCHEMA_VERSION,
        "metadata": baseline_metadata,
        "games": games,
        "by_opponent": by_opponent,
        "overall": aggregate_games(
            games,
            require_balanced=True,
            expected_games=20 * len(opponents),
        ),
    }


def _summary_text(report: Mapping[str, Any]) -> str:
    lines = [
        "Model quality benchmark",
        f"  git_sha: {report['metadata']['git_sha']}",
        f"  checkpoint_epoch: {report['metadata']['checkpoint_epoch']}",
    ]
    for opponent, summary in report["by_opponent"].items():
        lines.append(
            f"  {opponent}: W/D/L={summary['wins']}/{summary['draws']}/{summary['losses']} "
            f"score={summary['score_rate']:.3f} actions={summary['average_actions']:.2f}"
        )
    overall = report["overall"]
    lines.append(
        f"  overall: W/D/L={overall['wins']}/{overall['draws']}/{overall['losses']} "
        f"score={overall['score_rate']:.3f}"
    )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the fixed-seed, side-balanced Local AI model-quality benchmark"
    )
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--checkpoint-source-run", required=True)
    parser.add_argument("--checkpoint-artifact", required=True)
    parser.add_argument("--git-sha", default=os.environ.get("GITHUB_SHA", ""))
    parser.add_argument(
        "--opponent",
        action="append",
        choices=list(DEFAULT_OPPONENTS),
        help="opponent to benchmark; repeat to select multiple; defaults to all",
    )
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="cpu")
    parser.add_argument("--planner-states", type=int, default=256)
    parser.add_argument(
        "--planner-actions", type=int, default=DEFAULT_PLANNER_CANDIDATE_LIMIT
    )
    parser.add_argument("--planner-moves", type=int, default=32)
    parser.add_argument("--planner-seconds", type=float, default=5.0)
    parser.add_argument("--max-actions", type=int, default=120)
    parser.add_argument("--output", choices=["text", "json", "JSON"], default="text")
    parser.add_argument("--result-json", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_benchmark(
        checkpoint=args.checkpoint,
        checkpoint_source_run=args.checkpoint_source_run,
        checkpoint_artifact=args.checkpoint_artifact,
        git_sha=args.git_sha,
        opponents=args.opponent or DEFAULT_OPPONENTS,
        device=args.device,
        planner_states=args.planner_states,
        planner_actions=args.planner_actions,
        planner_moves=args.planner_moves,
        planner_seconds=args.planner_seconds,
        max_actions=args.max_actions,
    )
    if args.result_json is not None:
        write_json(args.result_json, report)
    if str(args.output).lower() == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(_summary_text(report))

    reliability = report["overall"]
    return 1 if (
        reliability["illegal_action_count"]
        or reliability["stale_failure_count"]
        or reliability["unexpected_failure_count"]
        or reliability["planner_failure_count"]
    ) else 0


if __name__ == "__main__":
    raise SystemExit(main())