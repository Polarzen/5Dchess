"""Arena evaluation for neural policy checkpoints against canonical baselines."""
from __future__ import annotations

import argparse
from enum import Enum
import hashlib
import json
from pathlib import Path
import time
import traceback
from typing import Any, Mapping, Sequence

from src.ai.action_planner import (
    ActionApplicationError,
    ActionPlanningError,
    ActionSearchBudget,
    InvalidActionPlanError,
    StaleActionPlanError,
    apply_action_plan,
    engine_state_signature,
)
from src.ai.alpha_beta import AlphaBetaAI
from src.ai.hard_ai import HardAI
from src.ai.random_ai import RandomAI
from src.engine.engine import FiveDEngine
from src.engine.outcome_rules import OutcomeKind, OutcomeRules
from src.training.agent import NeuralPolicyValueAgent
from src.training.checkpoint import load_checkpoint
from src.training.config import (
    DEFAULT_ARENA_PLANNER_SECONDS,
    DEFAULT_PLANNER_CANDIDATE_LIMIT,
    parse_arena_planner_seconds,
    validate_arena_planner_seconds,
)
from src.training.utils import print_device_report, resolve_device, seed_everything, write_json
from src.utils.constants import ChessColor, GameState


def _jsonable(value: Any) -> Any:
    """Convert forensic values into plain JSON-compatible values."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _jsonable(item())
        except Exception:
            pass
    return str(value)


def _signature_sha256(value: Any) -> str | None:
    try:
        payload = json.dumps(
            _jsonable(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except Exception:
        return None
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _state_signature_sha256(engine: FiveDEngine) -> str | None:
    return _signature_sha256(engine_state_signature(engine))


def _square_forensic(square: Any) -> dict[str, Any] | None:
    board = getattr(square, "board", None)
    if board is None:
        return None
    return {
        "timeline": _jsonable(getattr(board, "timeline", None)),
        "turn": _jsonable(getattr(board, "turn", None)),
        "side": _jsonable(getattr(board, "side", None)),
        "x": _jsonable(getattr(square, "x", None)),
        "y": _jsonable(getattr(square, "y", None)),
    }


def _canonical_move_specs(plan: Any) -> tuple[int | None, list[dict[str, Any]]]:
    if plan is None:
        return None, []
    try:
        moves = tuple(plan.moves)
    except Exception:
        return None, []
    specs: list[dict[str, Any]] = []
    for index, move in enumerate(moves):
        source = _square_forensic(getattr(move, "source", None))
        destination = _square_forensic(getattr(move, "destination", None))
        specs.append({
            "index": index,
            "source": source,
            "destination": destination,
            "promotion": _jsonable(getattr(move, "promotion", None)),
        })
    return len(moves), specs


def _failure_record(
    *,
    engine: FiveDEngine,
    game_index: int,
    action_index: int,
    plan: Any,
    failure_stage: str,
    exc: Exception,
    traceback_text: str,
) -> dict[str, Any]:
    move_count, move_specs = _canonical_move_specs(plan)
    metadata: Mapping[str, Any] = {}
    if plan is not None:
        candidate_metadata = getattr(plan, "metadata", {})
        if isinstance(candidate_metadata, Mapping):
            metadata = candidate_metadata
    try:
        candidate_count = int(metadata.get("candidate_count", 0))
    except (TypeError, ValueError):
        candidate_count = 0
    if candidate_count < 0:
        candidate_count = 0
    chosen_index = metadata.get("selected_index")
    logit = getattr(plan, "score", None) if plan is not None else None
    if chosen_index is not None:
        chosen_index = _jsonable(chosen_index)
    logit = _jsonable(logit)

    planning_error = exc if isinstance(exc, ActionPlanningError) else None
    player = getattr(engine, "current_turn_color", None)
    timeline_manager = getattr(engine, "timeline_manager", None)
    timelines = getattr(timeline_manager, "timelines", {})
    try:
        timeline_count = len(timelines)
    except Exception:
        timeline_count = None
    plan_signature_sha256 = (
        _signature_sha256(getattr(plan, "start_signature", None))
        if plan is not None
        else None
    )
    return {
        "game_id": game_index + 1,
        "game_index": game_index,
        "action_index": action_index,
        "ply": _jsonable(getattr(engine, "move_counter", None)),
        "player": _jsonable(player),
        "state_signature_sha256": _state_signature_sha256(engine),
        "timeline_count": timeline_count,
        "candidate_count": candidate_count,
        "chosen_index": chosen_index,
        "logit": logit,
        "plan_move_count": move_count,
        "canonical_move_specs": move_specs,
        "failure_stage": failure_stage,
        "exception_class": type(exc).__name__,
        "exception_qualified_class": f"{type(exc).__module__}.{type(exc).__qualname__}",
        "message": str(exc),
        "traceback": traceback_text,
        "planning_reason": (
            _jsonable(planning_error.reason) if planning_error is not None else None
        ),
        "planning_incomplete": (
            _jsonable(planning_error.incomplete) if planning_error is not None else None
        ),
        "explored_states": (
            _jsonable(planning_error.explored_states)
            if planning_error is not None
            else _jsonable(metadata.get("explored_states", 0))
        ),
        "explored_actions": (
            _jsonable(planning_error.explored_actions)
            if planning_error is not None
            else _jsonable(metadata.get("explored_actions", 0))
        ),
        "plan_metadata": _jsonable(dict(metadata)) if plan is not None else None,
        "plan_start_signature_sha256": plan_signature_sha256,
    }


def _record_first_failure(
    first_failure: dict[str, Any] | None,
    **kwargs: Any,
) -> dict[str, Any]:
    return first_failure if first_failure is not None else _failure_record(**kwargs)


def _baseline(name: str, color: ChessColor, seed: int, budget: ActionSearchBudget):
    if name == "easy":
        return RandomAI(color, seed=seed, budget=budget)
    if name == "medium":
        return AlphaBetaAI(color, search_depth=1, budget=budget)
    if name == "hard":
        return HardAI(color, search_depth=2, budget=budget)
    raise ValueError("opponent must be easy, medium, or hard")


def _adjudicate_proven_no_action(
    engine: FiveDEngine,
    planning_error: ActionPlanningError,
) -> None:
    """Finish a game from a complete planner proof without repeating the search."""
    if planning_error.incomplete or planning_error.reason != "no_legal_action":
        raise ValueError("terminal adjudication requires a complete no-action proof")
    outcome = OutcomeRules.classify_proven_no_legal_action(
        engine,
        engine.current_turn_color,
        explored_states=planning_error.explored_states,
    )
    engine.game_state = (
        GameState.CHECKMATE
        if outcome.kind == OutcomeKind.CHECKMATE
        else GameState.STALEMATE
    )


def evaluate_arena(
    *,
    checkpoint: str | Path,
    opponent: str,
    games: int,
    device_name: str,
    seed: int,
    max_actions: int = 120,
    budget: ActionSearchBudget | None = None,
    max_wall_seconds: float | None = None,
    output: str = "text",
) -> dict:
    if isinstance(games, bool) or not isinstance(games, int) or games < 1:
        raise ValueError("games must be at least 1")
    if isinstance(max_actions, bool) or not isinstance(max_actions, int) or not 1 <= max_actions <= 1000:
        raise ValueError("max_actions must be an integer in the range 1..1000")
    if max_wall_seconds is not None:
        if isinstance(max_wall_seconds, bool) or not isinstance(max_wall_seconds, (int, float)):
            raise ValueError("max_wall_seconds must be a non-negative number or null")
        if float(max_wall_seconds) < 0.0:
            raise ValueError("max_wall_seconds must be non-negative")
    output = str(output).lower()
    if output not in {"text", "json"}:
        raise ValueError("output must be text or JSON")
    if budget is None:
        budget = ActionSearchBudget(
            max_states=256,
            max_actions=DEFAULT_PLANNER_CANDIDATE_LIMIT,
            max_move_depth=32,
            max_seconds=DEFAULT_ARENA_PLANNER_SECONDS,
        )
    else:
        # Arena always requires an explicit, finite per-action wall budget.
        # Rebuild the immutable budget with the normalized value so result
        # metadata and the actual planner use the same float.
        planner_seconds = validate_arena_planner_seconds(budget.max_seconds)
        budget = ActionSearchBudget(
            max_states=budget.max_states,
            max_actions=budget.max_actions,
            max_move_depth=budget.max_move_depth,
            max_seconds=planner_seconds,
        )
    quiet = output == "json"
    # NumPy requires an unsigned seed; cloud workflow inputs intentionally
    # allow signed decimal values.
    seed_everything(int(seed) % (2**32))
    device = resolve_device(device_name)
    if not quiet:
        print_device_report(device_name)
    model, metadata = load_checkpoint(checkpoint, device=device)
    wins = draws = losses = 0
    illegal = stale_failures = budget_terminations = 0
    planning_failures = unexpected_failures = 0
    proven_terminal_adjudications = 0
    first_failure: dict[str, Any] | None = None
    action_counts: list[int] = []
    inference_times: list[float] = []
    started = time.monotonic()
    games_played = 0

    for game_index in range(games):
        if (
            max_wall_seconds is not None
            and games_played > 0
            and time.monotonic() - started >= float(max_wall_seconds)
        ):
            budget_terminations += 1
            break
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
        for action_index in range(max_actions):
            if engine.game_state != GameState.PLAYING:
                break
            plan = None
            failure_stage = "planning"
            try:
                if engine.current_turn_color == neural_color:
                    plan = neural.plan_action(engine)
                    if neural.last_decision is not None:
                        inference_times.append(neural.last_decision.inference_ms)
                else:
                    plan = baseline.plan_action(engine)
                failure_stage = "application"
                apply_action_plan(engine, plan)
                completed_actions += 1
            except Exception as exc:
                if (
                    isinstance(exc, ActionPlanningError)
                    and exc.reason == "no_legal_action"
                    and not exc.incomplete
                ):
                    _adjudicate_proven_no_action(engine, exc)
                    proven_terminal_adjudications += 1
                    break
                if isinstance(exc, StaleActionPlanError):
                    stale_failures += 1
                elif isinstance(exc, (InvalidActionPlanError, ActionApplicationError)):
                    illegal += 1
                elif isinstance(exc, ActionPlanningError):
                    planning_failures += 1
                    if exc.incomplete:
                        budget_terminations += 1
                else:
                    unexpected_failures += 1
                first_failure = _record_first_failure(
                    first_failure,
                    engine=engine,
                    game_index=game_index,
                    action_index=action_index,
                    plan=plan,
                    failure_stage=failure_stage,
                    exc=exc,
                    traceback_text=traceback.format_exc(),
                )
                failed = True
                break
        else:
            budget_terminations += 1

        action_counts.append(completed_actions)
        games_played += 1
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

        if not quiet:
            print(
                f"arena game {game_index + 1}/{games}: neural={neural_color.value} "
                f"actions={completed_actions} state={engine.game_state.name}"
            )

    total = games_played
    result = {
        "checkpoint": str(Path(checkpoint).resolve()),
        "opponent": opponent,
        "games": total,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "win_rate": wins / max(1, total),
        "draw_rate": draws / max(1, total),
        "average_actions": sum(action_counts) / max(1, len(action_counts)),
        "illegal_action_count": illegal,
        "stale_failure_count": stale_failures,
        "budget_termination_count": budget_terminations,
        "planning_failure_count": planning_failures,
        "unexpected_failure_count": unexpected_failures,
        "proven_terminal_adjudication_count": proven_terminal_adjudications,
        "first_failure": first_failure,
        "average_inference_ms": (
            sum(inference_times) / len(inference_times) if inference_times else 0.0
        ),
        "checkpoint_epoch": metadata.get("epoch"),
        "games_requested": games,
        "candidate_limit": budget.max_actions,
        "planner_budget_seconds": budget.max_seconds,
    }
    if not quiet:
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
    parser.add_argument(
        "--planner-actions", type=int, default=DEFAULT_PLANNER_CANDIDATE_LIMIT
    )
    parser.add_argument("--planner-moves", type=int, default=32)
    parser.add_argument(
        "--planner-seconds",
        type=parse_arena_planner_seconds,
        default=DEFAULT_ARENA_PLANNER_SECONDS,
    )
    parser.add_argument("--max-wall-seconds", type=float, default=None)
    parser.add_argument(
        "--output",
        choices=["text", "JSON", "json"],
        default="text",
        help="output format; JSON emits one machine-readable result object",
    )
    parser.add_argument(
        "--result-json",
        type=Path,
        help="write a clean machine-readable result file independent of stdout logs",
    )
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
        max_wall_seconds=args.max_wall_seconds,
        output=args.output,
    )
    if str(args.output).lower() == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
    if args.result_json is not None:
        write_json(args.result_json, result)
    return 1 if (
        result["illegal_action_count"]
        or result["stale_failure_count"]
        or result.get("unexpected_failure_count", 0)
    ) else 0


if __name__ == "__main__":
    raise SystemExit(main())
