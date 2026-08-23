"""
5D Chess - Web 服务器 (Flask)
"""
import sys
import json
from pathlib import Path
from flask import Flask, render_template, jsonify, request, send_from_directory

# 确保项目根目录在 path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.engine import FiveDEngine, Position, Move, TimelineManager
from src.modes import PvPMode, PvEMode, ReplayMode
from src.ai import create_ai
from src.utils.constants import ChessColor, GameState
from src.utils.logger import logger

app = Flask(__name__,
            template_folder=str(Path(__file__).parent / "templates"),
            static_folder=str(Path(__file__).parent / "static"))

# ============================================================
# 全局游戏会话（单实例，简化处理）
# ============================================================
_game_session = {
    "mode": None,          # "pvp" | "pve" | "replay"
    "mode_instance": None,
    "ai_difficulty": "medium",
    "player_color": None,
}


def _get_mode_instance():
    return _game_session.get("mode_instance")


# ============================================================
# 页面路由
# ============================================================

@app.route("/")
def index():
    """主页面"""
    return render_template("index.html")


# ============================================================
# 游戏 API
# ============================================================

@app.route("/api/game/start", methods=["POST"])
def start_game():
    """启动新游戏"""
    data = request.get_json() or {}
    mode = data.get("mode", "pvp")
    difficulty = data.get("difficulty", "medium")
    player_color = data.get("player_color", "white")

    try:
        engine = FiveDEngine()

        if mode == "pvp":
            instance = PvPMode(engine)
        elif mode == "pve":
            pc = ChessColor(player_color)
            instance = PvEMode(engine, player_color=pc, ai_difficulty=difficulty)
        elif mode == "replay":
            instance = ReplayMode(engine)
        else:
            return jsonify({"error": f"未知模式: {mode}"}), 400

        instance.start()
        _game_session["mode"] = mode
        _game_session["mode_instance"] = instance
        _game_session["ai_difficulty"] = difficulty
        _game_session["player_color"] = player_color

        return jsonify({"success": True, **get_game_state()})

    except Exception as e:
        logger.error(f"启动游戏失败: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/game/state")
def api_game_state():
    """获取当前游戏状态"""
    instance = _get_mode_instance()
    if instance is None:
        return jsonify({"error": "没有活跃游戏"}), 400
    return jsonify(get_game_state())


