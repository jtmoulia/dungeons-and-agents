"""Tests for game/preview.py — dice expressions, previews, odds, and conditionals."""

from __future__ import annotations

import random

import pytest

from game.engine import GameEngine
from game.models import CharacterClass
from game.preview import (
    OddsResult,
    PreviewEngine,
    PreviewResult,
    dice_avg,
    dice_range,
    roll_dice_expr,
)


@pytest.fixture
def engine() -> GameEngine:
    """Create an in-memory GameEngine with a test game."""
    e = GameEngine(in_memory=True)
    e.init_game("Test Game")
    return e


@pytest.fixture
def preview(engine: GameEngine) -> PreviewEngine:
    return PreviewEngine(engine)


@pytest.fixture
def marine(engine: GameEngine) -> str:
    """Create a marine character and return the name."""
    engine.create_character("Vex", CharacterClass.MARINE)
    return "Vex"


# --- Dice expression tests ---

class TestDiceExpressions:
    def test_roll_basic(self):
        random.seed(42)
        result = roll_dice_expr("1d20")
        assert 1 <= result <= 20

    def test_roll_multiple_dice(self):
        random.seed(42)
        result = roll_dice_expr("3d6")
        assert 3 <= result <= 18

    def test_roll_with_positive_modifier(self):
        random.seed(42)
        result = roll_dice_expr("1d20+5")
        assert 6 <= result <= 25

    def test_roll_with_negative_modifier(self):
        random.seed(42)
        result = roll_dice_expr("1d20-3")
        assert -2 <= result <= 17

    def test_roll_whitespace(self):
        random.seed(42)
        result = roll_dice_expr("  1d20  ")
        assert 1 <= result <= 20

    def test_roll_case_insensitive(self):
        random.seed(42)
        result = roll_dice_expr("1D20")
        assert 1 <= result <= 20

    def test_roll_invalid_expr(self):
        with pytest.raises(ValueError, match="Invalid dice expression"):
            roll_dice_expr("not_dice")

    def test_roll_invalid_format(self):
        with pytest.raises(ValueError):
            roll_dice_expr("d20")  # missing count

    def test_dice_range_basic(self):
        lo, hi = dice_range("1d20")
        assert lo == 1
        assert hi == 20

    def test_dice_range_multiple(self):
        lo, hi = dice_range("3d6")
        assert lo == 3
        assert hi == 18

    def test_dice_range_with_modifier(self):
        lo, hi = dice_range("2d10+5")
        assert lo == 7
        assert hi == 25

    def test_dice_range_negative_mod(self):
        lo, hi = dice_range("1d6-2")
        assert lo == -1
        assert hi == 4

    def test_dice_range_invalid(self):
        with pytest.raises(ValueError):
            dice_range("abc")

    def test_dice_avg_basic(self):
        avg = dice_avg("1d6")
        assert avg == 3.5

    def test_dice_avg_2d10(self):
        avg = dice_avg("2d10")
        assert avg == 11.0

    def test_dice_avg_with_mod(self):
        avg = dice_avg("1d20+5")
        assert avg == 15.5


# --- Preview engine tests ---

class TestPreviewEngine:
    def test_preview_roll_no_side_effects(self, engine, preview, marine):
        """Preview roll should not change character state (e.g. stress on failure)."""
        char_before = engine.get_character(marine)
        stress_before = char_before.stress

        # Seed so we get a failure (high roll on d100 = fail in roll-under)
        random.seed(999)
        result = preview.preview_roll(marine, "combat")

        assert isinstance(result, PreviewResult)
        assert "[PREVIEW]" in result.description
        assert result.committed is False

        # Stress should be unchanged
        char_after = engine.get_character(marine)
        assert char_after.stress == stress_before

    def test_preview_damage_no_side_effects(self, engine, preview, marine):
        """Preview damage should not change character HP."""
        char_before = engine.get_character(marine)
        hp_before = char_before.hp

        result = preview.preview_damage(marine, 5)

        assert isinstance(result, PreviewResult)
        assert "[PREVIEW]" in result.description

        char_after = engine.get_character(marine)
        assert char_after.hp == hp_before

    def test_preview_roll_returns_details(self, engine, preview, marine):
        random.seed(42)
        result = preview.preview_roll(marine, "combat")
        assert "roll" in result.details
        assert "target" in result.details
        assert "result" in result.details
        assert "succeeded" in result.details

    def test_preview_damage_returns_details(self, engine, preview, marine):
        result = preview.preview_damage(marine, 10)
        assert "damage_taken" in result.details
        assert "wound" in result.details
        assert "dead" in result.details


# --- Snapshot tests ---

class TestSnapshots:
    def test_save_and_restore(self, engine, preview, marine):
        preview.save_snapshot("before_damage")
        engine.apply_damage(marine, 5)
        char = engine.get_character(marine)
        hp_after_damage = char.hp

        assert preview.restore_snapshot("before_damage") is True
        char_restored = engine.get_character(marine)
        assert char_restored.hp > hp_after_damage

    def test_restore_nonexistent(self, preview):
        assert preview.restore_snapshot("nope") is False

    def test_list_snapshots(self, preview):
        assert preview.list_snapshots() == []
        preview.save_snapshot("a")
        preview.save_snapshot("b")
        assert sorted(preview.list_snapshots()) == ["a", "b"]

    def test_delete_snapshot(self, preview):
        preview.save_snapshot("x")
        assert preview.delete_snapshot("x") is True
        assert preview.delete_snapshot("x") is False

    def test_default_snapshot_name(self, preview):
        preview.save_snapshot()
        assert "default" in preview.list_snapshots()
        assert preview.restore_snapshot() is True


