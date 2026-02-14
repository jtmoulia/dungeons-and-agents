"""Combat encounter logic."""

from __future__ import annotations

from game.dice import roll_d10, stat_check
from game.engine import EngineError, GameEngine
from game.models import Combatant, CombatState


class CombatEngine:
    """Manages combat encounters on top of GameEngine."""

    def __init__(self, engine: GameEngine):
        self.engine = engine

    def start_combat(self, combatant_names: list[str]) -> CombatState:
        state = self.engine._load()

        if state.combat.active:
            raise EngineError("Combat already in progress. End it first.")

        # Validate all combatants exist
        for name in combatant_names:
            if name not in state.characters:
                raise EngineError(f"Character '{name}' not found.")

        # Roll initiative: Speed stat check, with roll as tiebreaker
        combatants = []
        for name in combatant_names:
            char = state.characters[name]
            result = stat_check(char.stats.speed)
            # Higher initiative = earlier turn. Successes get speed + roll bonus.
            initiative = (char.stats.speed + result.roll) if result.succeeded else result.roll
            combatants.append(Combatant(name=name, initiative=initiative))
            self.engine._log(
                state,
                f"{name} rolls initiative: {result.roll} "
                f"(Speed {char.stats.speed}) -> {initiative}",
                "combat",
            )

        # Sort by initiative descending (highest goes first)
        combatants.sort(key=lambda c: c.initiative, reverse=True)

        state.combat = CombatState(
            active=True,
            round=1,
            combatants=combatants,
            current_index=0,
        )

        order = ", ".join(c.name for c in combatants)
        self.engine._log(state, f"Combat started! Turn order: {order}", "combat")
        self.engine._save(state)
        return state.combat

    def combat_action(
        self,
        name: str,
        action: str,
        target: str | None = None,
        advantage: bool = False,
        disadvantage: bool = False,
    ) -> dict:
        state = self.engine._load()

        if not state.combat.active:
            raise EngineError("No combat in progress.")

        char = state.characters.get(name)
        if not char:
            raise EngineError(f"Character '{name}' not found.")
        if not char.alive:
            raise EngineError(f"{name} is dead and cannot act.")

        result: dict = {"actor": name, "action": action, "target": target}

        if action == "attack":
            if not target:
                raise EngineError("Attack requires a --target.")
            target_char = state.characters.get(target)
            if not target_char:
                raise EngineError(f"Target '{target}' not found.")

            # Roll combat stat check
            check = stat_check(
                char.stats.combat,
                advantage=advantage,
                disadvantage=disadvantage,
            )
            result["roll"] = check.roll
            result["check_result"] = check.result.value

            if check.succeeded:
                # Roll damage based on equipped weapon or unarmed
                if char.weapons:
                    weapon = char.weapons[0]
                    damage = _roll_damage(weapon.damage)
                    result["weapon"] = weapon.name
                else:
                    damage = roll_d10()
                    result["weapon"] = "unarmed"

                result["damage"] = damage
                self.engine._log(
                    state,
                    f"{name} attacks {target} with {result['weapon']}: "
                    f"rolled {check.roll} ({check.result.value}), "
                    f"dealing {damage} damage!",
                    "combat",
                )
                # Apply damage inline (avoid re-loading state)
                _apply_combat_damage(state, target, damage, self.engine)
            else:
                result["damage"] = 0
                self.engine._log(
                    state,
                    f"{name} attacks {target}: rolled {check.roll} ({check.result.value}), miss!",
                    "combat",
                )

        elif action == "defend":
            self.engine._log(state, f"{name} takes a defensive stance.", "combat")
            result["effect"] = "Defending: +10 to Body saves until next turn."

        elif action == "flee":
            check = stat_check(
                char.stats.speed,
                advantage=advantage,
                disadvantage=disadvantage,
            )
            result["roll"] = check.roll
            result["check_result"] = check.result.value
            if check.succeeded:
                self.engine._log(
                    state,
                    f"{name} flees combat! (Speed check: {check.roll}, success)",
                    "combat",
                )
                result["fled"] = True
                # Remove from combatant list
                state.combat.combatants = [
                    c for c in state.combat.combatants if c.name != name
                ]
                if state.combat.current_index >= len(state.combat.combatants):
                    state.combat.current_index = 0
            else:
                self.engine._log(
                    state,
                    f"{name} tries to flee but fails! (Speed check: {check.roll}, failure)",
                    "combat",
                )
                result["fled"] = False

        elif action == "use_item":
            self.engine._log(state, f"{name} uses an item.", "combat")
            result["effect"] = "Item used. DM resolves effect."

        else:
            self.engine._log(state, f"{name}: {action}", "combat")
            result["effect"] = "Custom action. DM resolves."

        # Advance turn
        _advance_turn(state, self.engine)
        self.engine._save(state)
        return result

    def end_combat(self) -> None:
        state = self.engine._load()
        if not state.combat.active:
            raise EngineError("No combat in progress.")

        state.combat = CombatState()
        self.engine._log(state, "Combat ended.", "combat")
        self.engine._save(state)


def _roll_damage(damage_str: str) -> int:
    """Parse and roll damage like '2d10', '1d10', '4d10'."""
    parts = damage_str.lower().split("d")
    count = int(parts[0]) if parts[0] else 1
    sides = int(parts[1])
    total = 0
    for _ in range(count):
        if sides == 10:
            total += roll_d10()
        else:
            import random
            total += random.randint(1, sides)
    return total


def _apply_combat_damage(state, target_name: str, amount: int, engine) -> None:
    """Apply damage during combat without re-loading state."""
    char = state.characters[target_name]

    if char.armor.ap > 0:
        if amount < char.armor.ap:
            engine._log(state, f"{target_name}'s {char.armor.name} absorbs {amount} damage.", "combat")
            return
        else:
            engine._log(
                state,
                f"{target_name}'s {char.armor.name} (AP {char.armor.ap}) destroyed!",
                "combat",
            )
            amount -= char.armor.ap
            char.armor.ap = 0
            char.armor.name = "none (destroyed)"

    char.hp -= amount
    if char.hp <= 0:
        char.hp = char.max_hp
        char.wounds += 1
        engine._log(
            state,
            f"{target_name} takes {amount} damage -> wound! ({char.wounds}/{char.max_wounds})",
            "combat",
        )
        if char.wounds >= char.max_wounds:
            char.alive = False
            engine._log(state, f"{target_name} is dead!", "combat")
    else:
        engine._log(
            state,
            f"{target_name} takes {amount} damage (HP: {char.hp}/{char.max_hp})",
            "combat",
        )


def _advance_turn(state, engine) -> None:
    """Advance to next combatant in initiative order."""
    combat = state.combat
    if not combat.combatants:
        return

    combat.current_index += 1
    if combat.current_index >= len(combat.combatants):
        combat.current_index = 0
        combat.round += 1
        engine._log(state, f"--- Round {combat.round} ---", "combat")
