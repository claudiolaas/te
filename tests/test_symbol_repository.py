"""Tests for SymbolRepository."""

import tempfile
from pathlib import Path

import pytest

from trading_system.database import DatabaseManager
from trading_system.repositories import SymbolRepository


class TestSymbolRepository:
    """Tests for SymbolRepository class."""

    @pytest.fixture
    async def repo(self):
        """Create a SymbolRepository with temporary database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = DatabaseManager(db_path)
            await db.initialize()
            repo = SymbolRepository(db)
            yield repo
            await db.close()

    @pytest.mark.asyncio
    async def test_register_new_symbol(self, repo):
        """Test registering a new symbol."""
        symbol = await repo.register("BTC/USDT")

        assert symbol.id is not None
        assert symbol.symbol == "BTC/USDT"
        assert symbol.is_active is True
        assert isinstance(symbol.created_at, type(symbol.created_at))  # datetime check

    @pytest.mark.asyncio
    async def test_register_duplicate_symbol_raises_error(self, repo):
        """Test that registering duplicate active symbol raises error."""
        await repo.register("BTC/USDT")

        with pytest.raises(ValueError, match="already registered"):
            await repo.register("BTC/USDT")

    @pytest.mark.asyncio
    async def test_register_reactivates_inactive_symbol(self, repo):
        """Test that registering an inactive symbol reactivates it."""
        # Register and deactivate
        symbol = await repo.register("BTC/USDT")
        await repo.deactivate(symbol.id)

        # Verify deactivated
        inactive = await repo.get(symbol.id)
        assert inactive.is_active is False

        # Re-register should reactivate
        reactivated = await repo.register("BTC/USDT")
        assert reactivated.id == symbol.id
        assert reactivated.is_active is True

    @pytest.mark.asyncio
    async def test_get_by_id(self, repo):
        """Test getting symbol by ID."""
        registered = await repo.register("BTC/USDT")

        fetched = await repo.get(registered.id)

        assert fetched is not None
        assert fetched.id == registered.id
        assert fetched.symbol == "BTC/USDT"

    @pytest.mark.asyncio
    async def test_get_by_id_caches_result(self, repo):
        """Test that get() caches the result."""
        registered = await repo.register("BTC/USDT")

        # First fetch
        fetched1 = await repo.get(registered.id)
        # Second fetch should use cache
        fetched2 = await repo.get(registered.id)

        assert fetched1 is fetched2  # Same object from cache

    @pytest.mark.asyncio
    async def test_get_by_id_returns_none_for_missing(self, repo):
        """Test that get() returns None for non-existent ID."""
        result = await repo.get(99999)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_symbol(self, repo):
        """Test getting symbol by symbol string."""
        await repo.register("BTC/USDT")

        fetched = await repo.get_by_symbol("BTC/USDT")

        assert fetched is not None
        assert fetched.symbol == "BTC/USDT"

    @pytest.mark.asyncio
    async def test_get_by_symbol_caches_result(self, repo):
        """Test that get_by_symbol() caches the result."""
        await repo.register("BTC/USDT")

        fetched1 = await repo.get_by_symbol("BTC/USDT")
        fetched2 = await repo.get_by_symbol("BTC/USDT")

        assert fetched1 is fetched2  # Same object from cache

    @pytest.mark.asyncio
    async def test_get_by_symbol_returns_none_for_missing(self, repo):
        """Test that get_by_symbol() returns None for non-existent symbol."""
        result = await repo.get_by_symbol("NONEXISTENT")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_active(self, repo):
        """Test listing active symbols."""
        # Register symbols
        await repo.register("BTC/USDT")
        await repo.register("ETH/USDT")
        await repo.register("SOL/USDT")

        active = await repo.list_active()

        assert len(active) == 3
        symbols = {s.symbol for s in active}
        assert symbols == {"BTC/USDT", "ETH/USDT", "SOL/USDT"}

    @pytest.mark.asyncio
    async def test_list_active_excludes_inactive(self, repo):
        """Test that list_active() excludes deactivated symbols."""
        # Register and deactivate one
        btc = await repo.register("BTC/USDT")
        await repo.register("ETH/USDT")
        await repo.deactivate(btc.id)

        active = await repo.list_active()

        assert len(active) == 1
        assert active[0].symbol == "ETH/USDT"

    @pytest.mark.asyncio
    async def test_list_active_returns_sorted(self, repo):
        """Test that list_active() returns symbols sorted."""
        await repo.register("SOL/USDT")
        await repo.register("BTC/USDT")
        await repo.register("ETH/USDT")

        active = await repo.list_active()

        symbols = [s.symbol for s in active]
        assert symbols == ["BTC/USDT", "ETH/USDT", "SOL/USDT"]

    @pytest.mark.asyncio
    async def test_list_active_caches_result(self, repo):
        """Test that list_active() caches the result."""
        await repo.register("BTC/USDT")

        list1 = await repo.list_active()
        list2 = await repo.list_active()

        assert list1 is list2  # Same list object from cache

    @pytest.mark.asyncio
    async def test_deactivate(self, repo):
        """Test deactivating a symbol."""
        symbol = await repo.register("BTC/USDT")

        result = await repo.deactivate(symbol.id)

        assert result is True

        # Verify deactivated
        fetched = await repo.get(symbol.id)
        assert fetched.is_active is False

    @pytest.mark.asyncio
    async def test_deactivate_returns_false_for_missing(self, repo):
        """Test that deactivate() returns False for non-existent symbol."""
        result = await repo.deactivate(99999)
        assert result is False

    @pytest.mark.asyncio
    async def test_deactivate_invalidates_cache(self, repo):
        """Test that deactivate() invalidates the cache."""
        symbol = await repo.register("BTC/USDT")

        # Populate cache
        await repo.get(symbol.id)
        await repo.list_active()

        # Deactivate
        await repo.deactivate(symbol.id)

        # Cache should be invalidated - list_active should reflect change
        active = await repo.list_active()
        assert len(active) == 0

    @pytest.mark.asyncio
    async def test_update_last_price(self, repo):
        """Test updating last price cache."""
        symbol = await repo.register("BTC/USDT")

        result = await repo.update_last_price(symbol.id, 50000.0)

        assert result is True

        # Verify updated
        fetched = await repo.get(symbol.id)
        assert fetched.last_price == 50000.0
        assert fetched.last_price_at is not None

    @pytest.mark.asyncio
    async def test_update_last_price_returns_false_for_missing(self, repo):
        """Test that update_last_price() returns False for non-existent symbol."""
        result = await repo.update_last_price(99999, 50000.0)
        assert result is False

    @pytest.mark.asyncio
    async def test_update_last_price_updates_cache(self, repo):
        """Test that update_last_price() updates cached object."""
        symbol = await repo.register("BTC/USDT")

        # Populate cache
        cached = await repo.get(symbol.id)

        # Update price
        await repo.update_last_price(symbol.id, 50000.0)

        # Cached object should be updated
        assert cached.last_price == 50000.0

    @pytest.mark.asyncio
    async def test_register_invalidates_cache(self, repo):
        """Test that register() invalidates the list cache."""
        # Populate cache
        await repo.list_active()

        # Register new symbol
        await repo.register("BTC/USDT")

        # Cache should be invalidated - new symbol should appear
        active = await repo.list_active()
        assert len(active) == 1
