"""Configurable dice rolling for the generic engine."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from enum import Enum


class CheckResult(Enum):
    CRITICAL_SUCCESS = "critical_success"
    SUCCESS = "success"
    FAILURE = "failure"
    CRITICAL_FAILURE = "critical_failure"


@dataclass
class GenericRollResult:
    roll: int
    natural: int
    target: int
    result: CheckResult
    all_rolls: list[int] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return self.result in (CheckResult.SUCCESS, CheckResult.CRITICAL_SUCCESS)


_DICE_RE = re.compile(r"^(\d+)d(\d+)([+-]\d+)?$")


def roll_dice_expr(expr: str) -> tuple[int, int]:
    """Roll a dice expression like '1d20' or '2d6+3'.

    Returns (total, natural) where natural is the sum of dice without modifier.
    """
    m = _DICE_RE.match(expr.strip().lower())
    if not m:
        raise ValueError(f"Invalid dice expression: {expr}")
    count = int(m.group(1))
    sides = int(m.group(2))
    mod = int(m.group(3)) if m.group(3) else 0
    natural = sum(random.randint(1, sides) for _ in range(count))
    return natural + mod, natural


def generic_check(
    target: int,
    dice_expr: str = "1d20",
    direction: str = "over",
    modifier: int = 0,
    critical_success: int | None = None,
    critical_failure: int | None = None,
    advantage: bool = False,
    disadvantage: bool = False,
) -> GenericRollResult:
    """Perform a configurable stat check.

    direction="over":  roll + modifier >= target = success
    direction="under": roll + modifier <= target = success
    """
    if advantage and disadvantage:
        advantage = False
        disadvantage = False

    def _roll() -> tuple[int, int]:
        return roll_dice_expr(dice_expr)

    if advantage or disadvantage:
        total1, nat1 = _roll()
        total2, nat2 = _roll()
        all_rolls = [total1, total2]
        if direction == "over":
            better_first = total1 >= total2
        else:
            better_first = total1 <= total2
        if advantage:
            total, natural = (total1, nat1) if better_first else (total2, nat2)
        else:
            total, natural = (total2, nat2) if better_first else (total1, nat1)
    else:
        total, natural = _roll()
        all_rolls = [total]

    effective = total + modifier

    if critical_success is not None and natural == critical_success:
        result = CheckResult.CRITICAL_SUCCESS
    elif critical_failure is not None and natural == critical_failure:
        result = CheckResult.CRITICAL_FAILURE
    elif direction == "over":
        result = CheckResult.SUCCESS if effective >= target else CheckResult.FAILURE
    else:
        result = CheckResult.SUCCESS if effective <= target else CheckResult.FAILURE

    return GenericRollResult(
        roll=effective,
        natural=natural,
        target=target,
        result=result,
        all_rolls=all_rolls,
    )
