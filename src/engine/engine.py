"""
5D Chess - 五维核心引擎
整合棋盘、走子生成、校验、时间线管理、规则判定
"""
from __future__ import annotations
from dataclasses import dataclass, field, replace
from src.config import DEFAULT_MAX_TIMELINES, DEFAULT_MAX_TURNS
from src.utils.constants import ChessColor, PieceType, GameState
from src.utils.logger import logger
from src.engine.action import Action, ActionRules
from src.engine.piece import Piece
from src.engine.board import Position
from src.engine.coordinates import BoardCoord
from src.engine.move_generator import Move, MoveGenerator
from src.engine.move_validator import MoveValidator
from src.engine.multiverse import MultiverseBoardView
from src.engine.outcome_rules import OutcomeKind, OutcomeRules
from src.engine.pawn_rules import PawnRules
from src.engine.timeline import TimelineManager
from src.engine.timeline_rules import PresentState, TimelineRules
from src.engine.rules import RulesEngine


_OUTCOME_UNSET = object()


@dataclass
class FiveDEngine:
    """5D国际象棋核心引擎。"""

    max_timelines: int = DEFAULT_MAX_TIMELINES
    max_turns: int = DEFAULT_MAX_TURNS
    timeline_manager: TimelineManager = field(default_factory=TimelineManager)
    rules_engine: RulesEngine = field(default_factory=RulesEngine)
    game_state: GameState = GameState.WAITING
    move_history: list[Move] = field(default_factory=list)
    move_counter: int = 0
    current_turn_color: ChessColor = ChessColor.WHITE
    action_history: list[Action] = field(default_factory=list)
    current_action: Action | None = None

    def __post_init__(self):
        self.timeline_manager.max_timelines = self.max_timelines
        self._init_game()

    def _init_game(self):
        """初始化游戏。"""
        tl = self.timeline_manager.create_initial_timeline()
        initial_pos = Position.initial(timeline_id=tl.timeline_id, time_point=0)
        tl.add_position(initial_pos)
        self.timeline_manager.refresh_activity()
        self.game_state = GameState.PLAYING
        self.move_history = []
        self.action_history = []
        self.move_counter = 0
        self.current_turn_color = ChessColor.WHITE
        self.current_action = ActionRules.begin(
            self.current_turn_color,
            self.timeline_manager.timelines,
        )
        logger.info("游戏初始化完成")

    def _board_view(self) -> MultiverseBoardView:
        """Return the canonical lookup layer over the current multiverse."""
        return MultiverseBoardView(self.timeline_manager.timelines)

    def _resolve_position(self, coord: BoardCoord) -> Position | None:
        """Resolve a canonical board coordinate at the legacy storage boundary."""
        return self._board_view().resolve(coord)

    def _coord_for_position(self, position: Position) -> BoardCoord:
        return BoardCoord.from_legacy_time_point(
            timeline=position.timeline_id,
            time_point=position.time_point,
            side=position.turn,
        )

    def _ensure_current_action(self) -> Action:
        action = self.current_action
        if (
            action is None
            or action.submitted
            or action.color != self.current_turn_color
        ):
            action = ActionRules.begin(
                self.current_turn_color,
                self.timeline_manager.timelines,
            )
            self.current_action = action
        return action

    def get_present(self) -> PresentState | None:
        """Return The Present derived from active playable timelines."""
        return TimelineRules.present(self.timeline_manager.timelines)

    def get_required_action_boards(self) -> tuple[BoardCoord, ...]:
        """Boards that must still be advanced before the current Action submits."""
        action = self._ensure_current_action()
        return ActionRules.required_boards(
            action,
            self.timeline_manager.timelines,
        )

    def can_submit_action(self) -> bool:
        if self.game_state != GameState.PLAYING:
            return False
        action = self._ensure_current_action()
        return ActionRules.can_submit(
            action,
            self.timeline_manager.timelines,
        )

    def _build_successor(self, position: Position) -> Position:
        """Create the next immutable board state for one timeline.

        Timeline storage still uses legacy half-move integer keys. Conversion is
        intentionally centralized here rather than spread through move execution.
        """
        before = BoardCoord.from_legacy_time_point(
            timeline=position.timeline_id,
            time_point=position.time_point,
            side=position.turn,
        )
        after = before.next()

        successor = position.copy()
        successor.time_point = after.legacy_time_point
        successor.turn = after.side
        successor.move_number = self.move_counter + 1
        successor.en_passant_target = None
        return successor

    def _build_source_departure_successor(
        self,
        position: Position,
        move: Move,
    ) -> Position:
        successor = self._build_successor(position)
        successor.set_piece(move.source.x, move.source.y, None)
        self._update_castling_rights(successor, move)
        return successor

    def _build_destination_arrival_successor(
        self,
        position: Position,
        move: Move,
    ) -> Position:
        successor = self._build_successor(position)
        arriving_piece = (
            Piece(move.promotion, move.piece.color)
            if move.promotion is not None
            else move.piece
        )
        successor.set_piece(
            move.destination.x,
            move.destination.y,
            arriving_piece,
        )
        return successor

    def get_current_position(self) -> Position:
        """获取 legacy UI 当前选中时间线的最新棋盘。"""
        tl = self.timeline_manager.get_timeline(
            self.timeline_manager.active_timeline_id
        )
        if tl is None:
            raise RuntimeError("没有选中的时间线")
        return tl.positions[tl.latest_time]

    def _select_action_position(self) -> Position | None:
        """Choose a sensible board for legacy callers that omit ``position``."""
        action = self._ensure_current_action()
        movable = ActionRules.movable_boards(
            action,
            self.timeline_manager.timelines,
        )
        if not movable:
            return None

        selected = self.get_current_position()
        if self._coord_for_position(selected) in movable:
            return selected

        required = ActionRules.required_boards(
            action,
            self.timeline_manager.timelines,
        )
        candidates = required or movable
        return self._resolve_position(candidates[0])

    def get_legal_moves(self, position: Position = None) -> list[Move]:
        """获取当前 Action 可走棋盘上的合法 Move。"""
        if self.game_state != GameState.PLAYING:
            return []

        action = self._ensure_current_action()
        if position is None:
            position = self._select_action_position()
        if position is None:
            return []

        coord = self._coord_for_position(position)
        if coord not in ActionRules.movable_boards(
            action,
            self.timeline_manager.timelines,
        ):
            return []

        generator = MoveGenerator(position, self.timeline_manager.timelines)
        validator = MoveValidator(self.timeline_manager.timelines)
        pseudo_moves = generator.generate_all()
        return validator.filter_legal_moves(position, pseudo_moves)

    def get_legal_moves_from_square(
        self,
        position: Position,
        x: int,
        y: int,
    ) -> list[Move]:
        """Return the canonical legal-Move subset for one source square.

        The same MoveGenerator and MoveValidator are used as ``get_legal_moves``;
        only unrelated source pieces are skipped before validation.
        """
        if self.game_state != GameState.PLAYING:
            return []

        action = self._ensure_current_action()
        coord = self._coord_for_position(position)
        if coord not in ActionRules.movable_boards(
            action,
            self.timeline_manager.timelines,
        ):
            return []

        generator = MoveGenerator(position, self.timeline_manager.timelines)
        validator = MoveValidator(self.timeline_manager.timelines)
        pseudo_moves = generator.generate_from_square(x, y)
        return validator.filter_legal_moves(position, pseudo_moves)

    def execute_action_move(self, move: Move) -> bool:
        """Execute one Move inside the current player's Action without submitting.

        Callers that need true 5D turn control should use this method followed by
        ``submit_action()`` when ``can_submit_action()`` becomes true.  This
        leaves optional future/inactive-board moves available before submission.
        """
        if self.game_state != GameState.PLAYING:
            logger.warning("游戏已结束，无法走子")
            return False

        action = self._ensure_current_action()
        if not ActionRules.can_play_move(
            action,
            move,
            self.timeline_manager.timelines,
        ):
            logger.warning("走子不属于当前 Action 的可走棋盘")
            return False

        recorded_move = self._execute_state_move(move)
        if recorded_move is None:
            return False

        self.move_counter += 1
        self.move_history.append(recorded_move)
        action.record(recorded_move)
        self.timeline_manager.refresh_activity()
        return True

    def execute_move(self, move: Move) -> bool:
        """Compatibility entry point: execute a Move and submit when possible.

        On a single timeline this preserves the old one-call-per-turn behavior.
        With multiple required boards it keeps the same Action open until The
        Present reaches the opponent.  Use ``execute_action_move`` for callers
        that want to make optional future moves before explicit submission.
        """
        if not self.execute_action_move(move):
            return False
        if self.can_submit_action():
            return self.submit_action()
        return True

    def submit_action(self, *, evaluate_outcome: bool = True) -> bool:
        """Finalize a royal-safe Action and, by default, evaluate the outcome.

        ``evaluate_outcome=False`` is an internal transaction hook used only
        when a caller has isolated the submitted state and will apply a
        separately validated outcome. Canonical Action submission is never
        skipped.
        """
        if self.game_state != GameState.PLAYING:
            return False

        action = self._ensure_current_action()
        if not ActionRules.submit(action, self.timeline_manager.timelines):
            return False

        self.action_history.append(action)
        self.current_turn_color = self.current_turn_color.opposite()
        self.current_action = ActionRules.begin(
            self.current_turn_color,
            self.timeline_manager.timelines,
        )

        # Checkmate/stalemate is global: after every submitted Action, determine
        # whether the next player has at least one complete legal Action. The
        # default public behavior is unchanged; the false branch is reserved for
        # an isolated caller that already owns outcome-validation evidence.
        if evaluate_outcome:
            self._check_multiverse_game_result()
        return True

    def _execute_state_move(self, move: Move) -> Move | None:
        """Apply one canonical state transition without Action/turn bookkeeping."""
        try:
            if move.is_branching:
                return self._execute_branching_move(move)
            if move.is_cross_timeline:
                return self._execute_cross_timeline_move(move)
            return self._execute_normal_move(move)
        except Exception as e:
            logger.error(f"走子执行失败: {e}")
            return None

    def _execute_normal_move(self, move: Move) -> Move | None:
        """执行同一 canonical Board 上的普通空间移动。"""
        source = move.source
        destination = move.destination
        if source.board != destination.board:
            return None

        resolved = self._board_view().describe(source.board)
        if resolved is None or not resolved.is_playable:
            return None
        current_pos = resolved.position
        if current_pos.get_piece(source.x, source.y) != move.piece:
            return None

        new_pos = self._build_successor(current_pos)
        new_pos.move_piece(source.x, source.y, destination.x, destination.y)

        if move.is_castling:
            row = destination.y
            if destination.x == 6:
                new_pos.move_piece(7, row, 5, row)
            elif destination.x == 2:
                new_pos.move_piece(0, row, 3, row)

        if move.is_en_passant:
            new_pos.set_piece(destination.x, source.y, None)

        if move.promotion:
            new_pos.set_piece(
                destination.x,
                destination.y,
                Piece(move.promotion, move.piece.color),
            )

        if (
            move.piece.piece_type == PieceType.PAWN
            and PawnRules.is_spatial_double(move.vector)
        ):
            new_pos.en_passant_target = (
                source.x,
                (source.y + destination.y) // 2,
            )

        self._update_castling_rights(new_pos, move)

        timeline = self.timeline_manager.get_timeline(source.board.timeline)
        if timeline is None:
            return None
        timeline.add_position(new_pos)
        return move

    def _execute_branching_move(self, move: Move) -> Move | None:
        """执行落到 historical canonical Board 并创建新时间线的走子。"""
        source = move.source
        destination = move.destination
        board_view = self._board_view()
        source_board = board_view.describe(source.board)
        destination_board = board_view.describe(destination.board)

        if source_board is None or not source_board.is_playable:
            return None
        if destination_board is None or not destination_board.is_historical:
            return None
        if source_board.position.get_piece(source.x, source.y) != move.piece:
            return None

        source_timeline = self.timeline_manager.get_timeline(source.board.timeline)
        if source_timeline is None:
            return None

        target_time = destination.board.legacy_time_point
        new_timeline = self.timeline_manager.create_branch(
            parent_id=destination.board.timeline,
            branch_turn=source.board.legacy_time_point,
            branch_move_id=self.move_counter + 1,
            target_time=target_time,
            creator=move.piece.color,
        )
        if new_timeline is None:
            logger.warning("无法创建新时间线：已达上限或目标棋盘不存在")
            return None

        branch_target = new_timeline.positions.get(target_time)
        if branch_target is None:
            return None

        new_target_pos = self._build_destination_arrival_successor(
            branch_target,
            move,
        )
        new_timeline.add_position(new_target_pos)

        # The source history remains immutable; removal happens in a successor.
        new_source_pos = self._build_source_departure_successor(
            source_board.position,
            move,
        )
        source_timeline.add_position(new_source_pos)

        # Legacy UI selection follows the newly-created lane, but this does not
        # control whether the timeline is active for The Present.
        self.timeline_manager.switch_active(new_timeline.timeline_id)

        recorded_move = replace(move, created_timeline=new_timeline.timeline_id)
        logger.info(
            f"时间线分支: L{new_timeline.timeline_id:+d} ← "
            f"L{new_timeline.parent_id:+d} @ {destination.board}"
        )
        return recorded_move

    def _execute_cross_timeline_move(self, move: Move) -> Move | None:
        """执行两个 playable canonical Board 之间的跨时间线移动。"""
        source = move.source
        destination = move.destination
        board_view = self._board_view()
        source_board = board_view.describe(source.board)
        destination_board = board_view.describe(destination.board)

        if source_board is None or not source_board.is_playable:
            return None
        if destination_board is None or not destination_board.is_playable:
            return None
        if source_board.position.get_piece(source.x, source.y) != move.piece:
            return None

        source_timeline = self.timeline_manager.get_timeline(source.board.timeline)
        target_timeline = self.timeline_manager.get_timeline(destination.board.timeline)
        if source_timeline is None or target_timeline is None:
            return None

        new_source_pos = self._build_source_departure_successor(
            source_board.position,
            move,
        )
        new_target_pos = self._build_destination_arrival_successor(
            destination_board.position,
            move,
        )

        source_timeline.add_position(new_source_pos)
        target_timeline.add_position(new_target_pos)
        return move

    def _update_castling_rights(self, position: Position, move: Move):
        """更新王车易位权。"""
        rights = position.castling_rights
        piece = move.piece
        source = move.source

        if piece.piece_type == PieceType.KING:
            if piece.color == ChessColor.WHITE:
                rights["white_kingside"] = False
                rights["white_queenside"] = False
            else:
                rights["black_kingside"] = False
                rights["black_queenside"] = False

        if piece.piece_type == PieceType.ROOK:
            if piece.color == ChessColor.WHITE:
                if source.x == 7 and source.y == 7:
                    rights["white_kingside"] = False
                if source.x == 0 and source.y == 7:
                    rights["white_queenside"] = False
            else:
                if source.x == 7 and source.y == 0:
                    rights["black_kingside"] = False
                if source.x == 0 and source.y == 0:
                    rights["black_queenside"] = False

    def _evaluate_multiverse_game_result(self):
        """Evaluate terminal state without applying it to ``game_state``."""
        outcome = OutcomeRules.evaluate(self, self.current_turn_color)
        return outcome, getattr(self, "rule_warning", None)

    def _check_multiverse_game_result(
        self,
        *,
        precomputed_outcome=_OUTCOME_UNSET,
        rule_warning: str | None = None,
    ) -> None:
        """Update terminal state from complete Action-level 5D rules.

        Supplying ``precomputed_outcome`` applies outcome evidence produced from
        an isolated but canonically submitted equivalent state. This avoids
        repeating the expensive ActionSearch while keeping the normal no-argument
        submission path unchanged.
        """
        if precomputed_outcome is _OUTCOME_UNSET:
            outcome, _ = self._evaluate_multiverse_game_result()
        else:
            outcome = precomputed_outcome
            setattr(self, "rule_warning", rule_warning)

        if outcome is None:
            return

        if outcome.kind == OutcomeKind.CHECKMATE:
            self.game_state = GameState.CHECKMATE
            winner = outcome.winner.value if outcome.winner else "unknown"
            logger.info(
                f"5D checkmate: {self.current_turn_color.value} has no legal "
                f"Action; winner={winner}"
            )
            return

        if outcome.kind == OutcomeKind.STALEMATE:
            self.game_state = GameState.STALEMATE
            logger.info(
                f"5D stalemate: {self.current_turn_color.value} has no legal Action"
            )

    def _check_game_result(self, position: Position):
        """Legacy board-local result helper retained for old direct callers."""
        result = self.rules_engine.get_game_result(position)
        if result == "white_win":
            self.game_state = GameState.CHECKMATE
            logger.info("白方获胜！")
        elif result == "black_win":
            self.game_state = GameState.CHECKMATE
            logger.info("黑方获胜！")
        elif result == "draw":
            self.game_state = GameState.DRAW
            logger.info("和棋！")

    def get_game_summary(self) -> dict:
        """获取游戏摘要。"""
        tl_mgr = self.timeline_manager
        present = self.get_present()
        action = self._ensure_current_action()
        return {
            "game_state": self.game_state.name,
            "total_moves": self.move_counter,
            "total_actions": len(self.action_history),
            "total_timelines": len(tl_mgr.timelines),
            "active_timelines": len(tl_mgr.get_active_timelines()),
            "current_turn": self.current_turn_color.value,
            "active_timeline_id": tl_mgr.active_timeline_id,
            "present": (
                {
                    "time_point": present.legacy_time_point,
                    "turn": present.turn,
                    "side": present.side.value,
                    "timelines": list(present.timeline_ids),
                }
                if present is not None
                else None
            ),
            "current_action_moves": len(action.moves),
            "required_action_boards": [
                str(coord) for coord in self.get_required_action_boards()
            ],
            "can_submit_action": self.can_submit_action(),
            "move_history": [m.to_notation() for m in self.move_history],
        }

    def to_dict(self) -> dict:
        """序列化完整游戏状态。

        Replay/storage migration for full Action history remains a later layer;
        current board state and current player stay backward compatible here.
        """
        return {
            "max_timelines": self.max_timelines,
            "max_turns": self.max_turns,
            "timeline_manager": self.timeline_manager.to_dict(),
            "game_state": self.game_state.name,
            "move_history": [
                {
                    "piece_type": m.piece.piece_type.value,
                    "piece_color": m.piece.color.value,
                    "from_x": m.from_x, "from_y": m.from_y,
                    "to_x": m.to_x, "to_y": m.to_y,
                    "from_timeline_id": m.from_timeline_id,
                    "to_timeline_id": m.to_timeline_id,
                    "from_time": m.from_time, "to_time": m.to_time,
                    "is_branching": m.is_branching,
                    "created_timeline": m.created_timeline,
                    "is_castling": m.is_castling,
                    "is_en_passant": m.is_en_passant,
                    "promotion": m.promotion.value if m.promotion else None,
                    "captured": m.captured.piece_type.value if m.captured else None,
                    "notation": m.to_notation(),
                }
                for m in self.move_history
            ],
            "move_counter": self.move_counter,
            "current_turn_color": self.current_turn_color.value,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FiveDEngine":
        engine = cls(
            max_timelines=data.get("max_timelines", DEFAULT_MAX_TIMELINES),
            max_turns=data.get("max_turns", DEFAULT_MAX_TURNS),
        )
        engine.timeline_manager = TimelineManager.from_dict(data["timeline_manager"])
        engine.game_state = GameState[data["game_state"]]
        engine.move_counter = data["move_counter"]
        engine.current_turn_color = ChessColor(data["current_turn_color"])
        engine.action_history = []
        engine.current_action = ActionRules.begin(
            engine.current_turn_color,
            engine.timeline_manager.timelines,
        )
        return engine
