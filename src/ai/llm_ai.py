"""LLM selects an ID from complete, locally proven legal Action candidates."""
from __future__ import annotations

import json

from src.ai.action_planner import AIActionPlan, ActionPlanner, ActionPlanningError, ActionSearchBudget, engine_state_signature
from src.ai.base import AIPlayer
from src.ai.llm_client import LLMConfig, LLMRequestError, load_llm_config, request_completion
from src.engine.coordinates import BoardCoord
from src.utils.constants import AIDifficulty, GameState


SYSTEM_PROMPT = """You play 5D chess with time travel and branching timelines.
Choose the strongest complete legal Action from the supplied candidates.
All candidates are validated by the local rules engine. Do not invent moves.
An Action may require several moves on different boards before submitting.
Kings on every active timeline, including in history, must be protected.
Travelling to history creates a branch; it does not erase the original future.
Coordinates are [timeline, full_turn, side, file, rank], file/rank use chess notation.
Boards list ranks 8 to 1, files a to h; uppercase=white, lowercase=black, .=empty.
Consider captures, development, threats across boards and king safety.
Some remote history may be omitted; legality is still checked locally.
Return only JSON with the chosen integer ID, for example {"candidate_id":0}.
"""
WARNINGS = {
    "timeout": "在线 AI 响应超时，本回合已使用本地合法方案。",
    "credentials": "在线 AI 密钥或账户额度不可用，本回合已使用本地合法方案。",
    "rate_limit": "在线 AI 请求受限，本回合已使用本地合法方案。",
    "invalid_response": "在线 AI 未返回有效方案编号，本回合已使用本地合法方案。",
    "network": "在线 AI 连接失败，本回合已使用本地合法方案。",
    "busy": "上一条在线请求尚未结束，本回合已使用本地合法方案。",
    "request_limit": "已达到本局在线请求上限，后续回合使用本地合法方案。",
    "context_limit": "棋局规模超出在线上下文限制，本回合已使用本地合法方案。",
}


def _square(square):
    return [square.board.timeline, square.board.turn, square.board.side.value,
            chr(97 + square.x), 8 - square.y]


def build_messages(engine, candidates) -> list[dict]:
    # Send game data only: no archive metadata, file paths, logs or identities.
    coordinates = dict.fromkeys(s.board for moves in candidates for move in moves
                                for s in (move.source, move.destination))
    for timeline in engine.timeline_manager.timelines.values():
        position = timeline.get_position(timeline.latest_time)
        if position is not None:
            coordinates[BoardCoord.from_legacy_time_point(timeline.timeline_id, position.time_point)] = None
    boards = []
    for coord in list(coordinates)[:24]:
        timeline = engine.timeline_manager.get_timeline(coord.timeline)
        position = timeline.get_position(coord.legacy_time_point) if timeline else None
        if position is not None:
            boards.append({"coord": [coord.timeline, coord.turn, coord.side.value],
                           "rows": ["".join(piece or "." for piece in row) for row in position.board]})
    payload = {"side": engine.current_turn_color.value, "boards": boards,
               "history_omitted": True,
               "candidates": [{"id": i, "moves": [
                   {"from": _square(m.source), "to": _square(m.destination),
                    "promotion": m.promotion.value if m.promotion else None}
                   for m in moves]} for i, moves in enumerate(candidates)]}
    content = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    if len(content) > 24000:
        raise LLMRequestError("context_limit")
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": content}]


class LLMAI(AIPlayer):
    def __init__(self, color, config: LLMConfig | None = None, *, budget=None):
        super().__init__(color, AIDifficulty.LLM, budget or ActionSearchBudget(
            max_states=512, max_actions=12, max_move_depth=32, max_seconds=2.0))
        self.config = config or load_llm_config()
        self.requests_used = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.last_source = "pending"

    def public_status(self):
        return {"model": self.config.model, "requests_used": self.requests_used,
                "max_requests": self.config.max_requests, "last_source": self.last_source,
                "prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens}

    def plan_action(self, engine):
        if engine.current_turn_color != self.color or engine.game_state != GameState.PLAYING:
            raise ActionPlanningError("wrong_turn_or_game_over", incomplete=False)
        result = ActionPlanner(self.budget, strategy="probe_then_depth_first", track_repetition=True).search(engine)
        if not result.candidates:
            raise ActionPlanningError(result.termination_reason or "no_legal_action",
                                      incomplete=result.termination_reason is not None)
        counts = result.frontier_repetitions or (0,) * len(result.candidates)
        fresh = tuple(moves for moves, count in zip(result.candidates, counts) if count < 2)
        candidates = fresh or result.candidates
        selected, warning = 0, None
        self.last_source = "local"
        if len(candidates) > 1:
            try:
                if self.requests_used >= self.config.max_requests:
                    raise LLMRequestError("request_limit")
                messages = build_messages(engine, candidates)
                self.requests_used += 1
                response = request_completion(self.config, messages)
                # Count reported usage even if the model's selection is invalid.
                usage = response.get("usage", {}) if isinstance(response, dict) else {}
                for field in ("prompt_tokens", "completion_tokens"):
                    value = usage.get(field) if isinstance(usage, dict) else None
                    if type(value) is int and 0 <= value <= 2000000:
                        setattr(self, field, getattr(self, field) + value)
                choice = response["choices"][0]
                if choice.get("finish_reason") != "stop":
                    raise ValueError()
                answer = json.loads(choice["message"]["content"])
                index = answer.get("candidate_id")
                if type(index) is not int or not 0 <= index < len(candidates):
                    raise ValueError()
                selected = index
                self.last_source = "llm"
            except LLMRequestError as exc:
                warning = WARNINGS.get(str(exc), WARNINGS["network"])
            except (ValueError, TypeError, KeyError, IndexError, AttributeError, RecursionError):
                warning = WARNINGS["invalid_response"]
        return AIActionPlan(color=self.color, moves=candidates[selected],
                            start_signature=engine_state_signature(engine), warning=warning,
                            metadata={"candidate_count": len(candidates), "selected_index": selected,
                                      "source": self.last_source})
