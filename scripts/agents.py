"""LLM-backed game agents for autonomous play-by-post games.

Provides GameAgent base class and AIPlayer/AIDM subclasses that use
the Anthropic Claude API to generate in-character actions and narration.
Each agent communicates with the server via the HTTP API.

Messages are cached locally — each agent only fetches new messages since
the last poll, using the ?after= parameter for efficient incremental reads.
"""

from __future__ import annotations

import httpx
import anthropic


MODEL = "claude-sonnet-4-5-20250929"
DM_MAX_TOKENS = 512
PLAYER_MAX_TOKENS = 200


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
        self._message_cache: list[dict] = []
        self._last_msg_id: str | None = None

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "X-Session-Token": self.session_token,
        }

    def sync_messages(self) -> list[dict]:
        """Fetch only new messages since last sync, append to cache."""
        params: dict = {"limit": 500}
        if self._last_msg_id:
            params["after"] = self._last_msg_id
        resp = self.http.get(
            f"/games/{self.game_id}/messages",
            params=params,
            headers=self._headers(),
        )
        resp.raise_for_status()
        new_msgs = resp.json()
        if new_msgs:
            self._message_cache.extend(new_msgs)
            self._last_msg_id = new_msgs[-1]["id"]
        return self._message_cache

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

    def generate(self, instruction: str, max_tokens: int = DM_MAX_TOKENS) -> str:
        """Call the LLM with system prompt + cached transcript + instruction."""
        all_messages = self.sync_messages()
        transcript = self.format_transcript(all_messages)

        user_content = ""
        if transcript:
            user_content += f"## Game transcript so far\n\n{transcript}\n\n---\n\n"
        user_content += f"## Your instruction\n\n{instruction}"

        response = self.llm.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            system=self.system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
        return response.content[0].text

    def post_message(self, content: str, msg_type: str, to_agents: list[str] | None = None) -> dict:
        """Post a message to the game and add it to the local cache."""
        body: dict = {"content": content, "type": msg_type}
        if to_agents:
            body["to_agents"] = to_agents
        resp = self.http.post(
            f"/games/{self.game_id}/messages",
            json=body,
            headers=self._headers(),
        )
        resp.raise_for_status()
        posted = resp.json()
        # Add to cache so we don't re-fetch our own message
        self._message_cache.append(posted)
        self._last_msg_id = posted["id"]
        return posted


class AIPlayer(GameAgent):
    """Player agent that generates in-character action declarations."""

    def take_turn(self, instruction: str = "It's your turn. Declare your action.") -> dict:
        """Generate and post an action message."""
        content = self.generate(instruction, max_tokens=PLAYER_MAX_TOKENS)
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
