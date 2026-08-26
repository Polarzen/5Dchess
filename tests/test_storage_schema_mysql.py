"""MySQL integration check for the canonical Replay/Storage v2 schema."""
from __future__ import annotations

import os
from pathlib import Path

import pytest


def _schema_statements() -> list[str]:
    text = Path("sql/schema.sql").read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if not line.lstrip().startswith("--")]
    return [statement.strip() for statement in "\n".join(lines).split(";") if statement.strip()]


def test_mysql_schema_supports_signed_lane_action_and_canonical_move():
    required = ("DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME")
    if not all(os.environ.get(name) for name in required):
        pytest.skip("MySQL integration environment is not configured")

    mysql_connector = pytest.importorskip("mysql.connector")
    connection = mysql_connector.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ["DB_PORT"]),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        autocommit=True,
    )
    cursor = connection.cursor()
    try:
        for statement in _schema_statements():
            cursor.execute(statement)

        cursor.execute(f"USE `{os.environ['DB_NAME']}`")
        cursor.execute("INSERT INTO games (mode) VALUES ('pvp')")
        game_id = cursor.lastrowid

        cursor.execute(
            """INSERT INTO timelines
               (game_id, lane_id, parent_lane_id, owner, is_active)
               VALUES (%s, %s, %s, %s, %s)""",
            (game_id, -1, 0, "black", True),
        )
        cursor.execute(
            """INSERT INTO actions
               (game_id, action_index, color, starting_present_json, submitted, move_count)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (game_id, 0, "black", "null", True, 1),
        )
        cursor.execute(
            """INSERT INTO moves
               (game_id, action_index, move_index, piece_type, piece_color,
                source_timeline, source_turn, source_side, source_x, source_y,
                destination_timeline, destination_turn, destination_side,
                destination_x, destination_y, from_time, to_time, notation)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                game_id, 0, 0, "R", "black",
                -1, 2, "black", 0, 0,
                0, 1, "black", 0, 1,
                5, 3, "(L-1→L0) Ra1-a2",
            ),
        )

        cursor.execute(
            """SELECT t.lane_id, a.submitted, m.source_timeline,
                      m.source_turn, m.source_side, m.destination_timeline
               FROM timelines t
               JOIN actions a ON a.game_id = t.game_id
               JOIN moves m ON m.game_id = a.game_id
                           AND m.action_index = a.action_index
               WHERE t.game_id = %s""",
            (game_id,),
        )
        row = cursor.fetchone()
        assert row == (-1, 1, -1, 2, "black", 0)
    finally:
        try:
            if "game_id" in locals():
                cursor.execute("DELETE FROM games WHERE game_id = %s", (game_id,))
        finally:
            cursor.close()
            connection.close()
