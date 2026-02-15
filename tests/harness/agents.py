"""Agent-backed test players for integration testing (opt-in)."""

from __future__ import annotations

from httpx import AsyncClient

from tests.harness.base import TestPlayer


class AgentBackedPlayer(TestPlayer):
    """Player whose actions come from an actual LLM agent.

    This is opt-in and requires API keys. Used for integration tests
    with real agent interactions.

    If ``llm_client`` is provided (an ``anthropic.Anthropic`` instance),
    ``decide_action()`` calls the LLM with the game transcript and system
    prompt to generate a response. Otherwise it returns a fixed stub for
    testing the harness structure without LLM access.
    """

    def __init__(
        self,
        name: str,
        client: AsyncClient,
        system_prompt: str,
        llm_client: object | None = None,
        model: str = "claude-sonnet-4-5-20250929",
    ):
        super().__init__(name, client)
        self.system_prompt = system_prompt
        self.llm_client = llm_client
        self.model = model
        self._last_message_id: str | None = None

    async def decide_action(self, game_id: str) -> str:
        """Poll for new messages and decide on an action.

        If an LLM client was provided, formats the transcript and calls
        the LLM. Otherwise returns a fixed action for testing.
        """
        messages = await self.poll_messages(game_id, after=self._last_message_id)
        if messages:
            self._last_message_id = messages[-1]["id"]

        if self.llm_client is None:
            return "I look around cautiously."

        # Format messages as a simple transcript for the LLM
        transcript_lines = []
        for m in messages:
            author = m.get("character_name") or m.get("agent_name") or "System"
            transcript_lines.append(f"[{m['type'].upper()}] {author}: {m['content']}")
        transcript = "\n\n".join(transcript_lines)

        user_content = ""
        if transcript:
            user_content += f"## Recent messages\n\n{transcript}\n\n---\n\n"
        user_content += "Respond in character with a short action (1-4 sentences)."

        response = self.llm_client.messages.create(
            model=self.model,
            max_tokens=256,
            system=self.system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
        return response.content[0].text

    async def take_turn(self, game_id: str) -> dict:
        """Decide and submit an action."""
        action_text = await self.decide_action(game_id)
        return await self.declare_action(game_id, action_text)
