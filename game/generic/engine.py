"""Generic game engine: configurable state machine for any setting."""

from __future__ import annotations

import tempfile
from pathlib import Path

from game.models import LogEntry
from game.generic.dice import GenericRollResult, generic_check, roll_dice_expr
from game.generic.models import (
    GenericCharacter,
    GenericCombatant,
    GenericCombatState,
    GenericEngineConfig,
    GenericGameState,
)


class GenericEngineError(Exception):
    pass


class GenericEngine:
    """Manages generic game state with atomic JSON persistence or in-memory."""

    def __init__(
        self,
        state_path: Path | None = None,
        in_memory: bool = False,
    ):
        self.in_memory = in_memory
        self.state_path = state_path
        self._state: GenericGameState | None = None

    def _load(self) -> GenericGameState:
        if self.in_memory:
            if self._state is None:
                raise GenericEngineError("No game found. Call init_game() first.")
            return self._state
        if not self.state_path or not self.state_path.exists():
            raise GenericEngineError("No game found.")
        return GenericGameState.model_validate_json(self.state_path.read_text())

    def _save(self, state: GenericGameState) -> None:
        if self.in_memory:
            self._state = state
            return
        assert self.state_path is not None
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        data = state.model_dump_json(indent=2)
        fd, tmp_path = tempfile.mkstemp(dir=self.state_path.parent, suffix=".tmp")
        try:
            with open(fd, "w") as f:
                f.write(data)
            Path(tmp_path).rename(self.state_path)
        except BaseException:
            Path(tmp_path).unlink(missing_ok=True)
            raise

    def _log(self, state: GenericGameState, message: str, category: str = "action") -> None:
        state.log.append(LogEntry(message=message, category=category))

    def save_state_json(self) -> str:
        return self._load().model_dump_json()

    def load_state_json(self, data: str) -> None:
        self._save(GenericGameState.model_validate_json(data))

    # --- Game management ---

    def init_game(
        self, name: str, config: GenericEngineConfig | None = None
    ) -> GenericGameState:
        state = GenericGameState(name=name, config=config or GenericEngineConfig())
        self._log(state, f"Game '{name}' initialized.", "system")
        self._save(state)
        return state

    def get_state(self) -> GenericGameState:
        return self._load()

    # --- Character management ---

    def create_character(
        self,
        name: str,
        stats: dict[str, int] | None = None,
        hp: int | None = None,
    ) -> GenericCharacter:
        state = self._load()
        if name in state.characters:
            raise GenericEngineError(f"Character '{name}' already exists.")

        config = state.config
        char_stats = stats or {}
        for stat_name in char_stats:
            if stat_name not in config.stat_names:
                raise GenericEngineError(
                    f"Unknown stat '{stat_name}'. Valid: {config.stat_names}"
                )

        char_hp = None
        char_max_hp = None
        if config.health.enabled:
            char_hp = hp if hp is not None else config.health.default_max_hp
            char_max_hp = char_hp

        char = GenericCharacter(
            name=name,
            stats=char_stats,
            hp=char_hp,
            max_hp=char_max_hp,
        )
        state.characters[name] = char
        self._log(state, f"{name} created.", "system")
        self._save(state)
        return char

    def get_character(self, name: str) -> GenericCharacter:
        state = self._load()
        if name not in state.characters:
            raise GenericEngineError(f"Character '{name}' not found.")
        return state.characters[name]

    def set_stat(self, name: str, stat: str, value: int) -> GenericCharacter:
        """Set a single stat value on a character."""
        state = self._load()
        char = state.characters.get(name)
        if not char:
            raise GenericEngineError(f"Character '{name}' not found.")
        if stat not in state.config.stat_names:
            raise GenericEngineError(
                f"Unknown stat '{stat}'. Valid: {state.config.stat_names}"
            )
        char.stats[stat] = value
        self._log(state, f"{name}'s {stat} set to {value}.")
        self._save(state)
        return char

    # --- Stat checks ---

    def roll_check(
        self,
        name: str,
        stat: str,
        modifier: int = 0,
        advantage: bool = False,
        disadvantage: bool = False,
    ) -> GenericRollResult:
        state = self._load()
        char = state.characters.get(name)
        if not char:
            raise GenericEngineError(f"Character '{name}' not found.")
        if stat not in state.config.stat_names:
            raise GenericEngineError(
                f"Unknown stat '{stat}'. Valid: {state.config.stat_names}"
            )
        target = char.stats.get(stat)
        if target is None:
            raise GenericEngineError(f"{name} has no value for stat '{stat}'.")

        dice_cfg = state.config.dice
        result = generic_check(
            target=target,
            dice_expr=dice_cfg.dice,
            direction=dice_cfg.direction,
            modifier=modifier,
            critical_success=dice_cfg.critical_success,
            critical_failure=dice_cfg.critical_failure,
            advantage=advantage,
            disadvantage=disadvantage,
        )

        self._log(
            state,
            f"{name} rolls {stat} ({dice_cfg.dice}, target {result.target}): "
            f"{result.roll} -> {result.result.value}",
        )
        self._save(state)
        return result

    # --- Health ---

    def apply_damage(self, name: str, amount: int) -> dict:
        state = self._load()
        if not state.config.health.enabled:
            raise GenericEngineError("Health tracking is not enabled.")
        char = state.characters.get(name)
        if not char:
            raise GenericEngineError(f"Character '{name}' not found.")

        result: dict = {"character": name, "damage": amount, "dead": False}
        char.hp = (char.hp or 0) - amount
        result["hp"] = char.hp
        result["max_hp"] = char.max_hp

        if char.hp <= 0 and state.config.health.death_at_zero:
            char.alive = False
            result["dead"] = True
            self._log(state, f"{name} takes {amount} damage and dies! (HP: {char.hp})", "system")
        else:
            self._log(state, f"{name} takes {amount} damage (HP: {char.hp}/{char.max_hp}).")

        self._save(state)
        return result

    def heal(self, name: str, amount: int) -> int:
        state = self._load()
        if not state.config.health.enabled:
            raise GenericEngineError("Health tracking is not enabled.")
        char = state.characters.get(name)
        if not char:
            raise GenericEngineError(f"Character '{name}' not found.")

        old_hp = char.hp or 0
        char.hp = min(old_hp + amount, char.max_hp or old_hp + amount)
        healed = char.hp - old_hp
        self._log(state, f"{name} heals {healed} HP (HP: {char.hp}/{char.max_hp}).")
        self._save(state)
        return healed

    def set_hp(self, name: str, hp: int, max_hp: int | None = None) -> GenericCharacter:
        """Directly set HP (and optionally max HP) for a character."""
        state = self._load()
        if not state.config.health.enabled:
            raise GenericEngineError("Health tracking is not enabled.")
        char = state.characters.get(name)
        if not char:
            raise GenericEngineError(f"Character '{name}' not found.")
        if max_hp is not None:
            char.max_hp = max_hp
        char.hp = hp
        self._log(state, f"{name}'s HP set to {hp}/{char.max_hp}.")
        self._save(state)
        return char

    # --- Conditions ---

    def add_condition(self, name: str, condition: str) -> list[str]:
        state = self._load()
        if not state.config.conditions.enabled:
            raise GenericEngineError("Condition tracking is not enabled.")
        char = state.characters.get(name)
        if not char:
            raise GenericEngineError(f"Character '{name}' not found.")
        if (
            state.config.conditions.conditions
            and condition not in state.config.conditions.conditions
        ):
            raise GenericEngineError(
                f"Unknown condition '{condition}'. "
                f"Valid: {state.config.conditions.conditions}"
            )
        if condition not in char.conditions:
            char.conditions.append(condition)
        self._log(state, f"{name} gains condition: {condition}.")
        self._save(state)
        return char.conditions

    def remove_condition(self, name: str, condition: str) -> list[str]:
        state = self._load()
        if not state.config.conditions.enabled:
            raise GenericEngineError("Condition tracking is not enabled.")
        char = state.characters.get(name)
        if not char:
            raise GenericEngineError(f"Character '{name}' not found.")
        if condition not in char.conditions:
            raise GenericEngineError(f"{name} doesn't have condition '{condition}'.")
        char.conditions.remove(condition)
        self._log(state, f"{name} loses condition: {condition}.")
        self._save(state)
        return char.conditions

    # --- Combat ---

    def start_combat(self, combatant_names: list[str]) -> GenericCombatState:
        state = self._load()
        if not state.config.combat.enabled:
            raise GenericEngineError("Combat tracking is not enabled.")
        if state.combat.active:
            raise GenericEngineError("Combat already active.")

        for n in combatant_names:
            if n not in state.characters:
                raise GenericEngineError(f"Character '{n}' not found.")

        combatants = []
        init_stat = state.config.combat.initiative_stat
        init_dice = state.config.combat.initiative_dice

        for n in combatant_names:
            char = state.characters[n]
            roll_total, _ = roll_dice_expr(init_dice)
            if init_stat and init_stat in char.stats:
                initiative = roll_total + char.stats[init_stat]
            else:
                initiative = roll_total
            combatants.append(GenericCombatant(name=n, initiative=initiative))
            self._log(state, f"{n} rolls initiative: {initiative}", "combat")

        combatants.sort(key=lambda c: c.initiative, reverse=True)
        state.combat = GenericCombatState(active=True, round=1, combatants=combatants)

        order = ", ".join(c.name for c in combatants)
        self._log(state, f"Combat started! Turn order: {order}", "combat")
        self._save(state)
        return state.combat

    def next_turn(self) -> GenericCombatState:
        """Advance to the next combatant."""
        state = self._load()
        if not state.combat.active:
            raise GenericEngineError("No combat active.")
        combat = state.combat
        combat.current_index += 1
        if combat.current_index >= len(combat.combatants):
            combat.current_index = 0
            combat.round += 1
            self._log(state, f"--- Round {combat.round} ---", "combat")
        self._save(state)
        return state.combat

    def end_combat(self) -> None:
        state = self._load()
        if not state.combat.active:
            raise GenericEngineError("No combat active.")
        state.combat = GenericCombatState()
        self._log(state, "Combat ended.", "combat")
        self._save(state)

    # --- Inventory ---

    def add_inventory(self, name: str, item: str) -> list[str]:
        state = self._load()
        char = state.characters.get(name)
        if not char:
            raise GenericEngineError(f"Character '{name}' not found.")
        char.inventory.append(item)
        self._log(state, f"{name} gains item: {item}.")
        self._save(state)
        return char.inventory

    def remove_inventory(self, name: str, item: str) -> list[str]:
        state = self._load()
        char = state.characters.get(name)
        if not char:
            raise GenericEngineError(f"Character '{name}' not found.")
        if item not in char.inventory:
            raise GenericEngineError(f"{name} doesn't have '{item}'.")
        char.inventory.remove(item)
        self._log(state, f"{name} loses item: {item}.")
        self._save(state)
        return char.inventory

    # --- Scene and log ---

    def set_scene(self, description: str) -> str:
        state = self._load()
        state.scene = description
        self._log(state, f"Scene: {description}", "scene")
        self._save(state)
        return description

    def get_log(self, count: int = 20) -> list[LogEntry]:
        state = self._load()
        return state.log[-count:]

    # --- Notes ---

    def set_note(self, name: str, key: str, value: str) -> dict[str, str]:
        """Set freeform per-character metadata."""
        state = self._load()
        char = state.characters.get(name)
        if not char:
            raise GenericEngineError(f"Character '{name}' not found.")
        char.notes[key] = value
        self._log(state, f"{name} note '{key}' set.")
        self._save(state)
        return char.notes
