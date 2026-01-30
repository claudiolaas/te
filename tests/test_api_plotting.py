"""Tests for plotting API endpoints."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from trading_system.api import app, get_db, get_settings


class TestAPIPlotting:
    """Tests for the plotting API endpoints."""

    @pytest.fixture
    def client_with_mocks(self):
        """Create a test client with mocked dependencies."""
        mock_db = MagicMock()
        mock_settings = MagicMock()

        app.dependency_overrides[get_db] = lambda: mock_db
        app.dependency_overrides[get_settings] = lambda: mock_settings

        with TestClient(app) as test_client:
            yield test_client, mock_db

        app.dependency_overrides.clear()

    def test_plot_prices_empty_data(self, client_with_mocks):
        """Test plotting endpoint with no price data."""
        client, mock_db = client_with_mocks

        # Mock empty result
        mock_db.fetch_all = AsyncMock(return_value=[])

        response = client.get("/plot/prices")

        assert response.status_code == 200
        assert "No price data available" in response.text

    def test_plot_prices_with_data(self, client_with_mocks):
        """Test plotting endpoint returns HTML with Plotly chart."""
        client, mock_db = client_with_mocks

        # Mock price data for multiple symbols
        mock_db.fetch_all = AsyncMock(return_value=[
            {
                "symbol": "BTC/USDT",
                "timestamp": 1704067200000,  # 2024-01-01 00:00:00 UTC
                "close": 42000.0,
            },
            {
                "symbol": "BTC/USDT",
                "timestamp": 1704067260000,  # +1 minute
                "close": 42100.0,
            },
            {
                "symbol": "ETH/USDT",
                "timestamp": 1704067200000,
                "close": 2200.0,
            },
            {
                "symbol": "ETH/USDT",
                "timestamp": 1704067260000,
                "close": 2210.0,
            },
        ])

        response = client.get("/plot/prices")

        assert response.status_code == 200
        # Should return HTML
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        # Should contain Plotly
        assert "plotly" in response.text.lower()
        # Should contain the chart title
        assert "Historical Price Data" in response.text
        # Should indicate 2 symbols in subtitle
        assert "2 symbol(s)" in response.text
        # Should have chart container
        assert "chart-container" in response.text

    def test_plot_prices_log_scale(self, client_with_mocks):
        """Test that chart uses log scale Y-axis."""
        client, mock_db = client_with_mocks

        mock_db.fetch_all = AsyncMock(return_value=[
            {
                "symbol": "BTC/USDT",
                "timestamp": 1704067200000,
                "close": 42000.0,
            },
        ])

        response = client.get("/plot/prices")

        assert response.status_code == 200
        # Plotly log scale is set via 'type': 'log' in yaxis config
        assert '"type":"log"' in response.text or "'type': 'log'" in response.text


class TestAPIPlottingIntegration:
    """Integration tests for plotting with real database."""

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
        """Create a test client with real database."""
        from trading_system.config import Settings
        mock_settings = Settings()

        app.dependency_overrides[get_db] = lambda: real_db
        app.dependency_overrides[get_settings] = lambda: mock_settings

        with TestClient(app) as test_client:
            yield test_client, real_db

        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_plot_prices_integration(self, client_with_real_db):
        """Test plotting with real data in database."""
        client, db = client_with_real_db

        # Insert test symbols
        await db.execute(
            "INSERT INTO symbols (symbol, is_active) VALUES (?, 1)",
            ("BTC/USDT",)
        )
        await db.execute(
            "INSERT INTO symbols (symbol, is_active) VALUES (?, 1)",
            ("ETH/USDT",)
        )

        # Get symbol IDs
        btc_row = await db.fetch_one(
            "SELECT id FROM symbols WHERE symbol = ?", ("BTC/USDT",)
        )
        eth_row = await db.fetch_one(
            "SELECT id FROM symbols WHERE symbol = ?", ("ETH/USDT",)
        )

        # Insert price data
        base_time = 1704067200000  # 2024-01-01 00:00:00 UTC
        for i in range(5):
            await db.execute(
                """INSERT INTO price_data 
                    (symbol_id, timestamp, open, high, low, close, volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (btc_row["id"], base_time + i * 60000, 42000.0, 42100.0, 41900.0, 42050.0 + i * 10, 100.0)
            )
            await db.execute(
                """INSERT INTO price_data 
                    (symbol_id, timestamp, open, high, low, close, volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (eth_row["id"], base_time + i * 60000, 2200.0, 2210.0, 2190.0, 2205.0 + i, 500.0)
            )

        response = client.get("/plot/prices")

        assert response.status_code == 200
        # Should have the chart title
        assert "Historical Price Data" in response.text
        # Should indicate 2 symbols
        assert "2 symbol(s)" in response.text
        # Check for Plotly JavaScript
        assert "Plotly" in response.text
