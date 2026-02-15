"""Integration test runner for play-by-post scenarios."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tests.harness.scenarios import (
    scenario_basic_game,
    scenario_freestyle_game,
    scenario_kick_player,
    scenario_mid_session_join,
    scenario_with_rolls,
)


@pytest_asyncio.fixture
async def harness_client():
    """Create a fresh client for harness scenarios."""
    from server.config import settings

    settings.db_path = ":memory:"

    from server.app import app
    from server.db import close_db, init_db

    await init_db(":memory:")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    await close_db()


@pytest.mark.asyncio
async def test_scenario_basic_game(harness_client: AsyncClient):
    await scenario_basic_game(harness_client)


@pytest.mark.asyncio
async def test_scenario_kick_player(harness_client: AsyncClient):
    await scenario_kick_player(harness_client)


@pytest.mark.asyncio
async def test_scenario_mid_session_join(harness_client: AsyncClient):
    await scenario_mid_session_join(harness_client)


@pytest.mark.asyncio
async def test_scenario_freestyle_game(harness_client: AsyncClient):
    await scenario_freestyle_game(harness_client)


@pytest.mark.asyncio
async def test_scenario_with_rolls(harness_client: AsyncClient):
    await scenario_with_rolls(harness_client)
