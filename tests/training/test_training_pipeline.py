from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("safetensors")

from src.ai.action_planner import (
    AIActionPlan,
    ActionPlanner,
    ActionPlanningError,
    ActionSearchBudget,
    apply_action_plan,
    engine_state_signature,
)
from src.engine.action import ActionRules
from src.engine.coordinates import BoardCoord, Square5D
from src.engine.engine import FiveDEngine
from src.engine.move_generator import Move
from src.engine.piece import Piece
from src.engine.timeline import Timeline
from src.training.arena import build_parser as build_arena_parser, evaluate_arena
from src.training.agent import NeuralPolicyValueAgent
from src.training.checkpoint import (
    CheckpointFormatError,
    load_checkpoint,
    load_resume_state,
    save_checkpoint,
)
from src.training.config import (
    DEFAULT_ARENA_PLANNER_SECONDS,
    DEFAULT_ENCODING,
    DEFAULT_PLANNER_CANDIDATE_LIMIT,
    DEFAULT_PLANNER_SECONDS,
    PlannerConfig,
    model_preset,
)
from src.training.dataset import (
    DatasetFormatError,
    DatasetWriter,
    ShardedDataset,
    TrainingSample,
    collate_training_batch,
)
from src.training.encoding import (
    EncodedCandidates,
    _move_feature_vector,
    encode_action,
    encode_candidates,
    encode_state,
)
from src.training.model import PolicyValueModel, policy_value_loss
from src.training.selfplay import build_parser as build_selfplay_parser, generate_selfplay
from src.training.utils import resolve_device, seed_everything
from src.utils.constants import ChessColor, PieceType


def _planner(engine, *, actions=4):
    return ActionPlanner(
        ActionSearchBudget(
            max_states=128,
            max_actions=actions,
            max_move_depth=8,
            max_seconds=None,
        )
    ).search(engine)


def _encoded(engine=None, candidate_count=2):
    engine = engine or FiveDEngine()
    result = _planner(engine, actions=max(2, candidate_count))
    assert len(result.candidates) >= candidate_count
    state = encode_state(engine, engine.current_turn_color)
    candidates = encode_candidates(engine, result.candidates[:candidate_count])
    return engine, result, state, candidates


def _training_sample(engine=None, candidate_count=2, selected=0, value_mask=True):
    engine, result, state, candidates = _encoded(engine, candidate_count)
    return TrainingSample(
        state=state,
        candidates=candidates,
        selected_index=selected,
        value_target=1.0 if value_mask else 0.0,
        value_mask=value_mask,
        player_color=1,
        game_id=0,
        action_index=0,
        termination_reason="checkmate" if value_mask else "max_actions",
    )


def test_state_encoding_is_deterministic():
    engine = FiveDEngine()
    first = encode_state(engine, ChessColor.WHITE)
    second = encode_state(engine, ChessColor.WHITE)
    assert np.array_equal(first.boards, second.boards)
    assert np.array_equal(first.board_meta, second.board_meta)
    assert np.array_equal(first.board_mask, second.board_mask)
    assert np.array_equal(first.global_features, second.global_features)


def test_state_encoding_preserves_signed_timeline():
    engine = FiveDEngine()
    original = engine.get_current_position()
    copied = original.copy()
    copied.timeline_id = -1
    engine.timeline_manager.timelines[-1] = Timeline(
        timeline_id=-1,
        owner=ChessColor.BLACK,
        positions={copied.time_point: copied},
    )
    engine.timeline_manager.refresh_activity()
    engine.current_action = ActionRules.begin(
        engine.current_turn_color, engine.timeline_manager.timelines
    )
    encoded = encode_state(engine, ChessColor.WHITE)
    active_meta = encoded.board_meta[encoded.board_mask]
    assert np.any(active_meta[:, 0] < 0.0)


def test_state_encoding_perspective_and_masks():
    engine = FiveDEngine()
    white = encode_state(engine, ChessColor.WHITE)
    black = encode_state(engine, ChessColor.BLACK)
    assert white.global_features[0] == 1.0
    assert black.global_features[0] == -1.0
    assert white.board_mask.shape == (DEFAULT_ENCODING.max_relevant_boards,)
    assert white.board_mask.any()


