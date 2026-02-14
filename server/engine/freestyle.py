"""Freestyle engine plugin — no rules engine, DM resolves everything."""

from __future__ import annotations

import json

from server.engine.base import EngineAction, EngineResult, GameEnginePlugin


class FreestylePlugin(GameEnginePlugin):
    """No-engine freestyle mode. DM narrates and resolves everything via messages."""

    def __init__(self) -> None:
        self._characters: dict[str, dict] = {}

    def get_name(self) -> str:
        return "freestyle"

    def create_character(self, name: str, **kwargs: object) -> dict:
        char = {"name": name, **kwargs}
        self._characters[name] = char
        return char

    def get_character(self, name: str) -> dict | None:
        return self._characters.get(name)

    def list_characters(self) -> list[dict]:
        return list(self._characters.values())

    def process_action(self, action: EngineAction) -> EngineResult:
        return EngineResult(
            success=True,
            summary=f"{action.character}: {action.action_type} — DM resolves.",
            details=action.params,
            state_changed=False,
        )

    def get_state(self) -> dict:
        return {"engine": "freestyle", "characters": self._characters}

    def get_available_actions(self, character: str) -> list[str]:
        return ["any"]

    def save_state(self) -> str:
        return json.dumps(self._characters)

    def load_state(self, state: str) -> None:
        self._characters = json.loads(state)
