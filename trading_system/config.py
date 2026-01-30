"""Configuration management using pydantic-settings."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Binance API
    binance_api_key: str = Field(min_length=1, description="Binance API key")
    binance_api_secret: str = Field(min_length=1, description="Binance API secret")

    # Database
    db_path: Path = Field(default=Path("./data/trading.db"), description="SQLite database file path")

    # Backfill
    backfill_minutes: int = Field(default=5, ge=1, le=1000, description="Minutes of historical data to fetch")
    gap_fill_enabled: bool = Field(default=True, description="Enable automatic gap filling on startup")
    gap_fill_threshold_minutes: int = Field(default=1, ge=0, description="Minimum gap in minutes to trigger fill")
    max_gap_fill_minutes: int = Field(default=1000, ge=1, description="Maximum gap in minutes to fill in one operation")

    # Heartbeat
    heartbeat_interval: int = Field(default=60, ge=10, description="Heartbeat interval in seconds")
    heartbeat_buffer_delay: int = Field(default=5, ge=0, le=30, description="Delay after minute mark before fetching")

    # Logging
    log_level: str = Field(default="INFO", pattern=r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    log_dir: Path = Field(default=Path("./logs"), description="Directory for log files")

    @property
    def db_uri(self) -> str:
        """Return SQLite URI for database connection."""
        return f"sqlite:///{self.db_path}"

    @property
    def effective_heartbeat_interval(self) -> int:
        """Return total interval including buffer delay."""
        return self.heartbeat_interval + self.heartbeat_buffer_delay