def test_action_encoding_contains_every_planned_move():
    engine = FiveDEngine()
    original = engine.get_current_position()
    copied = original.copy()
    copied.timeline_id = 1
    engine.timeline_manager.timelines[1] = Timeline(
        timeline_id=1,
        owner=ChessColor.WHITE,
        positions={copied.time_point: copied},
    )
    engine.timeline_manager.refresh_activity()
    engine.current_action = ActionRules.begin(
        engine.current_turn_color, engine.timeline_manager.timelines
    )
    result = _planner(engine, actions=1)
    assert result.candidates
    candidate = result.candidates[0]
    assert candidate
    moves, move_mask, action_global = encode_action(engine, candidate)
    assert int(move_mask.sum()) == len(candidate)
    assert action_global[0] > 0.0


def test_move_features_keep_branching_and_cross_timeline_flags():
    engine = FiveDEngine()
    piece = Piece(PieceType.QUEEN, ChessColor.WHITE)
    spatial = BoardCoord(0, 0, ChessColor.WHITE)
    historical = BoardCoord(0, 1, ChessColor.WHITE)
    branch_move = Move(
        piece,
        Square5D(spatial, 0, 0),
        Square5D(historical, 1, 1),
        is_branching=True,
        created_timeline=1,
    )
    branch_features = _move_feature_vector(branch_move, engine, DEFAULT_ENCODING)
    assert branch_features[18] == 1.0
    assert branch_features[20] > 0.0

    cross_move = Move(
        piece,
        Square5D(spatial, 0, 0),
        Square5D(BoardCoord(-1, 0, ChessColor.WHITE), 1, 1),
    )
    cross_features = _move_feature_vector(cross_move, engine, DEFAULT_ENCODING)
    assert cross_features[19] == 1.0
    assert cross_features[10] < 0.0


def test_dataset_round_trip_without_pickle(tmp_path):
    sample = _training_sample()
    root = tmp_path / "dataset"
    with DatasetWriter(
        root,
        generator_config={"teacher": "easy"},
        seed=1,
        shard_size=1,
    ) as writer:
        writer.add(sample)
        writer.finish_game()
    dataset = ShardedDataset(root)
    assert len(dataset) == 1
    loaded = dataset[0]
    assert loaded["selected_index"] == sample.selected_index
    assert loaded["action_moves"].shape[0] == sample.candidates.candidate_count
    assert loaded["value_mask"] is True


def test_dataset_schema_mismatch_fails_closed(tmp_path):
    sample = _training_sample()
    root = tmp_path / "dataset"
    with DatasetWriter(root, generator_config={}, seed=1, shard_size=1) as writer:
        writer.add(sample)
    metadata_path = root / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["state_encoding_version"] = 999
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(DatasetFormatError):
        ShardedDataset(root)


def test_variable_candidate_batch_and_forward_shapes():
    first = _training_sample(candidate_count=1)
    second = _training_sample(candidate_count=2, selected=1)
    def as_dict(sample):
        c = sample.candidates.candidate_count
        return {
            "state_boards": sample.state.boards,
            "board_meta": sample.state.board_meta,
            "board_mask": sample.state.board_mask,
            "state_global": sample.state.global_features,
            "action_moves": sample.candidates.moves[:c],
            "action_move_mask": sample.candidates.move_mask[:c],
            "action_global": sample.candidates.action_global[:c],
            "candidate_mask": sample.candidates.candidate_mask[:c],
            "selected_index": sample.selected_index,
            "value_target": sample.value_target,
            "value_mask": sample.value_mask,
        }
    batch = collate_training_batch([as_dict(first), as_dict(second)])
    model = PolicyValueModel(model_preset("tiny"))
    logits, value = model(
        batch["state_boards"], batch["board_meta"], batch["board_mask"],
        batch["state_global"], batch["action_moves"], batch["action_move_mask"],
        batch["action_global"], batch["candidate_mask"],
    )
    assert logits.shape == (2, 2)
    assert value.shape == (2,)
    assert logits[0, 1] < -1e20
    assert int(logits[0].argmax()) == 0


def test_tiny_batch_backward_changes_parameters():
    sample = _training_sample(candidate_count=2)
    c = sample.candidates.candidate_count
    raw = {
        "state_boards": sample.state.boards,
        "board_meta": sample.state.board_meta,
        "board_mask": sample.state.board_mask,
        "state_global": sample.state.global_features,
        "action_moves": sample.candidates.moves[:c],
        "action_move_mask": sample.candidates.move_mask[:c],
        "action_global": sample.candidates.action_global[:c],
        "candidate_mask": sample.candidates.candidate_mask[:c],
        "selected_index": 0,
        "value_target": 1.0,
        "value_mask": True,
    }
    batch = collate_training_batch([raw])
    model = PolicyValueModel(model_preset("tiny"))
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    before = next(model.parameters()).detach().clone()
    logits, value = model(
        batch["state_boards"], batch["board_meta"], batch["board_mask"],
        batch["state_global"], batch["action_moves"], batch["action_move_mask"],
        batch["action_global"], batch["candidate_mask"],
    )
    loss, metrics = policy_value_loss(
        logits, value, batch["selected_index"], batch["value_target"], batch["value_mask"]
    )
    assert torch.isfinite(loss)
    optimizer.zero_grad()
    loss.backward()
    optimizer.step()
    after = next(model.parameters()).detach()
    assert not torch.equal(before, after)
    assert torch.isfinite(metrics["policy_loss"])


