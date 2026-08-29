"""Online two-player room transport for the Web UI.

The engine remains authoritative on the host machine.  This module owns the
small, single-room HTTP transport around it, including token authentication
and bounded reconnect leases.
"""
from __future__ import annotations

from collections import deque
import secrets
import threading
import time
from typing import Any, Callable

from flask import jsonify, request

from src.engine import FiveDEngine
from src.engine.multiverse import MultiverseBoardView
from src.modes import PvPMode
from src.utils.constants import ChessColor, GameState
from src.utils.logger import logger


_ROOM_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
PLAYER_LEASE_TIMEOUT = 8.0
PLAYER_RECONNECT_GRACE = 30.0
_EXPIRED_ROOM_LIMIT = 64
_ERROR_MESSAGES = {
    "room_not_found": "房间不存在",
    "room_expired": "房间已过期",
    "invalid_token": "玩家 token 无效",
    "room_full": "房间已满",
    "opponent_not_connected": "对手尚未连接",
    "opponent_offline": "对手暂时离线",
    "not_your_turn": "不是你的回合",
    "illegal_move": "非法走子",
    "action_not_submittable": "Action 尚不能 Submit",
    "invalid_request": "请求格式无效",
    "p2p_room_active": "在线 P2P 房间进行中，legacy mutation 已阻断",
    "internal_error": "服务器内部错误",
}

_room_lock = threading.RLock()
_room: dict[str, Any] | None = None
_expired_room_codes: deque[str] = deque(maxlen=_EXPIRED_ROOM_LIMIT)

# Tests can replace this callable with a fake monotonic clock.
_clock: Callable[[], float] = time.monotonic


def _now() -> float:
    return float(_clock())


def _new_room_code(length: int = 6) -> str:
    return "".join(secrets.choice(_ROOM_ALPHABET) for _ in range(length))


def _new_player_token() -> str:
    return secrets.token_urlsafe(32)


def _safe_compare(candidate: str, expected: str | None) -> bool:
    return bool(expected) and secrets.compare_digest(candidate, expected)


def _error(code: str, status: int):
    """Return the stable P2P error envelope."""
    return jsonify({"error": _ERROR_MESSAGES[code], "code": code}), status


def _reset_game_session(game_session: dict[str, Any]) -> None:
    game_session.update({
        "mode": None,
        "mode_instance": None,
        "ai_difficulty": "medium",
        "player_color": None,
    })


def _remember_expired(code: str) -> None:
    if code not in _expired_room_codes:
        _expired_room_codes.append(code)


def _is_expired_code(code: str) -> bool:
    return bool(code) and code in _expired_room_codes


def _lease(room: dict[str, Any], color: ChessColor) -> dict[str, Any] | None:
    return room.get("leases", {}).get(color.value)


def _player_connected(room: dict[str, Any], color: ChessColor, now: float) -> bool:
    token = room.get("players", {}).get(color.value)
    lease = _lease(room, color)
    if token is None or lease is None:
        return False
    return bool(lease.get("online", False)) and (
        now - float(lease.get("last_heartbeat", now)) <= PLAYER_LEASE_TIMEOUT
    )


def _set_player_heartbeat(
    room: dict[str, Any], color: ChessColor, now: float
) -> None:
    lease = _lease(room, color)
    if lease is None:
        return
    was_online = bool(lease.get("online", False))
    lease["last_heartbeat"] = now
    if not was_online:
        lease["online"] = True
        room["version"] += 1


def _cleanup_lifecycle(game_session: dict[str, Any], now: float | None = None) -> None:
    """Observe lease transitions and lazily release/expire stale rooms.

    The lock is owned by callers.  A transition is recorded only when it is
    first observed, making repeated polling idempotent.
    """
    global _room
    if _room is None:
        return
    now = _now() if now is None else now

    for color in (ChessColor.WHITE, ChessColor.BLACK):
        token = _room["players"].get(color.value)
        lease = _lease(_room, color)
        if token is None or lease is None:
            continue

        age = now - float(lease["last_heartbeat"])
        online = age <= PLAYER_LEASE_TIMEOUT
        if online != bool(lease.get("online", False)):
            lease["online"] = online
            _room["version"] += 1

        if (
            color == ChessColor.BLACK
            and not online
            and age > PLAYER_LEASE_TIMEOUT + PLAYER_RECONNECT_GRACE
        ):
            _room["players"][color.value] = None
            _room["leases"][color.value] = None
            _room["version"] += 1

    white_lease = _lease(_room, ChessColor.WHITE)
    if (
        _room is not None
        and _room["players"].get(ChessColor.WHITE.value) is not None
        and white_lease is not None
        and now - float(white_lease["last_heartbeat"])
        > PLAYER_LEASE_TIMEOUT + PLAYER_RECONNECT_GRACE
    ):
        code = _room["code"]
        _remember_expired(code)
        _room = None
        _reset_game_session(game_session)


