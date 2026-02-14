"""Pydantic v2 models for campaign/module data."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EntityStats(BaseModel):
    strength: int = 30
    speed: int = 30
    intellect: int = 30
    combat: int = 30
    hp: int = 20
    armor: int = 0


class Entity(BaseModel):
    name: str
    entity_type: str = "npc"  # npc, creature, hazard, etc.
    description: str = ""
    stats: EntityStats | None = None
    tags: list[str] = Field(default_factory=list)
    location: str | None = None  # reference to location ID


class Location(BaseModel):
    name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    connections: list[str] = Field(default_factory=list)  # IDs of connected locations
    entities: list[str] = Field(default_factory=list)  # IDs of entities here


class Mission(BaseModel):
    name: str
    description: str = ""
    objectives: list[str] = Field(default_factory=list)
    rewards: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    location: str | None = None  # primary location ID


class Faction(BaseModel):
    name: str
    description: str = ""
    disposition: str = "neutral"  # friendly, neutral, hostile
    tags: list[str] = Field(default_factory=list)


class Asset(BaseModel):
    name: str
    description: str = ""
    asset_type: str = "item"  # item, ship, facility, etc.
    tags: list[str] = Field(default_factory=list)


class TableEntry(BaseModel):
    min_roll: int
    max_roll: int
    description: str
    effect: str = ""


class RandomTable(BaseModel):
    name: str
    dice: str = "1d20"  # e.g. "1d20", "1d100"
    entries: list[TableEntry] = Field(default_factory=list)


class CampaignModule(BaseModel):
    name: str
    version: str = "1.0"
    description: str = ""
    author: str = ""
    tags: list[str] = Field(default_factory=list)
    locations: dict[str, Location] = Field(default_factory=dict)
    entities: dict[str, Entity] = Field(default_factory=dict)
    missions: dict[str, Mission] = Field(default_factory=dict)
    factions: dict[str, Faction] = Field(default_factory=dict)
    assets: dict[str, Asset] = Field(default_factory=dict)
    random_tables: dict[str, RandomTable] = Field(default_factory=dict)
    metadata: dict[str, str] = Field(default_factory=dict)
