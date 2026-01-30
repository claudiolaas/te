"""Database connection manager using aiosqlite."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages async SQLite database connections and schema.
    
    This class provides:
    - Async connection management with aiosqlite
    - Automatic schema initialization
    - Connection pooling via context managers
    - Safe concurrent access handling
    
    Usage:
        db = DatabaseManager(db_path="data/trading.db")
        await db.initialize()
        
        async with db.connection() as conn:
            cursor = await conn.execute("SELECT * FROM symbols")
            rows = await cursor.fetchall()
        
        await db.close()
    """

    def __init__(self, db_path: Path | str) -> None:
        """Initialize database manager.
        
        Args:
            db_path: Path to SQLite database file
        """
        self._db_path = Path(db_path)
        self._connection: aiosqlite.Connection | None = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize database connection and schema.
        
        Creates the database file and parent directories if they don't exist.
        Executes schema.sql to set up tables and indexes.
        """
        if self._initialized:
            return

        # Ensure parent directory exists
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        # Create connection
        self._connection = await aiosqlite.connect(self._db_path)
        self._connection.row_factory = aiosqlite.Row

        # Enable foreign keys
        await self._connection.execute("PRAGMA foreign_keys = ON")

        # Initialize schema
        await self._init_schema()

        self._initialized = True
        logger.info(f"Database initialized: {self._db_path}")

    async def _init_schema(self) -> None:
        """Execute schema.sql to create tables and indexes."""
        schema_path = Path(__file__).parent / "schema.sql"

        if not schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_path}")

        schema_sql = schema_path.read_text()

        # Execute schema script
        await self._connection.executescript(schema_sql)
        await self._connection.commit()

        logger.debug("Database schema initialized")

    @asynccontextmanager
    async def connection(self):
        """Get a database connection context manager.
        
        Yields:
            aiosqlite.Connection: Database connection
            
        Raises:
            RuntimeError: If database not initialized
        """
        if not self._initialized or self._connection is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")

        try:
            yield self._connection
        except Exception:
            # Rollback on error
            await self._connection.rollback()
            raise

    async def execute(
        self,
        sql: str,
        parameters: tuple[Any, ...] | dict[str, Any] = ()
    ) -> aiosqlite.Cursor:
        """Execute a SQL query.
        
        Args:
            sql: SQL statement
            parameters: Query parameters (tuple or dict)
            
        Returns:
            aiosqlite.Cursor: Cursor object
        """
        async with self.connection() as conn:
            cursor = await conn.execute(sql, parameters)
            await conn.commit()
            return cursor

    async def fetch_one(
        self,
        sql: str,
        parameters: tuple[Any, ...] | dict[str, Any] = ()
    ) -> aiosqlite.Row | None:
        """Fetch a single row.
        
        Args:
            sql: SQL SELECT statement
            parameters: Query parameters
            
        Returns:
            Single row or None if no results
        """
        async with self.connection() as conn:
            cursor = await conn.execute(sql, parameters)
            return await cursor.fetchone()

    async def fetch_all(
        self,
        sql: str,
        parameters: tuple[Any, ...] | dict[str, Any] = ()
    ) -> list[aiosqlite.Row]:
        """Fetch all rows.
        
        Args:
            sql: SQL SELECT statement
            parameters: Query parameters
            
        Returns:
            List of rows
        """
        async with self.connection() as conn:
            cursor = await conn.execute(sql, parameters)
            return await cursor.fetchall()

    async def close(self) -> None:
        """Close database connection."""
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
            self._initialized = False
            logger.info("Database connection closed")

    async def __aenter__(self) -> "DatabaseManager":
        """Async context manager entry."""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()
