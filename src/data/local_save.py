"""Managed local/AI saves, kept separate from online room checkpoints."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import secrets

from src.data.pgn_parser import FiveDPGN


class LocalSaveStore:
    def __init__(self, directory):
        self.directory = Path(directory) / "local"

    def path(self, save_id):
        if not isinstance(save_id, str) or not re.fullmatch(r"local-[0-9a-f]{32}", save_id):
            raise ValueError("invalid local save id")
        return self.directory / f"{save_id[6:]}.5dpgn"

    @staticmethod
    def summary(save_id, data):
        metadata, game = data["metadata"], data["game"]
        if not isinstance(metadata, dict) or not isinstance(game, dict):
            raise ValueError("invalid local save payload")
        if metadata.get("mode") not in {"pvp", "pve"}:
            raise ValueError("invalid local save mode")
        if not isinstance(metadata.get("date"), str):
            raise ValueError("invalid local save date")
        return {"save_id": save_id, "saved_at": metadata["date"], "mode": metadata["mode"],
                "difficulty": metadata.get("difficulty"), "player_color": metadata.get("player_color"),
                "game_state": game["game_state"], "turn": game["current_turn_color"],
                "action_counter": len(game["action_history"]), "move_counter": game["move_counter"]}

    def save(self, engine, metadata, save_id=None):
        save_id = save_id or "local-" + secrets.token_hex(16)
        path = self.path(save_id)
        metadata = {**metadata, "date": datetime.now(timezone.utc).isoformat()}
        if not FiveDPGN.save(str(path), engine, metadata):
            raise OSError("local save failed")
        return self.summary(save_id, json.loads(path.read_text(encoding="utf-8")))

    def load(self, save_id):
        payload = FiveDPGN.load_archive(str(self.path(save_id)))
        if payload is None or payload.metadata.get("mode") not in {"pvp", "pve"}:
            raise ValueError("invalid local save")
        return payload

    def catalog(self):
        entries, unreadable = [], 0
        for path in self.directory.glob("*.5dpgn"):
            try:
                save_id = "local-" + path.stem
                self.path(save_id)
                entries.append(self.summary(save_id, json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, ValueError, KeyError, TypeError):
                unreadable += 1
        return {"saves": entries, "unreadable": unreadable}
