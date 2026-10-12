"""Atomic, credential-free checkpoints for host-owned online games."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from src.data.archive import GameArchive


class OnlineSaveStore:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)

    def _path(self, save_id: str) -> Path:
        if not isinstance(save_id, str) or not re.fullmatch(r"[0-9a-f]{32}", save_id):
            raise ValueError("invalid save id")
        return self.directory / f"{save_id}.json"

    @staticmethod
    def _encode(payload: dict) -> bytes:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")).encode("utf-8")

    @staticmethod
    def _summary(payload: dict) -> dict:
        return {
            "save_id": payload["save_id"], "saved_at": payload["saved_at"],
            "action_counter": len(payload["game"]["action_history"]),
            "move_counter": payload["game"]["move_counter"],
            "turn": payload["game"]["current_turn_color"],
            "game_state": payload["game"]["game_state"],
        }

    def save(self, save_id: str, engine) -> dict:
        path = self._path(save_id)
        payload = {"version": 1, "save_id": save_id,
                   "saved_at": datetime.now(timezone.utc).isoformat(),
                   "game": GameArchive.capture(engine)}
        envelope = {"payload": payload,
                    "sha256": hashlib.sha256(self._encode(payload)).hexdigest()}
        content = self._encode(envelope)
        summary = self._summary(payload)
        self.directory.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=self.directory,
                                             prefix=".checkpoint-", suffix=".tmp",
                                             delete=False) as stream:
                temp_path = Path(stream.name)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            # Same-directory replace: readers see either complete checkpoint.
            os.replace(temp_path, path)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
        return summary

    def _read(self, save_id: str) -> dict:
        envelope = json.loads(self._path(save_id).read_text(encoding="utf-8"))
        payload = envelope["payload"]
        if (payload["version"] != 1 or payload["save_id"] != save_id
                or hashlib.sha256(self._encode(payload)).hexdigest() != envelope["sha256"]):
            raise ValueError("invalid checkpoint")
        return payload

    def load(self, save_id: str):
        payload = self._read(save_id)
        engine = GameArchive.restore(payload["game"])
        if engine.current_action and engine.current_action.moves:
            raise ValueError("checkpoint contains unsubmitted moves")
        return engine, self._summary(payload)

    def catalog(self) -> dict:
        entries, unreadable = [], 0
        for path in self.directory.glob("*.json"):
            try:
                entries.append(self._summary(self._read(path.stem)))
            except (OSError, ValueError, KeyError, TypeError):
                unreadable += 1
        entries.sort(key=lambda item: item["saved_at"], reverse=True)
        return {"saves": entries, "unreadable": unreadable}
