"""Tests for the generic game engine."""

from unittest.mock import patch

import pytest

from game.generic.dice import CheckResult
from game.generic.engine import GenericEngine, GenericEngineError
from game.generic.models import (
    CombatConfig,
    ConditionConfig,
    DiceConfig,
    GenericEngineConfig,
    HealthConfig,
)


@pytest.fixture
def config():
    return GenericEngineConfig(
        stat_names=["strength", "agility", "wit"],
        dice=DiceConfig(
            dice="1d20", direction="over", critical_success=20, critical_failure=1
        ),
        health=HealthConfig(enabled=True, default_max_hp=20),
        combat=CombatConfig(enabled=True, initiative_stat="agility", initiative_dice="1d20"),
        conditions=ConditionConfig(enabled=True, conditions=["poisoned", "stunned"]),
    )


@pytest.fixture
def engine(tmp_path, config):
    e = GenericEngine(tmp_path / "game.json")
    e.init_game("Test Game", config=config)
    return e


@pytest.fixture
def mem_engine(config):
    e = GenericEngine(in_memory=True)
    e.init_game("Test Game", config=config)
    return e


class TestInitGame:
    def test_init(self, engine):
        state = engine.get_state()
        assert state.name == "Test Game"
        assert state.config.stat_names == ["strength", "agility", "wit"]
        assert len(state.log) == 1

    def test_default_config(self, tmp_path):
        e = GenericEngine(tmp_path / "game.json")
        e.init_game("Minimal")
        state = e.get_state()
        assert state.config.stat_names == []
        assert state.config.dice.dice == "1d20"


class TestCharacters:
    def test_create(self, engine):
        char = engine.create_character("Alice", stats={"strength": 14, "agility": 12})
        assert char.name == "Alice"
        assert char.stats["strength"] == 14
        assert char.hp == 20
        assert char.max_hp == 20

    def test_create_invalid_stat(self, engine):
        with pytest.raises(GenericEngineError, match="Unknown stat"):
            engine.create_character("Bob", stats={"charisma": 10})

    def test_create_duplicate(self, engine):
        engine.create_character("Alice")
        with pytest.raises(GenericEngineError, match="already exists"):
            engine.create_character("Alice")

    def test_create_custom_hp(self, engine):
        char = engine.create_character("Tank", hp=30)
        assert char.hp == 30
        assert char.max_hp == 30

    def test_get_character(self, engine):
        engine.create_character("Alice", stats={"strength": 14})
        char = engine.get_character("Alice")
        assert char.stats["strength"] == 14

    def test_get_character_not_found(self, engine):
        with pytest.raises(GenericEngineError, match="not found"):
            engine.get_character("Nobody")

    def test_set_stat(self, engine):
        engine.create_character("Alice", stats={"strength": 10})
        char = engine.set_stat("Alice", "strength", 16)
        assert char.stats["strength"] == 16

    def test_set_stat_unknown(self, engine):
        engine.create_character("Alice")
        with pytest.raises(GenericEngineError, match="Unknown stat"):
            engine.set_stat("Alice", "charisma", 10)

    def test_no_hp_when_health_disabled(self, tmp_path):
        config = GenericEngineConfig(stat_names=["str"])
        e = GenericEngine(tmp_path / "game.json")
        e.init_game("No HP", config=config)
        char = e.create_character("Alice", stats={"str": 10})
        assert char.hp is None
        assert char.max_hp is None


class TestRollCheck:
    def test_success(self, engine):
        engine.create_character("Alice", stats={"strength": 15})
        with patch("game.generic.dice.random.randint", return_value=16):
            result = engine.roll_check("Alice", "strength")
        assert result.succeeded
        assert result.target == 15

    def test_failure(self, engine):
        engine.create_character("Alice", stats={"strength": 15})
        with patch("game.generic.dice.random.randint", return_value=5):
            result = engine.roll_check("Alice", "strength")
        assert not result.succeeded

    def test_unknown_stat(self, engine):
        engine.create_character("Alice")
        with pytest.raises(GenericEngineError, match="Unknown stat"):
            engine.roll_check("Alice", "charisma")

    def test_no_stat_value(self, engine):
        engine.create_character("Alice", stats={"strength": 10})
        with pytest.raises(GenericEngineError, match="no value"):
            engine.roll_check("Alice", "agility")

    def test_character_not_found(self, engine):
        with pytest.raises(GenericEngineError, match="not found"):
            engine.roll_check("Nobody", "strength")

    def test_with_modifier(self, engine):
        engine.create_character("Alice", stats={"strength": 10})
        with patch("game.generic.dice.random.randint", return_value=8):
            result = engine.roll_check("Alice", "strength", modifier=3)
        assert result.roll == 11
        assert result.succeeded

    def test_advantage(self, engine):
        engine.create_character("Alice", stats={"strength": 10})
        rolls = iter([5, 15])
        with patch("game.generic.dice.random.randint", side_effect=rolls):
            result = engine.roll_check("Alice", "strength", advantage=True)
        assert result.roll == 15

    def test_critical_success(self, engine):
        engine.create_character("Alice", stats={"strength": 10})
        with patch("game.generic.dice.random.randint", return_value=20):
            result = engine.roll_check("Alice", "strength")
        assert result.result == CheckResult.CRITICAL_SUCCESS


