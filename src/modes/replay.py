"""5D Chess replay mode with Action-aware deterministic snapshots."""
from __future__ import annotations

from dataclasses import dataclass

from src.data.archive import GameArchive
from src.engine.action import Action
from src.engine.engine import FiveDEngine
from src.engine.move_generator import Move
from src.engine.timeline import TimelineManager
from src.modes.base import GameModeBase
from src.utils.constants import ChessColor
from src.utils.logger import logger


@dataclass(frozen=True, slots=True)
class ReplayStep:
    """One visible Move plus whether that Move closes its Action."""

    move: Move
    submit_after: bool
    action_index: int
    move_index: int


class ReplayMode(GameModeBase):
    """Replay complete 5D games without losing Action/Submit boundaries."""

    def __init__(self, engine: FiveDEngine = None):
        super().__init__(engine)
        self.current_index: int = 0
        self.move_list: list[Move] = []
        self.action_list: list[Action] = []
        self.steps: list[ReplayStep] = []
        # snapshots[i] is the exact engine state after i visible Moves.
        self.snapshots: list[dict] = []
        self.is_playing: bool = False
        self.play_speed: float = 1.0
        self.selected_timeline_id: int = 0
        self._play_timer: float = 0.0

    # ─── Loading ───────────────────────────────────────

    def load_from_engine(self, engine: FiveDEngine, *, strict: bool = True):
        """Load canonical history from an exact stored engine state."""
        self.move_list = list(engine.move_history)
        self.action_list = list(engine.action_history)
        self.steps = self._build_steps(engine)
        if len(self.steps) != len(self.move_list):
            raise ValueError("Replay Action history does not cover move_history")
        self._rebuild_snapshots(engine, strict=strict)
        self.current_index = len(self.steps)
        if self.snapshots:
            self.engine = GameArchive.restore(self.snapshots[-1])
        logger.info(
            f"加载棋谱: {len(self.action_list)} Actions, "
            f"{len(self.move_list)} Moves, "
            f"{len(engine.timeline_manager.timelines)} 条时间线"
        )

    def load_from_moves(self, moves: list[Move], timeline_manager: TimelineManager):
        """Compatibility loader for old callers of FiveDPGN.load()."""
        stored_actions = getattr(timeline_manager, "_replay_action_history", None)
        if stored_actions is not None:
            final_engine = FiveDEngine()
            final_engine.timeline_manager = timeline_manager
            final_engine.move_history = list(moves)
            final_engine.move_counter = len(moves)
            final_engine.action_history = list(stored_actions)
            final_engine.current_action = getattr(
                timeline_manager,
                "_replay_current_action",
                None,
            )
            final_engine.game_state = getattr(
                timeline_manager,
                "_replay_game_state",
                final_engine.game_state,
            )
            final_engine.current_turn_color = getattr(
                timeline_manager,
                "_replay_current_turn_color",
                final_engine.current_turn_color,
            )
            self.load_from_engine(final_engine, strict=True)
            return

        # Legacy v1 had no Action boundaries. Infer the old auto-submit behavior.
        inferred = FiveDEngine()
        for move in moves:
            if not inferred.execute_action_move(move):
                raise ValueError(f"legacy replay move cannot be executed: {move}")
            if inferred.can_submit_action():
                inferred.submit_action()
        self.load_from_engine(inferred, strict=False)

    def load_from_pgn(self, filepath: str):
        from src.data.pgn_parser import FiveDPGN

        payload = FiveDPGN.load_archive(filepath)
        if payload is None:
            return False
        self.load_from_engine(payload.engine, strict=payload.schema_version >= 2)
        return True

    def _build_steps(self, engine: FiveDEngine) -> list[ReplayStep]:
        steps: list[ReplayStep] = []
        for action_index, action in enumerate(engine.action_history):
            for move_index, move in enumerate(action.moves):
                steps.append(
                    ReplayStep(
                        move=move,
                        submit_after=(
                            action.submitted and move_index == len(action.moves) - 1
                        ),
                        action_index=action_index,
                        move_index=move_index,
                    )
                )

        current = engine.current_action
        if current is not None:
            action_index = len(engine.action_history)
            for move_index, move in enumerate(current.moves):
                steps.append(
                    ReplayStep(
                        move=move,
                        submit_after=False,
                        action_index=action_index,
                        move_index=move_index,
                    )
                )
        return steps

    def _rebuild_snapshots(self, final_engine: FiveDEngine, *, strict: bool):
        temp = FiveDEngine(
            max_timelines=final_engine.max_timelines,
            max_turns=final_engine.max_turns,
        )
        self.snapshots = [GameArchive.capture(temp)]
        for step in self.steps:
            if not temp.execute_action_move(step.move):
                raise ValueError(f"Replay Move failed while rebuilding: {step.move}")
            if step.submit_after and not temp.submit_action():
                raise ValueError(
                    f"Replay Action submit failed after move: {step.move}"
                )
            self.snapshots.append(GameArchive.capture(temp))

        if strict:
            expected = GameArchive.capture(final_engine)
            actual = self.snapshots[-1]
            # Date/user metadata is outside GameArchive, so exact equality here is
            # a strong replay determinism check for every rule-relevant field.
            if actual != expected:
                raise ValueError("stored game state is not reproducible from its Actions")

    # ─── Replay controls ───────────────────────────────

    def start(self):
        self.current_index = 0
        self.is_playing = False
        self.selected_timeline_id = 0
        self._play_timer = 0.0
        if self.snapshots:
            self.engine = GameArchive.restore(self.snapshots[0])
        else:
            self.engine = FiveDEngine()
        logger.info("Replay模式启动")
        self.emit(
            "replay_started",
            {
                "total_moves": len(self.steps),
                "total_actions": len(self.action_list),
            },
        )

    def step_forward(self) -> bool:
        if self.current_index >= len(self.steps):
            return False
        step = self.steps[self.current_index]
        self.current_index += 1
        self.engine = GameArchive.restore(self.snapshots[self.current_index])
        self._update_timeline_view(step.move)
        self.emit(
            "step_changed",
            {
                "index": self.current_index,
                "move": step.move,
                "action_index": step.action_index,
                "submitted": step.submit_after,
            },
        )
        return True

    def step_backward(self) -> bool:
        if self.current_index <= 0:
            return False
        self.current_index -= 1
        self.engine = GameArchive.restore(self.snapshots[self.current_index])
        self.emit("step_changed", {"index": self.current_index})
        return True

    def jump_to(self, index: int):
        index = max(0, min(index, len(self.steps)))
        self.current_index = index
        self.engine = GameArchive.restore(self.snapshots[index])
        self.emit("step_changed", {"index": self.current_index})

    def jump_to_start(self):
        self.jump_to(0)

    def jump_to_end(self):
        self.jump_to(len(self.steps))

    def toggle_play(self):
        self.is_playing = not self.is_playing
        self.emit("play_toggled", {"playing": self.is_playing})

    def set_speed(self, speed: float):
        self.play_speed = max(0.25, min(4.0, speed))

    def update(self, dt: float):
        if not self.is_playing:
            return
        self._play_timer += dt
        steps = int(self._play_timer * self.play_speed)
        if steps <= 0:
            return
        self._play_timer -= steps / self.play_speed
        for _ in range(steps):
            if not self.step_forward():
                self.is_playing = False
                self.emit("play_completed", {})
                break

    # ─── Timeline / statistics ─────────────────────────

    def select_timeline(self, timeline_id: int):
        if self.engine.timeline_manager.get_timeline(timeline_id):
            self.selected_timeline_id = timeline_id
            self.emit("timeline_changed", {"timeline_id": timeline_id})

    def get_timeline_tree(self) -> dict:
        return self.engine.timeline_manager.build_tree()

    def get_timeline_board(
        self,
        timeline_id: int,
        time_point: int = None,
    ) -> list[list[str]] | None:
        timeline = self.engine.timeline_manager.get_timeline(timeline_id)
        if timeline is None:
            return None
        if time_point is None:
            time_point = timeline.latest_time
        position = timeline.get_position(time_point)
        return position.board if position else None

    def get_statistics(self) -> dict:
        timelines = self.engine.timeline_manager.timelines
        white_time_travels = sum(
            1
            for move in self.move_list
            if move.piece.color == ChessColor.WHITE
            and (move.is_branching or move.is_time_travel)
        )
        black_time_travels = sum(
            1
            for move in self.move_list
            if move.piece.color == ChessColor.BLACK
            and (move.is_branching or move.is_time_travel)
        )
        depths = []
        for timeline in timelines.values():
            depth = 0
            current = timeline
            while current.parent_id is not None:
                depth += 1
                current = timelines.get(current.parent_id)
                if current is None:
                    break
            depths.append(depth)

        current_action_index = 0
        if self.current_index:
            current_action_index = self.steps[self.current_index - 1].action_index + 1
        return {
            "total_moves": len(self.move_list),
            "current_index": self.current_index,
            "total_actions": len(self.action_list),
            "current_action_index": current_action_index,
            "total_timelines": len(timelines),
            "active_timelines": len(self.engine.timeline_manager.get_active_timelines()),
            "branching_moves": sum(1 for move in self.move_list if move.is_branching),
            "cross_timeline_moves": sum(
                1 for move in self.move_list if move.is_cross_timeline
            ),
            "white_time_travels": white_time_travels,
            "black_time_travels": black_time_travels,
            "max_branch_depth": max(depths) if depths else 0,
            "avg_branch_depth": sum(depths) / len(depths) if depths else 0,
            "result": self.engine.game_state.name,
        }

    def get_overview(self) -> dict:
        overview = {}
        for timeline_id, timeline in self.engine.timeline_manager.timelines.items():
            latest = timeline.latest_time
            position = timeline.get_position(latest)
            if position:
                overview[timeline_id] = {
                    "board": position.board,
                    "time_point": latest,
                    "parent_id": timeline.parent_id,
                    "branch_turn": timeline.branch_turn,
                    "is_active": timeline.is_active,
                }
        return overview

    def _update_timeline_view(self, move: Move):
        if move.created_timeline is not None:
            self.selected_timeline_id = move.created_timeline
        elif move.is_cross_timeline:
            self.selected_timeline_id = move.destination.timeline

    def handle_move(self, move: Move) -> bool:
        return False

    def get_current_board(self) -> list[list[str]]:
        return self.get_timeline_board(self.selected_timeline_id) or [[]]
