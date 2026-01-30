"""Tests for logging infrastructure."""

import logging
import tempfile
from pathlib import Path

import pytest

import trading_system.logger as logger_module
from trading_system.config import Settings
from trading_system.logger import LogManager, get_logger, setup_logging


class TestLogManager:
    """Test suite for logging infrastructure."""

    @pytest.fixture(autouse=True)
    def reset_log_manager(self):
        """Reset log manager state before each test."""
        # First, flush and close handlers from any cached loggers
        # Use a copy of keys since we may modify the dict
        for name in list(logging.Logger.manager.loggerDict.keys()):
            if name.startswith("trading_system"):
                # Get logger object directly from the manager to avoid recreating
                logger = logging.Logger.manager.loggerDict[name]
                if isinstance(logger, logging.Logger):
                    for handler in logger.handlers[:]:
                        handler.flush()
                        handler.close()
                        logger.removeHandler(handler)
                # Now remove from the manager's dict
                del logging.Logger.manager.loggerDict[name]

        # Reset the LogManager singleton
        LogManager._instance = None
        LogManager._initialized = False

        # Reset the global log_manager reference
        logger_module.log_manager = LogManager()

        yield

    @pytest.fixture
    def temp_log_dir(self):
        """Create a temporary directory for log files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def settings(self, temp_log_dir):
        """Create settings with temporary log directory."""
        return Settings(
            _env_file=None,  # Disable .env loading
            binance_api_key="test_key",
            binance_api_secret="test_secret",
            log_dir=temp_log_dir,
            log_level="DEBUG",
        )

    def test_logger_creates_separate_files_per_component(self, settings, temp_log_dir):
        """Verify each component gets its own log file."""
        setup_logging(settings)

        # Get loggers for different components
        heartbeat_logger = logger_module.log_manager.get_heartbeat_logger()
        api_logger = logger_module.log_manager.get_api_logger()
        strategy_logger = logger_module.log_manager.get_strategy_logger("test_strategy")

        # Log messages
        heartbeat_logger.info("Heartbeat message")
        api_logger.info("API message")
        strategy_logger.info("Strategy message")

        # Verify separate log files exist
        assert (temp_log_dir / "heartbeat.log").exists()
        assert (temp_log_dir / "api.log").exists()
        assert (temp_log_dir / "strategy.test_strategy.log").exists()

    def test_log_format_includes_timestamp_level_component(self, settings, temp_log_dir):
        """Verify log format includes required fields."""
        setup_logging(settings)
        logger = logger_module.log_manager.get_heartbeat_logger()
        logger.info("Test message")

        # Flush and close handlers to ensure file is written
        for handler in logger.handlers:
            handler.flush()
            handler.close()

        # Read log file
        log_content = (temp_log_dir / "heartbeat.log").read_text()

        # Verify format: timestamp | level | component | message
        assert " | INFO     | " in log_content
        assert "trading_system.heartbeat" in log_content or "heartbeat" in log_content
        assert "Test message" in log_content

    def test_log_level_configurable_via_settings(self, temp_log_dir):
        """Verify log level is configurable."""
        settings = Settings(
            _env_file=None,
            binance_api_key="test_key",
            binance_api_secret="test_secret",
            log_dir=temp_log_dir,
            log_level="WARNING",
        )
        setup_logging(settings)

        logger = logger_module.log_manager.get_heartbeat_logger()

        # DEBUG and INFO should not be logged
        logger.debug("Debug message")
        logger.info("Info message")

        # WARNING should be logged
        logger.warning("Warning message")

        # Flush and close handlers to ensure file is written
        for handler in logger.handlers:
            handler.flush()
            handler.close()

        log_content = (temp_log_dir / "heartbeat.log").read_text()

        assert "Debug message" not in log_content
        assert "Info message" not in log_content
        assert "Warning message" in log_content

    def test_same_logger_name_returns_same_instance(self, settings, temp_log_dir):
        """Verify get_logger returns same instance for same name."""
        setup_logging(settings)

        logger1 = logger_module.log_manager.get_logger("test_component")
        logger2 = logger_module.log_manager.get_logger("test_component")

        assert logger1 is logger2

    def test_log_manager_is_singleton(self, settings, temp_log_dir):
        """Verify LogManager is a singleton."""
        setup_logging(settings)

        manager1 = LogManager()
        manager2 = LogManager()

        assert manager1 is manager2

    def test_strategy_logger_naming(self, settings, temp_log_dir):
        """Verify strategy logger creates correctly named file."""
        setup_logging(settings)

        logger = logger_module.log_manager.get_strategy_logger("my_strategy")
        logger.info("Strategy log")

        assert (temp_log_dir / "strategy.my_strategy.log").exists()

    def test_get_logger_convenience_function(self, settings, temp_log_dir):
        """Verify get_logger convenience function works."""
        setup_logging(settings)

        logger = get_logger("custom_component")
        logger.info("Custom message")

        assert (temp_log_dir / "custom_component.log").exists()
        assert "Custom message" in (temp_log_dir / "custom_component.log").read_text()

    def test_log_directory_created_if_not_exists(self, temp_log_dir):
        """Verify log directory is created if it doesn't exist."""
        new_log_dir = temp_log_dir / "nested" / "logs"

        settings = Settings(
            _env_file=None,
            binance_api_key="test_key",
            binance_api_secret="test_secret",
            log_dir=new_log_dir,
            log_level="INFO",
        )

        setup_logging(settings)
        logger = logger_module.log_manager.get_logger("test")
        logger.info("Test")

        assert new_log_dir.exists()
