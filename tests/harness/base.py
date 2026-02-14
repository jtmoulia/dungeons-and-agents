"""Test agent base classes for the play-by-post test harness."""

from __future__ import annotations

from httpx import AsyncClient


class TestAgent:
    """Simulated agent for testing."""

    def __init__(self, name: str, client: AsyncClient):
        self.name = name
        self.client = client
        self.agent_id: str | None = None
        self.api_key: str | None = None
        self._session_tokens: dict[str, str] = {}  # game_id -> session_token

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}"}

    def game_headers(self, game_id: str) -> dict:
        """Auth headers including session token for a specific game."""
        h = dict(self.headers)
        token = self._session_tokens.get(game_id)
        if token:
            h["X-Session-Token"] = token
        return h

    async def register(self) -> None:
        resp = await self.client.post("/agents/register", json={"name": self.name})
        resp.raise_for_status()
        data = resp.json()
        self.agent_id = data["id"]
        self.api_key = data["api_key"]

    async def create_game(self, config: dict) -> str:
        resp = await self.client.post("/lobby", json=config, headers=self.headers)
        resp.raise_for_status()
        data = resp.json()
        game_id = data["id"]
        if "session_token" in data:
            self._session_tokens[game_id] = data["session_token"]
        return game_id

    async def join_game(self, game_id: str, character_name: str | None = None) -> None:
        resp = await self.client.post(
            f"/games/{game_id}/join",
            json={"character_name": character_name},
            headers=self.headers,
        )
        resp.raise_for_status()
        data = resp.json()
        if "session_token" in data:
            self._session_tokens[game_id] = data["session_token"]

    async def post_message(self, game_id: str, content: str, msg_type: str = "action") -> dict:
        resp = await self.client.post(
            f"/games/{game_id}/messages",
            json={"content": content, "type": msg_type},
            headers=self.game_headers(game_id),
        )
        resp.raise_for_status()
        return resp.json()

    async def poll_messages(self, game_id: str, after: str | None = None) -> list[dict]:
        url = f"/games/{game_id}/messages"
        if after:
            url += f"?after={after}"
        resp = await self.client.get(url)
        resp.raise_for_status()
        return resp.json()

    async def engine_action(self, game_id: str, action: dict) -> dict:
        resp = await self.client.post(
            f"/games/{game_id}/engine/action",
            json=action,
            headers=self.game_headers(game_id),
        )
        resp.raise_for_status()
        return resp.json()


class TestDM(TestAgent):
    """DM-specific test methods."""

    async def start_game(self, game_id: str) -> None:
        resp = await self.client.post(
            f"/games/{game_id}/start", headers=self.headers
        )
        resp.raise_for_status()

    async def end_game(self, game_id: str) -> None:
        resp = await self.client.post(
            f"/games/{game_id}/end", headers=self.headers
        )
        resp.raise_for_status()

    async def narrate(self, game_id: str, text: str) -> dict:
        return await self.post_message(game_id, text, "narrative")

    async def kick_player(self, game_id: str, agent_id: str) -> None:
        resp = await self.client.post(
            f"/games/{game_id}/admin/kick",
            json={"agent_id": agent_id},
            headers=self.headers,
        )
        resp.raise_for_status()

    async def resolve_with_engine(self, game_id: str, action: dict) -> dict:
        return await self.engine_action(game_id, action)


class TestPlayer(TestAgent):
    """Player-specific test methods."""

    async def declare_action(self, game_id: str, text: str) -> dict:
        return await self.post_message(game_id, text, "action")
