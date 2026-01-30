"""Symbol repository with in-memory caching."""

from dataclasses import dataclass
from datetime import datetime

from trading_system.database import DatabaseManager


@dataclass
class Symbol:
    """Symbol data model."""
    id: int
    symbol: str
    created_at: datetime
    is_active: bool
    last_price: float | None = None
    last_price_at: datetime | None = None

    @classmethod
    def from_row(cls, row) -> "Symbol":
        """Create Symbol from database row."""
        return cls(
            id=row["id"],
            symbol=row["symbol"],
            created_at=datetime.fromisoformat(row["created_at"]),
            is_active=bool(row["is_active"]),
            last_price=row["last_price"],
            last_price_at=datetime.fromisoformat(row["last_price_at"]) if row["last_price_at"] else None
        )


class SymbolRepository:
    """Repository for symbol CRUD operations with caching.
    
    Provides in-memory caching for active symbols to reduce database queries.
    Cache is invalidated on symbol registration/deactivation.
    
    Usage:
        repo = SymbolRepository(db_manager)
        
        # Register new symbol
        symbol = await repo.register("BTC/USDT")
        
        # Get by ID (cached)
        symbol = await repo.get(1)
        
        # Get by symbol string (cached)
        symbol = await repo.get_by_symbol("BTC/USDT")
        
        # List all active symbols (cached)
        symbols = await repo.list_active()
    """

    def __init__(self, db: DatabaseManager) -> None:
        """Initialize repository.
        
        Args:
            db: Database manager instance
        """
        self._db = db
        self._cache: dict[int, Symbol] = {}  # id -> Symbol
        self._symbol_cache: dict[str, Symbol] = {}  # symbol string -> Symbol
        self._active_list_cache: list[Symbol] | None = None

    async def register(self, symbol: str) -> Symbol:
        """Register a new symbol.
        
        Args:
            symbol: Trading pair symbol (e.g., "BTC/USDT")
            
        Returns:
            Symbol: Created symbol object
            
        Raises:
            ValueError: If symbol already exists
        """
        # Check if already exists
        existing = await self.get_by_symbol(symbol)
        if existing is not None:
            if existing.is_active:
                raise ValueError(f"Symbol '{symbol}' is already registered and active")
            else:
                # Reactivate
                await self._db.execute(
                    "UPDATE symbols SET is_active = 1 WHERE id = ?",
                    (existing.id,)
                )
                self._invalidate_cache()
                return await self.get(existing.id)

        # Insert new symbol
        cursor = await self._db.execute(
            "INSERT INTO symbols (symbol, is_active) VALUES (?, 1)",
            (symbol,)
        )

        symbol_id = cursor.lastrowid

        # Fetch and cache
        result = await self.get(symbol_id)
        self._invalidate_cache()

        return result

    async def get(self, symbol_id: int) -> Symbol | None:
        """Get symbol by ID.
        
        Args:
            symbol_id: Symbol database ID
            
        Returns:
            Symbol or None if not found
        """
        # Check cache
        if symbol_id in self._cache:
            return self._cache[symbol_id]

        # Fetch from database
        row = await self._db.fetch_one(
            "SELECT * FROM symbols WHERE id = ?",
            (symbol_id,)
        )

        if row is None:
            return None

        symbol = Symbol.from_row(row)
        self._cache[symbol_id] = symbol
        self._symbol_cache[symbol.symbol] = symbol

        return symbol

    async def get_by_symbol(self, symbol: str) -> Symbol | None:
        """Get symbol by symbol string.
        
        Args:
            symbol: Trading pair symbol (e.g., "BTC/USDT")
            
        Returns:
            Symbol or None if not found
        """
        # Check cache
        if symbol in self._symbol_cache:
            return self._symbol_cache[symbol]

        # Fetch from database
        row = await self._db.fetch_one(
            "SELECT * FROM symbols WHERE symbol = ?",
            (symbol,)
        )

        if row is None:
            return None

        result = Symbol.from_row(row)
        self._cache[result.id] = result
        self._symbol_cache[symbol] = result

        return result

    async def list_active(self) -> list[Symbol]:
        """List all active symbols.
        
        Returns:
            List of active symbols
        """
        # Check cache
        if self._active_list_cache is not None:
            return self._active_list_cache

        # Fetch from database
        rows = await self._db.fetch_all(
            "SELECT * FROM symbols WHERE is_active = 1 ORDER BY symbol"
        )

        symbols = [Symbol.from_row(row) for row in rows]

        # Update caches
        for symbol in symbols:
            self._cache[symbol.id] = symbol
            self._symbol_cache[symbol.symbol] = symbol

        self._active_list_cache = symbols

        return symbols

    async def deactivate(self, symbol_id: int) -> bool:
        """Deactivate a symbol (soft delete).
        
        Args:
            symbol_id: Symbol database ID
            
        Returns:
            True if symbol was deactivated, False if not found
        """
        cursor = await self._db.execute(
            "UPDATE symbols SET is_active = 0 WHERE id = ?",
            (symbol_id,)
        )

        if cursor.rowcount == 0:
            return False

        self._invalidate_cache()
        return True

    async def update_last_price(self, symbol_id: int, price: float) -> bool:
        """Update the cached last price for a symbol.
        
        Args:
            symbol_id: Symbol database ID
            price: Current price
            
        Returns:
            True if updated, False if symbol not found
        """
        cursor = await self._db.execute(
            "UPDATE symbols SET last_price = ?, last_price_at = CURRENT_TIMESTAMP WHERE id = ?",
            (price, symbol_id)
        )

        if cursor.rowcount == 0:
            return False

        # Update cache if present
        if symbol_id in self._cache:
            self._cache[symbol_id].last_price = price
            self._cache[symbol_id].last_price_at = datetime.now()

        return True

    def _invalidate_cache(self) -> None:
        """Invalidate all caches."""
        self._cache.clear()
        self._symbol_cache.clear()
        self._active_list_cache = None
