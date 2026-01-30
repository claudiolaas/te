"""Database module for trading system.

Provides async SQLite database access via aiosqlite.
"""

from .database import DatabaseManager

__all__ = ["DatabaseManager"]
