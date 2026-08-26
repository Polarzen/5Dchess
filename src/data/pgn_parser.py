"""5D Chess .5dpgn storage.

Version 2 stores canonical BoardCoord/Square5D moves, replay origin, and explicit
Action submit boundaries. Version 1 files remain readable through GameArchive's
legacy adapter.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from src.data.archive import ARCHIVE_SCHEMA_VERSION, ArchivePayload, GameArchive
from src.engine.engine import FiveDEngine
from src.engine.move_generator import Move
from src.engine.timeline import TimelineManager
from src.utils.logger import logger


class FiveDPGN:
    """Read/write the project's replayable .5dpgn JSON archive."""

    FORMAT_NAME = "5dpgn"
    FORMAT_VERSION = "2.0"

    @classmethod
    def save(
        cls,
        filepath: str,
        engine: FiveDEngine,
        game_metadata: dict | None = None,
    ) -> bool:
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            metadata = {
                "format": cls.FORMAT_NAME,
                "version": cls.FORMAT_VERSION,
                "schema_version": ARCHIVE_SCHEMA_VERSION,
                "date": datetime.now().isoformat(),
                **(game_metadata or {}),
            }
            data = {"metadata": metadata, "game": GameArchive.capture(engine)}
            with path.open("w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
            logger.info(
                f"棋谱已保存: {filepath} "
                f"({len(engine.action_history)} Actions / {engine.move_counter} Moves)"
            )
            return True
        except Exception as exc:
            logger.error(f"棋谱保存失败: {exc}")
            return False

    @classmethod
    def load_archive(cls, filepath: str) -> ArchivePayload | None:
        path = Path(filepath)
        if not path.exists():
            logger.error(f"棋谱文件不存在: {filepath}")
            return None
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            metadata = dict(data.get("metadata", {}))
            if metadata.get("format", cls.FORMAT_NAME) != cls.FORMAT_NAME:
                raise ValueError("not a 5dpgn archive")
            game_data = data.get("game")
            if not isinstance(game_data, dict):
                raise ValueError("archive is missing game payload")
            engine = GameArchive.restore(game_data)
            version = int(game_data.get("schema_version", 1))
            logger.info(
                f"棋谱已加载: {filepath} "
                f"(schema={version}, {len(engine.action_history)} Actions, "
                f"{engine.move_counter} Moves)"
            )
            return ArchivePayload(
                engine=engine,
                metadata=metadata,
                schema_version=version,
            )
        except Exception as exc:
            logger.error(f"棋谱加载失败: {exc}")
            return None

    @classmethod
    def load_engine(cls, filepath: str) -> FiveDEngine | None:
        payload = cls.load_archive(filepath)
        return payload.engine if payload else None

    @classmethod
    def load(cls, filepath: str) -> tuple[list[Move] | None, TimelineManager | None]:
        """Compatibility API returning (moves, timeline_manager).

        New Replay code should prefer ``load_engine``/``load_archive``. Metadata
        attached to the returned manager lets legacy Web callers retain Action
        boundaries without changing the public two-tuple immediately.
        """
        payload = cls.load_archive(filepath)
        if payload is None:
            return None, None
        engine = payload.engine
        manager = engine.timeline_manager
        manager._replay_action_history = list(engine.action_history)
        manager._replay_current_action = engine.current_action
        manager._replay_game_state = engine.game_state
        manager._replay_current_turn_color = engine.current_turn_color
        manager._replay_origin = getattr(engine, "_replay_origin", None)
        manager._replay_max_timelines = engine.max_timelines
        manager._replay_max_turns = engine.max_turns
        return list(engine.move_history), manager

    @classmethod
    def save_text(
        cls,
        filepath: str,
        engine: FiveDEngine,
        game_metadata: dict | None = None,
    ) -> bool:
        """Write a human-readable transcript that preserves Action boundaries."""
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            meta = game_metadata or {}
            lines = [
                '[Game "5D Chess"]',
                f'[FormatVersion "{cls.FORMAT_VERSION}"]',
                f'[Mode "{meta.get("mode", "pvp")}"]',
                f'[Date "{meta.get("date", "")}"]',
                f'[White "{meta.get("white", "Player1")}"]',
                f'[Black "{meta.get("black", "Player2")}"]',
                f'[Result "{meta.get("result", engine.game_state.name)}"]',
                f'[TotalTimelines "{len(engine.timeline_manager.timelines)}"]',
                f'[TotalActions "{len(engine.action_history)}"]',
                f'[TotalMoves "{engine.move_counter}"]',
                "",
            ]

            for action_index, action in enumerate(engine.action_history, start=1):
                present = action.starting_present
                if present is None:
                    present_label = "none"
                else:
                    lanes = ",".join(f"L{lane:+d}" for lane in present.timeline_ids)
                    present_label = (
                        f"t={present.legacy_time_point} {present.side.value} [{lanes}]"
                    )
                lines.append(
                    f"Action {action_index} {action.color.value} Present({present_label})"
                )
                for move_index, move in enumerate(action.moves, start=1):
                    tags = []
                    if move.is_branching:
                        tags.append(
                            f"BRANCH→L{move.created_timeline:+d}"
                            if move.created_timeline is not None
                            else "BRANCH"
                        )
                    if move.is_cross_timeline:
                        tags.append("CROSS")
                    suffix = f" [{' '.join(tags)}]" if tags else ""
                    lines.append(f"  {move_index}. {move.to_notation()}{suffix}")
                lines.append("  SUBMIT")
                lines.append("")

            current = engine.current_action
            if current is not None and current.moves:
                lines.append(f"CurrentAction {current.color.value} (UNSUBMITTED)")
                for move_index, move in enumerate(current.moves, start=1):
                    lines.append(f"  {move_index}. {move.to_notation()}")
                lines.append("")

            lines.append(f"# Result: {meta.get('result', engine.game_state.name)}")
            with path.open("w", encoding="utf-8") as handle:
                handle.write("\n".join(lines))
            logger.info(f"文本棋谱已保存: {filepath}")
            return True
        except Exception as exc:
            logger.error(f"文本棋谱保存失败: {exc}")
            return False
