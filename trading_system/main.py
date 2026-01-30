"""Main entry point for the trading system.

Starts the heartbeat coordinator and REST API server concurrently,
with graceful shutdown handling.
"""

import asyncio
import signal
import sys
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI

from trading_system.api import app as api_app
from trading_system.clients import BinanceClient
from trading_system.config import Settings
from trading_system.database import DatabaseManager
from trading_system.heartbeat.coordinator import HeartbeatCoordinator
from trading_system.logger import log_manager


class TradingSystem:
    """Main trading system that orchestrates all components.

    Manages the lifecycle of:
    - Database connection
    - Binance API client
    - Heartbeat coordinator (price fetching)
    - REST API server

    Usage:
        system = TradingSystem()
        await system.start()
        # System is running...
        await system.stop()
    """

    def __init__(self) -> None:
        """Initialize trading system components."""
        self.settings = Settings()
        self.db: DatabaseManager | None = None
        self.binance_client: BinanceClient | None = None
        self.coordinator: HeartbeatCoordinator | None = None
        self.api_server: asyncio.Task | None = None
        self._shutdown_event: asyncio.Event | None = None
        self._running = False
        self._shutting_down = False

    async def start(self) -> None:
        """Start all system components.

        Starts components in order:
        1. Database
        2. Binance client
        3. Heartbeat coordinator
        4. API server

        Sets up signal handlers for graceful shutdown.
        """
        if self._running:
            return

        print("🚀 Starting Trading System...")
        self._shutdown_event = asyncio.Event()

        # Setup signal handlers
        self._setup_signal_handlers()

        # Initialize logging
        print("📝 Initializing logging...")
        log_manager.initialize(self.settings)

        # Initialize database
        print("📦 Initializing database...")
        self.db = DatabaseManager(self.settings.db_path)
        await self.db.initialize()

        # Initialize Binance client
        print("💱 Initializing Binance client...")
        self.binance_client = BinanceClient(self.settings)
        await self.binance_client.initialize()

        # Initialize heartbeat coordinator
        print("💓 Starting heartbeat coordinator...")
        self.coordinator = HeartbeatCoordinator(
            self.binance_client,
            self.db,
            self.settings
        )
        await self.coordinator.start()

        # Start API server
        print("🌐 Starting API server on http://127.0.0.1:8000")
        config = uvicorn.Config(
            api_app,
            host="0.0.0.0",
            port=8000,
            log_level="info",
        )
        server = uvicorn.Server(config)

        # Run server in background task
        self.api_server = asyncio.create_task(server.serve())

        self._running = True
        print("✅ Trading System is running!")
        print("   - API: http://127.0.0.1:8000")
        print("   - Health: http://127.0.0.1:8000/health")
        print("   - Docs: http://127.0.0.1:8000/docs")
        print("\nPress Ctrl+C to shutdown gracefully")

        # Wait for shutdown signal
        await self._shutdown_event.wait()

        # Stop everything
        await self.stop()

    async def stop(self) -> None:
        """Stop all system components gracefully."""
        if not self._running or self._shutting_down:
            return

        self._shutting_down = True
        print("\n🛑 Shutting down Trading System...")

        # Stop API server with timeout
        if self.api_server and not self.api_server.done():
            print("🌐 Stopping API server...")
            self.api_server.cancel()
            try:
                await asyncio.wait_for(self.api_server, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        # Stop heartbeat coordinator
        if self.coordinator:
            print("💓 Stopping heartbeat coordinator...")
            try:
                await asyncio.wait_for(self.coordinator.stop(), timeout=5.0)
            except asyncio.TimeoutError:
                print("   ⚠️  Coordinator stop timed out")

        # Close Binance client
        if self.binance_client:
            print("💱 Closing Binance client...")
            try:
                await asyncio.wait_for(self.binance_client.close(), timeout=5.0)
            except asyncio.TimeoutError:
                print("   ⚠️  Binance client close timed out")

        # Close database
        if self.db:
            print("📦 Closing database...")
            try:
                await asyncio.wait_for(self.db.close(), timeout=5.0)
            except asyncio.TimeoutError:
                print("   ⚠️  Database close timed out")

        self._running = False
        self._shutting_down = False
        print("✅ Trading System shutdown complete")

    def _setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown."""
        self._signal_received = False

        def signal_handler(sig, frame):
            """Handle shutdown signals (only process first signal)."""
            if self._signal_received:
                # Ignore subsequent signals
                return
            
            self._signal_received = True
            print(f"\n📡 Received signal {sig}, initiating shutdown...")
            print("   (Press Ctrl+C again to force exit if stuck)")
            if self._shutdown_event:
                self._shutdown_event.set()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    async def __aenter__(self) -> "TradingSystem":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.stop()


async def main() -> None:
    """Main entry point."""
    system = TradingSystem()

    try:
        await system.start()
    except KeyboardInterrupt:
        print("\n⚠️ Interrupted by user")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        sys.exit(1)
    finally:
        await system.stop()


if __name__ == "__main__":
    asyncio.run(main())
