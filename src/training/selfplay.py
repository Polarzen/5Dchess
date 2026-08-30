"""Canonical bounded self-play generator for Local AI Training v2."""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import random
import time
from typing import Sequence

from src.ai.action_planner import (
    AIActionPlan,
    ActionPlanner,
    ActionPlanningError,
    ActionSearchBudget,
    apply_action_plan,
    engine_state_signature,
)
from src.ai.evaluator import Evaluator
from src.engine.engine import FiveDEngine
from src.training.config import PlannerConfig
from src.training.dataset import DatasetWriter, TrainingSample
from src.training.encoding import EncodedCandidates, EncodedState, encode_candidates, encode_state
from src.training.utils import seed_everything, write_json
from src.utils.constants import ChessColor, GameState


@dataclass(slots=True)
class PendingSample:
    state: EncodedState
    candidates: EncodedCandidates
    selected_index: int
    player: ChessColor
    action_index: int


def _budget(config: PlannerConfig, *, deterministic: bool = False) -> ActionSearchBudget:
    return ActionSearchBudget(
        max_states=config.max_states,
        max_actions=config.max_actions,
        max_move_depth=config.max_move_depth,
        max_seconds=None if deterministic else config.max_seconds,
    )


def _candidate_plan(engine, specs) -> AIActionPlan:
    return AIActionPlan(
        color=engine.current_turn_color,
        moves=tuple(specs),
        start_signature=engine_state_signature(engine),
    )


def _evaluate_after(engine, specs, perspective: ChessColor) -> tuple[float, object]:
    child = deepcopy(engine)
    apply_action_plan(child, _candidate_plan(child, specs))
    if child.game_state == GameState.CHECKMATE:
        # submit_action() has already flipped to the losing side.
        return (100000.0 if child.current_turn_color != perspective else -100000.0), child
    if child.game_state in {GameState.STALEMATE, GameState.DRAW}:
        return 0.0, child
    return Evaluator().evaluate_engine(child, perspective), child


def _select_medium(engine, candidates) -> int:
    color = engine.current_turn_color
    scored = [(_evaluate_after(engine, specs, color)[0], index) for index, specs in enumerate(candidates)]
    return max(scored, key=lambda item: (item[0], -item[1]))[1]


def _select_hard(engine, candidates, planner_config: PlannerConfig) -> int:
    """Deterministic one-opponent-Action teacher over already legal root candidates."""
    color = engine.current_turn_color
    response_budget = ActionSearchBudget(
        max_states=min(planner_config.max_states, 128),
        max_actions=min(planner_config.max_actions, 8),
        max_move_depth=planner_config.max_move_depth,
        max_seconds=None,
    )
    root_scores: list[tuple[float, int]] = []
    evaluator = Evaluator()
    for root_index, specs in enumerate(candidates):
        immediate, child = _evaluate_after(engine, specs, color)
        if child.game_state != GameState.PLAYING:
            root_scores.append((immediate, root_index))
            continue
        responses = ActionPlanner(response_budget).search(child)
        if not responses.candidates:
            root_scores.append((evaluator.evaluate_engine(child, color), root_index))
            continue
        worst = float("inf")
        for response in responses.candidates:
            response_child = deepcopy(child)
            try:
                apply_action_plan(response_child, _candidate_plan(response_child, response))
            except Exception:
                continue
            worst = min(worst, evaluator.evaluate_engine(response_child, color))
        if worst == float("inf"):
            worst = evaluator.evaluate_engine(child, color)
        root_scores.append((worst, root_index))
    return max(root_scores, key=lambda item: (item[0], -item[1]))[1]


def choose_teacher_index(
    engine,
    candidates,
    teacher: str,
    rng: random.Random,
    planner_config: PlannerConfig,
) -> tuple[int, str]:
    teacher = teacher.lower()
    actual = teacher
    if teacher == "mixed":
        roll = rng.random()
        actual = "easy" if roll < 0.50 else "medium" if roll < 0.90 else "hard"
    if actual == "easy":
        return rng.randrange(len(candidates)), actual
    if actual == "medium":
        return _select_medium(engine, candidates), actual
    if actual == "hard":
        return _select_hard(engine, candidates, planner_config), actual
    raise ValueError("teacher must be easy, medium, hard, or mixed")


