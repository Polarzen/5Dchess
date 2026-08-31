from __future__ import annotations

import json
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("safetensors")

from src.training.checkpoint import save_checkpoint
from src.training.cloud import (
    arena_gate,
    artifact_names,
    build_cloud_config,
    cloud_preset,
    dataset_retention_days,
    retention_policy,
    validate_cloud_inputs,
    validate_cloud_resume,
    validate_run_id,
)
from src.training.config import PlannerConfig, model_preset
from src.training.model import PolicyValueModel
from src.training.selfplay import generate_selfplay
from src.training.train import train_local


@pytest.mark.parametrize(
    ("field", "bad"),
    [("games", 0), ("games", 5001), ("target_epochs", 0),
     ("target_epochs", 501), ("batch_size", 0), ("batch_size", 2049),
     ("arena_games", -1), ("arena_games", 501), ("max_actions", 0),
     ("max_actions", 1001)],
)
def test_cloud_numeric_bounds(field, bad):
    with pytest.raises(ValueError):
        validate_cloud_inputs(**{field: bad})


def test_cloud_enums_artifacts_retention_and_run_ids():
    with pytest.raises(ValueError):
        validate_cloud_inputs(teacher="oracle")
    with pytest.raises(ValueError):
        validate_cloud_inputs(preset="huge")
    with pytest.raises(ValueError):
        validate_run_id("../123")
    assert artifact_names("123") == {
        "dataset": "local-ai-dataset-123",
        "checkpoint": "local-ai-checkpoint-123",
        "report": "local-ai-report-123",
    }
    assert dataset_retention_days(False) == 1
    assert dataset_retention_days(True) == 7
    assert retention_policy(True) == {"dataset": 7, "checkpoint": 30, "report": 30}


def test_cloud_presets_and_config_are_deterministic():
    assert cloud_preset("cloud-tiny") == "tiny"
    assert cloud_preset("cloud-small") == "small"
    assert cloud_preset("cloud-long") == "medium"
    args = dict(games=2, target_epochs=3, batch_size=2, arena_games=2,
                max_actions=4, seed="-7", teacher="easy", preset="tiny", run_id="99")
    assert build_cloud_config(**args) == build_cloud_config(**args)


def test_arena_gate_only_rejects_illegal_or_stale():
    assert arena_gate({"illegal_action_count": 0, "stale_failure_count": 0,
                       "budget_termination_count": 4})
    with pytest.raises(RuntimeError):
        arena_gate({"illegal_action_count": 1, "stale_failure_count": 0})
    with pytest.raises(RuntimeError):
        arena_gate({"illegal_action_count": 0, "stale_failure_count": 1})


def test_arena_gate_rejects_unexpected_but_allows_planning_budget():
    assert arena_gate({
        "illegal_action_count": 0,
        "stale_failure_count": 0,
        "budget_termination_count": 1,
        "planning_failure_count": 1,
        "unexpected_failure_count": 0,
    })
    with pytest.raises(RuntimeError):
        arena_gate({
            "illegal_action_count": 0,
            "stale_failure_count": 0,
            "budget_termination_count": 0,
            "planning_failure_count": 0,
            "unexpected_failure_count": 1,
        })


def _checkpoint(path: Path, *, preset: str = "tiny", epoch: int = 1, step: int = 2):
    model = PolicyValueModel(model_preset(preset))
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=3)
    save_checkpoint(path, model, epoch=epoch, global_step=step, seed=1,
                    best_validation_loss=0.5, training_config={"preset": preset},
                    optimizer=optimizer, scheduler=scheduler)
    return path


def test_cloud_resume_fails_closed_and_checks_model(tmp_path):
    checkpoint = _checkpoint(tmp_path / "checkpoint")
    assert validate_cloud_resume(checkpoint, preset="tiny")["metadata"]["epoch"] == 1
    with pytest.raises(ValueError, match="does not match"):
        validate_cloud_resume(checkpoint, preset="small")
    (checkpoint / "resume_state.pt").unlink()
    with pytest.raises(ValueError, match="missing required"):
        validate_cloud_resume(checkpoint, preset="tiny")


def _tiny_dataset(path: Path, games: int = 1):
    return generate_selfplay(
        games=games,
        teacher="easy",
        output=path,
        seed=13,
        max_actions=1,
        planner_config=PlannerConfig(max_states=64, max_actions=4,
                                     max_move_depth=4, max_seconds=0.1),
        shard_size=8,
        deterministic_planner=True,
    )


def test_selfplay_wall_budget_finishes_one_game_and_records_reason(tmp_path):
    root = tmp_path / "dataset"
    result = generate_selfplay(
        games=2, teacher="easy", output=root, seed=3, max_actions=1,
        planner_config=PlannerConfig(max_states=64, max_actions=4,
                                     max_move_depth=4, max_seconds=0.1),
        shard_size=8, deterministic_planner=True, max_wall_seconds=0,
    )
    metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    assert result["games_generated"] == 1
    assert result["stop_reason"] == "wall_time_budget"
    assert metadata["generation_stop_reason"] == "wall_time_budget"


def _train(dataset: Path, output: Path, *, epochs: int, resume=None, wall=None):
    return train_local(
        dataset_path=dataset, output=output, epochs=epochs, batch_size=2,
        lr=1e-3, weight_decay=0.0, device_name="cpu", seed=17,
        num_workers=0, resume=resume, save_every=1, grad_clip=1.0,
        mixed_precision=False, validation_fraction=0.0, value_weight=0.5,
        preset="tiny", max_wall_seconds=wall,
    )


def test_train_wall_stop_publishes_portable_best_and_last(tmp_path):
    dataset = tmp_path / "dataset"
    _tiny_dataset(dataset)
    output = tmp_path / "run"
    result = _train(dataset, output, epochs=2, wall=0)
    assert result["stop_reason"] == "wall_time_budget"
    assert result["end_epoch"] == 0
    for name in ("best", "last"):
        assert (output / name / "model.safetensors").is_file()
        assert (output / name / "resume_state.pt").is_file()
    assert (output / "run-config.json").is_file()
    assert (output / "training-summary.json").is_file()
    run_config = json.loads((output / "run-config.json").read_text(encoding="utf-8"))
    assert "dataset" not in json.dumps(run_config).lower()


def test_train_resume_uses_total_target_and_increments_step(tmp_path):
    dataset = tmp_path / "dataset"
    _tiny_dataset(dataset)
    first = _train(dataset, tmp_path / "first", epochs=1)
    second = _train(dataset, tmp_path / "second", epochs=2,
                    resume=tmp_path / "first" / "last")
    assert (first["start_epoch"], first["end_epoch"]) == (0, 1)
    assert (second["start_epoch"], second["end_epoch"]) == (1, 2)
    assert second["start_step"] == first["end_step"]
    assert second["end_step"] > second["start_step"]


def test_cloud_workflow_is_manual_bounded_and_read_only():
    text = Path(".github/workflows/local-ai-train.yml").read_text(encoding="utf-8")
    required = ["workflow_dispatch:", "timeout-minutes:", "contents: read",
                "actions: read", "cancel-in-progress: false", "actions/upload-artifact@v4",
                "actions/download-artifact@v4", "src.training.selfplay",
                "src.training.train", "src.training.arena", "--result-json",
                "GITHUB_STEP_SUMMARY"]
    for token in required:
        assert token in text
    assert "contents: write" not in text
    assert "pull-requests: write" not in text
    assert "schedule:" not in text
    assert "git push" not in text
    trigger_prefix = text.split("permissions:", 1)[0]
    assert "\n  push:" not in trigger_prefix
    assert "\n  pull_request:" not in trigger_prefix
