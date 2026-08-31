"""Pure validation and workflow helpers for bounded CPU training artifacts.

The GitHub workflow is intentionally kept outside this module.  This file
owns the small, deterministic contract shared by workflow steps: accepted
inputs, model preset aliases, artifact names, retention policy, checkpoint
resume validation, and the arena safety gate.  Training modules are imported
only inside command handlers so importing the normal game package never
requires Torch.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from src.training.config import (
    PlannerConfig,
)


CLOUD_PRESETS: dict[str, str] = {
    "cloud-tiny": "tiny",
    "cloud-small": "small",
    "cloud-long": "medium",
}

# These are workflow safety ceilings, not claims about how long a particular
# runner will take.  A caller may choose a shorter explicit budget.
CLOUD_BUDGET_SECONDS: dict[str, float] = {
    "selfplay": 18_000.0,
    "train": 19_200.0,
    "arena": 9_000.0,
}
DEFAULT_SELFPLAY_MAX_WALL_SECONDS = CLOUD_BUDGET_SECONDS["selfplay"]
DEFAULT_TRAIN_MAX_WALL_SECONDS = CLOUD_BUDGET_SECONDS["train"]
DEFAULT_ARENA_MAX_WALL_SECONDS = CLOUD_BUDGET_SECONDS["arena"]

ARTIFACT_PREFIXES: dict[str, str] = {
    "dataset": "local-ai-dataset",
    "checkpoint": "local-ai-checkpoint",
    "report": "local-ai-report",
}

_TEACHERS = {"easy", "medium", "hard", "mixed"}
_MODEL_PRESETS = {"tiny", "small", "medium"}
_RUN_ID_RE = re.compile(r"^[0-9]+$")
_SIGNED_INT_RE = re.compile(r"^[+-]?[0-9]+$")


def _bounded_int(name: str, value: Any, lower: int, upper: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer in the range {lower}..{upper}")
    if isinstance(value, str):
        if not re.fullmatch(r"[0-9]+", value.strip()):
            raise ValueError(f"{name} must be an integer in the range {lower}..{upper}")
        value = int(value.strip())
    elif not isinstance(value, int):
        raise ValueError(f"{name} must be an integer in the range {lower}..{upper}")
    if not lower <= int(value) <= upper:
        raise ValueError(f"{name} must be in the range {lower}..{upper}")
    return int(value)


def validate_games(value: Any) -> int:
    return _bounded_int("games", value, 1, 5000)


def validate_target_epochs(value: Any) -> int:
    return _bounded_int("target_epochs", value, 1, 500)


def validate_epochs(value: Any) -> int:
    """Compatibility spelling for the total-target ``--epochs`` contract."""
    return validate_target_epochs(value)


def validate_batch(value: Any) -> int:
    return _bounded_int("batch", value, 1, 2048)


def validate_batch_size(value: Any) -> int:
    return validate_batch(value)


def validate_arena_games(value: Any) -> int:
    return _bounded_int("arena_games", value, 0, 500)


def validate_max_actions(value: Any) -> int:
    return _bounded_int("max_actions", value, 1, 1000)


def validate_seed(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("seed must be a signed integer")
    if isinstance(value, int):
        return int(value)
    text = str(value).strip()
    if not _SIGNED_INT_RE.fullmatch(text):
        raise ValueError("seed must be a signed integer")
    return int(text)


def validate_teacher(value: Any) -> str:
    teacher = str(value).strip().lower()
    if teacher not in _TEACHERS:
        raise ValueError("teacher must be easy, medium, hard, or mixed")
    return teacher


def validate_model_preset(value: Any) -> str:
    preset = str(value).strip().lower()
    if preset not in _MODEL_PRESETS:
        raise ValueError("preset must be tiny, small, or medium")
    return preset


def validate_preset(value: Any) -> str:
    """Validate either a native model preset or a workflow cloud alias."""
    preset = str(value).strip().lower()
    if preset in _MODEL_PRESETS or preset in CLOUD_PRESETS:
        return preset
    raise ValueError(
        "preset must be tiny, small, medium, cloud-tiny, cloud-small, or cloud-long"
    )


def resolve_preset(value: Any) -> str:
    preset = validate_preset(value)
    return CLOUD_PRESETS.get(preset, preset)


def cloud_preset(value: Any) -> str:
    """Return the native model preset used by a workflow-facing alias."""
    return resolve_preset(value)


def validate_run_id(value: Any) -> str:
    """Return a normalized positive decimal run id; blank means unsuffixed."""
    if value is None:
        return ""
    if isinstance(value, bool):
        raise ValueError("run_id must be blank or a positive decimal integer")
    text = str(value).strip()
    if not text:
        return ""
    if not _RUN_ID_RE.fullmatch(text) or int(text) <= 0:
        raise ValueError("run_id must be blank or a positive decimal integer")
    # Preserve decimal padding supplied by a workflow so artifact names stay
    # stable and unsurprising across reruns.
    return text


def validate_wall_seconds(
    value: Any,
    kind: str | None = None,
    *,
    allow_none: bool = True,
) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        if allow_none:
            return None
        raise ValueError("wall-time budget is required")
    if isinstance(value, bool):
        raise ValueError("wall-time budget must be a finite non-negative number")
    try:
        seconds = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("wall-time budget must be a finite non-negative number") from exc
    if not math.isfinite(seconds) or seconds < 0.0:
        raise ValueError("wall-time budget must be a finite non-negative number")
    if kind is not None:
        key = str(kind).strip().lower()
        if key not in CLOUD_BUDGET_SECONDS:
            raise ValueError(f"unknown cloud budget kind: {kind!r}")
        ceiling = CLOUD_BUDGET_SECONDS[key]
        if seconds > ceiling:
            raise ValueError(f"{key} wall-time budget cannot exceed {ceiling:g} seconds")
    return seconds


def cloud_budget(kind: str) -> float:
    try:
        return float(CLOUD_BUDGET_SECONDS[str(kind).lower()])
    except KeyError as exc:
        raise ValueError(f"unknown cloud budget kind: {kind!r}") from exc


def artifact_name(kind: str, run_id: Any = "") -> str:
    key = str(kind).strip().lower()
    if key not in ARTIFACT_PREFIXES:
        raise ValueError("artifact kind must be dataset, checkpoint, or report")
    suffix = validate_run_id(run_id)
    return ARTIFACT_PREFIXES[key] + (f"-{suffix}" if suffix else "")


def artifact_names(run_id: Any = "") -> dict[str, str]:
    normalized = validate_run_id(run_id)
    return {
        kind: artifact_name(kind, normalized)
        for kind in ("dataset", "checkpoint", "report")
    }


def artifact_paths(root: str | Path, run_id: Any = "") -> dict[str, Path]:
    root = Path(root)
    return {kind: root / name for kind, name in artifact_names(run_id).items()}


def dataset_retention_days(retain: Any = False) -> int:
    return 7 if bool(retain) else 1


def retention_days(retain: Any = False) -> int:
    return dataset_retention_days(retain)


def retention_policy(retain: Any = False) -> dict[str, int]:
    days = dataset_retention_days(retain)
    return {"dataset": days, "checkpoint": 30, "report": 30}


def validate_bool(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1"}:
        return True
    if text in {"false", "0"}:
        return False
    raise ValueError(f"{name} must be true or false")


def validate_resume_artifact_name(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        return ""
    if len(text) > 255 or not re.fullmatch(r"[A-Za-z0-9_.-]+", text):
        raise ValueError("resume_artifact must be a plain Actions artifact name")
    return text


def arena_passes(result: Mapping[str, Any]) -> bool:
    try:
        illegal = int(result["illegal_action_count"])
        stale = int(result["stale_failure_count"])
        unexpected = int(result.get("unexpected_failure_count", 0))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            "arena result must contain illegal_action_count and stale_failure_count"
        ) from exc
    if illegal < 0 or stale < 0 or unexpected < 0:
        raise ValueError("arena failure counts must be non-negative")
    return illegal == 0 and stale == 0 and unexpected == 0


def arena_gate(result: Mapping[str, Any]) -> bool:
    """Raise on unsafe arena results; budget termination is informational."""
    if not arena_passes(result):
        raise RuntimeError(
            "arena gate failed: illegal, stale, or unexpected failures were observed"
        )
    return True


def validate_arena_result(result: Mapping[str, Any]) -> bool:
    return arena_passes(result)


def validate_cloud_inputs(
    *,
    games: Any | None = None,
    target_epochs: Any | None = None,
    epochs: Any | None = None,
    batch: Any | None = None,
    batch_size: Any | None = None,
    arena_games: Any | None = None,
    max_actions: Any | None = None,
    seed: Any | None = None,
    teacher: Any | None = None,
    preset: Any | None = None,
    run_id: Any = "",
    run_arena: Any | None = None,
    arena_opponent: Any | None = None,
    retain_dataset: Any | None = None,
    resume_run_id: Any = "",
    resume_artifact: Any = "",
    selfplay_wall_seconds: Any | None = None,
    train_wall_seconds: Any | None = None,
    arena_wall_seconds: Any | None = None,
    max_wall_seconds: Any | None = None,
) -> dict[str, Any]:
    if target_epochs is None:
        target_epochs = epochs
    elif epochs is not None and int(target_epochs) != int(epochs):
        raise ValueError("target_epochs and epochs disagree")
    if batch is None:
        batch = batch_size

    result: dict[str, Any] = {}
    if games is not None:
        result["games"] = validate_games(games)
    if target_epochs is not None:
        result["target_epochs"] = validate_target_epochs(target_epochs)
        result["epochs"] = result["target_epochs"]
    if batch is not None:
        result["batch"] = validate_batch(batch)
        result["batch_size"] = result["batch"]
    if arena_games is not None:
        result["arena_games"] = validate_arena_games(arena_games)
    if max_actions is not None:
        result["max_actions"] = validate_max_actions(max_actions)
    if seed is not None:
        result["seed"] = validate_seed(seed)
    if teacher is not None:
        result["teacher"] = validate_teacher(teacher)
    if preset is not None:
        normalized_preset = validate_preset(preset)
        result["preset"] = normalized_preset
        result["model_preset"] = resolve_preset(normalized_preset)
    result["run_id"] = validate_run_id(run_id)
    if run_arena is not None:
        result["run_arena"] = validate_bool(run_arena, "run_arena")
    if arena_opponent is not None:
        opponent = str(arena_opponent).strip().lower()
        if opponent not in {"easy", "medium", "hard"}:
            raise ValueError("arena_opponent must be easy, medium, or hard")
        result["arena_opponent"] = opponent
    if retain_dataset is not None:
        result["retain_dataset"] = validate_bool(retain_dataset, "retain_dataset")
    result["resume_run_id"] = validate_run_id(resume_run_id)
    result["resume_artifact"] = validate_resume_artifact_name(resume_artifact)
    if result["resume_artifact"] and not result["resume_run_id"]:
        raise ValueError("resume_artifact requires resume_run_id")
    if max_wall_seconds is not None:
        # A single convenience budget applies to the requested stage.  Stage
        # values below take precedence when supplied explicitly.
        selfplay_wall_seconds = (
            max_wall_seconds if selfplay_wall_seconds is None else selfplay_wall_seconds
        )
        train_wall_seconds = (
            max_wall_seconds if train_wall_seconds is None else train_wall_seconds
        )
        arena_wall_seconds = (
            max_wall_seconds if arena_wall_seconds is None else arena_wall_seconds
        )
    # Cloud invocations are always bounded even when a caller omits a stage
    # override.  The local ``selfplay``/``train``/``arena`` CLIs retain their
    # documented None/unlimited default; only this workflow contract supplies
    # the conservative runner ceilings.
    if selfplay_wall_seconds is None:
        selfplay_wall_seconds = cloud_budget("selfplay")
    if train_wall_seconds is None:
        train_wall_seconds = cloud_budget("train")
    if arena_wall_seconds is None:
        arena_wall_seconds = cloud_budget("arena")
    result["selfplay_wall_seconds"] = validate_wall_seconds(
        selfplay_wall_seconds, "selfplay"
    )
    result["train_wall_seconds"] = validate_wall_seconds(train_wall_seconds, "train")
    result["arena_wall_seconds"] = validate_wall_seconds(arena_wall_seconds, "arena")
    result["artifacts"] = artifact_names(result["run_id"])
    return result


def deterministic_config(**kwargs: Any) -> dict[str, Any]:
    """Build JSON-safe normalized config with no timestamps or host paths."""
    config = validate_cloud_inputs(**kwargs)
    # JSON round-tripping catches accidental Path/custom-object additions and
    # makes the returned shape suitable for workflow logs and reports.
    return json.loads(json.dumps(config, sort_keys=True, separators=(",", ":")))


def build_cloud_config(**kwargs: Any) -> dict[str, Any]:
    return deterministic_config(**kwargs)


def required_cloud_resume_files(directory: str | Path) -> tuple[Path, ...]:
    root = Path(directory).expanduser().resolve()
    return tuple(root / name for name in ("metadata.json", "model.safetensors", "resume_state.pt"))


def validate_cloud_resume(
    directory: str | Path,
    *,
    preset: str | None = None,
) -> dict[str, Any]:
    """Validate a portable cloud resume artifact without using dataset paths."""
    root = Path(directory).expanduser().resolve()
    missing = [path.name for path in required_cloud_resume_files(root) if not path.is_file()]
    if missing:
        raise ValueError(
            f"cloud resume checkpoint is missing required files: {', '.join(missing)}"
        )
    try:
        metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError("cloud resume metadata is not valid JSON") from exc

    # Importing checkpoint/model here is intentional and lazy; ordinary
    # package imports still do not require Torch.
    from src.training.checkpoint import (
        load_checkpoint,
        validate_checkpoint_metadata,
        validate_resume_payload,
    )

    try:
        validate_checkpoint_metadata(metadata)
        load_checkpoint(root, device="cpu")
        validate_resume_payload(root, device="cpu")
    except Exception as exc:
        if isinstance(exc, ValueError):
            raise
        raise ValueError("cloud resume checkpoint model payload is incompatible") from exc

    stored_preset = str(metadata["model_config"]["preset"]).lower()
    if preset is not None and stored_preset != resolve_preset(preset):
        raise ValueError(
            f"cloud resume model preset {stored_preset!r} does not match requested {preset!r}"
        )
    return {
        "path": str(root),
        "metadata": metadata,
        "preset": stored_preset,
        "required_files": [str(path) for path in required_cloud_resume_files(root)],
    }


def validate_resume_artifact(directory: str | Path, *, preset: str | None = None) -> dict[str, Any]:
    return validate_cloud_resume(directory, preset=preset)


def check_arena_gate(result: Mapping[str, Any]) -> bool:
    return arena_gate(result)


def validate_arena_gate(result: Mapping[str, Any]) -> bool:
    return arena_gate(result)


def _empty_arena_result(checkpoint: str | Path, opponent: str, games: int) -> dict[str, Any]:
    return {
        "checkpoint": str(Path(checkpoint).expanduser().resolve()),
        "opponent": opponent,
        "games": 0,
        "games_requested": int(games),
        "wins": 0,
        "draws": 0,
        "losses": 0,
        "win_rate": 0.0,
        "draw_rate": 0.0,
        "average_actions": 0.0,
        "illegal_action_count": 0,
        "stale_failure_count": 0,
        "budget_termination_count": 0,
        "planning_failure_count": 0,
        "unexpected_failure_count": 0,
        "first_failure": None,
        "average_inference_ms": 0.0,
        "checkpoint_epoch": None,
    }


def _write_report(path: Path, result: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() != ".json":
        path = path / "arena-result.json"
        path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(dict(result), indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)
    return path


def _load_optional_json(root: Path, name: str, *, required: bool = True) -> dict[str, Any]:
    path = root / name
    if not path.is_file():
        if required:
            raise ValueError(f"report input not found: {path}")
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"report input must be a JSON object: {path}")
    return value


def build_report_bundle(
    input_dir: str | Path,
    output_dir: str | Path,
    *,
    run_id: Any,
    branch: str,
    sha: str,
) -> tuple[dict[str, Any], str]:
    """Build portable report JSON files and a GitHub Step Summary."""
    source = Path(input_dir)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    inputs = _load_optional_json(source, "workflow-inputs.json")
    dataset = _load_optional_json(source, "dataset-metadata.json")
    training = _load_optional_json(source, "training-summary.json")
    hardware = _load_optional_json(source, "hardware.json")
    arena = _load_optional_json(source, "arena-result.json", required=False)
    normalized_run_id = validate_run_id(run_id)
    names = artifact_names(normalized_run_id)
    bundle = {
        "run_id": normalized_run_id,
        "branch": str(branch),
        "sha": str(sha),
        "artifacts": names,
        "workflow_inputs": inputs,
        "dataset": dataset,
        "training": training,
        "hardware": hardware,
        "arena": arena or None,
    }
    for name, value in (
        ("workflow-inputs.json", inputs),
        ("dataset-metadata.json", dataset),
        ("training-summary.json", training),
        ("hardware.json", hardware),
    ):
        (output / name).write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    if arena:
        (output / "arena-result.json").write_text(
            json.dumps(arena, indent=2, sort_keys=True), encoding="utf-8"
        )

    metrics = training.get("metrics") or {}
    train_metrics = metrics.get("train") or {}
    validation = metrics.get("validation") or {}
    requested = dataset.get("games_requested", dataset.get("requested_games", inputs.get("games", 0)))
    generated = dataset.get("games_generated", dataset.get("generated_games", dataset.get("game_count", 0)))
    samples = dataset.get("sample_count", dataset.get("samples", 0))
    lines = [
        "# Local AI Cloud Training",
        "",
        f"- Run ID: `{normalized_run_id}`",
        f"- Branch / SHA: `{branch}` / `{sha}`",
        f"- Teacher: `{inputs.get('teacher', '')}`",
        f"- Games requested / generated / samples: `{requested}` / `{generated}` / `{samples}`",
        f"- Preset / device / Torch: `{inputs.get('preset', '')}` / `{training.get('device', 'cpu')}` / `{hardware.get('torch_version', hardware.get('torch', ''))}`",
        f"- Model parameters: `{training.get('parameters', '')}`",
        f"- Epoch start / end: `{training.get('start_epoch', '')}` / `{training.get('end_epoch', '')}`",
        f"- Global step start / end: `{training.get('start_step', '')}` / `{training.get('end_step', training.get('global_step', ''))}`",
        f"- Policy loss / value loss / policy accuracy: `{train_metrics.get('policy_loss', '')}` / `{train_metrics.get('value_loss', '')}` / `{train_metrics.get('policy_accuracy', '')}`",
        f"- Validation loss: `{metrics.get('validation_loss', validation.get('total_loss', ''))}`",
        f"- Best validation loss / best checkpoint epoch: `{training.get('best_validation_loss', '')}` / `{training.get('best_epoch', '')}`",
        f"- Elapsed / stop reason: `{training.get('elapsed_seconds', '')}` s / `{training.get('stop_reason', '')}`",
    ]
    if arena:
        lines.extend([
            f"- Arena opponent / W-D-L: `{arena.get('opponent', '')}` / `{arena.get('wins', 0)}-{arena.get('draws', 0)}-{arena.get('losses', 0)}`",
            f"- Arena illegal / stale / budget: `{arena.get('illegal_action_count', 0)}` / `{arena.get('stale_failure_count', 0)}` / `{arena.get('budget_termination_count', 0)}`",
        ])
    lines.extend([
        f"- Checkpoint Artifact: `{names['checkpoint']}` (30 days)",
        f"- Dataset Artifact: `{names['dataset']}` ({dataset_retention_days(inputs.get('retain_dataset', False))} day(s))",
        "",
        f"下一次继续训练请设置 `resume_run_id={normalized_run_id}`，并把 `target_epochs` 提高到新的总目标。",
        "",
    ])
    markdown = "\n".join(lines)
    (output / "summary.md").write_text(markdown, encoding="utf-8")
    (output / "report.json").write_text(json.dumps(bundle, indent=2, sort_keys=True), encoding="utf-8")
    return bundle, markdown


def _add_run_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-id", default="")
    parser.add_argument("--artifacts-dir", type=Path, default=Path("artifacts"))
    parser.add_argument("--retain", action="store_true")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bounded CPU training workflow helpers")
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate", help="validate and print normalized workflow inputs")
    validate.add_argument("--games", type=int)
    validate.add_argument("--target-epochs", "--epochs", dest="target_epochs", type=int)
    validate.add_argument("--batch", "--batch-size", dest="batch", type=int)
    validate.add_argument("--arena-games", type=int)
    validate.add_argument("--max-actions", type=int)
    validate.add_argument("--seed", type=int)
    validate.add_argument("--teacher")
    validate.add_argument("--preset")
    validate.add_argument("--run-id", default="")
    validate.add_argument("--selfplay-wall-seconds", type=float)
    validate.add_argument("--train-wall-seconds", type=float)
    validate.add_argument("--arena-wall-seconds", type=float)
    validate.add_argument("--run-arena")
    validate.add_argument("--arena-opponent")
    validate.add_argument("--retain-dataset")
    validate.add_argument("--resume-run-id", default="")
    validate.add_argument("--resume-artifact", default="")

    check_resume = sub.add_parser("check-resume", help="fail closed on an incompatible checkpoint")
    check_resume.add_argument("--checkpoint", type=Path, required=True)
    check_resume.add_argument("--preset", required=True)

    report = sub.add_parser("report", help="build report artifact and Step Summary markdown")
    report.add_argument("--input-dir", type=Path, required=True)
    report.add_argument("--output-dir", type=Path, required=True)
    report.add_argument("--run-id", required=True)
    report.add_argument("--branch", required=True)
    report.add_argument("--sha", required=True)
    report.add_argument("--summary-file", type=Path)

    selfplay = sub.add_parser("selfplay", help="generate a bounded dataset artifact")
    _add_run_options(selfplay)
    selfplay.add_argument("--games", type=int, required=True)
    selfplay.add_argument("--teacher", default="mixed")
    selfplay.add_argument("--output", type=Path)
    selfplay.add_argument("--seed", type=int, default=42)
    selfplay.add_argument("--max-actions", type=int, default=200)
    selfplay.add_argument("--shard-size", type=int, default=256)
    selfplay.add_argument("--planner-states", type=int, default=256)
    selfplay.add_argument("--planner-actions", type=int, default=24)
    selfplay.add_argument("--planner-moves", type=int, default=32)
    selfplay.add_argument("--planner-seconds", type=float, default=0.5)
    selfplay.add_argument("--max-wall-seconds", type=float)
    selfplay.add_argument("--resume", action="store_true")
    selfplay.add_argument("--deterministic-planner", action="store_true")

    train = sub.add_parser("train", help="train a bounded checkpoint artifact")
    _add_run_options(train)
    train.add_argument("--dataset", type=Path)
    train.add_argument("--output", type=Path)
    train.add_argument("--target-epochs", "--epochs", dest="target_epochs", type=int, required=True)
    train.add_argument("--batch", "--batch-size", dest="batch", type=int, default=64)
    train.add_argument("--lr", type=float, default=3e-4)
    train.add_argument("--weight-decay", type=float, default=1e-4)
    train.add_argument("--device", choices=["cpu", "auto", "cuda"], default="cpu")
    train.add_argument("--seed", type=int, default=42)
    train.add_argument("--num-workers", type=int, default=0)
    train.add_argument("--resume", type=Path)
    train.add_argument("--save-every", type=int, default=1)
    train.add_argument("--grad-clip", type=float, default=1.0)
    train.add_argument("--mixed-precision", action=argparse.BooleanOptionalAction, default=False)
    train.add_argument("--validation-fraction", type=float, default=0.05)
    train.add_argument("--value-weight", type=float, default=0.5)
    train.add_argument("--preset", default="cloud-small")
    train.add_argument("--max-wall-seconds", type=float)

    arena = sub.add_parser("arena", help="evaluate a checkpoint and enforce the safety gate")
    _add_run_options(arena)
    arena.add_argument("--checkpoint", type=Path)
    arena.add_argument("--opponent", choices=["easy", "medium", "hard"], default="medium")
    arena.add_argument("--arena-games", "--games", dest="arena_games", type=int, required=True)
    arena.add_argument("--device", choices=["cpu", "auto", "cuda"], default="cpu")
    arena.add_argument("--seed", type=int, default=100)
    arena.add_argument("--max-actions", type=int, default=120)
    arena.add_argument("--planner-states", type=int, default=256)
    arena.add_argument("--planner-actions", type=int, default=16)
    arena.add_argument("--planner-moves", type=int, default=32)
    arena.add_argument("--planner-seconds", type=float, default=0.5)
    arena.add_argument("--max-wall-seconds", type=float)
    arena.add_argument("--report", type=Path)

    return parser


def _run_selfplay(args: argparse.Namespace) -> int:
    values = validate_cloud_inputs(
        games=args.games,
        max_actions=args.max_actions,
        seed=args.seed,
        teacher=args.teacher,
        run_id=args.run_id,
        selfplay_wall_seconds=args.max_wall_seconds,
    )
    paths = artifact_paths(args.artifacts_dir, values["run_id"])
    output = args.output or paths["dataset"]
    from src.training.selfplay import generate_selfplay

    result = generate_selfplay(
        games=values["games"],
        teacher=values["teacher"],
        output=output,
        seed=values["seed"],
        max_actions=values["max_actions"],
        planner_config=PlannerConfig(
            max_states=args.planner_states,
            max_actions=args.planner_actions,
            max_move_depth=args.planner_moves,
            max_seconds=args.planner_seconds,
        ),
        shard_size=args.shard_size,
        resume=args.resume,
        deterministic_planner=args.deterministic_planner,
        max_wall_seconds=values["selfplay_wall_seconds"],
    )
    result["artifact"] = str(Path(output).expanduser().resolve())
    result["retention_days"] = dataset_retention_days(args.retain)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _run_train(args: argparse.Namespace) -> int:
    values = validate_cloud_inputs(
        target_epochs=args.target_epochs,
        batch=args.batch,
        seed=args.seed,
        preset=args.preset,
        run_id=args.run_id,
        train_wall_seconds=args.max_wall_seconds,
    )
    paths = artifact_paths(args.artifacts_dir, values["run_id"])
    dataset = args.dataset or artifact_paths(args.artifacts_dir, values["run_id"])["dataset"]
    output = args.output or paths["checkpoint"]
    resume = args.resume
    if resume is not None:
        validate_cloud_resume(resume, preset=values["model_preset"])
    from src.training.train import train_local

    result = train_local(
        dataset_path=dataset,
        output=output,
        epochs=values["target_epochs"],
        batch_size=values["batch"],
        lr=args.lr,
        weight_decay=args.weight_decay,
        device_name=args.device,
        seed=values["seed"],
        num_workers=args.num_workers,
        resume=resume,
        save_every=args.save_every,
        grad_clip=args.grad_clip,
        mixed_precision=args.mixed_precision,
        validation_fraction=args.validation_fraction,
        value_weight=args.value_weight,
        preset=values["model_preset"],
        max_wall_seconds=values["train_wall_seconds"],
        target_epochs=values["target_epochs"],
        cloud_resume=resume is not None,
    )
    result["artifact"] = str(Path(output).expanduser().resolve())
    result["retention_days"] = dataset_retention_days(args.retain)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _run_arena(args: argparse.Namespace) -> int:
    games = validate_arena_games(args.arena_games)
    max_actions = validate_max_actions(args.max_actions)
    seed = validate_seed(args.seed)
    wall = validate_wall_seconds(
        cloud_budget("arena") if args.max_wall_seconds is None else args.max_wall_seconds,
        "arena",
    )
    paths = artifact_paths(args.artifacts_dir, args.run_id)
    checkpoint = args.checkpoint or paths["checkpoint"] / "best"
    if games == 0:
        result = _empty_arena_result(checkpoint, args.opponent, games)
    else:
        from src.ai.action_planner import ActionSearchBudget
        from src.training.arena import evaluate_arena

        result = evaluate_arena(
            checkpoint=checkpoint,
            opponent=args.opponent,
            games=games,
            device_name=args.device,
            seed=seed,
            max_actions=max_actions,
            budget=ActionSearchBudget(
                max_states=args.planner_states,
                max_actions=args.planner_actions,
                max_move_depth=args.planner_moves,
                max_seconds=args.planner_seconds,
            ),
            max_wall_seconds=wall,
            output="json",
        )
    report = args.report or paths["report"]
    report_path = _write_report(Path(report), result)
    arena_gate(result)
    result = dict(result)
    result["report"] = str(report_path)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            result = deterministic_config(
                games=args.games,
                target_epochs=args.target_epochs,
                batch=args.batch,
                arena_games=args.arena_games,
                max_actions=args.max_actions,
                seed=args.seed,
                teacher=args.teacher,
                preset=args.preset,
                run_id=args.run_id,
                selfplay_wall_seconds=args.selfplay_wall_seconds,
                train_wall_seconds=args.train_wall_seconds,
                arena_wall_seconds=args.arena_wall_seconds,
                run_arena=args.run_arena,
                arena_opponent=args.arena_opponent,
                retain_dataset=args.retain_dataset,
                resume_run_id=args.resume_run_id,
                resume_artifact=args.resume_artifact,
            )
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        if args.command == "check-resume":
            result = validate_cloud_resume(args.checkpoint, preset=args.preset)
            print(json.dumps(result["metadata"], indent=2, sort_keys=True))
            return 0
        if args.command == "report":
            _, markdown = build_report_bundle(
                args.input_dir,
                args.output_dir,
                run_id=args.run_id,
                branch=args.branch,
                sha=args.sha,
            )
            if args.summary_file:
                args.summary_file.parent.mkdir(parents=True, exist_ok=True)
                with args.summary_file.open("a", encoding="utf-8") as handle:
                    handle.write(markdown)
            print(markdown)
            return 0
        if args.command == "selfplay":
            return _run_selfplay(args)
        if args.command == "train":
            return _run_train(args)
        if args.command == "arena":
            return _run_arena(args)
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        parser.error(str(exc))
    return 2


__all__ = [
    "ARTIFACT_PREFIXES",
    "CLOUD_BUDGET_SECONDS",
    "CLOUD_PRESETS",
    "DEFAULT_ARENA_MAX_WALL_SECONDS",
    "DEFAULT_SELFPLAY_MAX_WALL_SECONDS",
    "DEFAULT_TRAIN_MAX_WALL_SECONDS",
    "arena_gate",
    "arena_passes",
    "artifact_name",
    "artifact_names",
    "artifact_paths",
    "build_cloud_config",
    "build_report_bundle",
    "check_arena_gate",
    "cloud_budget",
    "cloud_preset",
    "dataset_retention_days",
    "deterministic_config",
    "main",
    "required_cloud_resume_files",
    "resolve_preset",
    "retention_days",
    "retention_policy",
    "validate_arena_games",
    "validate_arena_gate",
    "validate_arena_result",
    "validate_batch",
    "validate_batch_size",
    "validate_bool",
    "validate_cloud_inputs",
    "validate_cloud_resume",
    "validate_epochs",
    "validate_games",
    "validate_max_actions",
    "validate_model_preset",
    "validate_preset",
    "validate_resume_artifact",
    "validate_resume_artifact_name",
    "validate_run_id",
    "validate_seed",
    "validate_target_epochs",
    "validate_teacher",
    "validate_wall_seconds",
]


if __name__ == "__main__":
    raise SystemExit(main())
