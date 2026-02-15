"""Server configuration."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "DNA_"}

    db_path: str = "pbp.db"
    campaign_dir: str = "campaigns"
    web_dir: str = "web"
    log_dir: str = "logs"
    poll_interval_seconds: int = 3
    default_max_players: int = 4
    host: str = "0.0.0.0"
    port: int = 8000
    allowed_origins: list[str] = ["http://localhost:8000", "http://127.0.0.1:8000"]
    moderation_enabled: bool = True
    moderation_blocked_words: list[str] = []


settings = Settings()
