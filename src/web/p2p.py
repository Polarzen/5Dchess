"""Online two-player room transport for the Web UI.

The engine remains authoritative on the host machine.  This module owns the
small, single-room HTTP transport around it, including token authentication
and bounded reconnect leases.
"""
from __future__ import annotations

from collections import deque
from copy import deepcopy
import ipaddress
import os
from pathlib import Path
import secrets
import threading
import time
from typing import Any, Callable

from flask import g, jsonify, request

from src.data.online_save import OnlineSaveStore
from src.engine import FiveDEngine
from src.engine.multiverse import MultiverseBoardView
from src.modes import PvPMode, ReplayMode
from src.utils.constants import ChessColor, GameState
from src.utils.logger import logger


_ROOM_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
PLAYER_LEASE_SECONDS = 8.0
# A tunnel reconnect can take minutes. Keep seats and the in-memory game
# through that outage, while the short lease still pauses offline play.
RECONNECT_GRACE_SECONDS = 10 * 60.0
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
    "save_failed": "存档失败，行动尚未提交。请房主检查 saves 目录权限和磁盘空间后重试。",
    "save_unavailable": "存档不存在或已损坏；未改变当前棋局。请检查项目 saves 目录。",
    "host_required": "恢复存档需由房主在本机 127.0.0.1 页面操作。",
    "action_conflict": "棋局已更新，请重新同步后再操作。",
    "game_finished": "这份棋局已结束，请选择观看回放。",
    "replay_unavailable": "存档历史无法完整重建，未改变当前棋局。请保留原文件。",
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
        now - float(lease.get("last_heartbeat", now)) <= PLAYER_LEASE_SECONDS
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
        online = age <= PLAYER_LEASE_SECONDS
        if online != bool(lease.get("online", False)):
            lease["online"] = online
            _room["version"] += 1

        if (
            color == ChessColor.BLACK
            and not online
            and age > PLAYER_LEASE_SECONDS + RECONNECT_GRACE_SECONDS
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
        > PLAYER_LEASE_SECONDS + RECONNECT_GRACE_SECONDS
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
    flask_app.config.setdefault("P2P_SAVE_DIR", os.environ.get(
        "FIVE_D_CHESS_SAVE_DIR", str(Path(__file__).resolve().parents[2] / "saves")))

    def save_store():
        return OnlineSaveStore(flask_app.config["P2P_SAVE_DIR"])

    def is_local_host():
        # cloudflared connects from loopback too. Reject forwarded requests,
        # public Host names and cross-origin browser requests as well.
        try:
            loopback = ipaddress.ip_address(request.remote_addr or "").is_loopback
        except ValueError:
            return False
        hostname = request.host.split(":")[0].lower()
        if request.host.startswith("["):
            hostname = request.host.split("]")[0] + "]"
        return (loopback and hostname in {"localhost", "127.0.0.1", "[::1]"}
                and not any(name.lower().startswith(("x-forwarded-", "cf-"))
                            or name.lower() == "forwarded" for name in request.headers.keys())
                and request.headers.get("Sec-Fetch-Site") not in {"cross-site", "same-site"}
                and request.headers.get("Origin", request.host_url.rstrip("/"))
                == request.host_url.rstrip("/"))

    def open_room(engine, save_id, saved):
        global _room
        token = _new_player_token()
        _room = {
            "code": _new_room_code(),
            "players": {"white": token, "black": None},
            "leases": {"white": {"last_heartbeat": _now(), "online": True}, "black": None},
            "version": 1, "save_id": save_id, "saved": saved, "save_error": False,
        }
        game_session.update({"mode": "pvp", "mode_instance": PvPMode(engine),
                             "ai_difficulty": "medium", "player_color": None})
        return jsonify({"success": True, "room_code": _room["code"],
                        "player_token": token, **room_state_for(ChessColor.WHITE)})

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
            "retention_seconds": PLAYER_LEASE_SECONDS + RECONNECT_GRACE_SECONDS,
            "opponent_retention_remaining": max(0.0,
                PLAYER_LEASE_SECONDS + RECONNECT_GRACE_SECONDS
                - (_now() - _lease(_room, opponent)["last_heartbeat"]))
                if opponent_present else None,
            "saved": _room.get("saved"),
            "save_error": _room.get("save_error", False),
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
        is_legacy_request = request.path.startswith("/api/game/") or request.path.startswith(
            "/api/replay/"
        )
        if is_legacy_request:
            # Hold the same room lock from the lifecycle check through the
            # complete legacy request.  The teardown hook releases it even
            # when this hook returns the 409 guard response.
            _room_lock.acquire()
            g.p2p_legacy_lock_held = True
            _cleanup_lifecycle(game_session)
            if _room is not None:
                return _error("p2p_room_active", 409)
            return None

        with _room_lock:
            _cleanup_lifecycle(game_session)
        return None

    @flask_app.teardown_request
    def release_legacy_room_lock(_exception=None):
        if getattr(g, "p2p_legacy_lock_held", False):
            g.p2p_legacy_lock_held = False
            _room_lock.release()

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
                save_id = secrets.token_hex(16)
                saved = save_store().save(save_id, engine)
                return open_room(engine, save_id, saved)
            except OSError:
                return _error("save_failed", 503)
            except Exception:
                return internal_error("P2P room creation failed")

    @flask_app.route("/api/p2p/saves", methods=["GET"])
    def p2p_saved_games():
        if not is_local_host():
            return _error("host_required", 403)
        with _room_lock:
            try:
                return jsonify(save_store().catalog())
            except OSError:
                return _error("save_unavailable", 503)

    @flask_app.route("/api/p2p/restore", methods=["POST"])
    def p2p_restore_game():
        if not is_local_host():
            return _error("host_required", 403)
        data, error = request_object()
        if error:
            return error
        with _room_lock:
            if _room is not None:
                return _error("room_full", 409)
            try:
                save_id = data.get("save_id")
                engine, saved = save_store().load(save_id)
            except (OSError, ValueError, KeyError, TypeError):
                return _error("save_unavailable", 409)
            if engine.game_state != GameState.PLAYING:
                return _error("game_finished", 409)
            return open_room(engine, save_id, saved)

    @flask_app.route("/api/p2p/replay", methods=["POST"])
    def p2p_replay_saved_game():
        if not is_local_host():
            return _error("host_required", 403)
        data, error = request_object()
        if error:
            return error
        with _room_lock:
            if _room is not None:
                return _error("room_full", 409)
            try:
                engine, saved = save_store().load(data.get("save_id"))
            except (OSError, ValueError, KeyError, TypeError):
                return _error("save_unavailable", 409)
            # Build and verify all snapshots before replacing any live session.
            candidate = ReplayMode()
            try:
                candidate.load_from_engine(engine, strict=True)
                candidate.start()
            except (ValueError, KeyError, TypeError):
                return _error("replay_unavailable", 409)
            game_session.update({"mode": "replay", "mode_instance": candidate,
                                 "ai_difficulty": "medium", "player_color": None})
            return jsonify({"success": True, "saved": saved, **get_game_state()})

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

                if data.get("x") is not None and data.get("y") is not None:
                    x, y = int(data["x"]), int(data["y"])
                    moves = engine.get_legal_moves_from_square(position, x, y)
                else:
                    moves = engine.get_legal_moves(position)
                return jsonify({
                    "moves": [move_payload(move) for move in moves],
                    "state_version": _room["version"],
                })
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
                    "move": move_payload(engine.move_history[-1]),
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
                expected = data.get("expected_action_counter")
                if expected is not None and expected != len(engine.action_history):
                    return _error("action_conflict", 409)
                if not engine.can_submit_action():
                    return _error("action_not_submittable", 409)
                # Publish the new turn only after its checkpoint is on disk.
                # A disk error leaves the original pending Action retryable.
                candidate = deepcopy(engine)
                if not candidate.submit_action():
                    return _error("action_not_submittable", 409)
                assert _room is not None
                try:
                    saved = save_store().save(_room["save_id"], candidate)
                except OSError:
                    _room["save_error"] = True
                    _room["version"] += 1
                    return _error("save_failed", 503)
                instance.engine = candidate
                _room.update(saved=saved, save_error=False)
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