class TestHealth:
    def test_damage(self, engine):
        engine.create_character("Alice", hp=20)
        result = engine.apply_damage("Alice", 5)
        assert result["hp"] == 15
        assert not result["dead"]

    def test_damage_death(self, engine):
        engine.create_character("Alice", hp=5)
        result = engine.apply_damage("Alice", 10)
        assert result["hp"] == -5
        assert result["dead"]
        char = engine.get_character("Alice")
        assert not char.alive

    def test_damage_no_death(self, tmp_path):
        config = GenericEngineConfig(
            health=HealthConfig(enabled=True, default_max_hp=10, death_at_zero=False),
        )
        e = GenericEngine(tmp_path / "game.json")
        e.init_game("No Death", config=config)
        e.create_character("Alice")
        result = e.apply_damage("Alice", 15)
        assert result["hp"] == -5
        assert not result["dead"]

    def test_heal(self, engine):
        engine.create_character("Alice", hp=20)
        engine.apply_damage("Alice", 10)
        healed = engine.heal("Alice", 5)
        assert healed == 5
        assert engine.get_character("Alice").hp == 15

    def test_heal_capped(self, engine):
        engine.create_character("Alice", hp=20)
        engine.apply_damage("Alice", 3)
        healed = engine.heal("Alice", 10)
        assert healed == 3
        assert engine.get_character("Alice").hp == 20

    def test_set_hp(self, engine):
        engine.create_character("Alice", hp=20)
        char = engine.set_hp("Alice", 5, max_hp=25)
        assert char.hp == 5
        assert char.max_hp == 25

    def test_health_disabled(self, tmp_path):
        config = GenericEngineConfig(stat_names=["str"])
        e = GenericEngine(tmp_path / "game.json")
        e.init_game("No Health", config=config)
        e.create_character("Alice")
        with pytest.raises(GenericEngineError, match="not enabled"):
            e.apply_damage("Alice", 5)
        with pytest.raises(GenericEngineError, match="not enabled"):
            e.heal("Alice", 5)


class TestConditions:
    def test_add(self, engine):
        engine.create_character("Alice")
        conditions = engine.add_condition("Alice", "poisoned")
        assert "poisoned" in conditions

    def test_add_invalid(self, engine):
        engine.create_character("Alice")
        with pytest.raises(GenericEngineError, match="Unknown condition"):
            engine.add_condition("Alice", "flying")

    def test_add_freeform(self, tmp_path):
        config = GenericEngineConfig(
            conditions=ConditionConfig(enabled=True, conditions=[]),
        )
        e = GenericEngine(tmp_path / "game.json")
        e.init_game("Freeform", config=config)
        e.create_character("Alice")
        conditions = e.add_condition("Alice", "on_fire")
        assert "on_fire" in conditions

    def test_add_duplicate_idempotent(self, engine):
        engine.create_character("Alice")
        engine.add_condition("Alice", "poisoned")
        conditions = engine.add_condition("Alice", "poisoned")
        assert conditions.count("poisoned") == 1

    def test_remove(self, engine):
        engine.create_character("Alice")
        engine.add_condition("Alice", "poisoned")
        conditions = engine.remove_condition("Alice", "poisoned")
        assert "poisoned" not in conditions

    def test_remove_missing(self, engine):
        engine.create_character("Alice")
        with pytest.raises(GenericEngineError, match="doesn't have"):
            engine.remove_condition("Alice", "poisoned")

    def test_conditions_disabled(self, tmp_path):
        config = GenericEngineConfig()
        e = GenericEngine(tmp_path / "game.json")
        e.init_game("No Conditions", config=config)
        e.create_character("Alice")
        with pytest.raises(GenericEngineError, match="not enabled"):
            e.add_condition("Alice", "poisoned")


