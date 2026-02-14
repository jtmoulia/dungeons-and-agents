"""Campaign module manager: load, discover, and query campaign data."""

from __future__ import annotations

import random
from pathlib import Path

from game.campaign import (
    CampaignModule,
    Entity,
    Location,
    Mission,
    RandomTable,
    TableEntry,
)


class CampaignError(Exception):
    pass


class CampaignManager:
    """Loads and queries campaign modules from JSON files."""

    def __init__(self) -> None:
        self._loaded: dict[str, CampaignModule] = {}

    def load(self, path: Path) -> CampaignModule:
        """Load a campaign module from a JSON file."""
        if not path.exists():
            raise CampaignError(f"Campaign file not found: {path}")
        try:
            module = CampaignModule.model_validate_json(path.read_text())
        except Exception as e:
            raise CampaignError(f"Failed to parse campaign file {path}: {e}")
        self._loaded[module.name] = module
        return module

    def discover(self, directory: Path) -> dict[str, CampaignModule]:
        """Discover and load all campaign JSON files in a directory."""
        if not directory.exists():
            return {}
        modules: dict[str, CampaignModule] = {}
        for json_file in sorted(directory.glob("*.json")):
            try:
                module = self.load(json_file)
                modules[str(json_file)] = module
            except CampaignError:
                continue  # skip invalid files
        return modules

    def get(self, name: str) -> CampaignModule:
        """Get a loaded campaign module by name."""
        if name not in self._loaded:
            raise CampaignError(
                f"Campaign '{name}' not loaded. Use load() or discover() first."
            )
        return self._loaded[name]

    def list_loaded(self) -> list[str]:
        """List names of all loaded campaign modules."""
        return list(self._loaded.keys())

    # --- Query methods ---

    def query_locations(
        self, module: CampaignModule, tag: str | None = None
    ) -> dict[str, Location]:
        """Query locations, optionally filtering by tag."""
        if tag:
            return {
                k: v for k, v in module.locations.items() if tag in v.tags
            }
        return dict(module.locations)

    def get_location(self, module: CampaignModule, location_id: str) -> Location:
        """Get a specific location by ID."""
        if location_id not in module.locations:
            raise CampaignError(
                f"Location '{location_id}' not found in '{module.name}'."
            )
        return module.locations[location_id]

    def query_entities(
        self, module: CampaignModule, tag: str | None = None
    ) -> dict[str, Entity]:
        """Query entities, optionally filtering by tag."""
        if tag:
            return {
                k: v for k, v in module.entities.items() if tag in v.tags
            }
        return dict(module.entities)

    def get_entity(self, module: CampaignModule, entity_id: str) -> Entity:
        """Get a specific entity by ID."""
        if entity_id not in module.entities:
            raise CampaignError(
                f"Entity '{entity_id}' not found in '{module.name}'."
            )
        return module.entities[entity_id]

    def query_missions(
        self, module: CampaignModule, tag: str | None = None
    ) -> dict[str, Mission]:
        """Query missions, optionally filtering by tag."""
        if tag:
            return {
                k: v for k, v in module.missions.items() if tag in v.tags
            }
        return dict(module.missions)

    def get_mission(self, module: CampaignModule, mission_id: str) -> Mission:
        """Get a specific mission by ID."""
        if mission_id not in module.missions:
            raise CampaignError(
                f"Mission '{mission_id}' not found in '{module.name}'."
            )
        return module.missions[mission_id]

    def roll_on_table(
        self, module: CampaignModule, table_id: str
    ) -> tuple[int, TableEntry]:
        """Roll on a random table and return the roll and matching entry."""
        if table_id not in module.random_tables:
            raise CampaignError(
                f"Random table '{table_id}' not found in '{module.name}'."
            )
        table = module.random_tables[table_id]
        if not table.entries:
            raise CampaignError(f"Random table '{table_id}' has no entries.")

        # Parse dice string and roll
        roll = _roll_dice(table.dice)

        # Find matching entry
        for entry in table.entries:
            if entry.min_roll <= roll <= entry.max_roll:
                return roll, entry

        # If no match, return last entry (clamp)
        return roll, table.entries[-1]


def _roll_dice(dice_str: str) -> int:
    """Parse and roll a dice string like '1d20', '1d100'."""
    parts = dice_str.lower().split("d")
    count = int(parts[0]) if parts[0] else 1
    sides = int(parts[1])
    return sum(random.randint(1, sides) for _ in range(count))