def test_checkpoint_save_load_and_version_guard(tmp_path):
    seed_everything(7)
    model = PolicyValueModel(model_preset("tiny"))
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=2)
    checkpoint = tmp_path / "checkpoint"
    save_checkpoint(
        checkpoint,
        model,
        epoch=1,
        global_step=3,
        seed=7,
        best_validation_loss=0.5,
        training_config={"epochs": 2},
        optimizer=optimizer,
        scheduler=scheduler,
    )
    loaded, metadata = load_checkpoint(checkpoint)
    assert metadata["epoch"] == 1
    for original, restored in zip(model.parameters(), loaded.parameters()):
        assert torch.allclose(original, restored)

    metadata_path = checkpoint / "metadata.json"
    broken = json.loads(metadata_path.read_text(encoding="utf-8"))
    broken["action_encoding_version"] = 999
    metadata_path.write_text(json.dumps(broken), encoding="utf-8")
    with pytest.raises(CheckpointFormatError):
        load_checkpoint(checkpoint)


def test_resume_preserves_epoch_and_step(tmp_path):
    model = PolicyValueModel(model_preset("tiny"))
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=4)
    checkpoint = tmp_path / "checkpoint"
    save_checkpoint(
        checkpoint,
        model,
        epoch=2,
        global_step=9,
        seed=1,
        best_validation_loss=1.0,
        training_config={},
        optimizer=optimizer,
        scheduler=scheduler,
    )
    new_optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
    new_scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(new_optimizer, T_max=4)
    epoch, step = load_resume_state(
        checkpoint,
        optimizer=new_optimizer,
        scheduler=new_scheduler,
        device="cpu",
    )
    assert (epoch, step) == (2, 9)


