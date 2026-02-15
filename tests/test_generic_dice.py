"""Tests for the generic engine dice system."""

from unittest.mock import patch

import pytest

from game.generic.dice import (
    CheckResult,
    GenericRollResult,
    generic_check,
    roll_dice_expr,
)


class TestRollDiceExpr:
    def test_1d20(self):
        for _ in range(50):
            total, natural = roll_dice_expr("1d20")
            assert 1 <= total <= 20
            assert total == natural

    def test_2d6_plus_3(self):
        for _ in range(50):
            total, natural = roll_dice_expr("2d6+3")
            assert 2 <= natural <= 12
            assert total == natural + 3

    def test_1d6_minus_1(self):
        for _ in range(50):
            total, natural = roll_dice_expr("1d6-1")
            assert 1 <= natural <= 6
            assert total == natural - 1

    def test_whitespace_and_case(self):
        total, natural = roll_dice_expr("  1D20  ")
        assert 1 <= total <= 20

    def test_invalid_expression(self):
        with pytest.raises(ValueError, match="Invalid dice expression"):
            roll_dice_expr("banana")

    def test_invalid_no_d(self):
        with pytest.raises(ValueError):
            roll_dice_expr("20")


class TestGenericCheck:
    def test_roll_over_success(self):
        with patch("game.generic.dice.random.randint", return_value=15):
            result = generic_check(target=10, dice_expr="1d20", direction="over")
        assert result.result == CheckResult.SUCCESS
        assert result.succeeded

    def test_roll_over_failure(self):
        with patch("game.generic.dice.random.randint", return_value=5):
            result = generic_check(target=10, dice_expr="1d20", direction="over")
        assert result.result == CheckResult.FAILURE
        assert not result.succeeded

    def test_roll_under_success(self):
        with patch("game.generic.dice.random.randint", return_value=30):
            result = generic_check(target=50, dice_expr="1d100", direction="under")
        assert result.result == CheckResult.SUCCESS

    def test_roll_under_failure(self):
        with patch("game.generic.dice.random.randint", return_value=70):
            result = generic_check(target=50, dice_expr="1d100", direction="under")
        assert result.result == CheckResult.FAILURE

    def test_critical_success(self):
        with patch("game.generic.dice.random.randint", return_value=20):
            result = generic_check(
                target=25, dice_expr="1d20", direction="over", critical_success=20
            )
        assert result.result == CheckResult.CRITICAL_SUCCESS
        assert result.succeeded

    def test_critical_failure(self):
        with patch("game.generic.dice.random.randint", return_value=1):
            result = generic_check(
                target=5, dice_expr="1d20", direction="over", critical_failure=1
            )
        assert result.result == CheckResult.CRITICAL_FAILURE
        assert not result.succeeded

    def test_modifier(self):
        with patch("game.generic.dice.random.randint", return_value=8):
            result = generic_check(
                target=10, dice_expr="1d20", direction="over", modifier=3
            )
        # roll=8, modifier=3, effective=11 >= target=10
        assert result.roll == 11
        assert result.succeeded

    def test_advantage_picks_better_for_over(self):
        rolls = iter([5, 15])
        with patch("game.generic.dice.random.randint", side_effect=rolls):
            result = generic_check(
                target=10, dice_expr="1d20", direction="over", advantage=True
            )
        assert result.roll == 15
        assert result.succeeded
        assert len(result.all_rolls) == 2

    def test_disadvantage_picks_worse_for_over(self):
        rolls = iter([5, 15])
        with patch("game.generic.dice.random.randint", side_effect=rolls):
            result = generic_check(
                target=10, dice_expr="1d20", direction="over", disadvantage=True
            )
        assert result.roll == 5
        assert not result.succeeded

    def test_advantage_and_disadvantage_cancel(self):
        with patch("game.generic.dice.random.randint", return_value=10):
            result = generic_check(
                target=10,
                dice_expr="1d20",
                direction="over",
                advantage=True,
                disadvantage=True,
            )
        # Should roll once (cancelled out)
        assert len(result.all_rolls) == 1

    def test_roll_over_exact_target(self):
        with patch("game.generic.dice.random.randint", return_value=10):
            result = generic_check(target=10, dice_expr="1d20", direction="over")
        assert result.succeeded

    def test_roll_under_exact_target(self):
        with patch("game.generic.dice.random.randint", return_value=50):
            result = generic_check(target=50, dice_expr="1d100", direction="under")
        assert result.succeeded
