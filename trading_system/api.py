"""FastAPI REST API for trading system symbol management."""

from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncGenerator

import plotly.graph_objects as go
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse
from plotly.offline import plot
from pydantic import BaseModel, ConfigDict, Field

from trading_system.clients import BinanceClient
from trading_system.config import Settings
from trading_system.database import DatabaseManager
from trading_system.repositories import Symbol, SymbolRepository
from trading_system.services import BackfillService


# Global state for the API (initialized during lifespan)
_db: DatabaseManager | None = None
_settings: Settings | None = None
_binance_client: BinanceClient | None = None
_backfill_service: BackfillService | None = None


# Pydantic models for request/response validation
class SymbolCreate(BaseModel):
    """Request model for creating a new symbol."""
    symbol: str = Field(
        ...,
        description="Trading pair symbol (e.g., BTC/USDT)",
        min_length=3,
        examples=["BTC/USDT", "ETH/USDT"]
    )


class SymbolResponse(BaseModel):
    """Response model for symbol operations."""
    id: int
    symbol: str
    is_active: bool
    created_at: str
    last_price: float | None = None
    last_price_at: str | None = None

    model_config = ConfigDict(from_attributes=True)


class SymbolListResponse(BaseModel):
    """Response model for listing symbols."""
    symbols: list[SymbolResponse]
    count: int


class SymbolCreateResponse(BaseModel):
    """Response model for symbol creation with backfill status."""
    symbol: SymbolResponse
    backfill_status: dict
    message: str


def get_db() -> DatabaseManager:
    """Get the current database manager instance.

    Raises:
        RuntimeError: If database is not initialized.

    Returns:
        DatabaseManager: The current database instance.
    """
    if _db is None:
        raise RuntimeError("Database not initialized")
    return _db


def get_settings() -> Settings:
    """Get the current settings instance.

    Raises:
        RuntimeError: If settings are not initialized.

    Returns:
        Settings: The current settings instance.
    """
    if _settings is None:
        raise RuntimeError("Settings not initialized")
    return _settings


