"""Tests for FastAPI REST API."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from trading_system.api import app, get_db, get_settings


class TestAPI:
    """Tests for the REST API endpoints."""

    @pytest.fixture
    def client(self):
        """Create a test client with mocked dependencies."""
        # Create mock database with async methods
        mock_db = MagicMock()
        mock_db.fetch_one = AsyncMock(return_value={"1": 1})

        # Create mock settings
        mock_settings = MagicMock()
        mock_settings.db_path = ":memory:"

        # Override dependencies
        app.dependency_overrides[get_db] = lambda: mock_db
        app.dependency_overrides[get_settings] = lambda: mock_settings

        with TestClient(app) as test_client:
            yield test_client, mock_db

        # Clear overrides after test
        app.dependency_overrides.clear()

    def test_root_endpoint(self, client):
        """Test root endpoint returns API information."""
        test_client, _ = client

        response = test_client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Trading System API"
        assert "version" in data
        assert "docs" in data
        assert "health" in data

    def test_health_check_healthy(self, client):
        """Test health check returns healthy when database is connected."""
        test_client, mock_db = client

        response = test_client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["database"] == "connected"

    def test_health_check_unhealthy(self, client):
        """Test health check returns unhealthy when database has error."""
        test_client, mock_db = client

        # Make database query fail
        mock_db.fetch_one.side_effect = Exception("Database error")

        response = test_client.get("/health")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["database"] == "error"


class TestAPILifespan:
    """Tests for API lifespan (startup/shutdown) events."""

    @pytest.mark.asyncio
    async def test_lifespan_initializes_database(self):
        """Test that lifespan context manager initializes database."""
        mock_db_instance = MagicMock()
        mock_db_instance.initialize = AsyncMock()
        mock_db_instance.close = AsyncMock()

        mock_settings_instance = MagicMock()
        mock_settings_instance.db_path = ":memory:"

        mock_binance_instance = MagicMock()
        mock_binance_instance.initialize = AsyncMock()
        mock_binance_instance.close = AsyncMock()

        mock_backfill_instance = MagicMock()

        with patch("trading_system.api.DatabaseManager") as mock_db_class, \
             patch("trading_system.api.Settings") as mock_settings_class, \
             patch("trading_system.api.BinanceClient") as mock_binance_class, \
             patch("trading_system.api.BackfillService") as mock_backfill_class:

            mock_db_class.return_value = mock_db_instance
            mock_settings_class.return_value = mock_settings_instance
            mock_binance_class.return_value = mock_binance_instance
            mock_backfill_class.return_value = mock_backfill_instance

            from trading_system.api import lifespan

            async with lifespan(app):
                # During lifespan, database should be initialized
                mock_db_instance.initialize.assert_called_once()
                mock_binance_instance.initialize.assert_called_once()

            # After lifespan exits, database should be closed
            mock_db_instance.close.assert_called_once()
            mock_binance_instance.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_lifespan_closes_database_on_exception(self):
        """Test that lifespan closes database even if exception occurs during init."""
        mock_db_instance = MagicMock()
        mock_db_instance.initialize = AsyncMock(side_effect=Exception("Init failed"))
        mock_db_instance.close = AsyncMock()

        mock_settings_instance = MagicMock()
        mock_settings_instance.db_path = ":memory:"

        with patch("trading_system.api.DatabaseManager") as mock_db_class, \
             patch("trading_system.api.Settings") as mock_settings_class, \
             patch("trading_system.api.BinanceClient") as mock_binance_class:

            mock_db_class.return_value = mock_db_instance
            mock_settings_class.return_value = mock_settings_instance

            from trading_system.api import lifespan

            # Exception during initialize should still cleanup
            with pytest.raises(Exception, match="Init failed"):
                async with lifespan(app):
                    pass  # Never reached

            # Database should still be closed even if init failed
            mock_db_instance.close.assert_called_once()


class TestAPIHelpers:
    """Tests for API helper functions."""

    def test_get_db_raises_when_not_initialized(self):
        """Test get_db raises RuntimeError when database is not initialized."""
        from trading_system.api import _db

        # Store original value
        original_db = _db

        try:
            # Set to None to simulate uninitialized state
            import trading_system.api as api_module
            api_module._db = None

            with pytest.raises(RuntimeError, match="Database not initialized"):
                get_db()
        finally:
            # Restore original value
            api_module._db = original_db

    def test_get_settings_raises_when_not_initialized(self):
        """Test get_settings raises RuntimeError when settings are not initialized."""
        from trading_system.api import _settings

        # Store original value
        original_settings = _settings

        try:
            # Set to None to simulate uninitialized state
            import trading_system.api as api_module
            api_module._settings = None

            with pytest.raises(RuntimeError, match="Settings not initialized"):
                get_settings()
        finally:
            # Restore original value
            api_module._settings = original_settings
