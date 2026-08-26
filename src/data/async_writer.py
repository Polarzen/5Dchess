"""Asynchronous MySQL writer for canonical replay/storage records."""
from __future__ import annotations

import threading
import time
from queue import Empty, Queue

from src.config import ASYNC_QUEUE_MAXSIZE, ASYNC_WRITE_INTERVAL
from src.data.db import db
from src.utils.logger import logger


class AsyncDBWriter:
    """Non-blocking batch writer. Database availability remains optional."""

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
        if self._running:
            return
        self._running = True
        self._worker = threading.Thread(
            target=self._run,
            daemon=True,
            name="AsyncDBWriter",
        )
        self._worker.start()
        logger.info("异步写入器启动")

    def stop(self):
        self._running = False
        self._flush_buffer()
        if self._worker:
            self._worker.join(timeout=5.0)
        logger.info("异步写入器停止")

    def write_move(self, data: dict):
        self._enqueue("move", data)

    def write_action(self, data: dict):
        self._enqueue("action", data)

    def write_position(self, data: dict):
        self._enqueue("position", data)

    def write_game(self, data: dict):
        self._enqueue("game", data)

    def write_timeline(self, data: dict):
        self._enqueue("timeline", data)

    def write_stats(self, data: dict):
        self._enqueue("stats", data)

    def _enqueue(self, op: str, data: dict):
        try:
            self._queue.put_nowait((op, data))
        except Exception:
            logger.warning("异步写入队列已满，丢弃数据")

    def _run(self):
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
            except Exception as exc:
                logger.error(f"异步写入异常: {exc}")

    def _flush_buffer(self):
        if not self._batch_buffer:
            return
        buffer = self._batch_buffer[:]
        self._batch_buffer.clear()
        self._last_flush = time.time()
        if not db.is_available:
            return

        try:
            games = [data for op, data in buffer if op == "game"]
            timelines = [data for op, data in buffer if op == "timeline"]
            actions = [data for op, data in buffer if op == "action"]
            moves = [data for op, data in buffer if op == "move"]
            positions = [data for op, data in buffer if op == "position"]
            stats = [data for op, data in buffer if op == "stats"]
            if games:
                self._insert_games(games)
            if timelines:
                self._insert_timelines(timelines)
            if actions:
                self._insert_actions(actions)
            if moves:
                self._insert_moves(moves)
            if positions:
                self._insert_positions(positions)
            if stats:
                self._insert_stats(stats)
            logger.debug(f"批量写入完成: {len(buffer)} 条")
        except Exception as exc:
            logger.error(f"批量写入失败: {exc}")

    def _insert_games(self, games: list[dict]):
        sql = """INSERT INTO games
                 (mode, player_white, player_black, ai_difficulty, result,
                  start_time, total_moves, total_actions, total_timelines, archive_version)
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
        tuples = [
            (
                game["mode"], game["player_white"], game["player_black"],
                game.get("ai_difficulty"), game.get("result", "ongoing"),
                game["start_time"], game.get("total_moves", 0),
                game.get("total_actions", 0), game.get("total_timelines", 1),
                game.get("archive_version", 2),
            )
            for game in games
        ]
        db.execute_many(sql, tuples)

    def _insert_timelines(self, timelines: list[dict]):
        sql = """INSERT INTO timelines
                 (game_id, lane_id, parent_lane_id, branch_move_id, branch_turn,
                  owner, is_active)
                 VALUES (%s, %s, %s, %s, %s, %s, %s)"""
        tuples = [
            (
                item["game_id"], item["lane_id"], item.get("parent_lane_id"),
                item.get("branch_move_id"), item.get("branch_turn"),
                item.get("owner"), item.get("is_active", True),
            )
            for item in timelines
        ]
        db.execute_many(sql, tuples)

    def _insert_actions(self, actions: list[dict]):
        sql = """INSERT INTO actions
                 (game_id, action_index, color, starting_present_json, submitted, move_count)
                 VALUES (%s, %s, %s, %s, %s, %s)"""
        tuples = [
            (
                item["game_id"], item["action_index"], item["color"],
                item.get("starting_present_json", "null"),
                item.get("submitted", False), item.get("move_count", 0),
            )
            for item in actions
        ]
        db.execute_many(sql, tuples)

    def _insert_moves(self, moves: list[dict]):
        sql = """INSERT INTO moves
                 (game_id, action_index, move_index, piece_type, piece_color,
                  source_timeline, source_turn, source_side, source_x, source_y,
                  destination_timeline, destination_turn, destination_side,
                  destination_x, destination_y, from_time, to_time,
                  is_branching, is_cross_timeline, is_castling, is_en_passant,
                  created_timeline, captured_type, captured_color, promotion, notation)
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                         %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                         %s, %s, %s, %s, %s, %s)"""
        tuples = []
        for item in moves:
            tuples.append((
                item.get("game_id"), item.get("action_index", 0),
                item.get("move_index", 0), item["piece_type"], item["piece_color"],
                item["source_timeline"], item["source_turn"], item["source_side"],
                item["source_x"], item["source_y"],
                item["destination_timeline"], item["destination_turn"],
                item["destination_side"], item["destination_x"],
                item["destination_y"], item.get("from_time", 0),
                item.get("to_time", 0), item.get("is_branching", False),
                item.get("is_cross_timeline", False),
                item.get("is_castling", False), item.get("is_en_passant", False),
                item.get("created_timeline"), item.get("captured_type"),
                item.get("captured_color"), item.get("promotion"),
                item.get("notation", ""),
            ))
        db.execute_many(sql, tuples)

    def _insert_positions(self, positions: list[dict]):
        sql = """INSERT INTO positions
                 (game_id, lane_id, board_turn, board_side, time_point,
                  board_fen, board_json, is_playable, is_check, is_checkmate)
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
        tuples = [
            (
                item["game_id"], item["lane_id"], item.get("board_turn", 0),
                item.get("board_side", "white"), item.get("time_point", 0),
                item.get("board_fen", ""), item.get("board_json", "{}"),
                item.get("is_playable", False), item.get("is_check", False),
                item.get("is_checkmate", False),
            )
            for item in positions
        ]
        db.execute_many(sql, tuples)

    def _insert_stats(self, stats: list[dict]):
        sql = """INSERT INTO game_stats
                 (game_id, avg_branch_depth, max_timelines,
                  white_time_travels, black_time_travels)
                 VALUES (%s, %s, %s, %s, %s)"""
        tuples = [
            (
                item["game_id"], item.get("avg_branch_depth", 0),
                item.get("max_timelines", 0), item.get("white_time_travels", 0),
                item.get("black_time_travels", 0),
            )
            for item in stats
        ]
        db.execute_many(sql, tuples)


async_writer = AsyncDBWriter()
