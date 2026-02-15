"""LLM-backed game agents for autonomous play-by-post games.

Provides GameAgent base class and AIPlayer/AIDM subclasses that use
the Anthropic Claude API to generate in-character actions and narration.
Each agent communicates with the server via the HTTP API.
"""

from __future__ import annotations

import httpx
import anthropic


MODEL = "claude-sonnet-4-5-20250929"
MAX_TOKENS = 1024


class GameAgent:
    """Base class for LLM-backed game agents."""

    def __init__(
        self,
        *,
        name: str,
        system_prompt: str,
        llm: anthropic.Anthropic,
        http: httpx.Client,
        api_key: str,
        session_token: str,
        game_id: str,
    ):
        self.name = name
        self.system_prompt = system_prompt
        self.llm = llm
        self.http = http
        self.api_key = api_key
        self.session_token = session_token
        self.game_id = game_id

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "X-Session-Token": self.session_token,
        }

    def get_messages(self) -> list[dict]:
        """Fetch the full message history for this game."""
        resp = self.http.get(
            f"/games/{self.game_id}/messages?limit=500",
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    def format_transcript(self, messages: list[dict]) -> str:
        """Convert game messages into a readable transcript for the LLM."""
        lines: list[str] = []
        for msg in messages:
            sender = msg.get("agent_name", "SYSTEM")
            whisper = " [whisper]" if msg.get("to_agents") else ""
            mtype = msg["type"].upper()
            content = msg["content"]

            if msg["type"] == "narrative":
                lines.append(f"[NARRATIVE]{whisper} WARDEN:\n{content}")
            elif msg["type"] == "action":
                lines.append(f"[ACTION] {sender}:\n{content}")
            elif msg["type"] == "ooc":
                lines.append(f"[OOC] {sender}: {content}")
            elif msg["type"] == "system":
                lines.append(f"[SYSTEM] {content}")
            else:
                lines.append(f"[{mtype}] {sender}: {content}")
        return "\n\n".join(lines)

    def generate(self, instruction: str) -> str:
        """Call the LLM with system prompt + game transcript + instruction."""
        messages_history = self.get_messages()
        transcript = self.format_transcript(messages_history)

        user_content = ""
        if transcript:
            user_content += f"## Game transcript so far\n\n{transcript}\n\n---\n\n"
        user_content += f"## Your instruction\n\n{instruction}"

        response = self.llm.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=self.system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
        return response.content[0].text

    def post_message(self, content: str, msg_type: str, to_agents: list[str] | None = None) -> dict:
        """Post a message to the game."""
        body: dict = {"content": content, "type": msg_type}
        if to_agents:
            body["to_agents"] = to_agents
        resp = self.http.post(
            f"/games/{self.game_id}/messages",
            json=body,
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()


class AIPlayer(GameAgent):
    """Player agent that generates in-character action declarations."""

    def take_turn(self, instruction: str = "It's your turn. Declare your action.") -> dict:
        """Generate and post an action message."""
        content = self.generate(instruction)
        return self.post_message(content, "action")


class AIDM(GameAgent):
    """DM agent that generates narration and manages game flow."""

    def narrate(self, instruction: str) -> dict:
        """Generate and post a narrative message."""
        content = self.generate(instruction)
        return self.post_message(content, "narrative")

    def whisper(self, to_agent_ids: list[str], instruction: str) -> dict:
        """Generate and post a whispered narrative message."""
        content = self.generate(instruction)
        return self.post_message(content, "narrative", to_agents=to_agent_ids)
