"""Tests for dice rolling and check resolution."""

from unittest.mock import patch

from game.dice import (
    CheckResult,
    RollResult,
    is_doubles,
    roll_d10,
    roll_d100,
    roll_d20,
    stat_check,
)


def test_roll_d100_range():
    for _ in range(100):
        r = roll_d100()
        assert 0 <= r <= 99


def test_roll_d20_range():
    for _ in range(100):
        r = roll_d20()
        assert 1 <= r <= 20


def test_roll_d10_range():
    for _ in range(100):
        r = roll_d10()
        assert 1 <= r <= 10


def test_is_doubles():
    assert is_doubles(0)   # 00
    assert is_doubles(11)
    assert is_doubles(22)
    assert is_doubles(33)
    assert is_doubles(44)
    assert is_doubles(55)
    assert is_doubles(99)
    assert not is_doubles(12)
    assert not is_doubles(1)
    assert not is_doubles(90)


def test_stat_check_success():
    with patch("game.dice.roll_d100", return_value=30):
        result = stat_check(50)
        assert result.roll == 30
        assert result.target == 50
        assert result.result == CheckResult.SUCCESS
        assert result.succeeded


def test_stat_check_failure():
    with patch("game.dice.roll_d100", return_value=60):
        result = stat_check(50)
        assert result.result == CheckResult.FAILURE
        assert not result.succeeded


def test_stat_check_critical_success_on_doubles():
    with patch("game.dice.roll_d100", return_value=33):
        result = stat_check(50)
        assert result.result == CheckResult.CRITICAL_SUCCESS
        assert result.doubles


def test_stat_check_critical_failure_on_doubles():
    with patch("game.dice.roll_d100", return_value=66):
        result = stat_check(50)
        assert result.result == CheckResult.CRITICAL_FAILURE
        assert result.doubles


def test_stat_check_90_plus_always_fails():
    with patch("game.dice.roll_d100", return_value=91):
        result = stat_check(95)
        assert result.result == CheckResult.FAILURE


def test_stat_check_99_critical_failure():
    with patch("game.dice.roll_d100", return_value=99):
        result = stat_check(99)
        assert result.result == CheckResult.CRITICAL_FAILURE


def test_stat_check_with_modifier():
    with patch("game.dice.roll_d100", return_value=55):
        result = stat_check(50, modifier=10)
        assert result.target == 60
        # 55 is doubles and under target, so critical success
        assert result.result == CheckResult.CRITICAL_SUCCESS


def test_stat_check_with_skill_bonus():
    with patch("game.dice.roll_d100", return_value=58):
        # Without modifier, 58 > 50 = fail
        result = stat_check(50, modifier=0)
        assert result.result == CheckResult.FAILURE
        # With +10 modifier, 58 <= 60 = success
        result = stat_check(50, modifier=10)
        assert result.result == CheckResult.SUCCESS


def test_roll_result_succeeded_property():
    assert RollResult(roll=10, target=50, result=CheckResult.SUCCESS, doubles=False).succeeded
    assert RollResult(roll=10, target=50, result=CheckResult.CRITICAL_SUCCESS, doubles=True).succeeded
    assert not RollResult(roll=60, target=50, result=CheckResult.FAILURE, doubles=False).succeeded
    assert not RollResult(roll=66, target=50, result=CheckResult.CRITICAL_FAILURE, doubles=True).succeeded


# --- Advantage / Disadvantage tests ---


def test_advantage_takes_lower_roll():
    """Advantage rolls twice and takes the lower (better for roll-under)."""
    with patch("game.dice.roll_d100", side_effect=[60, 20]):
        result = stat_check(50, advantage=True)
        assert result.roll == 20
        assert result.all_rolls == [60, 20]
        assert result.succeeded


def test_disadvantage_takes_higher_roll():
    """Disadvantage rolls twice and takes the higher (worse for roll-under)."""
    with patch("game.dice.roll_d100", side_effect=[20, 60]):
        result = stat_check(50, disadvantage=True)
        assert result.roll == 60
        assert result.all_rolls == [20, 60]
        assert not result.succeeded


def test_advantage_and_disadvantage_cancel():
    """Both advantage and disadvantage cancel to a normal roll."""
    with patch("game.dice.roll_d100", return_value=30):
        result = stat_check(50, advantage=True, disadvantage=True)
        assert result.roll == 30
        assert result.all_rolls == [30]


def test_doubles_checked_on_chosen_roll():
    """Doubles are checked on the chosen roll, not the discarded one."""
    # Chosen roll is 33 (doubles, under target) -> critical success
    with patch("game.dice.roll_d100", side_effect=[70, 33]):
        result = stat_check(50, advantage=True)
        assert result.roll == 33
        assert result.doubles is True
        assert result.result == CheckResult.CRITICAL_SUCCESS

    # Discarded roll is 44 (doubles), chosen is 60 (not doubles) -> failure
    with patch("game.dice.roll_d100", side_effect=[44, 60]):
        result = stat_check(50, disadvantage=True)
        assert result.roll == 60
        assert result.doubles is False
        assert result.result == CheckResult.FAILURE


def test_all_rolls_populated_normal():
    """Normal rolls have a single entry in all_rolls."""
    with patch("game.dice.roll_d100", return_value=42):
        result = stat_check(50)
        assert result.all_rolls == [42]


def test_all_rolls_populated_advantage():
    """Advantage rolls have both entries in all_rolls."""
    with patch("game.dice.roll_d100", side_effect=[42, 78]):
        result = stat_check(50, advantage=True)
        assert len(result.all_rolls) == 2
        assert result.all_rolls == [42, 78]