class TestCombat:
    def test_start(self, engine):
        engine.create_character("Alice", stats={"agility": 14})
        engine.create_character("Bob", stats={"agility": 10})
        with patch("game.generic.engine.roll_dice_expr", return_value=(10, 10)):
            combat = engine.start_combat(["Alice", "Bob"])
        assert combat.active
        assert combat.round == 1
        # Alice has higher initiative (10 + 14 = 24 vs 10 + 10 = 20)
        assert combat.combatants[0].name == "Alice"

    def test_next_turn(self, engine):
        engine.create_character("Alice", stats={"agility": 14})
        engine.create_character("Bob", stats={"agility": 10})
        with patch("game.generic.engine.roll_dice_expr", return_value=(10, 10)):
            engine.start_combat(["Alice", "Bob"])
        combat = engine.next_turn()
        assert combat.current_index == 1
        assert combat.round == 1

    def test_next_turn_wraps_round(self, engine):
        engine.create_character("Alice", stats={"agility": 14})
        engine.create_character("Bob", stats={"agility": 10})
        with patch("game.generic.engine.roll_dice_expr", return_value=(10, 10)):
            engine.start_combat(["Alice", "Bob"])
        engine.next_turn()  # Bob's turn
        combat = engine.next_turn()  # wrap to round 2
        assert combat.current_index == 0
        assert combat.round == 2

    def test_end_combat(self, engine):
        engine.create_character("Alice", stats={"agility": 14})
        with patch("game.generic.engine.roll_dice_expr", return_value=(10, 10)):
            engine.start_combat(["Alice"])
        engine.end_combat()
        state = engine.get_state()
        assert not state.combat.active

    def test_combat_disabled(self, tmp_path):
        config = GenericEngineConfig()
        e = GenericEngine(tmp_path / "game.json")
        e.init_game("No Combat", config=config)
        e.create_character("Alice")
        with pytest.raises(GenericEngineError, match="not enabled"):
            e.start_combat(["Alice"])

    def test_combat_already_active(self, engine):
        engine.create_character("Alice", stats={"agility": 14})
        with patch("game.generic.engine.roll_dice_expr", return_value=(10, 10)):
            engine.start_combat(["Alice"])
        with pytest.raises(GenericEngineError, match="already active"):
            engine.start_combat(["Alice"])

    def test_unknown_combatant(self, engine):
        with pytest.raises(GenericEngineError, match="not found"):
            engine.start_combat(["Nobody"])


class TestInventory:
    def test_add(self, engine):
        engine.create_character("Alice")
        inv = engine.add_inventory("Alice", "sword")
        assert "sword" in inv

    def test_remove(self, engine):
        engine.create_character("Alice")
        engine.add_inventory("Alice", "sword")
        inv = engine.remove_inventory("Alice", "sword")
        assert "sword" not in inv

    def test_remove_missing(self, engine):
        engine.create_character("Alice")
        with pytest.raises(GenericEngineError, match="doesn't have"):
            engine.remove_inventory("Alice", "sword")


class TestSceneAndLog:
    def test_set_scene(self, engine):
        engine.set_scene("A dark tavern.")
        state = engine.get_state()
        assert state.scene == "A dark tavern."

    def test_log(self, engine):
        engine.create_character("Alice")
        log = engine.get_log(10)
        assert len(log) >= 2  # init + create
        assert any("Alice" in entry.message for entry in log)


class TestNotes:
    def test_set_note(self, engine):
        engine.create_character("Alice")
        notes = engine.set_note("Alice", "class", "wizard")
        assert notes["class"] == "wizard"

    def test_note_not_found(self, engine):
        with pytest.raises(GenericEngineError, match="not found"):
            engine.set_note("Nobody", "class", "wizard")


class TestPersistence:
    def test_file_roundtrip(self, tmp_path, config):
        e1 = GenericEngine(tmp_path / "game.json")
        e1.init_game("Persist Test", config=config)
        e1.create_character("Alice", stats={"strength": 14}, hp=20)
        e1.add_condition("Alice", "poisoned")

        e2 = GenericEngine(tmp_path / "game.json")
        state = e2.get_state()
        assert state.name == "Persist Test"
        assert state.characters["Alice"].stats["strength"] == 14
        assert "poisoned" in state.characters["Alice"].conditions

    def test_json_serialization(self, mem_engine, config):
        mem_engine.create_character("Alice", stats={"strength": 14})
        json_data = mem_engine.save_state_json()

        e2 = GenericEngine(in_memory=True)
        e2.load_state_json(json_data)
        state = e2.get_state()
        assert state.characters["Alice"].stats["strength"] == 14

    def test_no_game_error(self, tmp_path):
        e = GenericEngine(tmp_path / "nonexistent.json")
        with pytest.raises(GenericEngineError, match="No game found"):
            e.get_state()

    def test_in_memory_no_game_error(self):
        e = GenericEngine(in_memory=True)
        with pytest.raises(GenericEngineError, match="No game found"):
            e.get_state()
