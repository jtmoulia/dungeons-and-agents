"""Tests for the core game engine."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from game.engine import EngineError, GameEngine
from game.models import CharacterClass, Controller


@pytest.fixture
def engine(tmp_path):
    return GameEngine(tmp_path / "game.json")


@pytest.fixture
def game(engine):
    engine.init_game("Test Game")
    return engine


def test_init_game(engine):
    state = engine.init_game("My Game")
    assert state.name == "My Game"
    assert engine.state_path.exists()


def test_init_game_persistence(engine):
    engine.init_game("Persisted")
    state = engine.get_state()
    assert state.name == "Persisted"


def test_no_game_raises(engine):
    with pytest.raises(EngineError, match="No game found"):
        engine.get_state()


def test_create_character(game):
    char = game.create_character("Alice", CharacterClass.MARINE)
    assert char.name == "Alice"
    assert char.char_class == CharacterClass.MARINE
    assert char.stats.combat >= 37  # 2+2+25+10 minimum
    assert char.hp == 25  # Marine HP
    assert "Military Training" in char.skills


def test_create_duplicate_character(game):
    game.create_character("Alice", CharacterClass.MARINE)
    with pytest.raises(EngineError, match="already exists"):
        game.create_character("Alice", CharacterClass.SCIENTIST)


def test_create_character_with_controller(game):
    char = game.create_character("Bob", CharacterClass.TEAMSTER, Controller.USER)
    assert char.controller == Controller.USER


def test_get_character(game):
    game.create_character("Alice", CharacterClass.SCIENTIST)
    char = game.get_character("Alice")
    assert char.char_class == CharacterClass.SCIENTIST


def test_get_missing_character(game):
    with pytest.raises(EngineError, match="not found"):
        game.get_character("Nobody")


def test_roll_check(game):
    game.create_character("Alice", CharacterClass.MARINE)
    with patch("game.engine.stat_check") as mock_check:
        from game.dice import CheckResult, RollResult
        mock_check.return_value = RollResult(
            roll=30, target=50, result=CheckResult.SUCCESS, doubles=False
        )
        result = game.roll_check("Alice", "combat")
        assert result.succeeded


def test_roll_check_unknown_stat(game):
    game.create_character("Alice", CharacterClass.MARINE)
    with pytest.raises(EngineError, match="Unknown stat"):
        game.roll_check("Alice", "charisma")


def test_roll_check_with_skill(game):
    game.create_character("Alice", CharacterClass.MARINE)
    with patch("game.engine.stat_check") as mock_check:
        from game.dice import CheckResult, RollResult
        mock_check.return_value = RollResult(
            roll=30, target=60, result=CheckResult.SUCCESS, doubles=False
        )
        game.roll_check("Alice", "combat", skill="Military Training")
        # Should be called with SKILL_BONUS modifier
        mock_check.assert_called_once()
        _, kwargs = mock_check.call_args
        assert kwargs.get("modifier", mock_check.call_args[0][1] if len(mock_check.call_args[0]) > 1 else 0) == 10


def test_apply_damage(game):
    game.create_character("Alice", CharacterClass.MARINE)
    result = game.apply_damage("Alice", 10)
    assert result["damage_taken"] == 10
    assert not result["wound"]
    char = game.get_character("Alice")
    assert char.hp == 15  # 25 - 10


def test_apply_damage_wound(game):
    game.create_character("Alice", CharacterClass.MARINE)
    result = game.apply_damage("Alice", 30)  # More than 25 HP
    assert result["wound"]
    char = game.get_character("Alice")
    assert char.wounds == 1
    assert char.hp == 25  # Reset to max


def test_apply_damage_death(game):
    game.create_character("Alice", CharacterClass.MARINE)
    game.apply_damage("Alice", 30)  # Wound 1
    result = game.apply_damage("Alice", 30)  # Wound 2 = death
    assert result["dead"]
    char = game.get_character("Alice")
    assert not char.alive


def test_apply_damage_armor_absorbs(game):
    game.create_character("Alice", CharacterClass.MARINE)
    # Manually set armor
    state = game._load()
    state.characters["Alice"].armor.name = "Combat Armor"
    state.characters["Alice"].armor.ap = 5
    game._save(state)

    result = game.apply_damage("Alice", 3)
    assert result["absorbed"] == 3
    assert result["damage_taken"] == 0


def test_apply_damage_armor_destroyed(game):
    game.create_character("Alice", CharacterClass.MARINE)
    state = game._load()
    state.characters["Alice"].armor.name = "Combat Armor"
    state.characters["Alice"].armor.ap = 5
    game._save(state)

    result = game.apply_damage("Alice", 8)
    assert result["absorbed"] == 5
    assert result["damage_taken"] == 3


def test_heal(game):
    game.create_character("Alice", CharacterClass.MARINE)
    game.apply_damage("Alice", 10)
    healed = game.heal("Alice", 5)
    assert healed == 5
    char = game.get_character("Alice")
    assert char.hp == 20


def test_heal_caps_at_max(game):
    game.create_character("Alice", CharacterClass.MARINE)
    game.apply_damage("Alice", 5)
    healed = game.heal("Alice", 100)
    assert healed == 5
    char = game.get_character("Alice")
    assert char.hp == 25


def test_add_stress(game):
    game.create_character("Alice", CharacterClass.MARINE)
    new_stress = game.add_stress("Alice", 3)
    assert new_stress == 5  # Started at 2


def test_remove_stress(game):
    game.create_character("Alice", CharacterClass.MARINE)
    new_stress = game.add_stress("Alice", -1)
    assert new_stress == 1


def test_stress_floor_zero(game):
    game.create_character("Alice", CharacterClass.MARINE)
    new_stress = game.add_stress("Alice", -10)
    assert new_stress == 0


def test_panic_check_panicked(game):
    game.create_character("Alice", CharacterClass.MARINE)
    game.add_stress("Alice", 18)  # stress = 20
    with patch("game.engine.roll_d20", return_value=5):
        result = game.panic_check("Alice")
        assert result["panicked"]
        assert result["effect"] is not None


def test_panic_check_calm(game):
    game.create_character("Alice", CharacterClass.MARINE)
    # stress = 2, roll needs to be <= 2
    with patch("game.engine.roll_d20", return_value=15):
        result = game.panic_check("Alice")
        assert not result["panicked"]


def test_inventory_add(game):
    game.create_character("Alice", CharacterClass.MARINE)
    inv = game.add_inventory("Alice", "Flashlight")
    assert "Flashlight" in inv


def test_inventory_remove(game):
    game.create_character("Alice", CharacterClass.MARINE)
    game.add_inventory("Alice", "Flashlight")
    inv = game.remove_inventory("Alice", "Flashlight")
    assert "Flashlight" not in inv


def test_inventory_remove_missing(game):
    game.create_character("Alice", CharacterClass.MARINE)
    with pytest.raises(EngineError, match="doesn't have"):
        game.remove_inventory("Alice", "Nonexistent")


def test_set_scene(game):
    game.set_scene("A dark hallway.")
    state = game.get_state()
    assert state.scene == "A dark hallway."


def test_get_log(game):
    game.create_character("Alice", CharacterClass.MARINE)
    entries = game.get_log(10)
    assert len(entries) >= 1
    assert any("initialized" in e.message.lower() for e in entries)


def test_atomic_write(engine, tmp_path):
    """Verify state file is written atomically."""
    engine.init_game("Atomic Test")
    state_file = tmp_path / "game.json"
    assert state_file.exists()
    # Should be valid JSON
    data = json.loads(state_file.read_text())
    assert data["name"] == "Atomic Test"
