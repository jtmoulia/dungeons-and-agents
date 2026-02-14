"""Pydantic v2 models for Mothership-inspired game state."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class CharacterClass(str, Enum):
    TEAMSTER = "teamster"
    SCIENTIST = "scientist"
    ANDROID = "android"
    MARINE = "marine"


class Controller(str, Enum):
    USER = "user"
    AI = "ai"
    NPC = "npc"


class Condition(str, Enum):
    BLEEDING = "bleeding"
    BROKEN_LIMB = "broken_limb"
    UNCONSCIOUS = "unconscious"
    PANICKED = "panicked"
    STUNNED = "stunned"
    PARALYZED = "paralyzed"


class SkillLevel(str, Enum):
    TRAINED = "trained"
    EXPERT = "expert"
    MASTER = "master"


class Stats(BaseModel):
    strength: int = 30
    speed: int = 30
    intellect: int = 30
    combat: int = 30


class Saves(BaseModel):
    sanity: int = 30
    fear: int = 30
    body: int = 30


class Armor(BaseModel):
    name: str = "none"
    ap: int = 0  # armor points


class Weapon(BaseModel):
    name: str
    damage: str  # e.g. "1d10", "2d10"
    range: str = "close"  # close, nearby, far
    shots: int | None = None  # ammo, None = melee
    special: str = ""


class Character(BaseModel):
    name: str
    char_class: CharacterClass
    controller: Controller = Controller.AI
    stats: Stats = Field(default_factory=Stats)
    saves: Saves = Field(default_factory=Saves)
    hp: int = 20
    max_hp: int = 20
    wounds: int = 0
    max_wounds: int = 2
    stress: int = 2
    armor: Armor = Field(default_factory=Armor)
    inventory: list[str] = Field(default_factory=list)
    weapons: list[Weapon] = Field(default_factory=list)
    skills: dict[str, SkillLevel] = Field(default_factory=dict)
    conditions: list[Condition] = Field(default_factory=list)
    alive: bool = True

    @model_validator(mode="before")
    @classmethod
    def migrate_skills_list(cls, data: Any) -> Any:
        """Migrate old list[str] skills format to dict[str, SkillLevel]."""
        if isinstance(data, dict) and "skills" in data:
            skills = data["skills"]
            if isinstance(skills, list):
                data["skills"] = {s: SkillLevel.TRAINED for s in skills}
        return data


class Combatant(BaseModel):
    name: str
    initiative: int = 0
    has_acted: bool = False


class CombatState(BaseModel):
    active: bool = False
    round: int = 1
    combatants: list[Combatant] = Field(default_factory=list)
    current_index: int = 0

    @property
    def current_combatant(self) -> str | None:
        if not self.combatants:
            return None
        return self.combatants[self.current_index].name


class LogEntry(BaseModel):
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    message: str
    category: Literal["action", "combat", "scene", "system"] = "action"


class GameState(BaseModel):
    name: str = "Untitled Game"
    characters: dict[str, Character] = Field(default_factory=dict)
    combat: CombatState = Field(default_factory=CombatState)
    scene: str = ""
    log: list[LogEntry] = Field(default_factory=list)
    active_campaign: str | None = None
