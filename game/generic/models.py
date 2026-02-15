"""Pydantic models for the generic game engine."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from game.models import LogEntry


# --- Engine Configuration (set once at game creation) ---


class DiceConfig(BaseModel):
    """How dice rolls work in this game."""

    dice: str = "1d20"
    direction: Literal["over", "under"] = "over"
    critical_success: int | None = None
    critical_failure: int | None = None


class HealthConfig(BaseModel):
    """Optional health tracking."""

    enabled: bool = False
    default_max_hp: int = 10
    death_at_zero: bool = True


class CombatConfig(BaseModel):
    """Optional combat (initiative + turn order)."""

    enabled: bool = False
    initiative_stat: str | None = None
    initiative_dice: str = "1d20"


class ConditionConfig(BaseModel):
    """Optional condition/status tracking."""

    enabled: bool = False
    conditions: list[str] = Field(default_factory=list)


class GenericEngineConfig(BaseModel):
    """Full configuration for a generic engine game."""

    stat_names: list[str] = Field(default_factory=list)
    dice: DiceConfig = Field(default_factory=DiceConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)
    combat: CombatConfig = Field(default_factory=CombatConfig)
    conditions: ConditionConfig = Field(default_factory=ConditionConfig)

    @model_validator(mode="after")
    def validate_combat_stat(self) -> GenericEngineConfig:
        if (
            self.combat.enabled
            and self.combat.initiative_stat
            and self.combat.initiative_stat not in self.stat_names
        ):
            raise ValueError(
                f"initiative_stat '{self.combat.initiative_stat}' "
                f"not in stat_names: {self.stat_names}"
            )
        return self


# --- Character State ---


class GenericCharacter(BaseModel):
    name: str
    stats: dict[str, int] = Field(default_factory=dict)
    hp: int | None = None
    max_hp: int | None = None
    alive: bool = True
    conditions: list[str] = Field(default_factory=list)
    inventory: list[str] = Field(default_factory=list)
    notes: dict[str, str] = Field(default_factory=dict)


# --- Combat State ---


class GenericCombatant(BaseModel):
    name: str
    initiative: int = 0


class GenericCombatState(BaseModel):
    active: bool = False
    round: int = 1
    combatants: list[GenericCombatant] = Field(default_factory=list)
    current_index: int = 0

    @property
    def current_combatant(self) -> str | None:
        if not self.combatants:
            return None
        return self.combatants[self.current_index].name


# --- Game State ---


class GenericGameState(BaseModel):
    name: str = "Untitled Game"
    config: GenericEngineConfig = Field(default_factory=GenericEngineConfig)
    characters: dict[str, GenericCharacter] = Field(default_factory=dict)
    combat: GenericCombatState = Field(default_factory=GenericCombatState)
    scene: str = ""
    log: list[LogEntry] = Field(default_factory=list)
