"""Integration tests for FastAPI REST API with real database.

These tests verify that API endpoints work correctly with actual database operations,
providing end-to-end validation beyond the mocked unit tests.
"""

import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from trading_system.api import app, get_db, get_settings
from trading_system.config import Settings
from trading_system.database import DatabaseManager


@pytest_asyncio.fixture
async def real_db():
    """Create a real database for integration testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = DatabaseManager(db_path)
        await db.initialize()

        yield db

        await db.close()


@pytest_asyncio.fixture
async def real_settings():
    """Create real settings for integration testing."""
    # Use default settings (will load from .env if present)
    settings = Settings()
    return settings


@pytest.fixture
def client_with_real_db(real_db, real_settings):
    """Create a test client with real database and settings."""
    # Override dependencies to use real components
    app.dependency_overrides[get_db] = lambda: real_db
    app.dependency_overrides[get_settings] = lambda: real_settings

    with TestClient(app) as test_client:
        yield test_client

    # Clear overrides after test
    app.dependency_overrides.clear()


@pytest.mark.integration
class TestAPIHealthIntegration:
    """Integration tests for API health endpoints with real database."""

    def test_health_check_with_real_database(self, client_with_real_db):
        """Test health check returns healthy when using real database connection."""
        response = client_with_real_db.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["database"] == "connected"

    def test_root_endpoint_returns_api_info(self, client_with_real_db):
        """Test root endpoint returns API information."""
        response = client_with_real_db.get("/")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Trading System API"
        assert "version" in data
        assert "docs" in data
        assert "health" in data


@pytest.mark.integration
class TestAPIDatabaseOperations:
    """Integration tests verifying database operations through API."""

    @pytest.mark.asyncio
    async def test_health_check_after_database_operations(self, real_db, real_settings):
        """Test health check works correctly after performing database operations."""
        # Perform some database operations first
        await real_db.execute(
            "INSERT INTO symbols (symbol, is_active) VALUES (?, ?)",
            ("BTC/USDT", True)
        )

        # Now test health check
        app.dependency_overrides[get_db] = lambda: real_db
        app.dependency_overrides[get_settings] = lambda: real_settings

        try:
            with TestClient(app) as client:
                response = client.get("/health")

                assert response.status_code == 200
                assert response.json()["status"] == "healthy"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_health_check_database_error_handling(self, real_db, real_settings):
        """Test health check correctly identifies database errors.

        This simulates a database error by closing the connection before the health check.
        """
        # Close the database to simulate connection error
        await real_db.close()

        app.dependency_overrides[get_db] = lambda: real_db
        app.dependency_overrides[get_settings] = lambda: real_settings

        try:
            with TestClient(app) as client:
                response = client.get("/health")

                assert response.status_code == 503
                data = response.json()
                assert data["status"] == "unhealthy"
                assert data["database"] == "error"
        finally:
            app.dependency_overrides.clear()


@pytest.mark.integration
class TestAPILifespanIntegration:
    """Integration tests for API lifespan with real components."""

    @pytest.mark.asyncio
    async def test_lifespan_initializes_real_database(self):
        """Test that lifespan correctly initializes a real database."""
        from trading_system.api import lifespan

        # Use a temporary database path
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "lifespan_test.db"

            # Create custom settings with temp path
            settings = Settings(db_path=str(db_path))

            # Override settings in the app
            original_overrides = app.dependency_overrides.copy()

            # Store original state
            from trading_system import api as api_module
            original_db = api_module._db
            original_settings = api_module._settings

            try:
                async with lifespan(app):
                    # During lifespan, database should be initialized
                    assert api_module._db is not None
                    assert api_module._settings is not None

                    # Verify database is actually working
                    result = await api_module._db.fetch_one("SELECT 1 as test")
                    assert result["test"] == 1

                    # Verify tables were created
                    tables = await api_module._db.fetch_all(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                    table_names = [t["name"] for t in tables]
                    assert "symbols" in table_names
                    assert "price_data" in table_names

                # After lifespan exits, database should be closed
                assert api_module._db is None
                assert api_module._settings is None

            finally:
                # Restore original state
                api_module._db = original_db
                api_module._settings = original_settings
                app.dependency_overrides = original_overrides


@pytest.mark.integration
class TestAPIMultipleRequests:
    """Integration tests for handling multiple requests with real database."""

    def test_multiple_health_checks_consistent(self, client_with_real_db):
        """Test that multiple health checks return consistent results."""
        responses = []
        for _ in range(5):
            response = client_with_real_db.get("/health")
            responses.append(response)

        # All should succeed
        assert all(r.status_code == 200 for r in responses)

        # All should have same structure
        for r in responses:
            data = r.json()
            assert data["status"] == "healthy"
            assert data["database"] == "connected"

    @pytest.mark.asyncio
    async def test_concurrent_health_checks(self, real_db, real_settings):
        """Test handling of concurrent health check requests."""
        import asyncio

        app.dependency_overrides[get_db] = lambda: real_db
        app.dependency_overrides[get_settings] = lambda: real_settings

        try:
            with TestClient(app) as client:
                # Make multiple concurrent requests
                async def make_request():
                    return client.get("/health")

                # Run 10 concurrent requests
                tasks = [make_request() for _ in range(10)]
                responses = await asyncio.gather(*tasks)

                # All should succeed
                assert all(r.status_code == 200 for r in responses)

                # All should have consistent structure
                for r in responses:
                    data = r.json()
                    assert data["status"] == "healthy"

        finally:
            app.dependency_overrides.clear()
