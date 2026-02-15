"""Dice rolling and check resolution — d100 roll-under system."""

import random
from dataclasses import dataclass, field
from enum import Enum


class CheckResult(Enum):
    CRITICAL_SUCCESS = "critical_success"
    SUCCESS = "success"
    FAILURE = "failure"
    CRITICAL_FAILURE = "critical_failure"


@dataclass
class RollResult:
    roll: int
    target: int
    result: CheckResult
    doubles: bool
    all_rolls: list[int] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return self.result in (CheckResult.SUCCESS, CheckResult.CRITICAL_SUCCESS)


def roll_d100() -> int:
    return random.randint(0, 99)


def roll_d20() -> int:
    return random.randint(1, 20)


def roll_d10() -> int:
    return random.randint(1, 10)


def roll_2d10() -> int:
    return roll_d10() + roll_d10()


def is_doubles(roll: int) -> bool:
    """Check if a d100 roll has matching tens and ones digits (00, 11, 22, ..., 99)."""
    return (roll // 10) == (roll % 10)


def stat_check(
    target: int,
    modifier: int = 0,
    advantage: bool = False,
    disadvantage: bool = False,
) -> RollResult:
    """Perform a d100 roll-under check against a target stat.

    Rules:
    - Roll <= target (after modifier) = success
    - Roll in 90-99 = always failure
    - Roll of 99 = critical failure
    - Doubles that succeed = critical success
    - Doubles that fail = critical failure
    - Advantage: roll twice, take lower (better for roll-under)
    - Disadvantage: roll twice, take higher (worse for roll-under)
    - Both cancel out to a normal single roll
    """
    effective_target = target + modifier

    # Advantage and disadvantage cancel out
    if advantage and disadvantage:
        advantage = False
        disadvantage = False

    if advantage or disadvantage:
        roll1 = roll_d100()
        roll2 = roll_d100()
        all_rolls = [roll1, roll2]
        roll = min(roll1, roll2) if advantage else max(roll1, roll2)
    else:
        roll = roll_d100()
        all_rolls = [roll]

    doubles = is_doubles(roll)

    # 90-99 always fails
    if roll >= 90:
        if roll == 99 or doubles:
            result = CheckResult.CRITICAL_FAILURE
        else:
            result = CheckResult.FAILURE
    elif roll <= effective_target:
        if doubles:
            result = CheckResult.CRITICAL_SUCCESS
        else:
            result = CheckResult.SUCCESS
    else:
        if doubles:
            result = CheckResult.CRITICAL_FAILURE
        else:
            result = CheckResult.FAILURE

    return RollResult(
        roll=roll,
        target=effective_target,
        result=result,
        doubles=doubles,
        all_rolls=all_rolls,
    )
