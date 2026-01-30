"""Logging infrastructure with per-component log files."""

import logging
import sys
from pathlib import Path
from typing import Self

from trading_system.config import Settings


class LogManager:
    """Manages loggers for different components of the system."""

    _instance: Self | None = None
    _initialized: bool = False

    def __new__(cls) -> Self:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if LogManager._initialized:
            return
        self._loggers: dict[str, logging.Logger] = {}
        self._log_dir: Path = Path("./logs")
        self._log_level: int = logging.INFO
        self._formatter: logging.Formatter | None = None
        LogManager._initialized = True

    def initialize(self, settings: Settings) -> None:
        """Initialize the logging system with settings."""
        self._log_dir = settings.log_dir
        self._log_level = getattr(logging, settings.log_level.upper())
        self._formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # Ensure log directory exists
        self._log_dir.mkdir(parents=True, exist_ok=True)

        # Setup root console handler for early logging (only if not already configured)
        root_logger = logging.getLogger("trading_system")
        if not root_logger.handlers:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(self._formatter)
            root_logger.setLevel(self._log_level)
            root_logger.addHandler(console_handler)

    def get_logger(self, name: str) -> logging.Logger:
        """Get or create a logger for a specific component.

        Each component gets its own log file in addition to console output.
        Auto-initializes with defaults if not already initialized.
        """
        if name in self._loggers:
            return self._loggers[name]

        # Auto-initialize with defaults if not done yet
        if self._formatter is None:
            self._log_dir.mkdir(parents=True, exist_ok=True)
            self._formatter = logging.Formatter(
                fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )

        logger = logging.getLogger(f"trading_system.{name}")
        logger.setLevel(self._log_level)

        # Prevent propagation to avoid duplicate logs
        logger.propagate = False

        # Ensure log directory exists before creating file handler
        self._log_dir.mkdir(parents=True, exist_ok=True)

        # Add file handler for this component
        log_file = self._log_dir / f"{name}.log"
        file_handler = logging.FileHandler(log_file, mode="a")
        file_handler.setFormatter(self._formatter)
        file_handler.setLevel(self._log_level)
        logger.addHandler(file_handler)

        # Add console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(self._formatter)
        console_handler.setLevel(self._log_level)
        logger.addHandler(console_handler)

        self._loggers[name] = logger
        return logger

    def get_heartbeat_logger(self) -> logging.Logger:
        """Get logger for the heartbeat component."""
        return self.get_logger("heartbeat")

    def get_strategy_logger(self, strategy_name: str) -> logging.Logger:
        """Get logger for a specific strategy."""
        return self.get_logger(f"strategy.{strategy_name}")

    def get_binance_logger(self) -> logging.Logger:
        """Get logger for Binance API client."""
        return self.get_logger("binance")

    def get_api_logger(self) -> logging.Logger:
        """Get logger for REST API."""
        return self.get_logger("api")


# Global instance
log_manager = LogManager()


def setup_logging(settings: Settings) -> None:
    """Initialize logging with settings."""
    log_manager.initialize(settings)


def get_logger(name: str) -> logging.Logger:
    """Get a logger for a component."""
    return log_manager.get_logger(name)
