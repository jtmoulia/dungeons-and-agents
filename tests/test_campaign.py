"""Tests for campaign models and campaign manager."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from game.campaign import (
    Asset,
    CampaignModule,
    Entity,
    EntityStats,
    Faction,
    Location,
    Mission,
    RandomTable,
    TableEntry,
)
from game.campaign_engine import CampaignError, CampaignManager


# --- Model tests ---


def test_campaign_module_creation():
    module = CampaignModule(
        name="Test Module",
        version="1.0",
        description="A test campaign.",
    )
    assert module.name == "Test Module"
    assert module.locations == {}
    assert module.entities == {}


def test_campaign_module_roundtrip():
    module = CampaignModule(
        name="Test Module",
        version="2.0",
        locations={
            "room_a": Location(
                name="Room A",
                description="A dark room.",
                tags=["dark", "start"],
                connections=["room_b"],
            ),
        },
        entities={
            "monster_1": Entity(
                name="Monster",
                entity_type="creature",
                stats=EntityStats(strength=50, combat=40, hp=30, armor=2),
                tags=["hostile"],
            ),
        },
        missions={
            "main_quest": Mission(
                name="Escape",
                objectives=["Find the exit", "Survive"],
                tags=["main"],
            ),
        },
        factions={
            "crew": Faction(name="Crew", disposition="friendly"),
        },
        random_tables={
            "events": RandomTable(
                name="Events",
                dice="1d6",
                entries=[
                    TableEntry(min_roll=1, max_roll=3, description="Nothing happens."),
                    TableEntry(min_roll=4, max_roll=6, description="Something happens!", effect="Gain 1 stress."),
                ],
            ),
        },
    )
    data = module.model_dump_json()
    restored = CampaignModule.model_validate_json(data)
    assert restored.name == "Test Module"
    assert restored.version == "2.0"
    assert "room_a" in restored.locations
    assert restored.locations["room_a"].tags == ["dark", "start"]
    assert "monster_1" in restored.entities
    assert restored.entities["monster_1"].stats.strength == 50
    assert "main_quest" in restored.missions
    assert "crew" in restored.factions
    assert "events" in restored.random_tables
    assert len(restored.random_tables["events"].entries) == 2


def test_entity_stats_defaults():
    stats = EntityStats()
    assert stats.strength == 30
    assert stats.hp == 20
    assert stats.armor == 0


def test_entity_without_stats():
    entity = Entity(name="Ghost", entity_type="npc")
    assert entity.stats is None


# --- CampaignManager tests ---


@pytest.fixture
def sample_module_data():
    return {
        "name": "Test Campaign",
        "version": "1.0",
        "locations": {
            "loc_a": {"name": "Location A", "tags": ["safe"]},
            "loc_b": {"name": "Location B", "tags": ["danger"]},
            "loc_c": {"name": "Location C", "tags": ["safe", "loot"]},
        },
        "entities": {
            "npc_1": {"name": "NPC One", "entity_type": "npc", "tags": ["friendly"]},
            "monster_1": {"name": "Monster", "entity_type": "creature", "tags": ["hostile"]},
        },
        "missions": {
            "quest_1": {"name": "Main Quest", "tags": ["main"]},
            "quest_2": {"name": "Side Quest", "tags": ["side"]},
        },
        "random_tables": {
            "events": {
                "name": "Events",
                "dice": "1d6",
                "entries": [
                    {"min_roll": 1, "max_roll": 3, "description": "All quiet."},
                    {"min_roll": 4, "max_roll": 6, "description": "Attack!", "effect": "Roll initiative."},
                ],
            },
        },
    }


@pytest.fixture
def campaign_file(tmp_path, sample_module_data):
    path = tmp_path / "test_campaign.json"
    path.write_text(json.dumps(sample_module_data))
    return path


def test_load_campaign(campaign_file):
    manager = CampaignManager()
    module = manager.load(campaign_file)
    assert module.name == "Test Campaign"
    assert len(module.locations) == 3


def test_load_missing_file():
    manager = CampaignManager()
    with pytest.raises(CampaignError, match="not found"):
        manager.load(Path("/nonexistent/file.json"))


def test_load_invalid_json(tmp_path):
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("not valid json{{{")
    manager = CampaignManager()
    with pytest.raises(CampaignError, match="Failed to parse"):
        manager.load(bad_file)


def test_discover_campaigns(tmp_path, sample_module_data):
    # Write two campaign files
    (tmp_path / "camp1.json").write_text(json.dumps(sample_module_data))
    data2 = dict(sample_module_data, name="Second Campaign")
    (tmp_path / "camp2.json").write_text(json.dumps(data2))
    # Write a non-json file (should be ignored)
    (tmp_path / "readme.txt").write_text("not a campaign")

    manager = CampaignManager()
    modules = manager.discover(tmp_path)
    assert len(modules) == 2
    names = [m.name for m in modules.values()]
    assert "Test Campaign" in names
    assert "Second Campaign" in names


def test_discover_empty_dir(tmp_path):
    manager = CampaignManager()
    modules = manager.discover(tmp_path)
    assert modules == {}


def test_discover_nonexistent_dir():
    manager = CampaignManager()
    modules = manager.discover(Path("/nonexistent/dir"))
    assert modules == {}


def test_get_loaded_campaign(campaign_file):
    manager = CampaignManager()
    manager.load(campaign_file)
    module = manager.get("Test Campaign")
    assert module.name == "Test Campaign"


def test_get_unloaded_campaign():
    manager = CampaignManager()
    with pytest.raises(CampaignError, match="not loaded"):
        manager.get("Nonexistent")


def test_list_loaded(campaign_file):
    manager = CampaignManager()
    assert manager.list_loaded() == []
    manager.load(campaign_file)
    assert manager.list_loaded() == ["Test Campaign"]


# --- Query tests ---


def test_query_locations(campaign_file):
    manager = CampaignManager()
    module = manager.load(campaign_file)
    locs = manager.query_locations(module)
    assert len(locs) == 3


def test_query_locations_by_tag(campaign_file):
    manager = CampaignManager()
    module = manager.load(campaign_file)
    safe_locs = manager.query_locations(module, tag="safe")
    assert len(safe_locs) == 2
    assert "loc_a" in safe_locs
    assert "loc_c" in safe_locs


def test_get_location(campaign_file):
    manager = CampaignManager()
    module = manager.load(campaign_file)
    loc = manager.get_location(module, "loc_a")
    assert loc.name == "Location A"


def test_get_location_not_found(campaign_file):
    manager = CampaignManager()
    module = manager.load(campaign_file)
    with pytest.raises(CampaignError, match="not found"):
        manager.get_location(module, "nonexistent")


def test_query_entities_by_tag(campaign_file):
    manager = CampaignManager()
    module = manager.load(campaign_file)
    hostile = manager.query_entities(module, tag="hostile")
    assert len(hostile) == 1
    assert "monster_1" in hostile


def test_get_entity(campaign_file):
    manager = CampaignManager()
    module = manager.load(campaign_file)
    entity = manager.get_entity(module, "npc_1")
    assert entity.name == "NPC One"


def test_get_entity_not_found(campaign_file):
    manager = CampaignManager()
    module = manager.load(campaign_file)
    with pytest.raises(CampaignError, match="not found"):
        manager.get_entity(module, "nonexistent")


def test_query_missions_by_tag(campaign_file):
    manager = CampaignManager()
    module = manager.load(campaign_file)
    main = manager.query_missions(module, tag="main")
    assert len(main) == 1
    assert "quest_1" in main


def test_get_mission(campaign_file):
    manager = CampaignManager()
    module = manager.load(campaign_file)
    mission = manager.get_mission(module, "quest_1")
    assert mission.name == "Main Quest"


def test_get_mission_not_found(campaign_file):
    manager = CampaignManager()
    module = manager.load(campaign_file)
    with pytest.raises(CampaignError, match="not found"):
        manager.get_mission(module, "nonexistent")


# --- Random table tests ---


def test_roll_on_table(campaign_file):
    manager = CampaignManager()
    module = manager.load(campaign_file)
    with patch("game.campaign_engine._roll_dice", return_value=2):
        roll, entry = manager.roll_on_table(module, "events")
        assert roll == 2
        assert entry.description == "All quiet."


def test_roll_on_table_high(campaign_file):
    manager = CampaignManager()
    module = manager.load(campaign_file)
    with patch("game.campaign_engine._roll_dice", return_value=5):
        roll, entry = manager.roll_on_table(module, "events")
        assert roll == 5
        assert entry.description == "Attack!"
        assert entry.effect == "Roll initiative."


def test_roll_on_table_not_found(campaign_file):
    manager = CampaignManager()
    module = manager.load(campaign_file)
    with pytest.raises(CampaignError, match="not found"):
        manager.roll_on_table(module, "nonexistent_table")


def test_roll_on_empty_table(campaign_file):
    manager = CampaignManager()
    module = manager.load(campaign_file)
    # Add an empty table
    module.random_tables["empty"] = RandomTable(name="Empty", dice="1d6", entries=[])
    with pytest.raises(CampaignError, match="no entries"):
        manager.roll_on_table(module, "empty")


# --- Hull Breach scaffold test ---


def test_hull_breach_scaffold_loads():
    """Verify the hull breach scaffold JSON loads and parses correctly."""
    scaffold_path = Path("campaigns/hull_breach_scaffold.json")
    if not scaffold_path.exists():
        pytest.skip("Hull breach scaffold not found")
    manager = CampaignManager()
    module = manager.load(scaffold_path)
    assert module.name == "Hull Breach Scaffold"
    assert len(module.locations) >= 5
    assert len(module.entities) >= 3
    assert len(module.missions) >= 2
    assert len(module.factions) >= 2
    assert len(module.random_tables) >= 1
