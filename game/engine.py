"""Core game engine: state transitions, rules, and persistence."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from game.dice import roll_2d10, roll_d20, stat_check, RollResult
from game.models import (
    Character,
    CharacterClass,
    CombatState,
    Controller,
    GameState,
    LogEntry,
)
from game.tables import (
    CLASS_HP,
    CLASS_SAVES,
    CLASS_STARTING_SKILLS,
    CLASS_STATS,
    PANIC_TABLE,
    SKILL_TIER_BONUS,
)

DEFAULT_STATE_DIR = Path("state")
DEFAULT_STATE_FILE = DEFAULT_STATE_DIR / "game.json"


class EngineError(Exception):
    pass


class GameEngine:
    """Manages game state with atomic JSON persistence or in-memory."""

    def __init__(
        self,
        state_path: Path | None = DEFAULT_STATE_FILE,
        in_memory: bool = False,
    ):
        self.in_memory = in_memory
        self.state_path = state_path
        self._state: GameState | None = None

    def _load(self) -> GameState:
        if self.in_memory:
            if self._state is None:
                raise EngineError("No game found. Call init_game() first.")
            return self._state
        if not self.state_path.exists():
            raise EngineError("No game found. Run 'game init' first.")
        return GameState.model_validate_json(self.state_path.read_text())

    def _save(self, state: GameState) -> None:
        if self.in_memory:
            self._state = state
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        data = state.model_dump_json(indent=2)
        # Atomic write: write to temp file then rename
        fd, tmp_path = tempfile.mkstemp(
            dir=self.state_path.parent, suffix=".tmp"
        )
        try:
            with open(fd, "w") as f:
                f.write(data)
            Path(tmp_path).rename(self.state_path)
        except BaseException:
            Path(tmp_path).unlink(missing_ok=True)
            raise

    def save_state_json(self) -> str:
        """Serialize current state to JSON string."""
        state = self._load()
        return state.model_dump_json()

    def load_state_json(self, data: str) -> None:
        """Restore state from JSON string."""
        state = GameState.model_validate_json(data)
        self._save(state)

    def _log(self, state: GameState, message: str, category: str = "action") -> None:
        state.log.append(LogEntry(message=message, category=category))

    # --- Game management ---

    def init_game(self, name: str = "Untitled Game") -> GameState:
        state = GameState(name=name)
        self._log(state, f"Game '{name}' initialized.", "system")
        self._save(state)
        return state

    def get_state(self) -> GameState:
        return self._load()

    # --- Character management ---

    def create_character(
        self,
        name: str,
        char_class: CharacterClass,
        controller: Controller = Controller.AI,
    ) -> Character:
        state = self._load()
        if name in state.characters:
            raise EngineError(f"Character '{name}' already exists.")

        # Generate base stats: 2d10+25 each, plus class modifiers
        class_mods = CLASS_STATS[char_class]
        base = lambda: roll_2d10() + 25  # noqa: E731
        stats_dict = {
            "strength": base() + class_mods.strength,
            "speed": base() + class_mods.speed,
            "intellect": base() + class_mods.intellect,
            "combat": base() + class_mods.combat,
        }

        from game.models import Saves, Stats

        char = Character(
            name=name,
            char_class=char_class,
            controller=controller,
            stats=Stats(**stats_dict),
            saves=CLASS_SAVES[char_class].model_copy(),
            hp=CLASS_HP[char_class],
            max_hp=CLASS_HP[char_class],
            skills=dict(CLASS_STARTING_SKILLS[char_class]),
        )
        state.characters[name] = char
        self._log(state, f"{name} ({char_class.value}) created.", "system")
        self._save(state)
        return char

    def get_character(self, name: str) -> Character:
        state = self._load()
        if name not in state.characters:
            raise EngineError(f"Character '{name}' not found.")
        return state.characters[name]

    # --- Stat checks ---

    def roll_check(
        self,
        name: str,
        stat: str,
        skill: str | None = None,
        advantage: bool = False,
        disadvantage: bool = False,
    ) -> RollResult:
        state = self._load()
        char = state.characters.get(name)
        if not char:
            raise EngineError(f"Character '{name}' not found.")

        # Get target value from stats or saves
        stat_lower = stat.lower()
        target = None
        for model in (char.stats, char.saves):
            if hasattr(model, stat_lower):
                target = getattr(model, stat_lower)
                break
        if target is None:
            raise EngineError(
                f"Unknown stat '{stat}'. Valid: strength, speed, intellect, "
                "combat, sanity, fear, body."
            )

        modifier = 0
        if skill and skill in char.skills:
            modifier = SKILL_TIER_BONUS[char.skills[skill]]

        result = stat_check(
            target, modifier, advantage=advantage, disadvantage=disadvantage
        )

        rolls_info = ""
        if len(result.all_rolls) > 1:
            rolls_info = f" [rolls: {result.all_rolls[0]}, {result.all_rolls[1]}]"

        self._log(
            state,
            f"{name} rolls {stat} (target {result.target}): "
            f"{result.roll} -> {result.result.value}"
            + (f" [skill: {skill}]" if skill else "")
            + (" [advantage]" if advantage and not disadvantage else "")
            + (" [disadvantage]" if disadvantage and not advantage else "")
            + rolls_info,
        )

        # Failed check adds stress
        if not result.succeeded:
            char.stress += 1
            self._log(state, f"{name} gains 1 stress (now {char.stress}).")

        self._save(state)
        return result

    # --- Health and damage ---

    def apply_damage(self, name: str, amount: int) -> dict:
        state = self._load()
        char = state.characters.get(name)
        if not char:
            raise EngineError(f"Character '{name}' not found.")

        result = {"raw_damage": amount, "absorbed": 0, "damage_taken": 0, "wound": False, "dead": False}

        # Armor absorbs damage
        if char.armor.ap > 0:
            if amount < char.armor.ap:
                result["absorbed"] = amount
                self._log(state, f"{name}'s {char.armor.name} absorbs {amount} damage.")
                self._save(state)
                return result
            else:
                result["absorbed"] = char.armor.ap
                amount -= char.armor.ap
                self._log(
                    state,
                    f"{name}'s {char.armor.name} (AP {char.armor.ap}) destroyed! "
                    f"{amount} damage gets through.",
                )
                char.armor.ap = 0
                char.armor.name = "none (destroyed)"

        result["damage_taken"] = amount
        char.hp -= amount

        if char.hp <= 0:
            char.hp = char.max_hp
            char.wounds += 1
            result["wound"] = True
            self._log(
                state,
                f"{name} takes {amount} damage, HP drops to 0! "
                f"Gains wound ({char.wounds}/{char.max_wounds}), HP reset to {char.max_hp}.",
            )
            if char.wounds >= char.max_wounds:
                char.alive = False
                result["dead"] = True
                self._log(state, f"{name} has died from wounds!", "system")
        else:
            self._log(state, f"{name} takes {amount} damage (HP: {char.hp}/{char.max_hp}).")

        self._save(state)
        return result

    def heal(self, name: str, amount: int) -> int:
        state = self._load()
        char = state.characters.get(name)
        if not char:
            raise EngineError(f"Character '{name}' not found.")

        old_hp = char.hp
        char.hp = min(char.hp + amount, char.max_hp)
        healed = char.hp - old_hp
        self._log(state, f"{name} heals {healed} HP (HP: {char.hp}/{char.max_hp}).")
        self._save(state)
        return healed

    # --- Stress and panic ---

    def add_stress(self, name: str, amount: int) -> int:
        state = self._load()
        char = state.characters.get(name)
        if not char:
            raise EngineError(f"Character '{name}' not found.")

        char.stress += amount
        if char.stress < 0:
            char.stress = 0
        self._log(
            state,
            f"{name} {'gains' if amount > 0 else 'loses'} "
            f"{abs(amount)} stress (now {char.stress}).",
        )
        self._save(state)
        return char.stress

    def panic_check(self, name: str) -> dict:
        state = self._load()
        char = state.characters.get(name)
        if not char:
            raise EngineError(f"Character '{name}' not found.")

        roll = roll_d20()
        panicked = roll <= char.stress
        result = {"roll": roll, "stress": char.stress, "panicked": panicked, "effect": None}

        if panicked:
            # Clamp to table range
            table_roll = max(1, min(roll, 20))
            effect = PANIC_TABLE[table_roll]
            result["effect"] = effect
            from game.models import Condition
            if Condition.PANICKED not in char.conditions:
                char.conditions.append(Condition.PANICKED)
            self._log(
                state,
                f"{name} panics! (rolled {roll} vs stress {char.stress}) — {effect}",
                "action",
            )
        else:
            self._log(
                state,
                f"{name} keeps it together (rolled {roll} vs stress {char.stress}).",
            )

        self._save(state)
        return result

    # --- Inventory ---

    def add_inventory(self, name: str, item: str) -> list[str]:
        state = self._load()
        char = state.characters.get(name)
        if not char:
            raise EngineError(f"Character '{name}' not found.")

        char.inventory.append(item)
        self._log(state, f"{name} gains item: {item}.")
        self._save(state)
        return char.inventory

    def remove_inventory(self, name: str, item: str) -> list[str]:
        state = self._load()
        char = state.characters.get(name)
        if not char:
            raise EngineError(f"Character '{name}' not found.")

        if item not in char.inventory:
            raise EngineError(f"{name} doesn't have '{item}'.")
        char.inventory.remove(item)
        self._log(state, f"{name} loses item: {item}.")
        self._save(state)
        return char.inventory

    # --- Scene ---

    def set_scene(self, description: str) -> str:
        state = self._load()
        state.scene = description
        self._log(state, f"Scene: {description}", "scene")
        self._save(state)
        return description

    # --- Log ---

    def get_log(self, count: int = 20) -> list[LogEntry]:
        state = self._load()
        return state.log[-count:]

    # --- Campaign ---

    def set_campaign(self, campaign_name: str) -> None:
        state = self._load()
        state.active_campaign = campaign_name
        self._log(state, f"Active campaign set to '{campaign_name}'.", "system")
        self._save(state)

    def get_active_campaign(self) -> str | None:
        state = self._load()
        return state.active_campaign
