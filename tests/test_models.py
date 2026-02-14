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
        skills=["Computers", "First Aid"],
        conditions=[Condition.PANICKED],
    )
    data = char.model_dump_json()
    restored = Character.model_validate_json(data)
    assert restored.name == "Alice"
    assert restored.stats.intellect == 55
    assert restored.armor.ap == 3
    assert restored.weapons[0].name == "Revolver"
    assert Condition.PANICKED in restored.conditions


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
