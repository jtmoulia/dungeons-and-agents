"""Preview and what-if system for the DM engine.

Lets DMs simulate actions before committing them, inspect probability
distributions, and define conditional action chains like:
  "roll 1d20, on 15+ do 1d10 damage"
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from game.dice import roll_d100, stat_check
from game.engine import GameEngine


@dataclass
class PreviewResult:
    """Result of a previewed (uncommitted) action."""

    description: str
    details: dict = field(default_factory=dict)
    committed: bool = False


@dataclass
class OddsResult:
    """Probability analysis for a stat check."""

    target: int
    modifier: int
    effective_target: int
    success_pct: float
    critical_success_pct: float
    failure_pct: float
    critical_failure_pct: float


def roll_dice_expr(expr: str) -> int:
    """Parse and roll a dice expression like '1d20', '2d10+5', '3d6-2'.

    Supports: NdM, NdM+X, NdM-X
    """
    expr = expr.strip().lower()
    m = re.match(r"^(\d+)d(\d+)([+-]\d+)?$", expr)
    if not m:
        raise ValueError(f"Invalid dice expression: {expr}")
    count = int(m.group(1))
    sides = int(m.group(2))
    mod = int(m.group(3)) if m.group(3) else 0
    total = sum(random.randint(1, sides) for _ in range(count)) + mod
    return total


def dice_range(expr: str) -> tuple[int, int]:
    """Return (min, max) possible values for a dice expression."""
    expr = expr.strip().lower()
    m = re.match(r"^(\d+)d(\d+)([+-]\d+)?$", expr)
    if not m:
        raise ValueError(f"Invalid dice expression: {expr}")
    count = int(m.group(1))
    sides = int(m.group(2))
    mod = int(m.group(3)) if m.group(3) else 0
    return count + mod, count * sides + mod


def dice_avg(expr: str) -> float:
    """Return the expected average for a dice expression."""
    lo, hi = dice_range(expr)
    return (lo + hi) / 2


class PreviewEngine:
    """Wraps a GameEngine to support previews and what-if analysis."""

    def __init__(self, engine: GameEngine):
        self._engine = engine
        self._snapshots: dict[str, str] = {}

    # --- Snapshots ---

    def save_snapshot(self, name: str = "default") -> None:
        """Save current engine state as a named snapshot."""
        self._snapshots[name] = self._engine.save_state_json()

    def restore_snapshot(self, name: str = "default") -> bool:
        """Restore engine state from a named snapshot. Returns False if not found."""
        if name not in self._snapshots:
            return False
        self._engine.load_state_json(self._snapshots[name])
        return True

    def list_snapshots(self) -> list[str]:
        return list(self._snapshots.keys())

    def delete_snapshot(self, name: str) -> bool:
        return self._snapshots.pop(name, None) is not None

    # --- Preview (dry-run) actions ---

    def preview_roll(
        self,
        character: str,
        stat: str,
        skill: str | None = None,
        advantage: bool = False,
        disadvantage: bool = False,
    ) -> PreviewResult:
        """Roll a check without committing state changes (no stress on failure)."""
        # Snapshot, roll, restore
        state_json = self._engine.save_state_json()
        try:
            result = self._engine.roll_check(
                character, stat, skill=skill,
                advantage=advantage, disadvantage=disadvantage,
            )
            return PreviewResult(
                description=(
                    f"[PREVIEW] {character} rolls {stat} "
                    f"(target {result.target}): "
                    f"{result.roll} -> {result.result.value}"
                ),
                details={
                    "roll": result.roll,
                    "target": result.target,
                    "result": result.result.value,
                    "doubles": result.doubles,
                    "all_rolls": result.all_rolls,
                    "succeeded": result.succeeded,
                },
            )
        finally:
            self._engine.load_state_json(state_json)

    def preview_damage(self, character: str, amount: int) -> PreviewResult:
        """Preview damage without committing."""
        state_json = self._engine.save_state_json()
        try:
            result = self._engine.apply_damage(character, amount)
            return PreviewResult(
                description=(
                    f"[PREVIEW] {character} would take {result['damage_taken']} damage"
                    + (f" (wound!)" if result["wound"] else "")
                    + (f" (DEATH)" if result["dead"] else "")
                ),
                details=result,
            )
        finally:
            self._engine.load_state_json(state_json)

    # --- Probability analysis ---

    def check_odds(
        self,
        character: str,
        stat: str,
        skill: str | None = None,
    ) -> OddsResult:
        """Calculate success/failure probabilities for a stat check."""
        from game.tables import SKILL_TIER_BONUS

        char = self._engine.get_character(character)

        # Find target stat
        stat_lower = stat.lower()
        target = None
        for model in (char.stats, char.saves):
            if hasattr(model, stat_lower):
                target = getattr(model, stat_lower)
                break
        if target is None:
            raise ValueError(f"Unknown stat: {stat}")

        modifier = 0
        if skill and skill in char.skills:
            modifier = SKILL_TIER_BONUS[char.skills[skill]]

        effective = target + modifier

        # Calculate exact probabilities for d100 roll-under
        # Rolls 0-99, success if roll <= effective, but 90-99 always fail
        crit_success = 0
        success = 0
        failure = 0
        crit_failure = 0

        for roll in range(100):
            tens = roll // 10
            ones = roll % 10
            doubles = tens == ones

            if roll >= 90:
                if roll == 99 or doubles:
                    crit_failure += 1
                else:
                    failure += 1
            elif roll <= effective:
                if doubles:
                    crit_success += 1
                else:
                    success += 1
            else:
                if doubles:
                    crit_failure += 1
                else:
                    failure += 1

        return OddsResult(
            target=target,
            modifier=modifier,
            effective_target=effective,
            success_pct=success,
            critical_success_pct=crit_success,
            failure_pct=failure,
            critical_failure_pct=crit_failure,
        )

    # --- Conditional action chains ---

    def resolve_conditional(
        self,
        dice_expr: str,
        threshold: int,
        on_success_expr: str | None = None,
        on_fail_expr: str | None = None,
        target_character: str | None = None,
        commit: bool = False,
    ) -> PreviewResult:
        """Resolve a conditional action chain.

        Example: resolve_conditional("1d20", 15, on_success_expr="1d10")
          -> Roll 1d20. If >= 15, roll 1d10 for effect.

        Args:
            dice_expr: The triggering roll (e.g., "1d20")
            threshold: Minimum value needed for success
            on_success_expr: Dice to roll if threshold met (e.g., "1d10" for damage)
            on_fail_expr: Dice to roll on failure (optional)
            target_character: Character to apply damage to (if committing)
            commit: If True, actually apply damage to the character
        """
        trigger_roll = roll_dice_expr(dice_expr)
        succeeded = trigger_roll >= threshold

        details: dict = {
            "trigger_dice": dice_expr,
            "trigger_roll": trigger_roll,
            "threshold": threshold,
            "succeeded": succeeded,
        }

        effect_roll = None
        if succeeded and on_success_expr:
            effect_roll = roll_dice_expr(on_success_expr)
            details["effect_dice"] = on_success_expr
            details["effect_roll"] = effect_roll
        elif not succeeded and on_fail_expr:
            effect_roll = roll_dice_expr(on_fail_expr)
            details["effect_dice"] = on_fail_expr
            details["effect_roll"] = effect_roll

        # Build description
        lo, hi = dice_range(dice_expr)
        desc_parts = [f"Rolled {dice_expr}: {trigger_roll} (need {threshold}+)"]
        if succeeded:
            desc_parts.append("-> HIT")
            if effect_roll is not None:
                desc_parts.append(f"-> {on_success_expr}: {effect_roll}")
        else:
            desc_parts.append("-> MISS")
            if effect_roll is not None:
                desc_parts.append(f"-> {on_fail_expr}: {effect_roll}")

        committed = False
        if commit and target_character and effect_roll is not None and succeeded:
            result = self._engine.apply_damage(target_character, effect_roll)
            details["damage_result"] = result
            desc_parts.append(
                f"({target_character} takes {result['damage_taken']} damage)"
            )
            committed = True

        return PreviewResult(
            description=" ".join(desc_parts),
            details=details,
            committed=committed,
        )

    def simulate_conditional(
        self,
        dice_expr: str,
        threshold: int,
        effect_expr: str,
        trials: int = 10000,
    ) -> dict:
        """Monte Carlo simulation of a conditional chain.

        Returns probability distribution and expected damage.

        Example: simulate_conditional("1d20", 15, "1d10")
          -> What % of the time does this hit, and what's the average damage?
        """
        hits = 0
        total_damage = 0
        damage_values: list[int] = []

        trigger_lo, trigger_hi = dice_range(dice_expr)
        effect_lo, effect_hi = dice_range(effect_expr)

        for _ in range(trials):
            trigger = roll_dice_expr(dice_expr)
            if trigger >= threshold:
                hits += 1
                dmg = roll_dice_expr(effect_expr)
                total_damage += dmg
                damage_values.append(dmg)

        hit_pct = (hits / trials) * 100
        avg_damage_on_hit = total_damage / hits if hits else 0
        expected_damage = total_damage / trials

        return {
            "trials": trials,
            "hit_rate_pct": round(hit_pct, 1),
            "avg_damage_on_hit": round(avg_damage_on_hit, 1),
            "expected_damage_per_roll": round(expected_damage, 1),
            "trigger_range": f"{trigger_lo}-{trigger_hi}",
            "threshold": threshold,
            "effect_range": f"{effect_lo}-{effect_hi}",
            "effect_avg": dice_avg(effect_expr),
        }
