"""Tests for symbol management API endpoints."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from trading_system.api import app, get_backfill_service, get_db, get_settings


class TestAPISymbols:
    """Tests for the symbol management API endpoints."""

    @pytest.fixture
    def client_with_mocks(self):
        """Create a test client with mocked dependencies."""
        # Create mock database
        mock_db = MagicMock()
        mock_db.fetch_one = AsyncMock(return_value={"1": 1})

        # Create mock settings
        mock_settings = MagicMock()
        mock_settings.db_path = ":memory:"
        mock_settings.backfill_minutes = 5

        # Create mock backfill service
        mock_backfill_service = MagicMock()

        # Override dependencies
        app.dependency_overrides[get_db] = lambda: mock_db
        app.dependency_overrides[get_settings] = lambda: mock_settings
        app.dependency_overrides[get_backfill_service] = lambda: mock_backfill_service

        with TestClient(app) as test_client:
            yield test_client, mock_db, mock_backfill_service

        # Clear overrides after test
        app.dependency_overrides.clear()

    def test_list_symbols_empty(self, client_with_mocks):
        """Test listing symbols when no symbols are registered."""
        client, mock_db, _ = client_with_mocks

        # Mock empty list
        mock_db.fetch_all = AsyncMock(return_value=[])

        response = client.get("/symbols")

        assert response.status_code == 200
        data = response.json()
        assert data["symbols"] == []
        assert data["count"] == 0

    def test_list_symbols_with_data(self, client_with_mocks):
        """Test listing symbols with registered symbols."""
        client, mock_db, _ = client_with_mocks

        # Mock symbols in database
        mock_db.fetch_all = AsyncMock(return_value=[
            {
                "id": 1,
                "symbol": "BTC/USDT",
                "is_active": 1,
                "created_at": "2024-01-01T00:00:00",
                "last_price": 50000.0,
                "last_price_at": "2024-01-01T01:00:00",
            },
            {
                "id": 2,
                "symbol": "ETH/USDT",
                "is_active": 1,
                "created_at": "2024-01-01T00:00:00",
                "last_price": None,
                "last_price_at": None,
            },
        ])

        response = client.get("/symbols")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2
        assert len(data["symbols"]) == 2

        # Check first symbol
        btc = next(s for s in data["symbols"] if s["symbol"] == "BTC/USDT")
        assert btc["is_active"] is True
        assert btc["last_price"] == 50000.0

    def test_list_symbols_inactive_filter(self, client_with_mocks):
        """Test listing symbols with active_only=false includes inactive."""
        client, mock_db, _ = client_with_mocks

        # Mock symbols including inactive
        mock_db.fetch_all = AsyncMock(return_value=[
            {
                "id": 1,
                "symbol": "BTC/USDT",
                "is_active": 1,
                "created_at": "2024-01-01T00:00:00",
                "last_price": None,
                "last_price_at": None,
            },
            {
                "id": 2,
                "symbol": "ETH/USDT",
                "is_active": 0,
                "created_at": "2024-01-01T00:00:00",
                "last_price": None,
                "last_price_at": None,
            },
        ])

        response = client.get("/symbols?active_only=false")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2

    def test_get_symbol_success(self, client_with_mocks):
        """Test getting a specific symbol that exists."""
        client, mock_db, _ = client_with_mocks

        # Mock symbol in database
        mock_db.fetch_one = AsyncMock(return_value={
            "id": 1,
            "symbol": "BTC/USDT",
            "is_active": 1,
            "created_at": "2024-01-01T00:00:00",
            "last_price": 50000.0,
            "last_price_at": "2024-01-01T01:00:00",
        })

        response = client.get(f"/symbols/{quote('BTC/USDT', safe='')}")

        assert response.status_code == 200
        data = response.json()
        assert data["symbol"] == "BTC/USDT"
        assert data["is_active"] is True
        assert data["last_price"] == 50000.0

    def test_get_symbol_not_found(self, client_with_mocks):
        """Test getting a symbol that doesn't exist returns 404."""
        client, mock_db, _ = client_with_mocks

        # Mock no symbol found
        mock_db.fetch_one = AsyncMock(return_value=None)

        response = client.get("/symbols/INVALID%2FPAIR")

        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()

    def test_create_symbol_success(self, client_with_mocks):
        """Test creating a new symbol successfully."""
        client, mock_db, mock_backfill = client_with_mocks

        # Track calls to return different values
        call_count = {"fetch_one": 0}

        async def mock_fetch_one(*args, **kwargs):
            call_count["fetch_one"] += 1
            query = args[0] if args else ""
            # First call checks for duplicate by symbol
            if call_count["fetch_one"] == 1 and "symbol =" in query:
                return None  # No existing symbol
            # Second call fetches created symbol by ID
            elif "id =" in query:
                return {
                    "id": 1,
                    "symbol": "BTC/USDT",
                    "is_active": 1,
                    "created_at": "2024-01-01T00:00:00",
                    "last_price": None,
                    "last_price_at": None,
                }
            return None

        mock_db.fetch_one = mock_fetch_one

        # Mock cursor for INSERT
        mock_cursor = MagicMock()
        mock_cursor.lastrowid = 1
        mock_db.execute = AsyncMock(return_value=mock_cursor)

        # Mock backfill service
        mock_backfill.backfill_symbol = AsyncMock(return_value={
            "symbol": "BTC/USDT",
            "status": "success",
            "strategy": "full_backfill",
            "records_stored": 1,
        })
        mock_backfill.get_backfill_status = AsyncMock(return_value={
            "symbol": "BTC/USDT",
            "total_records": 1,
        })

        response = client.post("/symbols", json={"symbol": "BTC/USDT"})

        assert response.status_code == 201
        data = response.json()
        assert data["symbol"]["symbol"] == "BTC/USDT"
        assert data["symbol"]["is_active"] is True
        assert "backfill_status" in data

        # Verify backfill was called
        mock_backfill.backfill_symbol.assert_called_once_with("BTC/USDT")

    def test_create_symbol_duplicate(self, client_with_mocks):
        """Test creating a duplicate symbol returns 400."""
        client, mock_db, _ = client_with_mocks

        # Mock existing active symbol
        mock_db.fetch_one = AsyncMock(return_value={
            "id": 1,
            "symbol": "BTC/USDT",
            "is_active": 1,
            "created_at": "2024-01-01T00:00:00",
            "last_price": None,
            "last_price_at": None,
        })

        response = client.post("/symbols", json={"symbol": "BTC/USDT"})

        assert response.status_code == 400
        data = response.json()
        assert "already registered" in data["detail"].lower()

    def test_create_symbol_backfill_failure(self, client_with_mocks):
        """Test symbol creation succeeds even if backfill fails."""
        client, mock_db, mock_backfill = client_with_mocks

        # Track calls to return different values
        call_count = {"fetch_one": 0}

        async def mock_fetch_one(*args, **kwargs):
            call_count["fetch_one"] += 1
            query = args[0] if args else ""
            if call_count["fetch_one"] == 1 and "symbol =" in query:
                return None
            elif "id =" in query:
                return {
                    "id": 1,
                    "symbol": "BTC/USDT",
                    "is_active": 1,
                    "created_at": "2024-01-01T00:00:00",
                    "last_price": None,
                    "last_price_at": None,
                }
            return None

        mock_db.fetch_one = mock_fetch_one

        # Mock cursor for INSERT
        mock_cursor = MagicMock()
        mock_cursor.lastrowid = 1
        mock_db.execute = AsyncMock(return_value=mock_cursor)

        # Mock backfill service to fail
        mock_backfill.backfill_symbol = AsyncMock(
            side_effect=Exception("Network error")
        )
        mock_backfill.get_backfill_status = AsyncMock(return_value={
            "symbol": "BTC/USDT",
            "total_records": 0,
        })

        response = client.post("/symbols", json={"symbol": "BTC/USDT"})

        # Should still succeed (201) even if backfill fails
        assert response.status_code == 201
        data = response.json()
        assert "backfill failed" in data["message"].lower()
        assert "backfill_error" in data["backfill_status"]

    def test_create_symbol_invalid_format(self, client_with_mocks):
        """Test creating a symbol with invalid format."""
        client, _, _ = client_with_mocks

        # Empty symbol should fail validation
        response = client.post("/symbols", json={"symbol": ""})

        # FastAPI/Pydantic validation error
        assert response.status_code == 422

    def test_create_symbol_missing_field(self, client_with_mocks):
        """Test creating a symbol without required field."""
        client, _, _ = client_with_mocks

        response = client.post("/symbols", json={})

        assert response.status_code == 422
        data = response.json()
        assert "symbol" in str(data["detail"]).lower()


