"""Mothership engine plugin — wraps dnd-party's GameEngine."""

from __future__ import annotations

import logging

from game.combat import CombatEngine
from game.engine import GameEngine
from game.models import CharacterClass, Controller
from server.engine.base import EngineAction, EngineResult, GameEnginePlugin


class MothershipPlugin(GameEnginePlugin):
    """Wraps dnd-party's GameEngine as a play-by-post plugin."""

    def __init__(self) -> None:
        self._engine = GameEngine(in_memory=True)
        self._engine.init_game("PBP Game")
        self._combat = CombatEngine(self._engine)

    def get_name(self) -> str:
        return "mothership"

    def create_character(self, name: str, **kwargs: object) -> dict:
        char_class_str = str(kwargs.get("char_class", "marine"))
        controller_str = str(kwargs.get("controller", "ai"))
        try:
            char_class = CharacterClass(char_class_str)
        except ValueError:
            char_class = CharacterClass.MARINE
        try:
            controller = Controller(controller_str)
        except ValueError:
            controller = Controller.AI

        char = self._engine.create_character(name, char_class, controller)
        return char.model_dump()

    def get_character(self, name: str) -> dict | None:
        try:
            char = self._engine.get_character(name)
            return char.model_dump()
        except Exception:
            return None

    def list_characters(self) -> list[dict]:
        state = self._engine.get_state()
        return [c.model_dump() for c in state.characters.values()]

    def process_action(self, action: EngineAction) -> EngineResult:
        try:
            match action.action_type:
                case "roll":
                    stat = action.params.get("stat", "combat")
                    skill = action.params.get("skill")
                    advantage = action.params.get("advantage", False)
                    disadvantage = action.params.get("disadvantage", False)
                    result = self._engine.roll_check(
                        action.character, stat,
                        skill=skill,
                        advantage=advantage,
                        disadvantage=disadvantage,
                    )
                    return EngineResult(
                        success=result.succeeded,
                        summary=(
                            f"{action.character} rolls {stat} "
                            f"(target {result.target}): "
                            f"{result.roll} -> {result.result.value}"
                        ),
                        details={
                            "roll": result.roll,
                            "target": result.target,
                            "result": result.result.value,
                            "doubles": result.doubles,
                            "all_rolls": result.all_rolls,
                        },
                    )
                case "attack":
                    target = action.params.get("target", "")
                    advantage = action.params.get("advantage", False)
                    disadvantage = action.params.get("disadvantage", False)
                    result = self._combat.combat_action(
                        action.character, "attack", target=target,
                        advantage=advantage, disadvantage=disadvantage,
                    )
                    return EngineResult(
                        success=result.get("check_result", "") in ("success", "critical_success"),
                        summary=f"{action.character} attacks {target}: {result.get('check_result', 'unknown')}",
                        details=result,
                    )
                case "damage":
                    target = action.params.get("target", action.character)
                    amount = int(action.params.get("amount", 0))
                    result = self._engine.apply_damage(target, amount)
                    return EngineResult(
                        success=True,
                        summary=f"{target} takes {result['damage_taken']} damage",
                        details=result,
                    )
                case "heal":
                    target = action.params.get("target", action.character)
                    amount = int(action.params.get("amount", 0))
                    healed = self._engine.heal(target, amount)
                    return EngineResult(
                        success=True,
                        summary=f"{target} heals {healed} HP",
                        details={"healed": healed},
                    )
                case "panic":
                    result = self._engine.panic_check(action.character)
                    return EngineResult(
                        success=not result["panicked"],
                        summary=(
                            f"{action.character} panic check: "
                            f"{'panicked' if result['panicked'] else 'kept it together'}"
                        ),
                        details=result,
                    )
                case "start_combat":
                    combatants = action.params.get("combatants", [])
                    combat_state = self._combat.start_combat(combatants)
                    return EngineResult(
                        success=True,
                        summary=f"Combat started with {len(combat_state.combatants)} combatants",
                        details=combat_state.model_dump(),
                    )
                case "end_combat":
                    self._combat.end_combat()
                    return EngineResult(
                        success=True,
                        summary="Combat ended",
                    )
                case _:
                    return EngineResult(
                        success=False,
                        summary=f"Unknown action: {action.action_type}",
                        state_changed=False,
                    )
        except Exception as e:
            logging.getLogger(__name__).exception(
                "Engine error processing action %s for %s",
                action.action_type, action.character,
            )
            return EngineResult(
                success=False,
                summary="Engine error: action could not be processed",
                state_changed=False,
            )

    def get_state(self) -> dict:
        state = self._engine.get_state()
        return state.model_dump()

    def get_available_actions(self, character: str) -> list[str]:
        state = self._engine.get_state()
        actions = ["roll", "heal", "panic"]
        if state.combat.active:
            actions.extend(["attack", "end_combat"])
        else:
            actions.append("start_combat")
        return actions

    def save_state(self) -> str:
        return self._engine.save_state_json()

    def load_state(self, state: str) -> None:
        self._engine.load_state_json(state)
