"""
5D Chess - 异步数据库写入器
不阻塞游戏主循环，通过队列+工作线程批量写入
"""
from __future__ import annotations

import threading
import time
from queue import Queue, Empty
from src.config import ASYNC_WRITE_INTERVAL, ASYNC_QUEUE_MAXSIZE
from src.data.db import db
from src.utils.logger import logger


class AsyncDBWriter:
    """异步数据库写入器（单例）"""

    _instance: "AsyncDBWriter" | None = None

    def __new__(cls) -> "AsyncDBWriter":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._queue: Queue = Queue(maxsize=ASYNC_QUEUE_MAXSIZE)
        self._worker: threading.Thread | None = None
        self._running = False
        self._batch_buffer: list[tuple[str, dict]] = []
        self._batch_size = 50
        self._last_flush = time.time()

    def start(self):
        """启动工作线程"""
        if self._running:
            return
        self._running = True
        self._worker = threading.Thread(target=self._run, daemon=True, name="AsyncDBWriter")
        self._worker.start()
        logger.info("异步写入器启动")

    def stop(self):
        """停止工作线程"""
        self._running = False
        self._flush_buffer()
        if self._worker:
            self._worker.join(timeout=5.0)
        logger.info("异步写入器停止")

    def write_move(self, move_data: dict):
        """写入走子"""
        self._enqueue("move", move_data)

    def write_position(self, pos_data: dict):
        """写入棋盘快照"""
        self._enqueue("position", pos_data)

    def write_game(self, game_data: dict):
        """写入游戏记录"""
        self._enqueue("game", game_data)

    def write_timeline(self, timeline_data: dict):
        """写入时间线"""
        self._enqueue("timeline", timeline_data)

    def write_stats(self, stats_data: dict):
        """写入统计"""
        self._enqueue("stats", stats_data)

    def _enqueue(self, op: str, data: dict):
        """入队"""
        try:
            self._queue.put_nowait((op, data))
        except Exception:
            logger.warning("异步写入队列已满，丢弃数据")

    def _run(self):
        """工作线程主循环"""
        while self._running:
            try:
                op, data = self._queue.get(timeout=0.5)
                self._batch_buffer.append((op, data))

                if len(self._batch_buffer) >= self._batch_size:
                    self._flush_buffer()
                elif time.time() - self._last_flush > ASYNC_WRITE_INTERVAL:
                    self._flush_buffer()

            except Empty:
                if self._batch_buffer:
                    self._flush_buffer()
            except Exception as e:
                logger.error(f"异步写入异常: {e}")

    def _flush_buffer(self):
        """批量写入缓冲区"""
        if not self._batch_buffer:
            return

        buffer = self._batch_buffer[:]
        self._batch_buffer.clear()
        self._last_flush = time.time()

        if not db.is_available:
            return

        try:
            # 按操作类型分组
            moves = [d for op, d in buffer if op == "move"]
            positions = [d for op, d in buffer if op == "position"]
            games = [d for op, d in buffer if op == "game"]
            timelines = [d for op, d in buffer if op == "timeline"]
            stats = [d for op, d in buffer if op == "stats"]

            if games:
                self._insert_games(games)
            if timelines:
                self._insert_timelines(timelines)
            if moves:
                self._insert_moves(moves)
            if positions:
                self._insert_positions(positions)
            if stats:
                self._insert_stats(stats)

            logger.debug(f"批量写入完成: {len(buffer)} 条")
        except Exception as e:
            logger.error(f"批量写入失败: {e}")

    def _insert_games(self, games: list[dict]):
        sql = """INSERT INTO games (mode, player_white, player_black, ai_difficulty,
                 result, start_time, total_moves, total_timelines)
                 VALUES (%(mode)s, %(player_white)s, %(player_black)s, %(ai_difficulty)s,
                 %(result)s, %(start_time)s, %(total_moves)s, %(total_timelines)s)"""
        db.execute_many(sql, [(g["mode"], g["player_white"], g["player_black"],
                               g.get("ai_difficulty"), g.get("result", "ongoing"),
                               g["start_time"], g.get("total_moves", 0),
                               g.get("total_timelines", 1)) for g in games])

    def _insert_moves(self, moves: list[dict]):
        sql = """INSERT INTO moves (game_id, timeline_id, turn_number, piece_type, piece_color,
                 from_timeline_id, from_x, from_y, from_time, to_timeline_id, to_x, to_y, to_time,
                 is_branching, new_timeline_id, notation)
                 VALUES (%(game_id)s, %(timeline_id)s, %(turn_number)s, %(piece_type)s, %(piece_color)s,
                 %(from_timeline_id)s, %(from_x)s, %(from_y)s, %(from_time)s, %(to_timeline_id)s,
                 %(to_x)s, %(to_y)s, %(to_time)s, %(is_branching)s, %(new_timeline_id)s, %(notation)s)"""
        tuples = []
        for m in moves:
            tuples.append((
                m.get("game_id"), m["timeline_id"], m.get("turn_number", 0),
                m["piece_type"], m["piece_color"],
                m["from_timeline_id"], m["from_x"], m["from_y"], m["from_time"],
                m["to_timeline_id"], m["to_x"], m["to_y"], m["to_time"],
                m.get("is_branching", False), m.get("new_timeline_id"),
                m.get("notation", "")
            ))
        db.execute_many(sql, tuples)

    def _insert_timelines(self, timelines: list[dict]):
        sql = """INSERT INTO timelines (game_id, parent_id, branch_move_id, branch_turn)
                 VALUES (%(game_id)s, %(parent_id)s, %(branch_move_id)s, %(branch_turn)s)"""
        tuples = [(t["game_id"], t.get("parent_id"), t.get("branch_move_id"),
                   t.get("branch_turn")) for t in timelines]
        db.execute_many(sql, tuples)

    def _insert_positions(self, positions: list[dict]):
        sql = """INSERT INTO positions (timeline_id, turn_number, time_point, board_fen,
                 board_json, active_color, is_check, is_checkmate)
                 VALUES (%(timeline_id)s, %(turn_number)s, %(time_point)s, %(board_fen)s,
                 %(board_json)s, %(active_color)s, %(is_check)s, %(is_checkmate)s)"""
        tuples = [(p["timeline_id"], p.get("turn_number", 0), p["time_point"],
                   p.get("board_fen", ""), p.get("board_json", ""),
                   p.get("active_color", "white"), p.get("is_check", False),
                   p.get("is_checkmate", False)) for p in positions]
        db.execute_many(sql, tuples)

    def _insert_stats(self, stats: list[dict]):
        sql = """INSERT INTO game_stats (game_id, avg_branch_depth, max_timelines,
                 white_time_travels, black_time_travels)
                 VALUES (%(game_id)s, %(avg_branch_depth)s, %(max_timelines)s,
                 %(white_time_travels)s, %(black_time_travels)s)"""
        tuples = [(s["game_id"], s.get("avg_branch_depth", 0), s.get("max_timelines", 0),
                   s.get("white_time_travels", 0), s.get("black_time_travels", 0))
                  for s in stats]
        db.execute_many(sql, tuples)


# 全局异步写入器
async_writer = AsyncDBWriter()