def test_device_auto_falls_back_to_cpu(monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    assert resolve_device("auto").type == "cpu"


def test_planner_candidate_defaults_are_shared_across_training_parsers():
    assert PlannerConfig().max_actions == DEFAULT_PLANNER_CANDIDATE_LIMIT
    selfplay_args = build_selfplay_parser().parse_args(["--output", "dataset"])
    arena_args = build_arena_parser().parse_args(["--checkpoint", "checkpoint"])
    assert selfplay_args.planner_actions == DEFAULT_PLANNER_CANDIDATE_LIMIT
    assert arena_args.planner_actions == DEFAULT_PLANNER_CANDIDATE_LIMIT
    assert selfplay_args.planner_seconds == DEFAULT_PLANNER_SECONDS
    assert arena_args.planner_seconds == DEFAULT_ARENA_PLANNER_SECONDS


@pytest.mark.parametrize("value", [0, -1, "nan", "inf", 60.1, "not-a-number"])
def test_arena_parser_rejects_invalid_planner_seconds(value):
    with pytest.raises(SystemExit):
        build_arena_parser().parse_args([
            "--checkpoint", "checkpoint", "--planner-seconds", str(value)
        ])


def test_arena_cli_passes_explicit_planner_budget(monkeypatch):
    captured = {}

    def fake_evaluate_arena(**kwargs):
        captured.update(kwargs)
        return {
            "illegal_action_count": 0,
            "stale_failure_count": 0,
            "unexpected_failure_count": 0,
        }

    monkeypatch.setattr("src.training.arena.evaluate_arena", fake_evaluate_arena)
    from src.training.arena import main

    assert main([
        "--checkpoint", "checkpoint", "--games", "1", "--device", "cpu",
        "--planner-seconds", "2", "--output", "json",
    ]) == 0
    assert captured["budget"].max_actions == DEFAULT_PLANNER_CANDIDATE_LIMIT
    assert captured["budget"].max_seconds == 2.0


@pytest.mark.parametrize("seconds", [None, 0, -1, float("nan"), float("inf"), 60.1])
def test_evaluate_arena_rejects_invalid_supplied_planner_budget(seconds):
    with pytest.raises(ValueError):
        evaluate_arena(
            checkpoint="missing-checkpoint",
            opponent="easy",
            games=1,
            device_name="cpu",
            seed=1,
            budget=ActionSearchBudget(max_seconds=seconds),
        )


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA not available")
def test_cuda_device_when_available():
    assert resolve_device("cuda").type == "cuda"


def test_same_seed_selfplay_is_reproducible(tmp_path):
    config = PlannerConfig(max_states=64, max_actions=4, max_move_depth=4, max_seconds=0.1)
    roots = [tmp_path / "a", tmp_path / "b"]
    for root in roots:
        generate_selfplay(
            games=1,
            teacher="easy",
            output=root,
            seed=11,
            max_actions=1,
            planner_config=config,
            shard_size=8,
            deterministic_planner=True,
        )
    first = ShardedDataset(roots[0])[0]
    second = ShardedDataset(roots[1])[0]
    assert first["selected_index"] == second["selected_index"]
    assert np.array_equal(first["action_moves"], second["action_moves"])


def test_truncated_episode_masks_value_target(tmp_path):
    root = tmp_path / "dataset"
    generate_selfplay(
        games=1,
        teacher="easy",
        output=root,
        seed=5,
        max_actions=1,
        planner_config=PlannerConfig(max_states=64, max_actions=4, max_move_depth=4, max_seconds=0.1),
        shard_size=8,
        deterministic_planner=True,
    )
    sample = ShardedDataset(root)[0]
    assert sample["termination_reason"] == "max_actions"
    assert sample["value_mask"] is False


def test_planner_candidates_and_selected_plan_remain_canonical():
    engine, result, state, candidates = _encoded(candidate_count=2)
    assert candidates.candidate_count == 2
    plan = AIActionPlan(
        color=engine.current_turn_color,
        moves=result.candidates[0],
        start_signature=engine_state_signature(engine),
    )
    applied = apply_action_plan(engine, plan)
    assert applied
    assert len(engine.action_history) == 1


def test_arena_tiny_game_has_no_illegal_actions(tmp_path):
    model = PolicyValueModel(model_preset("tiny"))
    checkpoint = tmp_path / "checkpoint"
    save_checkpoint(
        checkpoint,
        model,
        epoch=0,
        global_step=0,
        seed=1,
        best_validation_loss=None,
        training_config={},
    )
    result = evaluate_arena(
        checkpoint=checkpoint,
        opponent="easy",
        games=1,
        device_name="cpu",
        seed=9,
        max_actions=1,
        budget=ActionSearchBudget(
            max_states=64, max_actions=4, max_move_depth=4, max_seconds=0.25
        ),
    )
    assert result["illegal_action_count"] == 0
    assert result["stale_failure_count"] == 0


def test_arena_incomplete_planning_failure_is_budget_termination(tmp_path, monkeypatch):
    model = PolicyValueModel(model_preset("tiny"))
    checkpoint = tmp_path / "checkpoint"
    save_checkpoint(
        checkpoint,
        model,
        epoch=0,
        global_step=0,
        seed=1,
        best_validation_loss=None,
        training_config={},
    )

    def fail_to_plan(self, engine):
        raise ActionPlanningError("time_budget", incomplete=True)

    monkeypatch.setattr(NeuralPolicyValueAgent, "plan_action", fail_to_plan)
    result = evaluate_arena(
        checkpoint=checkpoint,
        opponent="easy",
        games=1,
        device_name="cpu",
        seed=9,
        max_actions=1,
        budget=ActionSearchBudget(
            max_states=64, max_actions=4, max_move_depth=4, max_seconds=0.25
        ),
    )
    assert result["illegal_action_count"] == 0
    assert result["stale_failure_count"] == 0
    assert result["budget_termination_count"] == 1
    assert result["planning_failure_count"] == 1
    assert result["unexpected_failure_count"] == 0
    assert result["first_failure"]["game_id"] == 1
    assert result["first_failure"]["game_index"] == 0
    assert result["first_failure"]["candidate_count"] == 0
    assert result["first_failure"]["chosen_index"] is None
    assert result["first_failure"]["plan_move_count"] is None
    assert result["first_failure"]["failure_stage"] == "planning"
    assert result["first_failure"]["exception_class"] == "ActionPlanningError"
    assert result["first_failure"]["planning_reason"] == "time_budget"
    assert result["first_failure"]["planning_incomplete"] is True
    assert "fail_to_plan" in result["first_failure"]["traceback"]


def test_small_model_is_consumer_scale():
    model = PolicyValueModel(model_preset("small"))
    assert 100_000 < model.parameter_count < 5_000_000