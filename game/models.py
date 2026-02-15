"""Shared models used across game engines."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class LogEntry(BaseModel):
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    message: str
    category: Literal["action", "combat", "scene", "system"] = "action"
