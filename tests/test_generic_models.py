"""Tests for generic engine Pydantic models."""

import pytest
from pydantic import ValidationError

from game.generic.models import (
    CombatConfig,
    ConditionConfig,
    DiceConfig,
    GenericCharacter,
    GenericEngineConfig,
    GenericGameState,
    HealthConfig,
)


class TestGenericEngineConfig:
    def test_defaults(self):
        config = GenericEngineConfig()
        assert config.stat_names == []
        assert config.dice.dice == "1d20"
        assert config.dice.direction == "over"
        assert not config.health.enabled
        assert not config.combat.enabled
        assert not config.conditions.enabled

    def test_full_config(self):
        config = GenericEngineConfig(
            stat_names=["str", "dex", "int"],
            dice=DiceConfig(dice="1d20", direction="over", critical_success=20),
            health=HealthConfig(enabled=True, default_max_hp=20),
            combat=CombatConfig(enabled=True, initiative_stat="dex"),
            conditions=ConditionConfig(enabled=True, conditions=["stunned"]),
        )
        assert config.stat_names == ["str", "dex", "int"]
        assert config.health.default_max_hp == 20
        assert config.combat.initiative_stat == "dex"

    def test_invalid_initiative_stat(self):
        with pytest.raises(ValidationError, match="initiative_stat"):
            GenericEngineConfig(
                stat_names=["str", "dex"],
                combat=CombatConfig(enabled=True, initiative_stat="agility"),
            )

    def test_initiative_stat_not_validated_when_combat_disabled(self):
        config = GenericEngineConfig(
            stat_names=["str"],
            combat=CombatConfig(enabled=False, initiative_stat="agility"),
        )
        assert config.combat.initiative_stat == "agility"

    def test_serialization_roundtrip(self):
        config = GenericEngineConfig(
            stat_names=["cool", "hard"],
            dice=DiceConfig(dice="2d6", direction="over"),
            health=HealthConfig(enabled=True, default_max_hp=12, death_at_zero=False),
        )
        json_str = config.model_dump_json()
        restored = GenericEngineConfig.model_validate_json(json_str)
        assert restored == config


class TestGenericGameState:
    def test_full_state_roundtrip(self):
        state = GenericGameState(
            name="Test",
            config=GenericEngineConfig(stat_names=["str"]),
            characters={
                "Alice": GenericCharacter(
                    name="Alice",
                    stats={"str": 14},
                    hp=20,
                    max_hp=20,
                    conditions=["poisoned"],
                    inventory=["sword"],
                    notes={"class": "fighter"},
                )
            },
            scene="A dark tavern.",
        )
        json_str = state.model_dump_json()
        restored = GenericGameState.model_validate_json(json_str)
        assert restored.name == "Test"
        assert restored.characters["Alice"].stats["str"] == 14
        assert restored.characters["Alice"].conditions == ["poisoned"]
        assert restored.scene == "A dark tavern."