class TestAPISymbolsIntegration:
    """Integration tests for symbol API with real database."""

    @pytest.fixture
    async def real_db(self):
        """Create a real database for integration testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from trading_system.database import DatabaseManager
            db_path = Path(tmpdir) / "test.db"
            db = DatabaseManager(db_path)
            await db.initialize()
            yield db
            await db.close()

    @pytest.fixture
    def client_with_real_db(self, real_db):
        """Create a test client with real database but mocked backfill."""
        from trading_system.config import Settings

        mock_settings = Settings()

        # Mock backfill service
        mock_backfill = MagicMock()
        mock_backfill.backfill_symbol = AsyncMock(return_value={
            "symbol": "BTC/USDT",
            "status": "success",
            "strategy": "full_backfill",
            "records_stored": 0,
        })
        mock_backfill.get_backfill_status = AsyncMock(return_value={
            "symbol": "BTC/USDT",
            "total_records": 0,
        })

        app.dependency_overrides[get_db] = lambda: real_db
        app.dependency_overrides[get_settings] = lambda: mock_settings
        app.dependency_overrides[get_backfill_service] = lambda: mock_backfill

        with TestClient(app) as test_client:
            yield test_client, real_db

        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_create_and_list_symbol_integration(self, client_with_real_db):
        """Test creating a symbol and then listing it."""
        client, db = client_with_real_db

        # Create symbol
        response = client.post("/symbols", json={"symbol": "BTC/USDT"})
        assert response.status_code == 201

        # List symbols
        response = client.get("/symbols")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["symbols"][0]["symbol"] == "BTC/USDT"

    @pytest.mark.asyncio
    async def test_create_symbol_persists_to_database(self, client_with_real_db):
        """Test that created symbol is actually stored in database."""
        client, db = client_with_real_db

        # Create symbol via API
        response = client.post("/symbols", json={"symbol": "ETH/USDT"})
        assert response.status_code == 201

        # Verify directly in database
        row = await db.fetch_one("SELECT * FROM symbols WHERE symbol = ?", ("ETH/USDT",))
        assert row is not None
        assert row["symbol"] == "ETH/USDT"
        assert row["is_active"] == 1

    @pytest.mark.asyncio
    async def test_get_symbol_after_creation(self, client_with_real_db):
        """Test getting a symbol after creating it."""
        client, db = client_with_real_db

        # Create symbol
        client.post("/symbols", json={"symbol": "BTC/USDT"})

        # Get symbol
        response = client.get(f"/symbols/{quote('BTC/USDT', safe='')}")
        assert response.status_code == 200
        data = response.json()
        assert data["symbol"] == "BTC/USDT"
