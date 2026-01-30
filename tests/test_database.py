"""Tests for database layer."""

import tempfile
from pathlib import Path

import pytest

from trading_system.database import DatabaseManager


class TestDatabaseManager:
    """Tests for DatabaseManager class."""

    @pytest.fixture
    async def db(self):
        """Create a temporary database for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = DatabaseManager(db_path)
            await db.initialize()
            yield db
            await db.close()

    @pytest.mark.asyncio
    async def test_initialization_creates_database(self, db):
        """Test that initialization creates the database file."""
        # The database file should exist after initialization
        assert db._db_path.exists()
        assert db._initialized

    @pytest.mark.asyncio
    async def test_initialization_creates_tables(self, db):
        """Test that schema is applied and tables are created."""
        # Query for tables
        rows = await db.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        table_names = {row["name"] for row in rows}

        # Check MVP tables exist
        assert "symbols" in table_names
        assert "price_data" in table_names

        # Check future tables exist
        assert "strategies" in table_names
        assert "trades" in table_names
        assert "wallet_snapshots" in table_names

    @pytest.mark.asyncio
    async def test_initialization_creates_indexes(self, db):
        """Test that indexes are created."""
        rows = await db.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )
        index_names = {row["name"] for row in rows}

        # Check important indexes exist
        assert "idx_symbols_active" in index_names
        assert "idx_price_data_symbol_time" in index_names

    @pytest.mark.asyncio
    async def test_connection_context_manager(self, db):
        """Test that connection context manager works."""
        async with db.connection() as conn:
            cursor = await conn.execute("SELECT 1 as test")
            row = await cursor.fetchone()
            assert row["test"] == 1

    @pytest.mark.asyncio
    async def test_execute_and_fetch_one(self, db):
        """Test execute and fetch_one operations."""
        # Insert test data
        await db.execute(
            "INSERT INTO symbols (symbol, is_active) VALUES (?, ?)",
            ("TEST/USDT", 1)
        )

        # Fetch it back
        row = await db.fetch_one(
            "SELECT * FROM symbols WHERE symbol = ?",
            ("TEST/USDT",)
        )

        assert row is not None
        assert row["symbol"] == "TEST/USDT"
        assert row["is_active"] == 1

    @pytest.mark.asyncio
    async def test_fetch_all(self, db):
        """Test fetch_all operation."""
        # Insert multiple rows
        await db.execute(
            "INSERT INTO symbols (symbol, is_active) VALUES (?, ?)",
            ("BTC/USDT", 1)
        )
        await db.execute(
            "INSERT INTO symbols (symbol, is_active) VALUES (?, ?)",
            ("ETH/USDT", 1)
        )

        # Fetch all
        rows = await db.fetch_all(
            "SELECT * FROM symbols WHERE is_active = 1 ORDER BY symbol"
        )

        assert len(rows) == 2
        assert rows[0]["symbol"] == "BTC/USDT"
        assert rows[1]["symbol"] == "ETH/USDT"

    @pytest.mark.asyncio
    async def test_fetch_one_returns_none_for_missing(self, db):
        """Test that fetch_one returns None when no results."""
        row = await db.fetch_one(
            "SELECT * FROM symbols WHERE symbol = ?",
            ("NONEXISTENT",)
        )

        assert row is None

    @pytest.mark.asyncio
    async def test_execute_with_dict_params(self, db):
        """Test execute with dict parameters."""
        await db.execute(
            "INSERT INTO symbols (symbol, is_active) VALUES (:symbol, :active)",
            {"symbol": "DICT/TEST", "active": 1}
        )

        row = await db.fetch_one(
            "SELECT * FROM symbols WHERE symbol = :symbol",
            {"symbol": "DICT/TEST"}
        )

        assert row["symbol"] == "DICT/TEST"

    @pytest.mark.asyncio
    async def test_foreign_keys_enabled(self, db):
        """Test that foreign keys are enabled."""
        row = await db.fetch_one("PRAGMA foreign_keys")
        assert row[0] == 1  # Foreign keys should be enabled

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            async with DatabaseManager(db_path) as db:
                assert db._initialized
                # Should be able to execute queries
                row = await db.fetch_one("SELECT 1 as test")
                assert row["test"] == 1

            # After exiting context, connection should be closed
            assert not db._initialized
