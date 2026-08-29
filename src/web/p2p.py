"""Online two-player room transport for the Web UI.

The game engine remains authoritative on the host machine.  A single room is
exposed through token-authenticated HTTP endpoints, which is intentionally a
small fit for the project's existing single-session Flask architecture and for
sharing that host through Cloudflare Tunnel.
"""
from __future__ import annotations

import secrets
import threading
from typing import Any, Callable

from flask import jsonify, request

from src.engine import FiveDEngine
from src.engine.multiverse import MultiverseBoardView
from src.modes import PvPMode
from src.utils.constants import ChessColor, GameState
from src.utils.logger import logger


_ROOM_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_room_lock = threading.RLock()
_room: dict[str, Any] | None = None


def _new_room_code(length: int = 6) -> str:
    return "".join(secrets.choice(_ROOM_ALPHABET) for _ in range(length))


def _new_player_token() -> str:
    return secrets.token_urlsafe(32)


def _safe_compare(candidate: str, expected: str | None) -> bool:
    return bool(expected) and secrets.compare_digest(candidate, expected)


def _room_is_active() -> bool:
    return _room is not None


def register_p2p_routes(
    flask_app,
    game_session: dict[str, Any],
    *,
    get_game_state: Callable[[], dict[str, Any]],
    coord_from_payload: Callable[[dict[str, Any] | None], Any],
    find_exact_legal_move: Callable[[FiveDEngine, dict[str, Any]], Any],
    move_payload: Callable[[Any], dict[str, Any]],
) -> None:
    """Register the single-room P2P transport exactly once."""
    if flask_app.extensions.get("five_d_p2p_registered"):
        return
    flask_app.extensions["five_d_p2p_registered"] = True

    def room_state_for(color: ChessColor) -> dict[str, Any]:
        assert _room is not None
        instance = game_session["mode_instance"]
        engine = instance.engine
        state = get_game_state()
        state["mode"] = "p2p"
        state["player_color"] = color.value
        state["p2p"] = {
            "room_code": _room["code"],
            "player_color": color.value,
            "opponent_connected": _room["players"][ChessColor.BLACK.value] is not None,
            "can_act": (
                _room["players"][ChessColor.BLACK.value] is not None
                and engine.game_state == GameState.PLAYING
                and engine.current_turn_color == color
            ),
            "state_version": _room["version"],
        }
        return state

    def authenticate(data: dict[str, Any]) -> tuple[ChessColor | None, Any | None]:
        if _room is None:
            return None, (jsonify({"error": "当前没有在线房间"}), 404)

        room_code = str(data.get("room_code") or "").strip().upper()
        token = str(data.get("player_token") or "")
        if room_code != _room["code"]:
            return None, (jsonify({"error": "房间不存在或房间码错误"}), 404)

        for color in (ChessColor.WHITE, ChessColor.BLACK):
            expected = _room["players"].get(color.value)
            if _safe_compare(token, expected):
                return color, None
        return None, (jsonify({"error": "玩家令牌无效，请重新加入房间"}), 401)

    def require_ready_turn(color: ChessColor):
        assert _room is not None
        instance = game_session.get("mode_instance")
        if instance is None:
            return jsonify({"error": "在线棋局不存在"}), 409
        if _room["players"][ChessColor.BLACK.value] is None:
            return jsonify({"error": "等待第二位玩家加入房间"}), 409
        if instance.engine.game_state != GameState.PLAYING:
            return jsonify({"error": "棋局已经结束"}), 409
        if instance.engine.current_turn_color != color:
            return jsonify({"error": "当前是对手回合"}), 409
        return None

    @flask_app.before_request
    def protect_single_session_while_p2p_active():
        """Prevent legacy unauthenticated endpoints from mutating an online room."""
        if not _room_is_active():
            return None
        if request.path.startswith("/api/game/") or request.path.startswith("/api/replay/"):
            return jsonify({
                "error": "在线房间进行中；请使用 P2P 房间接口，避免绕过玩家身份校验"
            }), 409
        return None

    @flask_app.route("/api/p2p/create", methods=["POST"])
    def p2p_create_room():
        global _room
        with _room_lock:
            if _room is not None:
                return jsonify({
                    "error": "已有在线房间。房主请先返回菜单关闭旧房间，或重启服务。"
                }), 409

            engine = FiveDEngine()
            instance = PvPMode(engine)
            instance.start()
            white_token = _new_player_token()
            _room = {
                "code": _new_room_code(),
                "players": {
                    ChessColor.WHITE.value: white_token,
                    ChessColor.BLACK.value: None,
                },
                "version": 1,
            }
            game_session.update({
                "mode": "pvp",
                "mode_instance": instance,
                "ai_difficulty": "medium",
                "player_color": None,
            })
            logger.info(f"P2P房间创建: {_room['code']}")
            return jsonify({
                "success": True,
                "room_code": _room["code"],
                "player_token": white_token,
                **room_state_for(ChessColor.WHITE),
            })

    @flask_app.route("/api/p2p/join", methods=["POST"])
    def p2p_join_room():
        global _room
        data = request.get_json() or {}
        with _room_lock:
            if _room is None:
                return jsonify({"error": "当前没有可加入的在线房间"}), 404

            room_code = str(data.get("room_code") or "").strip().upper()
            if room_code != _room["code"]:
                return jsonify({"error": "房间不存在或房间码错误"}), 404

            # A stored token allows either player to reconnect after a refresh.
            reconnect_token = str(data.get("player_token") or "")
            if reconnect_token:
                for color in (ChessColor.WHITE, ChessColor.BLACK):
                    expected = _room["players"].get(color.value)
                    if _safe_compare(reconnect_token, expected):
                        return jsonify({
                            "success": True,
                            "room_code": _room["code"],
                            "player_token": reconnect_token,
                            "reconnected": True,
                            **room_state_for(color),
                        })

            if _room["players"][ChessColor.BLACK.value] is not None:
                return jsonify({"error": "房间已满"}), 409

            black_token = _new_player_token()
            _room["players"][ChessColor.BLACK.value] = black_token
            _room["version"] += 1
            logger.info(f"P2P房间加入: {_room['code']} / black")
            return jsonify({
                "success": True,
                "room_code": _room["code"],
                "player_token": black_token,
                "reconnected": False,
                **room_state_for(ChessColor.BLACK),
            })

    @flask_app.route("/api/p2p/state", methods=["POST"])
    def p2p_state():
        data = request.get_json() or {}
        with _room_lock:
            color, error = authenticate(data)
            if error:
                return error
            return jsonify(room_state_for(color))

    @flask_app.route("/api/p2p/legal_moves", methods=["POST"])
    def p2p_legal_moves():
        data = request.get_json() or {}
        with _room_lock:
            color, error = authenticate(data)
            if error:
                return error
            turn_error = require_ready_turn(color)
            if turn_error:
                return turn_error

            try:
                instance = game_session["mode_instance"]
                engine = instance.engine
                board_coord = coord_from_payload(data.get("board"))
                position = MultiverseBoardView(
                    engine.timeline_manager.timelines
                ).resolve(board_coord)
                if position is None:
                    return jsonify({"error": "棋盘不存在"}), 404

                moves = engine.get_legal_moves(position)
                if data.get("x") is not None and data.get("y") is not None:
                    x, y = int(data["x"]), int(data["y"])
                    moves = [
                        move for move in moves
                        if (move.source.x, move.source.y) == (x, y)
                    ]
                return jsonify({"moves": [move_payload(move) for move in moves]})
            except (TypeError, ValueError) as exc:
                return jsonify({"error": str(exc)}), 400
            except Exception as exc:
                logger.error(f"P2P获取合法走子失败: {exc}")
                return jsonify({"error": str(exc)}), 500

    @flask_app.route("/api/p2p/move", methods=["POST"])
    def p2p_execute_move():
        data = request.get_json() or {}
        with _room_lock:
            color, error = authenticate(data)
            if error:
                return error
            turn_error = require_ready_turn(color)
            if turn_error:
                return turn_error

            try:
                instance = game_session["mode_instance"]
                engine = instance.engine
                move = find_exact_legal_move(engine, data)
                if move is None:
                    return jsonify({"error": "非法或已过期的5D走子"}), 400
                if move.piece.color != color:
                    return jsonify({"error": "不能移动对手棋子"}), 403
                if not engine.execute_action_move(move):
                    return jsonify({"error": "引擎拒绝走子"}), 400

                assert _room is not None
                _room["version"] += 1
                return jsonify({
                    "success": True,
                    "move": move_payload(move),
                    **room_state_for(color),
                })
            except (TypeError, ValueError) as exc:
                return jsonify({"error": str(exc)}), 400
            except Exception as exc:
                logger.error(f"P2P执行走子失败: {exc}")
                return jsonify({"error": str(exc)}), 500

    @flask_app.route("/api/p2p/submit", methods=["POST"])
    def p2p_submit_action():
        data = request.get_json() or {}
        with _room_lock:
            color, error = authenticate(data)
            if error:
                return error
            turn_error = require_ready_turn(color)
            if turn_error:
                return turn_error

            instance = game_session["mode_instance"]
            engine = instance.engine
            if not engine.can_submit_action():
                return jsonify({"error": "The Present 尚未推进完成或王仍受威胁"}), 400
            if not engine.submit_action():
                return jsonify({"error": "Action提交失败"}), 400

            assert _room is not None
            _room["version"] += 1
            return jsonify({"success": True, **room_state_for(color)})

    @flask_app.route("/api/p2p/leave", methods=["POST"])
    def p2p_leave_room():
        global _room
        data = request.get_json() or {}
        with _room_lock:
            color, error = authenticate(data)
            if error:
                return error

            if color == ChessColor.WHITE:
                code = _room["code"] if _room else "?"
                _room = None
                game_session.update({
                    "mode": None,
                    "mode_instance": None,
                    "ai_difficulty": "medium",
                    "player_color": None,
                })
                logger.info(f"P2P房间关闭: {code}")
                return jsonify({"success": True, "closed": True})

            assert _room is not None
            _room["players"][ChessColor.BLACK.value] = None
            _room["version"] += 1
            logger.info(f"P2P玩家离开: {_room['code']} / black")
            return jsonify({"success": True, "closed": False})