def get_backfill_service() -> BackfillService:
    """Get the current backfill service instance.

    Raises:
        RuntimeError: If backfill service is not initialized.

    Returns:
        BackfillService: The current backfill service instance.
    """
    if _backfill_service is None:
        raise RuntimeError("Backfill service not initialized")
    return _backfill_service


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Async lifespan context manager for startup and shutdown events."""
    global _db, _settings, _binance_client, _backfill_service

    # Startup: Initialize database and settings
    _settings = Settings()
    _db = DatabaseManager(_settings.db_path)

    try:
        await _db.initialize()
    except Exception:
        # Cleanup on initialization failure
        await _db.close()
        _db = None
        _settings = None
        raise

    # Initialize Binance client and backfill service
    _binance_client = BinanceClient(_settings)
    await _binance_client.initialize()
    _backfill_service = BackfillService(_binance_client, _db, _settings)

    yield

    # Shutdown: Cleanup resources
    if _binance_client:
        await _binance_client.close()
        _binance_client = None
    if _db:
        await _db.close()
        _db = None
    _settings = None
    _backfill_service = None


# Create FastAPI app with lifespan
app = FastAPI(
    title="Trading System API",
    description="REST API for managing trading symbols and system operations",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health", response_class=JSONResponse)
async def health_check(db: DatabaseManager = Depends(get_db)) -> dict:
    """Health check endpoint to verify API and database connectivity.

    Args:
        db: Database manager instance (injected via dependency).

    Returns:
        dict: Health status information including:
            - status: "healthy" or "unhealthy"
            - database: Database connection status
    """
    health_status = {
        "status": "healthy",
        "database": "connected",
    }

    # Verify database is actually accessible
    try:
        # Simple query to verify connection is alive
        await db.fetch_one("SELECT 1")
    except Exception:
        health_status["status"] = "unhealthy"
        health_status["database"] = "error"

    status_code = (
        status.HTTP_200_OK
        if health_status["status"] == "healthy"
        else status.HTTP_503_SERVICE_UNAVAILABLE
    )

    return JSONResponse(content=health_status, status_code=status_code)


@app.get("/")
async def root() -> dict:
    """Root endpoint returning API information."""
    return {
        "name": "Trading System API",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
        "symbols": "/symbols",
    }


@app.post("/symbols", response_model=SymbolCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_symbol(
    symbol_data: SymbolCreate,
    db: DatabaseManager = Depends(get_db),
    backfill_service: BackfillService = Depends(get_backfill_service),
) -> SymbolCreateResponse:
    """Register a new symbol with automatic backfill.

    Args:
        symbol_data: Symbol creation data containing the symbol string.
        db: Database manager instance (injected via dependency).
        backfill_service: Backfill service instance (injected via dependency).

    Returns:
        SymbolCreateResponse: Created symbol with backfill status.

    Raises:
        HTTPException: 400 if symbol already registered and active.
        HTTPException: 500 if backfill fails after registration.
    """
    symbol_repo = SymbolRepository(db)

    # Check if symbol already exists and is active
    existing = await symbol_repo.get_by_symbol(symbol_data.symbol)
    if existing is not None and existing.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Symbol '{symbol_data.symbol}' is already registered and active"
        )

    try:
        # Register the symbol
        symbol = await symbol_repo.register(symbol_data.symbol)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        ) from e

    # Trigger automatic backfill
    backfill_result = {}
    backfill_error = None
    try:
        backfill_result = await backfill_service.backfill_symbol(symbol_data.symbol)
    except Exception as e:
        # Log the error but don't fail the registration
        backfill_error = str(e)

    # Get backfill status
    backfill_status = await backfill_service.get_backfill_status(symbol_data.symbol)
    backfill_status['backfill_result'] = backfill_result
    if backfill_error:
        backfill_status['backfill_error'] = backfill_error

    # Build response
    symbol_response = SymbolResponse(
        id=symbol.id,
        symbol=symbol.symbol,
        is_active=symbol.is_active,
        created_at=symbol.created_at.isoformat(),
        last_price=symbol.last_price,
        last_price_at=symbol.last_price_at.isoformat() if symbol.last_price_at else None,
    )

    message = f"Symbol '{symbol_data.symbol}' registered successfully"
    if backfill_error:
        message += f" but backfill failed: {backfill_error}"
    elif backfill_result.get('records_stored', 0) > 0:
        message += f" with {backfill_result['records_stored']} historical records"

    return SymbolCreateResponse(
        symbol=symbol_response,
        backfill_status=backfill_status,
        message=message,
    )


@app.get("/symbols", response_model=SymbolListResponse)
async def list_symbols(
    active_only: bool = True,
    db: DatabaseManager = Depends(get_db),
) -> SymbolListResponse:
    """List all registered symbols.

    Args:
        active_only: If True, return only active symbols. Default is True.
        db: Database manager instance (injected via dependency).

    Returns:
        SymbolListResponse: List of symbols with count.
    """
    symbol_repo = SymbolRepository(db)

    if active_only:
        symbols = await symbol_repo.list_active()
    else:
        # Get all symbols (we need to fetch from DB directly)
        rows = await db.fetch_all("SELECT * FROM symbols ORDER BY symbol")
        symbols = [Symbol.from_row(row) for row in rows]

    symbol_responses = [
        SymbolResponse(
            id=s.id,
            symbol=s.symbol,
            is_active=s.is_active,
            created_at=s.created_at.isoformat(),
            last_price=s.last_price,
            last_price_at=s.last_price_at.isoformat() if s.last_price_at else None,
        )
        for s in symbols
    ]

    return SymbolListResponse(
        symbols=symbol_responses,
        count=len(symbol_responses),
    )


@app.get("/symbols/{symbol:path}", response_model=SymbolResponse)
async def get_symbol(
    symbol: str,
    db: DatabaseManager = Depends(get_db),
) -> SymbolResponse:
    """Get a specific symbol by its trading pair string.

    Args:
        symbol: Trading pair symbol (e.g., BTC/USDT).
        db: Database manager instance (injected via dependency).

    Returns:
        SymbolResponse: Symbol details.

    Raises:
        HTTPException: 404 if symbol not found.
    """
    symbol_repo = SymbolRepository(db)
    symbol_obj = await symbol_repo.get_by_symbol(symbol)

    if symbol_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Symbol '{symbol}' not found"
        )

    return SymbolResponse(
        id=symbol_obj.id,
        symbol=symbol_obj.symbol,
        is_active=symbol_obj.is_active,
        created_at=symbol_obj.created_at.isoformat(),
        last_price=symbol_obj.last_price,
        last_price_at=symbol_obj.last_price_at.isoformat() if symbol_obj.last_price_at else None,
    )


@app.get("/plot/prices", response_class=HTMLResponse)
async def plot_prices(
    db: DatabaseManager = Depends(get_db),
) -> str:
    """Generate an interactive Plotly HTML chart of all price data.

    Displays closing prices for all registered symbols on a log-scale Y-axis,
    allowing symbols with different price ranges to be visualized together.

    Args:
        db: Database manager instance (injected via dependency).

    Returns:
        str: Complete HTML page with embedded Plotly chart.
    """
    # Fetch all price data joined with symbol names
    query = """
        SELECT 
            s.symbol,
            p.timestamp,
            p.close
        FROM price_data p
        JOIN symbols s ON p.symbol_id = s.id
        WHERE s.is_active = 1
        ORDER BY s.symbol, p.timestamp
    """
    rows = await db.fetch_all(query)

    if not rows:
        return "<html><body><h1>No price data available</h1></body></html>"

    # Organize data by symbol
    symbol_data: dict[str, dict] = {}
    for row in rows:
        symbol = row["symbol"]
        if symbol not in symbol_data:
            symbol_data[symbol] = {"timestamps": [], "prices": []}

        # Convert timestamp (ms) to datetime
        timestamp_ms = row["timestamp"]
        dt = datetime.fromtimestamp(timestamp_ms / 1000)

        symbol_data[symbol]["timestamps"].append(dt)
        symbol_data[symbol]["prices"].append(row["close"])

    # Create traces for each symbol
    traces = []
    for symbol, data in sorted(symbol_data.items()):
        trace = go.Scatter(
            x=data["timestamps"],
            y=data["prices"],
            mode="lines",
            name=symbol,
            connectgaps=False,  # Don't connect lines across gaps
        )
        traces.append(trace)

    # Create layout with log scale Y-axis
    layout = go.Layout(
        title="Historical Price Data (Log Scale)",
        xaxis=dict(
            title="Time",
            showgrid=True,
        ),
        yaxis=dict(
            title="Price (USD)",
            type="log",  # Logarithmic scale
            showgrid=True,
            tickformat=".2f",
        ),
        hovermode="x unified",
        legend=dict(
            title="Symbols",
            orientation="v",
            yanchor="top",
            y=1,
            xanchor="left",
            x=1.02,
        ),
        template="plotly",
        height=700,
    )

    # Create figure
    fig = go.Figure(data=traces, layout=layout)

    # Generate plotly div (just the chart, no full HTML)
    html_content = plot(
        fig,
        output_type="div",
        include_plotlyjs="cdn",
    )

    # Wrap in complete HTML document
    full_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Trading System - Price Chart</title>
    <style>
        body {{
            margin: 0;
            padding: 20px;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background-color: #f5f5f5;
        }}
        h1 {{
            text-align: center;
            color: #333;
            margin-bottom: 10px;
        }}
        .subtitle {{
            text-align: center;
            color: #666;
            font-size: 14px;
            margin-bottom: 20px;
        }}
        .chart-container {{
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            padding: 20px;
        }}
        .info {{
            margin-top: 20px;
            padding: 15px;
            background: #f9f9f9;
            border-radius: 4px;
            font-size: 13px;
            color: #555;
        }}
        .info ul {{
            margin: 5px 0;
            padding-left: 20px;
        }}
    </style>
</head>
<body>
    <h1>📈 Price Chart</h1>
    <div class="subtitle">
        {len(symbol_data)} symbol(s) | Log scale Y-axis | 
        {len(rows):,} data points
    </div>
    <div class="chart-container">
        {html_content}
    </div>
    <div class="info">
        <strong>💡 Tips:</strong>
        <ul>
            <li>Click legend items to show/hide symbols</li>
            <li>Drag to zoom, double-click to reset</li>
            <li>Hover for exact values</li>
            <li>Log scale allows comparing % moves across different price ranges</li>
        </ul>
    </div>
</body>
</html>"""

    return full_html
