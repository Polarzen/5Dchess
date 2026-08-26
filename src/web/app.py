"""5D Chess Web server and canonical multiverse interaction API.

The Web layer is the primary 5D GUI.  It exposes BoardCoord-aware state and
move endpoints so the browser can render and interact with the whole
multiverse instead of pretending that one selected 8x8 board is the game.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request

# Ensure project root is importable when running ``python src/main.py --web``.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.engine import FiveDEngine, Move
from src.engine.coordinates import BoardCoord
from src.engine.multiverse import MultiverseBoardView
from src.engine.royal_rules import RoyalRules
from src.engine.timeline_rules import TimelineRules
from src.data.pgn_parser import FiveDPGN
from src.modes import PvEMode, PvPMode, ReplayMode
from src.utils.constants import ChessColor, GameState
from src.utils.logger import logger


app = Flask(
    __name__,
    template_folder=str(Path(__file__).parent / "templates"),
    static_folder=str(Path(__file__).parent / "static"),
)

# Single-session local UI.  Multi-user/server deployment is intentionally out
# of scope for this project; the browser and engine live in one local process.
_game_session: dict[str, Any] = {
    "mode": None,
    "mode_instance": None,
    "ai_difficulty": "medium",
    "player_color": None,
}


def _get_mode_instance():
    return _game_session.get("mode_instance")


def _board_key(coord: BoardCoord) -> str:
    """Stable browser key for one canonical stored board."""
    return f"{coord.timeline}:{coord.legacy_time_point}"


def _coord_payload(coord: BoardCoord) -> dict[str, Any]:
    return {
        "key": _board_key(coord),
        "timeline": coord.timeline,
        "turn": coord.turn,
        "side": coord.side.value,
        "time_point": coord.legacy_time_point,
    }


def _coord_from_payload(payload: dict[str, Any] | None) -> BoardCoord:
    if not isinstance(payload, dict):
        raise ValueError("board coordinate must be an object")

    if "timeline" not in payload:
        raise ValueError("board coordinate is missing timeline")
    timeline = int(payload["timeline"])

    side_value = payload.get("side")
    if side_value is None and "time_point" in payload:
        # Legacy storage alternates WHITE/BLACK by half-move.
        side_value = "white" if int(payload["time_point"]) % 2 == 0 else "black"
    if side_value is None:
        raise ValueError("board coordinate is missing side")
    side = ChessColor(side_value)

    if "time_point" in payload:
        return BoardCoord.from_legacy_time_point(
            timeline=timeline,
            time_point=int(payload["time_point"]),
            side=side,
        )
    if "turn" not in payload:
        raise ValueError("board coordinate is missing turn/time_point")
    return BoardCoord(timeline=timeline, turn=int(payload["turn"]), side=side)


def _square_payload(square) -> dict[str, Any]:
    return {
        "board": _coord_payload(square.board),
        "x": square.x,
        "y": square.y,
    }


def _move_payload(move: Move) -> dict[str, Any]:
    return {
        "source": _square_payload(move.source),
        "destination": _square_payload(move.destination),
        # Flat fields remain useful to old/debug callers.
        "from": [move.source.x, move.source.y],
        "to": [move.destination.x, move.destination.y],
        "from_timeline": move.source.timeline,
        "to_timeline": move.destination.timeline,
        "from_time": move.source.board.legacy_time_point,
        "to_time": move.destination.board.legacy_time_point,
        "piece": move.piece.piece_type.value,
        "color": move.piece.color.value,
        "captured": move.captured.piece_type.value if move.captured else None,
        "promotion": move.promotion.value if move.promotion else None,
        "is_castling": move.is_castling,
        "is_en_passant": move.is_en_passant,
        "is_branching": move.is_branching,
        "is_cross_timeline": move.is_cross_timeline,
        "created_timeline": move.created_timeline,
        "notation": move.to_notation(),
    }


def _find_exact_legal_move(engine: FiveDEngine, payload: dict[str, Any]) -> Move | None:
    source_payload = payload.get("source") or {}
    destination_payload = payload.get("destination") or {}
    source_board = _coord_from_payload(source_payload.get("board"))
    destination_board = _coord_from_payload(destination_payload.get("board"))
    sx, sy = int(source_payload.get("x", -1)), int(source_payload.get("y", -1))
    dx, dy = int(destination_payload.get("x", -1)), int(destination_payload.get("y", -1))

    position = MultiverseBoardView(engine.timeline_manager.timelines).resolve(source_board)
    if position is None:
        return None

    requested_promotion = payload.get("promotion")
    for move in engine.get_legal_moves(position):
        if move.source.board != source_board or move.destination.board != destination_board:
            continue
        if (move.source.x, move.source.y) != (sx, sy):
            continue
        if (move.destination.x, move.destination.y) != (dx, dy):
            continue
        if requested_promotion and (
            move.promotion is None or move.promotion.value != requested_promotion
        ):
            continue
        return move
    return None


def _timeline_payloads(engine: FiveDEngine) -> list[dict[str, Any]]:
    engine.timeline_manager.refresh_activity()
    branch_moves = {
        move.created_timeline: move
        for move in engine.move_history
        if move.created_timeline is not None
    }

    payloads: list[dict[str, Any]] = []
    for timeline_id in sorted(engine.timeline_manager.timelines, reverse=True):
        timeline = engine.timeline_manager.timelines[timeline_id]
        branch_move = branch_moves.get(timeline_id)
        branch_from = None
        branch_to = None
        if branch_move is not None:
            branch_from = _coord_payload(branch_move.destination.board)
            next_on_parent = branch_move.destination.board.next()
            branch_coord = BoardCoord(
                timeline=timeline_id,
                turn=next_on_parent.turn,
                side=next_on_parent.side,
            )
            branch_to = _coord_payload(branch_coord)

        payloads.append({
            "id": timeline_id,
            "name": "L0" if timeline_id == 0 else f"L{timeline_id:+d}",
            "parent_id": timeline.parent_id,
            "owner": timeline.owner.value if timeline.owner else None,
            "branch_move_id": timeline.branch_move_id,
            "branch_turn": timeline.branch_turn,
            "branch_from": branch_from,
            "branch_to": branch_to,
            "is_active": timeline.is_active,
            "latest_time": timeline.latest_time,
            "time_points": sorted(timeline.positions),
        })
    return payloads


def _board_payloads(engine: FiveDEngine, interactive: bool) -> list[dict[str, Any]]:
    timelines = engine.timeline_manager.timelines
    view = MultiverseBoardView(timelines)
    present = engine.get_present()
    present_boards = set(present.boards if present else ())

    if interactive and engine.game_state == GameState.PLAYING:
        required_boards = set(engine.get_required_action_boards())
        movable_boards = set(
            TimelineRules.movable_boards(timelines, engine.current_turn_color)
        )
    else:
        required_boards = set()
        movable_boards = set()

    boards: list[dict[str, Any]] = []
    for resolved in view.iter_boards():
        coord = resolved.coord
        boards.append({
            "key": _board_key(coord),
            "coord": _coord_payload(coord),
            "board": [row[:] for row in resolved.position.board],
            "role": resolved.role.value,
            "playable": resolved.is_playable,
            "historical": resolved.is_historical,
            "timeline_active": resolved.timeline_active,
            "is_present": coord in present_boards,
            "is_required": coord in required_boards,
            "is_movable": coord in movable_boards,
            "move_number": resolved.position.move_number,
        })
    return boards


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------


@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Game API
# ---------------------------------------------------------------------------


@app.route("/api/game/start", methods=["POST"])
def start_game():
    data = request.get_json() or {}
    mode = data.get("mode", "pvp")
    difficulty = data.get("difficulty", "medium")
    player_color = data.get("player_color", "white")

    try:
        engine = FiveDEngine()
        if mode == "pvp":
            instance = PvPMode(engine)
        elif mode == "pve":
            instance = PvEMode(
                engine,
                player_color=ChessColor(player_color),
                ai_difficulty=difficulty,
            )
        elif mode == "replay":
            instance = ReplayMode(engine)
        else:
            return jsonify({"error": f"未知模式: {mode}"}), 400

        instance.start()
        _game_session.update({
            "mode": mode,
            "mode_instance": instance,
            "ai_difficulty": difficulty,
            "player_color": player_color,
        })
        return jsonify({"success": True, **get_game_state()})
    except Exception as exc:
        logger.error(f"启动游戏失败: {exc}")
        return jsonify({"error": str(exc)}), 500


@app.route("/api/game/state")
def api_game_state():
    if _get_mode_instance() is None:
        return jsonify({"error": "没有活跃游戏"}), 400
    return jsonify(get_game_state())


@app.route("/api/game/save", methods=["POST"])
def api_save_game():
    """Persist the active canonical engine without changing the live session."""
    instance = _get_mode_instance()
    if instance is None or _game_session["mode"] == "replay":
        return jsonify({"error": "当前模式没有可保存的进行中游戏"}), 400

    data = request.get_json() or {}
    filepath = data.get("filepath")
    if not filepath:
        return jsonify({"error": "缺少保存路径"}), 400

    metadata = {
        "mode": _game_session["mode"],
        "difficulty": _game_session.get("ai_difficulty"),
        "player_color": _game_session.get("player_color"),
    }
    if not FiveDPGN.save(str(filepath), instance.engine, metadata):
        return jsonify({"error": f"无法保存棋局: {filepath}"}), 500
    return jsonify({"success": True, "filepath": str(filepath), **get_game_state()})


@app.route("/api/game/load", methods=["POST"])
def api_load_game():
    """Restore a canonical archive into an interactive session for continuation."""
    data = request.get_json() or {}
    filepath = data.get("filepath")
    if not filepath:
        return jsonify({"error": "缺少棋谱路径"}), 400

    payload = FiveDPGN.load_archive(str(filepath))
    if payload is None:
        return jsonify({"error": f"无法加载棋局: {filepath}"}), 400

    mode = data.get("mode") or payload.metadata.get("mode") or "pvp"
    difficulty = (
        data.get("difficulty")
        or payload.metadata.get("difficulty")
        or "medium"
    )
    player_color = (
        data.get("player_color")
        or payload.metadata.get("player_color")
        or "white"
    )
    if mode == "pvp":
        instance = PvPMode(payload.engine)
    elif mode == "pve":
        instance = PvEMode(
            payload.engine,
            player_color=ChessColor(player_color),
            ai_difficulty=difficulty,
        )
    else:
        return jsonify({"error": f"棋局模式不能继续: {mode}"}), 400

    _game_session.update({
        "mode": mode,
        "mode_instance": instance,
        "ai_difficulty": difficulty,
        "player_color": player_color,
    })
    return jsonify({"success": True, "filepath": str(filepath), **get_game_state()})


@app.route("/api/game/legal_moves_5d", methods=["POST"])
def api_legal_moves_5d():
    """Return canonical legal moves from one selected BoardCoord/piece."""
    instance = _get_mode_instance()
    if instance is None or _game_session["mode"] == "replay":
        return jsonify({"error": "当前模式不能走子"}), 400

    data = request.get_json() or {}
    try:
        board_coord = _coord_from_payload(data.get("board"))
        position = MultiverseBoardView(
            instance.engine.timeline_manager.timelines
        ).resolve(board_coord)
        if position is None:
            return jsonify({"error": "棋盘不存在"}), 404

        moves = instance.engine.get_legal_moves(position)
        if data.get("x") is not None and data.get("y") is not None:
            x, y = int(data["x"]), int(data["y"])
            moves = [m for m in moves if (m.source.x, m.source.y) == (x, y)]
        return jsonify({"moves": [_move_payload(move) for move in moves]})
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.error(f"获取5D合法走子失败: {exc}")
        return jsonify({"error": str(exc)}), 500


@app.route("/api/game/move_5d", methods=["POST"])
def api_execute_move_5d():
    """Execute one exact canonical Move.

    PvP deliberately uses ``execute_action_move`` so the browser can make all
    required/optional moves and submit the complete Action explicitly.
    """
    instance = _get_mode_instance()
    if instance is None or _game_session["mode"] == "replay":
        return jsonify({"error": "当前模式不能走子"}), 400

    data = request.get_json() or {}
    try:
        move = _find_exact_legal_move(instance.engine, data)
        if move is None:
            return jsonify({"error": "非法或已过期的5D走子"}), 400

        if _game_session["mode"] == "pvp":
            success = instance.engine.execute_action_move(move)
        else:
            player = ChessColor(_game_session.get("player_color") or "white")
            if move.piece.color != player or instance.engine.current_turn_color != player:
                return jsonify({"error": "当前不是玩家回合"}), 400
            # PvE remains on the existing single-Move AI compatibility path.
            success = instance.engine.execute_move(move)

        if not success:
            return jsonify({"error": "引擎拒绝走子"}), 400
        return jsonify({"success": True, "move": _move_payload(move), **get_game_state()})
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.error(f"执行5D走子失败: {exc}")
        return jsonify({"error": str(exc)}), 500


@app.route("/api/game/submit_action", methods=["POST"])
def api_submit_action():
    instance = _get_mode_instance()
    if instance is None or _game_session["mode"] == "replay":
        return jsonify({"error": "当前模式不能提交Action"}), 400

    if not instance.engine.can_submit_action():
        return jsonify({"error": "The Present 尚未推进完成或王仍受威胁"}), 400
    if not instance.engine.submit_action():
        return jsonify({"error": "Action提交失败"}), 400
    return jsonify({"success": True, **get_game_state()})


# Compatibility endpoint used by older clients/tests.
@app.route("/api/game/moves")
def api_legal_moves():
    instance = _get_mode_instance()
    if instance is None:
        return jsonify({"error": "没有活跃游戏"}), 400
    if _game_session["mode"] == "replay":
        return jsonify({"moves": []})
    try:
        return jsonify({"moves": [_move_payload(m) for m in instance.engine.get_legal_moves()]})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# Compatibility endpoint for the old single-board browser client.
@app.route("/api/game/move", methods=["POST"])
def api_execute_move():
    instance = _get_mode_instance()
    if instance is None:
        return jsonify({"error": "没有活跃游戏"}), 400

    data = request.get_json() or {}
    fx, fy = data.get("from", [None, None])
    tx, ty = data.get("to", [None, None])
    if None in (fx, fy, tx, ty):
        return jsonify({"error": "缺少走子坐标"}), 400

    try:
        moves = instance.engine.get_legal_moves()
        match = next(
            (
                m for m in moves
                if (m.from_x, m.from_y, m.to_x, m.to_y) == (fx, fy, tx, ty)
            ),
            None,
        )
        if match is None:
            return jsonify({"error": "非法走子"}), 400
        success = instance.engine.execute_move(match)
        return jsonify({"success": success, **get_game_state()})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/game/select_square", methods=["POST"])
def api_select_square():
    """Legacy PvP single-board click API; the new UI does not use this route."""
    instance = _get_mode_instance()
    if instance is None or _game_session["mode"] != "pvp":
        return jsonify({"error": "非PvP模式"}), 400
    data = request.get_json() or {}
    x, y = data.get("x"), data.get("y")
    if x is None or y is None:
        return jsonify({"error": "缺少坐标"}), 400
    try:
        result = instance.select_square(int(x), int(y))
        return jsonify({"success": True, **get_game_state(), **result})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/game/ai_move", methods=["POST"])
def api_ai_move():
    """Let the legacy AI finish its current Action as far as it can."""
    instance = _get_mode_instance()
    if instance is None or _game_session["mode"] != "pve":
        return jsonify({"error": "非PvE模式"}), 400

    ai_color = instance.ai_color
    executed: list[dict[str, Any]] = []
    # Required boards normally bound Action length.  The guard prevents a
    # broken legacy AI from trapping the Web request forever.
    guard = 128
    try:
        while (
            guard > 0
            and instance.engine.game_state == GameState.PLAYING
            and instance.engine.current_turn_color == ai_color
        ):
            guard -= 1
            move = instance.ai.choose_move(instance.engine)
            if move is None or not instance.engine.execute_move(move):
                break
            executed.append(_move_payload(move))

        if guard == 0 and instance.engine.current_turn_color == ai_color:
            logger.warning("AI Action reached Web safety guard before submission")
        return jsonify({
            "success": bool(executed),
            "moves": executed,
            **get_game_state(),
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Replay API
# ---------------------------------------------------------------------------


@app.route("/api/replay/load", methods=["POST"])
def replay_load():
    instance = _get_mode_instance()
    if instance is None or _game_session["mode"] != "replay":
        engine = FiveDEngine()
        instance = ReplayMode(engine)
        _game_session["mode"] = "replay"
        _game_session["mode_instance"] = instance

    data = request.get_json() or {}
    filepath = data.get("filepath")
    if filepath:
        payload = FiveDPGN.load_archive(str(filepath))
        if payload is None:
            return jsonify({"error": f"无法加载棋谱: {filepath}"}), 400
        instance.load_from_engine(
            payload.engine,
            strict=payload.schema_version >= 2,
        )

    instance.start()
    return jsonify({"success": True, **get_game_state()})


@app.route("/api/replay/step", methods=["POST"])
def replay_step():
    instance = _get_mode_instance()
    if instance is None or _game_session["mode"] != "replay":
        return jsonify({"error": "非Replay模式"}), 400

    data = request.get_json() or {}
    action = data.get("action", "forward")
    handlers = {
        "forward": instance.step_forward,
        "backward": instance.step_backward,
        "start": instance.jump_to_start,
        "end": instance.jump_to_end,
        "toggle": instance.toggle_play,
    }
    if action == "jump":
        instance.jump_to(int(data.get("index", 0)))
    elif action in handlers:
        handlers[action]()
    return jsonify({"success": True, **get_game_state()})


@app.route("/api/replay/timeline", methods=["POST"])
def replay_timeline():
    """Compatibility route; the new multiverse canvas already shows every lane."""
    instance = _get_mode_instance()
    if instance is None or _game_session["mode"] != "replay":
        return jsonify({"error": "非Replay模式"}), 400
    timeline_id = int((request.get_json() or {}).get("timeline_id", 0))
    instance.select_timeline(timeline_id)
    return jsonify({"success": True, **get_game_state()})


# ---------------------------------------------------------------------------
# State serialization
# ---------------------------------------------------------------------------


def get_game_state() -> dict[str, Any]:
    instance = _get_mode_instance()
    if instance is None:
        return {"game_state": "WAITING"}

    engine = instance.engine
    mode = _game_session["mode"]
    interactive = mode in ("pvp", "pve")
    current_position = engine.get_current_position()
    summary = engine.get_game_summary()
    present = engine.get_present()

    required = list(engine.get_required_action_boards()) if interactive else []
    movable = (
        list(TimelineRules.movable_boards(
            engine.timeline_manager.timelines,
            engine.current_turn_color,
        ))
        if interactive and engine.game_state == GameState.PLAYING
        else []
    )

    action = engine.current_action
    action_payload = {
        "color": action.color.value if action else engine.current_turn_color.value,
        "move_count": len(action.moves) if action else 0,
        "can_submit": engine.can_submit_action() if interactive else False,
        "required_boards": [_coord_payload(coord) for coord in required],
        "movable_boards": [_coord_payload(coord) for coord in movable],
    }

    in_check = False
    if interactive and engine.game_state == GameState.PLAYING:
        try:
            in_check = RoyalRules(engine.timeline_manager.timelines).is_in_check(
                engine.current_turn_color
            )
        except Exception as exc:
            logger.warning(f"Web check indicator unavailable: {exc}")

    replay_data: dict[str, Any] = {}
    if mode == "replay":
        stats = instance.get_statistics()
        replay_data = {
            "current_index": stats["current_index"],
            "total_moves": stats["total_moves"],
            "is_playing": instance.is_playing,
            "selected_timeline_id": instance.selected_timeline_id,
            "statistics": stats,
        }

    pvp_data: dict[str, Any] = {}
    if mode == "pvp":
        pvp_data = {
            "selected_square": instance.selected_piece,
            "valid_moves": [_move_payload(m) for m in instance.legal_moves_for_selected],
        }

    last_move = _move_payload(engine.move_history[-1]) if engine.move_history else None
    present_payload = None
    if present is not None:
        present_payload = {
            "time_point": present.legacy_time_point,
            "turn": present.turn,
            "side": present.side.value,
            "boards": [_coord_payload(coord) for coord in present.boards],
        }

    return {
        "mode": mode,
        "game_state": engine.game_state.name,
        "turn": engine.current_turn_color.value,
        "move_counter": engine.move_counter,
        "move_history": [move.to_notation() for move in engine.move_history],
        "last_move": last_move,
        "active_timeline_id": engine.timeline_manager.active_timeline_id,
        "board": current_position.board,  # compatibility
        "boards": _board_payloads(engine, interactive=interactive),
        "timelines": _timeline_payloads(engine),
        "timeline_tree": engine.timeline_manager.build_tree(),
        "present": present_payload,
        "action": action_payload,
        "in_check": in_check,
        "summary": summary,
        "player_color": _game_session.get("player_color"),
        "ai_difficulty": _game_session.get("ai_difficulty"),
        **pvp_data,
        **replay_data,
    }


# ---------------------------------------------------------------------------
# Development server
# ---------------------------------------------------------------------------


def run_server(host: str = "127.0.0.1", port: int = 5000, debug: bool = True):
    logger.info(f"5D Chess Web 服务器启动: http://{host}:{port}")
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    run_server()
