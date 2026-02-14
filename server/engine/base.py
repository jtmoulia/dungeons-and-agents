"""Abstract game engine plugin interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field


class EngineAction(BaseModel):
    """An action submitted to the engine."""
    action_type: str
    character: str
    params: dict = Field(default_factory=dict)


class EngineResult(BaseModel):
    """Result of an engine action."""
    success: bool
    summary: str
    details: dict = Field(default_factory=dict)
    state_changed: bool = True


class GameEnginePlugin(ABC):
    """Interface for pluggable game engines."""

    @abstractmethod
    def get_name(self) -> str: ...

    @abstractmethod
    def create_character(self, name: str, **kwargs) -> dict: ...

    @abstractmethod
    def get_character(self, name: str) -> dict | None: ...

    @abstractmethod
    def list_characters(self) -> list[dict]: ...

    @abstractmethod
    def process_action(self, action: EngineAction) -> EngineResult: ...

    @abstractmethod
    def get_state(self) -> dict: ...

    @abstractmethod
    def get_available_actions(self, character: str) -> list[str]: ...

    @abstractmethod
    def save_state(self) -> str:
        """Serialize state to JSON string."""

    @abstractmethod
    def load_state(self, state: str) -> None:
        """Restore state from JSON string."""