def _room_is_active(game_session: dict[str, Any] | None = None) -> bool:
    with _room_lock:
        if game_session is not None:
            _cleanup_lifecycle(game_session)
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

    def request_object() -> tuple[dict[str, Any] | None, Any | None]:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return None, _error("invalid_request", 400)
        return data, None

    def room_state_for(color: ChessColor) -> dict[str, Any]:
        assert _room is not None
        instance = game_session.get("mode_instance")
        if instance is None:
            raise RuntimeError("P2P game session is unavailable")
        engine = instance.engine
        state = get_game_state()
        state["mode"] = "p2p"
        state["player_color"] = color.value

        opponent = (
            ChessColor.BLACK if color == ChessColor.WHITE else ChessColor.WHITE
        )
        opponent_present = _room["players"].get(opponent.value) is not None
        opponent_connected = _player_connected(_room, opponent, _now())
        if not opponent_present:
            opponent_status = "not_connected"
        elif opponent_connected:
            opponent_status = "connected"
        else:
            opponent_status = "offline"

        state["p2p"] = {
            "room_code": _room["code"],
            "player_color": color.value,
            "opponent_present": opponent_present,
            "opponent_connected": opponent_connected,
            "opponent_status": opponent_status,
            "can_act": (
                opponent_present
                and opponent_connected
                and engine.game_state == GameState.PLAYING
                and engine.current_turn_color == color
            ),
            "state_version": _room["version"],
        }
        return state

    def authenticate(
        data: dict[str, Any],
    ) -> tuple[ChessColor | None, Any | None]:
        room_code = str(data.get("room_code") or "").strip().upper()
        token = data.get("player_token")
        if _room is None:
            expired = _is_expired_code(room_code)
            return None, _error("room_expired" if expired else "room_not_found", 410 if expired else 404)
        if room_code != _room["code"]:
            expired = _is_expired_code(room_code)
            return None, _error("room_expired" if expired else "room_not_found", 410 if expired else 404)
        if not isinstance(token, str) or not token:
            return None, _error("invalid_token", 401)

        for color in (ChessColor.WHITE, ChessColor.BLACK):
            expected = _room["players"].get(color.value)
            if _safe_compare(token, expected):
                _set_player_heartbeat(_room, color, _now())
                return color, None
        return None, _error("invalid_token", 401)

    def require_ready_turn(color: ChessColor):
        assert _room is not None
        opponent = (
            ChessColor.BLACK if color == ChessColor.WHITE else ChessColor.WHITE
        )
        if _room["players"].get(opponent.value) is None:
            return _error("opponent_not_connected", 409)
        if not _player_connected(_room, opponent, _now()):
            return _error("opponent_offline", 409)

        instance = game_session.get("mode_instance")
        if instance is None:
            return _error("action_not_submittable", 409)
        if instance.engine.game_state != GameState.PLAYING:
            return _error("action_not_submittable", 409)
        if instance.engine.current_turn_color != color:
            return _error("not_your_turn", 409)
        return None

    def internal_error(log_message: str):
        # Never include request data or exception text: either may contain a
        # player token supplied by an embedding caller.
        logger.error(log_message)
        return _error("internal_error", 500)

    @flask_app.before_request
    def protect_single_session_while_p2p_active():
        """Clean stale lifecycle state and guard legacy mutation endpoints."""
        with _room_lock:
            _cleanup_lifecycle(game_session)
            active = _room is not None
        if not active:
            return None
        if request.path.startswith("/api/game/") or request.path.startswith("/api/replay/"):
            return _error("p2p_room_active", 409)
        return None

    @flask_app.route("/api/p2p/create", methods=["POST"])
    def p2p_create_room():
        global _room
        data, error = request_object()
        if error:
            return error
        with _room_lock:
            _cleanup_lifecycle(game_session)
            if _room is not None:
                return _error("room_full", 409)

            try:
                engine = FiveDEngine()
                instance = PvPMode(engine)
                instance.start()
                now = _now()
                white_token = _new_player_token()
                _room = {
                    "code": _new_room_code(),
                    "players": {
                        ChessColor.WHITE.value: white_token,
                        ChessColor.BLACK.value: None,
                    },
                    "leases": {
                        ChessColor.WHITE.value: {
                            "last_heartbeat": now,
                            "online": True,
                        },
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
                logger.info(f"P2P room created: {_room['code']}")
                return jsonify({
                    "success": True,
                    "room_code": _room["code"],
                    "player_token": white_token,
                    **room_state_for(ChessColor.WHITE),
                })
            except Exception:
                return internal_error("P2P room creation failed")

    @flask_app.route("/api/p2p/join", methods=["POST"])
    def p2p_join_room():
        global _room
        data, error = request_object()
        if error:
            return error
        with _room_lock:
            _cleanup_lifecycle(game_session)
            room_code = str(data.get("room_code") or "").strip().upper()
            if _room is None:
                expired = _is_expired_code(room_code)
                return _error("room_expired" if expired else "room_not_found", 410 if expired else 404)
            if room_code != _room["code"]:
                expired = _is_expired_code(room_code)
                return _error("room_expired" if expired else "room_not_found", 410 if expired else 404)

            reconnect_token = data.get("player_token")
            if reconnect_token is not None and not isinstance(reconnect_token, str):
                return _error("invalid_token", 401)
            if reconnect_token:
                for color in (ChessColor.WHITE, ChessColor.BLACK):
                    expected = _room["players"].get(color.value)
                    if _safe_compare(reconnect_token, expected):
                        _set_player_heartbeat(_room, color, _now())
                        try:
                            return jsonify({
                                "success": True,
                                "room_code": _room["code"],
                                "player_token": reconnect_token,
                                "reconnected": True,
                                **room_state_for(color),
                            })
                        except Exception:
                            return internal_error("P2P reconnect failed")
                return _error("invalid_token", 401)

            if _room["players"][ChessColor.BLACK.value] is not None:
                return _error("room_full", 409)

            try:
                black_token = _new_player_token()
                _room["players"][ChessColor.BLACK.value] = black_token
                _room["leases"][ChessColor.BLACK.value] = {
                    "last_heartbeat": _now(),
                    "online": True,
                }
                _room["version"] += 1
                logger.info(f"P2P room joined: {_room['code']} / black")
                return jsonify({
                    "success": True,
                    "room_code": _room["code"],
                    "player_token": black_token,
                    "reconnected": False,
                    **room_state_for(ChessColor.BLACK),
                })
            except Exception:
                return internal_error("P2P join failed")

    @flask_app.route("/api/p2p/state", methods=["POST"])
    def p2p_state():
        data, error = request_object()
        if error:
            return error
        with _room_lock:
            color, auth_error = authenticate(data)
            if auth_error:
                return auth_error
            try:
                return jsonify(room_state_for(color))
            except Exception:
                return internal_error("P2P state failed")

    @flask_app.route("/api/p2p/legal_moves", methods=["POST"])
    def p2p_legal_moves():
        data, error = request_object()
        if error:
            return error
        with _room_lock:
            color, auth_error = authenticate(data)
            if auth_error:
                return auth_error
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
                    return _error("invalid_request", 400)

                moves = engine.get_legal_moves(position)
                if data.get("x") is not None and data.get("y") is not None:
                    x, y = int(data["x"]), int(data["y"])
                    moves = [
                        move for move in moves
                        if (move.source.x, move.source.y) == (x, y)
                    ]
                return jsonify({"moves": [move_payload(move) for move in moves]})
            except (TypeError, ValueError):
                return _error("invalid_request", 400)
            except Exception:
                return internal_error("P2P legal-move lookup failed")

    @flask_app.route("/api/p2p/move", methods=["POST"])
    def p2p_execute_move():
        data, error = request_object()
        if error:
            return error
        with _room_lock:
            color, auth_error = authenticate(data)
            if auth_error:
                return auth_error
            turn_error = require_ready_turn(color)
            if turn_error:
                return turn_error

            try:
                instance = game_session["mode_instance"]
                engine = instance.engine
                move = find_exact_legal_move(engine, data)
                if move is None or move.piece.color != color:
                    return _error("illegal_move", 400)
                if not engine.execute_action_move(move):
                    return _error("illegal_move", 400)

                assert _room is not None
                _room["version"] += 1
                return jsonify({
                    "success": True,
                    "move": move_payload(move),
                    **room_state_for(color),
                })
            except (TypeError, ValueError):
                return _error("illegal_move", 400)
            except Exception:
                return internal_error("P2P move execution failed")

    @flask_app.route("/api/p2p/submit", methods=["POST"])
    def p2p_submit_action():
        data, error = request_object()
        if error:
            return error
        with _room_lock:
            color, auth_error = authenticate(data)
            if auth_error:
                return auth_error
            turn_error = require_ready_turn(color)
            if turn_error:
                return turn_error

            try:
                instance = game_session["mode_instance"]
                engine = instance.engine
                if not engine.can_submit_action() or not engine.submit_action():
                    return _error("action_not_submittable", 409)

                assert _room is not None
                _room["version"] += 1
                return jsonify({"success": True, **room_state_for(color)})
            except Exception:
                return internal_error("P2P action submission failed")

    @flask_app.route("/api/p2p/leave", methods=["POST"])
    def p2p_leave_room():
        global _room
        data, error = request_object()
        if error:
            return error
        with _room_lock:
            color, auth_error = authenticate(data)
            if auth_error:
                return auth_error

            try:
                assert _room is not None
                code = _room["code"]
                if color == ChessColor.WHITE:
                    _room = None
                    _reset_game_session(game_session)
                    logger.info(f"P2P room closed: {code}")
                    return jsonify({"success": True, "closed": True})

                _room["players"][ChessColor.BLACK.value] = None
                _room["leases"][ChessColor.BLACK.value] = None
                _room["version"] += 1
                logger.info(f"P2P player left: {code} / black")
                return jsonify({"success": True, "closed": False})
            except Exception:
                return internal_error("P2P leave failed")
