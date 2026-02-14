"""Tests for Pydantic models: serialization roundtrip, validation."""

import json

from game.models import (
    Armor,
    Character,
    CharacterClass,
    CombatState,
    Combatant,
    Condition,
    Controller,
    GameState,
    LogEntry,
    Saves,
    SkillLevel,
    Stats,
    Weapon,
)


def test_character_defaults():
    char = Character(name="Test", char_class=CharacterClass.MARINE)
    assert char.name == "Test"
    assert char.hp == 20
    assert char.stress == 2
    assert char.alive is True
    assert char.controller == Controller.AI
    assert char.inventory == []
    assert char.conditions == []


def test_character_roundtrip():
    char = Character(
        name="Alice",
        char_class=CharacterClass.SCIENTIST,
        controller=Controller.USER,
        stats=Stats(strength=35, speed=40, intellect=55, combat=30),
        saves=Saves(sanity=40, fear=25, body=25),
        hp=15,
        max_hp=15,
        stress=4,
        armor=Armor(name="Hazard Suit", ap=3),
        inventory=["Flashlight", "Medkit"],
        weapons=[Weapon(name="Revolver", damage="2d10", range="nearby", shots=6)],
        skills={"Computers": SkillLevel.TRAINED, "First Aid": SkillLevel.EXPERT},
        conditions=[Condition.PANICKED],
    )
    data = char.model_dump_json()
    restored = Character.model_validate_json(data)
    assert restored.name == "Alice"
    assert restored.stats.intellect == 55
    assert restored.armor.ap == 3
    assert restored.weapons[0].name == "Revolver"
    assert Condition.PANICKED in restored.conditions
    assert restored.skills["Computers"] == SkillLevel.TRAINED
    assert restored.skills["First Aid"] == SkillLevel.EXPERT


def test_skills_as_dict():
    """Skills are stored as dict[str, SkillLevel]."""
    char = Character(
        name="Test",
        char_class=CharacterClass.MARINE,
        skills={"Athletics": SkillLevel.EXPERT, "Military Training": SkillLevel.MASTER},
    )
    assert char.skills["Athletics"] == SkillLevel.EXPERT
    assert char.skills["Military Training"] == SkillLevel.MASTER


def test_skills_migration_from_list():
    """Old list[str] format is migrated to dict with TRAINED level."""
    data = {
        "name": "OldSave",
        "char_class": "marine",
        "skills": ["Military Training", "Athletics"],
    }
    char = Character.model_validate(data)
    assert isinstance(char.skills, dict)
    assert char.skills["Military Training"] == SkillLevel.TRAINED
    assert char.skills["Athletics"] == SkillLevel.TRAINED


def test_skills_roundtrip_with_tiers():
    """Skills with different tiers survive JSON roundtrip."""
    char = Character(
        name="Test",
        char_class=CharacterClass.SCIENTIST,
        skills={
            "Computers": SkillLevel.MASTER,
            "First Aid": SkillLevel.TRAINED,
            "Chemistry": SkillLevel.EXPERT,
        },
    )
    data = char.model_dump_json()
    restored = Character.model_validate_json(data)
    assert restored.skills["Computers"] == SkillLevel.MASTER
    assert restored.skills["First Aid"] == SkillLevel.TRAINED
    assert restored.skills["Chemistry"] == SkillLevel.EXPERT


def test_game_state_roundtrip():
    state = GameState(
        name="Test Game",
        characters={
            "Alice": Character(name="Alice", char_class=CharacterClass.MARINE),
        },
        scene="A dark corridor aboard the station.",
        log=[LogEntry(message="Game started.", category="system")],
    )
    data = state.model_dump_json()
    restored = GameState.model_validate_json(data)
    assert restored.name == "Test Game"
    assert "Alice" in restored.characters
    assert restored.characters["Alice"].char_class == CharacterClass.MARINE
    assert restored.scene == "A dark corridor aboard the station."
    assert len(restored.log) == 1


def test_game_state_active_campaign():
    """GameState includes active_campaign field."""
    state = GameState(name="Test", active_campaign="Hull Breach")
    data = state.model_dump_json()
    restored = GameState.model_validate_json(data)
    assert restored.active_campaign == "Hull Breach"


def test_game_state_active_campaign_default_none():
    state = GameState(name="Test")
    assert state.active_campaign is None


def test_combat_state_current_combatant():
    cs = CombatState(
        active=True,
        round=1,
        combatants=[
            Combatant(name="Alice", initiative=80),
            Combatant(name="Bob", initiative=60),
        ],
        current_index=0,
    )
    assert cs.current_combatant == "Alice"

    cs.current_index = 1
    assert cs.current_combatant == "Bob"


def test_combat_state_empty():
    cs = CombatState()
    assert cs.current_combatant is None
    assert cs.active is False


def test_weapon_model():
    w = Weapon(name="Pulse Rifle", damage="3d10", range="far", shots=30)
    data = w.model_dump_json()
    restored = Weapon.model_validate_json(data)
    assert restored.shots == 30
    assert restored.special == ""


def test_log_entry_has_timestamp():
    entry = LogEntry(message="Something happened.")
    assert entry.timestamp  # Should be auto-set
    assert entry.category == "action"
