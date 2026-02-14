"""Agent-backed test players for integration testing (opt-in)."""

from __future__ import annotations

from httpx import AsyncClient

from tests.harness.base import TestPlayer


class AgentBackedPlayer(TestPlayer):
    """Player whose actions come from an actual LLM agent.

    This is opt-in and requires API keys. Used for integration tests
    with real agent interactions.
    """

    def __init__(self, name: str, client: AsyncClient, system_prompt: str):
        super().__init__(name, client)
        self.system_prompt = system_prompt
        self._last_message_id: str | None = None

    async def decide_action(self, game_id: str) -> str:
        """Poll for new messages and decide on an action.

        This is a placeholder — actual LLM integration would go here.
        For now, returns a fixed action for testing the harness structure.
        """
        messages = await self.poll_messages(game_id, after=self._last_message_id)
        if messages:
            self._last_message_id = messages[-1]["id"]

        # Placeholder: return a simple action based on context
        return "I look around cautiously."

    async def take_turn(self, game_id: str) -> dict:
        """Decide and submit an action."""
        action_text = await self.decide_action(game_id)
        return await self.declare_action(game_id, action_text)