def _final_targets(engine, termination_reason: str):
    if termination_reason == "checkmate":
        winner = engine.current_turn_color.opposite()
        return winner, True
    if termination_reason in {"stalemate", "draw"}:
        return None, True
    return None, False


def _termination_from_engine(engine) -> str | None:
    if engine.game_state == GameState.CHECKMATE:
        return "checkmate"
    if engine.game_state == GameState.STALEMATE:
        return "stalemate"
    if engine.game_state == GameState.DRAW:
        return "draw"
    if engine.game_state != GameState.PLAYING:
        return "error"
    return None


def generate_selfplay(
    *,
    games: int,
    teacher: str,
    output: str | Path,
    seed: int,
    max_actions: int,
    planner_config: PlannerConfig,
    shard_size: int = 256,
    resume: bool = False,
    deterministic_planner: bool = False,
    max_wall_seconds: float | None = None,
) -> dict:
    if isinstance(games, bool) or not isinstance(games, int) or not 1 <= games <= 5000:
        raise ValueError("games must be an integer in the range 1..5000")
    if isinstance(max_actions, bool) or not isinstance(max_actions, int) or not 1 <= max_actions <= 1000:
        raise ValueError("max_actions must be an integer in the range 1..1000")
    teacher = str(teacher).lower().strip()
    if teacher not in {"easy", "medium", "hard", "mixed"}:
        raise ValueError("teacher must be easy, medium, hard, or mixed")
    if max_wall_seconds is not None:
        if isinstance(max_wall_seconds, bool) or not isinstance(max_wall_seconds, (int, float)):
            raise ValueError("max_wall_seconds must be a non-negative number or null")
        if max_wall_seconds < 0:
            raise ValueError("max_wall_seconds must be non-negative")
    # NumPy's seed API is unsigned while the cloud contract deliberately
    # accepts signed decimal seeds.  Preserve the user-visible seed in
    # metadata but map it deterministically for the underlying RNGs.
    seed_everything(int(seed) % (2**32))
    rng = random.Random(seed)
    generator_config = {
        "games_requested": int(games),
        "teacher": teacher,
        "max_actions": int(max_actions),
        "planner": planner_config.to_dict(),
        "deterministic_planner": bool(deterministic_planner),
    }
    if max_wall_seconds is not None:
        generator_config["max_wall_seconds"] = float(max_wall_seconds)
    writer = DatasetWriter(
        output,
        generator_config=generator_config,
        seed=seed,
        shard_size=shard_size,
        resume=resume,
    )
    start_game_id = writer.game_count
    teacher_counts = {"easy": 0, "medium": 0, "hard": 0}
    termination_counts: dict[str, int] = {}
    started = time.monotonic()
    games_generated = 0
    stop_reason = "completed"
    try:
        for local_game in range(games):
            game_id = start_game_id + local_game
            engine = FiveDEngine()
            pending: list[PendingSample] = []
            termination_reason = "max_actions"
            for action_index in range(max_actions):
                if engine.game_state != GameState.PLAYING:
                    termination_reason = _termination_from_engine(engine) or "error"
                    break
                result = ActionPlanner(
                    _budget(planner_config, deterministic=deterministic_planner)
                ).search(engine)
                if not result.candidates:
                    termination_reason = (
                        "planner_budget" if result.termination_reason else "error"
                    )
                    break
                player = engine.current_turn_color
                state = encode_state(engine, player)
                encoded_candidates = encode_candidates(engine, result.candidates)
                selected_index, actual_teacher = choose_teacher_index(
                    engine,
                    result.candidates,
                    teacher,
                    rng,
                    planner_config,
                )
                teacher_counts[actual_teacher] += 1
                pending.append(
                    PendingSample(
                        state=state,
                        candidates=encoded_candidates,
                        selected_index=selected_index,
                        player=player,
                        action_index=action_index,
                    )
                )
                try:
                    apply_action_plan(
                        engine,
                        _candidate_plan(engine, result.candidates[selected_index]),
                    )
                except Exception:
                    termination_reason = "error"
                    break
                terminal = _termination_from_engine(engine)
                if terminal is not None:
                    termination_reason = terminal
                    break

            winner, value_is_supervised = _final_targets(engine, termination_reason)
            for sample in pending:
                if value_is_supervised:
                    if winner is None:
                        target = 0.0
                    else:
                        target = 1.0 if sample.player == winner else -1.0
                else:
                    target = 0.0
                writer.add(
                    TrainingSample(
                        state=sample.state,
                        candidates=sample.candidates,
                        selected_index=sample.selected_index,
                        value_target=target,
                        value_mask=value_is_supervised,
                        player_color=1 if sample.player == ChessColor.WHITE else -1,
                        game_id=game_id,
                        action_index=sample.action_index,
                        termination_reason=termination_reason,
                    )
                )
            writer.finish_game()
            games_generated += 1
            termination_counts[termination_reason] = termination_counts.get(termination_reason, 0) + 1
            print(
                f"self-play game {local_game + 1}/{games}: "
                f"actions={len(pending)} termination={termination_reason}"
            )
            # A game is the smallest safe self-play commit unit.  Do not
            # interrupt an in-progress engine episode; DatasetWriter has now
            # recorded the completed game and its metadata before we stop.
            if (
                max_wall_seconds is not None
                and time.monotonic() - started >= float(max_wall_seconds)
                and games_generated < games
            ):
                stop_reason = "wall_time_budget"
                break
    finally:
        writer.close()

    elapsed = max(0.0, time.monotonic() - started)
    # Keep the status in the dataset itself so a workflow can inspect an
    # artifact without trusting stdout.  This write happens after close(),
    # which means pending shard data and the status are both durable.
    writer.metadata["games_requested"] = int(games)
    writer.metadata["games_generated"] = int(games_generated)
    writer.metadata["requested_games"] = int(games)
    writer.metadata["generated_games"] = int(games_generated)
    writer.metadata["samples"] = int(writer.metadata["sample_count"])
    writer.metadata["generation_stop_reason"] = stop_reason
    writer.metadata["generation_elapsed_seconds"] = float(elapsed)
    write_json(writer.metadata_path, writer.metadata)

    result = {
        "output": str(Path(output)),
        "games_requested": int(games),
        "games_generated": int(games_generated),
        "sample_count": writer.metadata["sample_count"],
        "samples": writer.metadata["sample_count"],
        "teacher_counts": teacher_counts,
        "termination_counts": termination_counts,
        "elapsed_seconds": float(elapsed),
        "stop_reason": stop_reason,
        "generation_stop_reason": stop_reason,
    }
    print(result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate canonical 5D self-play training shards")
    parser.add_argument("--games", type=int, default=100)
    parser.add_argument("--teacher", choices=["easy", "medium", "hard", "mixed"], default="mixed")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-actions", type=int, default=200)
    parser.add_argument("--shard-size", type=int, default=256)
    parser.add_argument("--planner-states", type=int, default=256)
    parser.add_argument("--planner-actions", type=int, default=24)
    parser.add_argument("--planner-moves", type=int, default=32)
    parser.add_argument("--planner-seconds", type=float, default=0.5)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--max-wall-seconds",
        type=float,
        default=None,
        help="stop after the current completed game (default: unlimited)",
    )
    parser.add_argument(
        "--deterministic-planner",
        action="store_true",
        help="disable wall-clock candidate cutoff and use only deterministic count budgets",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    planner = PlannerConfig(
        max_states=args.planner_states,
        max_actions=args.planner_actions,
        max_move_depth=args.planner_moves,
        max_seconds=args.planner_seconds,
    )
    try:
        generate_selfplay(
            games=args.games,
            teacher=args.teacher,
            output=args.output,
            seed=args.seed,
            max_actions=args.max_actions,
            planner_config=planner,
            shard_size=args.shard_size,
            resume=args.resume,
            deterministic_planner=args.deterministic_planner,
            max_wall_seconds=args.max_wall_seconds,
        )
    except KeyboardInterrupt:
        print("self-play interrupted; completed shards remain readable")
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