@app.route("/api/game/moves")
def api_legal_moves():
    """获取合法走子"""
    instance = _get_mode_instance()
    if instance is None:
        return jsonify({"error": "没有活跃游戏"}), 400

    try:
        if _game_session["mode"] == "pvp":
            moves = instance.engine.get_legal_moves()
        elif _game_session["mode"] == "pve":
            moves = instance.engine.get_legal_moves()
        elif _game_session["mode"] == "replay":
            return jsonify({"moves": []})
        else:
            return jsonify({"moves": []})

        return jsonify({
            "moves": [
                {
                    "from": [m.from_x, m.from_y],
                    "to": [m.to_x, m.to_y],
                    "from_timeline": m.from_timeline_id,
                    "to_timeline": m.to_timeline_id,
                    "from_time": m.from_time,
                    "to_time": m.to_time,
                    "is_branching": m.is_branching,
                    "is_cross_timeline": m.is_cross_timeline,
                    "piece": m.piece.piece_type.value,
                    "color": m.piece.color.value,
                    "notation": m.to_notation(),
                }
                for m in moves
            ]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/game/move", methods=["POST"])
def api_execute_move():
    """执行走子"""
    instance = _get_mode_instance()
    if instance is None:
        return jsonify({"error": "没有活跃游戏"}), 400

    data = request.get_json() or {}
    fx, fy = data.get("from", [None, None])
    tx, ty = data.get("to", [None, None])

    if None in (fx, fy, tx, ty):
        return jsonify({"error": "缺少走子坐标"}), 400

    try:
        if _game_session["mode"] == "pvp":
            # 通过 select_square 两步处理
            instance.select_square(fx, fy)
            result = instance.select_square(tx, ty)
            success = result.get("action") == "moved" and result.get("success", False)
        elif _game_session["mode"] == "pve":
            # 找到匹配的走子
            moves = instance.engine.get_legal_moves()
            match = None
            for m in moves:
                if m.from_x == fx and m.from_y == fy and m.to_x == tx and m.to_y == ty:
                    match = m
                    break
            if match:
                success = instance.handle_player_move(match)
            else:
                return jsonify({"error": "非法走子"}), 400
        else:
            return jsonify({"error": "当前模式不支持直接走子"}), 400

        return jsonify({"success": success, **get_game_state()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/game/ai_move", methods=["POST"])
def api_ai_move():
    """请求AI走子 (PvE模式)"""
    instance = _get_mode_instance()
    if instance is None or _game_session["mode"] != "pve":
        return jsonify({"error": "非PvE模式"}), 400

    try:
        move = instance.ai.choose_move(instance.engine)
        if move:
            instance.engine.execute_move(move)
            return jsonify({
                "success": True,
                "move": {
                    "from": [move.from_x, move.from_y],
                    "to": [move.to_x, move.to_y],
                    "notation": move.to_notation(),
                },
                **get_game_state(),
            })
        else:
            return jsonify({"success": False, "error": "AI无合法走子"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/game/select_square", methods=["POST"])
def api_select_square():
    """处理棋盘点击 (PvP模式)"""
    instance = _get_mode_instance()
    if instance is None or _game_session["mode"] != "pvp":
        return jsonify({"error": "非PvP模式"}), 400

    data = request.get_json() or {}
    x, y = data.get("x"), data.get("y")
    if x is None or y is None:
        return jsonify({"error": "缺少坐标"}), 400

    try:
        result = instance.select_square(x, y)
        return jsonify({"success": True, **get_game_state(), **result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================
# Replay API
# ============================================================

@app.route("/api/replay/load", methods=["POST"])
def replay_load():
    """加载棋谱"""
    instance = _get_mode_instance()
    if instance is None:
        engine = FiveDEngine()
        instance = ReplayMode(engine)
        _game_session["mode"] = "replay"
        _game_session["mode_instance"] = instance

    data = request.get_json() or {}
    filepath = data.get("filepath")

    if filepath:
        from src.data.pgn_parser import FiveDPGN
        moves, tl_mgr = FiveDPGN.load(filepath)
        if moves is not None:
            instance.load_from_moves(moves, tl_mgr)
        else:
            return jsonify({"error": f"无法加载棋谱: {filepath}"}), 400
    else:
        # 从上传的走子列表加载
        pass

    instance.start()
    return jsonify({"success": True, **get_game_state()})


@app.route("/api/replay/step", methods=["POST"])
def replay_step():
    """回放步进"""
    instance = _get_mode_instance()
    if instance is None or _game_session["mode"] != "replay":
        return jsonify({"error": "非Replay模式"}), 400

    data = request.get_json() or {}
    action = data.get("action", "forward")

    if action == "forward":
        instance.step_forward()
    elif action == "backward":
        instance.step_backward()
    elif action == "start":
        instance.jump_to_start()
    elif action == "end":
        instance.jump_to_end()
    elif action == "toggle":
        instance.toggle_play()
    elif action == "jump":
        idx = data.get("index", 0)
        instance.jump_to(idx)

    return jsonify({"success": True, **get_game_state()})


@app.route("/api/replay/timeline", methods=["POST"])
def replay_timeline():
    """切换查看的时间线"""
    instance = _get_mode_instance()
    if instance is None or _game_session["mode"] != "replay":
        return jsonify({"error": "非Replay模式"}), 400

    data = request.get_json() or {}
    tl_id = data.get("timeline_id", 0)
    instance.select_timeline(tl_id)
    return jsonify({"success": True, **get_game_state()})


# ============================================================
# 游戏状态序列化
# ============================================================

def get_game_state() -> dict:
    """获取完整游戏状态"""
    instance = _get_mode_instance()
    if instance is None:
        return {"game_state": "WAITING"}

    engine = instance.engine
    pos = engine.get_current_position()
    summary = engine.get_game_summary()

    # 棋盘数据
    board = pos.board

    # 当前时间线的最新棋盘
    active_tl = engine.timeline_manager.active_timeline_id

    # 构造时间线数据
    timelines = []
    for tid, tl in engine.timeline_manager.timelines.items():
        timeline_data = {
            "id": tid,
            "parent_id": tl.parent_id,
            "branch_turn": tl.branch_turn,
            "is_active": tl.is_active,
            "time_points": sorted(tl.positions.keys()),
            "latest_time": tl.latest_time,
        }
        timelines.append(timeline_data)

    # 时间线树
    tree = engine.timeline_manager.build_tree()

    # 合法走子
    legal_moves = []
    if _game_session["mode"] in ("pvp", "pve"):
        try:
            moves = engine.get_legal_moves()
            legal_moves = [
                {"from": [m.from_x, m.from_y], "to": [m.to_x, m.to_y],
                 "is_branching": m.is_branching, "notation": m.to_notation()}
                for m in moves
            ]
        except Exception:
            pass

    # Replay 特有数据
    replay_data = {}
    if _game_session["mode"] == "replay":
        stats = instance.get_statistics()
        replay_data = {
            "current_index": stats["current_index"],
            "total_moves": stats["total_moves"],
            "is_playing": instance.is_playing,
            "selected_timeline_id": instance.selected_timeline_id,
            "statistics": stats,
            "overview": {
                str(k): {"board": v["board"], "time_point": v["time_point"]}
                for k, v in instance.get_overview().items()
            },
        }

    # PvP 选中状态
    pvp_data = {}
    if _game_session["mode"] == "pvp":
        pvp_data = {
            "selected_square": instance.selected_piece,
            "valid_moves": [
                {"x": m.to_x, "y": m.to_y, "is_branching": m.is_branching,
                 "to_timeline": m.to_timeline_id, "to_time": m.to_time}
                for m in instance.legal_moves_for_selected
            ],
        }

    return {
        "mode": _game_session["mode"],
        "game_state": engine.game_state.name,
        "board": board,
        "turn": engine.current_turn_color.value,
        "active_timeline_id": active_tl,
        "move_counter": engine.move_counter,
        "move_history": [m.to_notation() for m in engine.move_history],
        "timelines": timelines,
        "timeline_tree": tree,
        "legal_moves": legal_moves,
        "summary": summary,
        **pvp_data,
        **replay_data,
    }


# ============================================================
# 启动
# ============================================================

def run_server(host: str = "127.0.0.1", port: int = 5000, debug: bool = True):
    """启动 Flask 开发服务器"""
    logger.info(f"5D Chess Web 服务器启动: http://{host}:{port}")
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    run_server()