"""Tests for configuration management."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from trading_system.config import Settings


class TestConfigLoading:
    """Test suite for configuration loading from environment variables."""

    def test_config_loads_from_env_vars(self, monkeypatch):
        """Verify config loads all values from environment variables."""
        monkeypatch.setenv("BINANCE_API_KEY", "test_key")
        monkeypatch.setenv("BINANCE_API_SECRET", "test_secret")
        monkeypatch.setenv("DB_PATH", "/custom/path/db.sqlite")
        monkeypatch.setenv("BACKFILL_MINUTES", "10")
        monkeypatch.setenv("HEARTBEAT_INTERVAL", "120")
        monkeypatch.setenv("HEARTBEAT_BUFFER_DELAY", "10")
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("LOG_DIR", "/custom/logs")

        settings = Settings()

        assert settings.binance_api_key == "test_key"
        assert settings.binance_api_secret == "test_secret"
        assert settings.db_path == Path("/custom/path/db.sqlite")
        assert settings.backfill_minutes == 10
        assert settings.heartbeat_interval == 120
        assert settings.heartbeat_buffer_delay == 10
        assert settings.log_level == "DEBUG"
        assert settings.log_dir == Path("/custom/logs")

    def test_default_values_work(self, monkeypatch):
        """Verify default values are used when env vars are not set."""
        monkeypatch.setenv("BINANCE_API_KEY", "test_key")
        monkeypatch.setenv("BINANCE_SECRET_KEY", "test_secret")

        settings = Settings()

        assert settings.db_path == Path("./data/trading.db")
        assert settings.backfill_minutes == 5
        assert settings.heartbeat_interval == 60
        assert settings.heartbeat_buffer_delay == 5
        assert settings.log_level == "INFO"
        assert settings.log_dir == Path("./logs")

    def test_validation_error_for_missing_required_fields(self, monkeypatch):
        """Verify validation errors are raised for missing required fields."""
        # Note: .env file may have values, so we need to ensure both are missing
        # by setting them to empty strings which should fail validation
        monkeypatch.setenv("BINANCE_API_KEY", "")
        monkeypatch.setenv("BINANCE_SECRET_KEY", "")

        with pytest.raises(ValidationError) as exc_info:
            Settings()

        errors = exc_info.value.errors()
        error_fields = {e["loc"][0] for e in errors}

        # Check that at least one required field is flagged
        assert "binance_api_key" in error_fields or "BINANCE_SECRET_KEY" in error_fields

    def test_db_uri_property(self, monkeypatch):
        """Verify db_uri property returns correct SQLite URI."""
        monkeypatch.setenv("BINANCE_API_KEY", "test_key")
        monkeypatch.setenv("BINANCE_SECRET_KEY", "test_secret")
        monkeypatch.setenv("DB_PATH", "/absolute/path/test.db")

        settings = Settings()

        assert settings.db_uri == "sqlite:////absolute/path/test.db"

    def test_effective_heartbeat_interval_property(self, monkeypatch):
        """Verify effective_heartbeat_interval includes buffer delay."""
        monkeypatch.setenv("BINANCE_API_KEY", "test_key")
        monkeypatch.setenv("BINANCE_SECRET_KEY", "test_secret")
        monkeypatch.setenv("HEARTBEAT_INTERVAL", "60")
        monkeypatch.setenv("HEARTBEAT_BUFFER_DELAY", "5")

        settings = Settings()

        assert settings.effective_heartbeat_interval == 65

    def test_log_level_validation(self, monkeypatch):
        """Verify log_level validates against allowed values."""
        monkeypatch.setenv("BINANCE_API_KEY", "test_key")
        monkeypatch.setenv("BINANCE_SECRET_KEY", "test_secret")
        monkeypatch.setenv("LOG_LEVEL", "INVALID")

        with pytest.raises(ValidationError):
            Settings()

    def test_backfill_minutes_range_validation(self, monkeypatch):
        """Verify backfill_minutes validates range constraints."""
        monkeypatch.setenv("BINANCE_API_KEY", "test_key")
        monkeypatch.setenv("BINANCE_SECRET_KEY", "test_secret")
        monkeypatch.setenv("BACKFILL_MINUTES", "0")

        with pytest.raises(ValidationError):
            Settings()

    def test_buffer_delay_range_validation(self, monkeypatch):
        """Verify heartbeat_buffer_delay validates range constraints."""
        monkeypatch.setenv("BINANCE_API_KEY", "test_key")
        monkeypatch.setenv("BINANCE_SECRET_KEY", "test_secret")
        monkeypatch.setenv("HEARTBEAT_BUFFER_DELAY", "31")

        with pytest.raises(ValidationError):
            Settings()
