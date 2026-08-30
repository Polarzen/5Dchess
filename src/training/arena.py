"""Arena evaluation for neural policy checkpoints against canonical baselines."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from src.ai.action_planner import ActionSearchBudget, apply_action_plan
from src.ai.alpha_beta import AlphaBetaAI
from src.ai.hard_ai import HardAI
from src.ai.random_ai import RandomAI
from src.engine.engine import FiveDEngine
from src.training.agent import NeuralPolicyValueAgent
from src.training.checkpoint import load_checkpoint
from src.training.utils import print_device_report, resolve_device, seed_everything
from src.utils.constants import ChessColor, GameState


def _baseline(name: str, color: ChessColor, seed: int, budget: ActionSearchBudget):
    if name == "easy":
        return RandomAI(color, seed=seed, budget=budget)
    if name == "medium":
        return AlphaBetaAI(color, search_depth=1, budget=budget)
    if name == "hard":
        return HardAI(color, search_depth=2, budget=budget)
    raise ValueError("opponent must be easy, medium, or hard")


def evaluate_arena(
    *,
    checkpoint: str | Path,
    opponent: str,
    games: int,
    device_name: str,
    seed: int,
    max_actions: int = 120,
    budget: ActionSearchBudget | None = None,
) -> dict:
    if games < 1:
        raise ValueError("games must be at least 1")
    seed_everything(seed)
    device = resolve_device(device_name)
    print_device_report(device_name)
    model, metadata = load_checkpoint(checkpoint, device=device)
    budget = budget or ActionSearchBudget(
        max_states=256, max_actions=16, max_move_depth=32, max_seconds=0.5
    )

    wins = draws = losses = 0
    illegal = stale_failures = budget_terminations = 0
    action_counts: list[int] = []
    inference_times: list[float] = []

    for game_index in range(games):
        neural_color = ChessColor.WHITE if game_index % 2 == 0 else ChessColor.BLACK
        engine = FiveDEngine()
        neural = NeuralPolicyValueAgent(
            model,
            neural_color,
            device=device,
            budget=budget,
        )
        baseline = _baseline(
            opponent,
            neural_color.opposite(),
            seed + game_index + 1,
            budget,
        )
        completed_actions = 0
        failed = False
        for _ in range(max_actions):
            if engine.game_state != GameState.PLAYING:
                break
            try:
                if engine.current_turn_color == neural_color:
                    plan = neural.plan_action(engine)
                    if neural.last_decision is not None:
                        inference_times.append(neural.last_decision.inference_ms)
                else:
                    plan = baseline.plan_action(engine)
                apply_action_plan(engine, plan)
                completed_actions += 1
            except Exception as exc:
                text = str(exc).lower()
                if "stale" in text or "state changed" in text:
                    stale_failures += 1
                else:
                    illegal += 1
                failed = True
                break
        else:
            budget_terminations += 1

        action_counts.append(completed_actions)
        if failed:
            losses += 1
        elif engine.game_state == GameState.CHECKMATE:
            winner = engine.current_turn_color.opposite()
            if winner == neural_color:
                wins += 1
            else:
                losses += 1
        elif engine.game_state in {GameState.STALEMATE, GameState.DRAW}:
            draws += 1
        else:
            # A bounded arena that reaches max_actions is an explicit draw-like
            # evaluation termination, not a fabricated win/loss.
            draws += 1

        print(
            f"arena game {game_index + 1}/{games}: neural={neural_color.value} "
            f"actions={completed_actions} state={engine.game_state.name}"
        )

    total = games
    result = {
        "checkpoint": str(Path(checkpoint).resolve()),
        "opponent": opponent,
        "games": total,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "win_rate": wins / total,
        "draw_rate": draws / total,
        "average_actions": sum(action_counts) / max(1, len(action_counts)),
        "illegal_action_count": illegal,
        "stale_failure_count": stale_failures,
        "budget_termination_count": budget_terminations,
        "average_inference_ms": (
            sum(inference_times) / len(inference_times) if inference_times else 0.0
        ),
        "checkpoint_epoch": metadata.get("epoch"),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate neural 5D Action policy in an arena")
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--opponent", choices=["easy", "medium", "hard"], default="medium")
    parser.add_argument("--games", type=int, default=20)
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    parser.add_argument("--seed", type=int, default=100)
    parser.add_argument("--max-actions", type=int, default=120)
    parser.add_argument("--planner-states", type=int, default=256)
    parser.add_argument("--planner-actions", type=int, default=16)
    parser.add_argument("--planner-moves", type=int, default=32)
    parser.add_argument("--planner-seconds", type=float, default=0.5)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = evaluate_arena(
        checkpoint=args.checkpoint,
        opponent=args.opponent,
        games=args.games,
        device_name=args.device,
        seed=args.seed,
        max_actions=args.max_actions,
        budget=ActionSearchBudget(
            max_states=args.planner_states,
            max_actions=args.planner_actions,
            max_move_depth=args.planner_moves,
            max_seconds=args.planner_seconds,
        ),
    )
    return 1 if (result["illegal_action_count"] or result["stale_failure_count"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