# --- Odds / probability analysis ---

class TestOdds:
    def test_check_odds_basic(self, engine, preview, marine):
        odds = preview.check_odds(marine, "combat")
        assert isinstance(odds, OddsResult)
        assert odds.target > 0
        assert odds.modifier == 0
        assert odds.effective_target == odds.target
        # Probabilities should sum to 100
        total = odds.success_pct + odds.critical_success_pct + odds.failure_pct + odds.critical_failure_pct
        assert total == 100

    def test_check_odds_with_skill(self, engine, preview, marine):
        # Give the marine a skill
        char = engine.get_character(marine)
        # Marines start with some skills — check
        if char.skills:
            skill_name = next(iter(char.skills))
            odds = preview.check_odds(marine, "combat", skill=skill_name)
            assert odds.modifier > 0
            assert odds.effective_target > odds.target

    def test_check_odds_unknown_stat(self, engine, preview, marine):
        with pytest.raises(ValueError, match="Unknown stat"):
            preview.check_odds(marine, "nonexistent_stat")

    def test_check_odds_probabilities_reasonable(self, engine, preview, marine):
        """With a typical stat around 30-60, odds should be reasonable."""
        odds = preview.check_odds(marine, "combat")
        # At least some chance of success and failure
        assert odds.success_pct + odds.critical_success_pct > 0
        assert odds.failure_pct + odds.critical_failure_pct > 0


# --- Conditional action chains ---

class TestConditional:
    def test_resolve_conditional_hit(self):
        random.seed(42)
        from game.preview import PreviewEngine, PreviewResult

        engine = GameEngine(in_memory=True)
        engine.init_game("Test")
        preview = PreviewEngine(engine)

        # Run enough times to get at least one hit and one miss
        hits = 0
        misses = 0
        for _ in range(100):
            result = preview.resolve_conditional("1d20", 10, on_success_expr="1d6")
            assert isinstance(result, PreviewResult)
            if result.details["succeeded"]:
                hits += 1
                assert "effect_roll" in result.details
            else:
                misses += 1
        assert hits > 0
        assert misses > 0

    def test_resolve_conditional_with_commit(self, engine, preview, marine):
        """When commit=True, damage should actually be applied."""
        char = engine.get_character(marine)
        hp_before = char.hp

        # Force a hit with a low threshold
        random.seed(42)
        result = preview.resolve_conditional(
            "1d20", 1,  # threshold of 1 = almost always hit
            on_success_expr="1d6",
            target_character=marine,
            commit=True,
        )
        if result.committed:
            char_after = engine.get_character(marine)
            assert char_after.hp <= hp_before

    def test_resolve_conditional_no_commit_default(self, engine, preview, marine):
        """Default is not to commit."""
        char = engine.get_character(marine)
        hp_before = char.hp

        random.seed(42)
        preview.resolve_conditional(
            "1d20", 1,
            on_success_expr="1d6",
            target_character=marine,
        )
        char_after = engine.get_character(marine)
        assert char_after.hp == hp_before

    def test_resolve_conditional_fail_expr(self):
        engine = GameEngine(in_memory=True)
        engine.init_game("Test")
        preview = PreviewEngine(engine)

        # Force a miss with impossible threshold
        random.seed(42)
        result = preview.resolve_conditional(
            "1d20", 999,
            on_fail_expr="1d4",
        )
        assert not result.details["succeeded"]
        assert "effect_roll" in result.details
        assert result.details["effect_dice"] == "1d4"


# --- Monte Carlo simulation ---

class TestSimulation:
    def test_simulate_basic(self, preview):
        result = preview.simulate_conditional("1d20", 15, "1d10", trials=1000)
        assert result["trials"] == 1000
        assert 0 <= result["hit_rate_pct"] <= 100
        assert result["avg_damage_on_hit"] >= 0
        assert result["expected_damage_per_roll"] >= 0
        assert result["threshold"] == 15

    def test_simulate_certain_hit(self, preview):
        """Threshold of 1 on 1d20 means always hit."""
        result = preview.simulate_conditional("1d20", 1, "1d6", trials=1000)
        assert result["hit_rate_pct"] == 100.0

    def test_simulate_impossible(self, preview):
        """Threshold of 100 on 1d20 means never hit."""
        result = preview.simulate_conditional("1d20", 100, "1d6", trials=1000)
        assert result["hit_rate_pct"] == 0.0

    def test_simulate_expected_damage_range(self, preview):
        """For 1d20 >= 11 (50% hit), 1d6 damage (avg 3.5), expected ~1.75."""
        result = preview.simulate_conditional("1d20", 11, "1d6", trials=50000)
        # With 50k trials, should be close
        assert 1.0 <= result["expected_damage_per_roll"] <= 2.5
