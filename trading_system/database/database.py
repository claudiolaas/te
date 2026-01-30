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

        # Run migrations for existing databases
        await self._run_migrations()

        logger.debug("Database schema initialized")

    async def _run_migrations(self) -> None:
        """Run migrations to update existing databases."""
        # Check current schema version (use direct connection, not public methods)
        try:
            cursor = await self._connection.execute(
                "SELECT value FROM system_metadata WHERE key = 'schema_version'"
            )
            row = await cursor.fetchone()
            current_version = int(row["value"]) if row else 0
        except Exception:
            current_version = 0

        # Migration v1 -> v2: Add datetime column to price_data
        # Always check for column existence regardless of version (idempotent)
        await self._migration_v2_add_datetime_column()

    async def _migration_v2_add_datetime_column(self) -> None:
        """Add datetime generated column to price_data table."""
        try:
            # Check if column already exists by trying to select it
            # (VIRTUAL columns don't show in PRAGMA table_info)
            try:
                cursor = await self._connection.execute(
                    "SELECT datetime FROM price_data LIMIT 1"
                )
                await cursor.fetchone()
                # If we get here, column exists
                logger.debug("datetime column already exists")
            except Exception:
                # Column doesn't exist, add it
                logger.info("Running migration v2: Adding datetime column to price_data")
                # Note: SQLite only allows adding VIRTUAL generated columns, not STORED
                await self._connection.execute(
                    """
                    ALTER TABLE price_data ADD COLUMN datetime TEXT 
                    GENERATED ALWAYS AS (
                        strftime('%Y-%m-%d %H:%M:%S', timestamp/1000, 'unixepoch')
                    ) VIRTUAL
                    """
                )
                await self._connection.commit()
                logger.info("Migration v2 complete: datetime column added")

            # Update schema version
            await self._connection.execute(
                "INSERT OR REPLACE INTO system_metadata (key, value) VALUES ('schema_version', '2')"
            )
            await self._connection.commit()

        except Exception as e:
            logger.error(f"Migration v2 failed: {e}")
            raise

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
