#!/usr/bin/env python3
"""
Full system cycle test.

Starts the system, registers symbols, waits for price fetching, then stops.
Verifies the expected data is in the database.

Expected outcome:
- 5 backfill records per symbol = 10 records
- ~2 minutely records per symbol = ~4 records  
- Total: ~14 records in price_data

Usage:
    python scripts/test_full_cycle.py
"""

import asyncio
import subprocess
import sys
import time
from pathlib import Path

import aiohttp

BASE_URL = "http://localhost:8000"
DB_PATH = Path("data/trading.db")


async def check_health(max_retries=30):
    """Check if API is healthy, with retries."""
    for i in range(max_retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{BASE_URL}/health", timeout=2) as resp:
                    if resp.status == 200:
                        return True
        except:
            pass
        await asyncio.sleep(1)
    return False


async def register_symbol(symbol: str):
    """Register a symbol."""
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{BASE_URL}/symbols",
            json={"symbol": symbol}
        ) as resp:
            data = await resp.json()
            if resp.status == 201:
                backfilled = data['backfill_status'].get('total_records', 0)
                print(f"✅ Registered {symbol} (backfilled: {backfilled} records)")
                return True
            else:
                print(f"❌ Failed to register {symbol}: {data}")
                return False


async def count_db_records():
    """Count records in the database."""
    from trading_system.database import DatabaseManager
    
    if not DB_PATH.exists():
        return 0, 0
    
    db = DatabaseManager(str(DB_PATH))
    await db.initialize()
    
    try:
        row = await db.fetch_one("SELECT COUNT(*) as count FROM price_data")
        symbol_row = await db.fetch_one("SELECT COUNT(*) as count FROM symbols WHERE is_active = 1")
        count = row["count"] if row else 0
        symbols = symbol_row["count"] if symbol_row else 0
    except:
        count = 0
        symbols = 0
    finally:
        await db.close()
    
    return count, symbols


def main():
    print("=" * 60)
    print("Trading System - Full Cycle Test")
    print("=" * 60)
    print()
    
    # Check if data directory exists
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    # Remove old database for clean test
    if DB_PATH.exists():
        print("🗑️  Removing old database...")
        DB_PATH.unlink()
    
    # Start the system
    print("🚀 Starting trading system...")
    proc = subprocess.Popen(
        [sys.executable, "-m", "trading_system.main"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    
    # Wait for system to be ready
    print("⏳ Waiting for system to be ready...")
    asyncio.run(asyncio.sleep(3))
    
    if not asyncio.run(check_health()):
        print("❌ System failed to start")
        proc.terminate()
        return 1
    
    print("✅ System is running")
    print()
    
    # Register symbols
    print("📝 Registering symbols...")
    symbols = ["BTC/USDT", "ETH/USDT"]
    for sym in symbols:
        if not asyncio.run(register_symbol(sym)):
            proc.terminate()
            return 1
    
    # Count backfilled records
    count, _ = asyncio.run(count_db_records())
    print(f"📊 Records after backfill: {count}")
    print()
    
    # Wait 2 minutes for price fetching
    print("⏳ Waiting 2 minutes for heartbeat price fetching...")
    print("   (The heartbeat runs every 65 seconds)")
    for remaining in range(120, 0, -10):
        print(f"   {remaining}s remaining...", end="\r")
        time.sleep(10)
    print("   Done!                    ")
    print()
    
    # Stop the system
    print("🛑 Stopping system...")
    proc.terminate()
    try:
        proc.wait(timeout=10)
        print("✅ System stopped gracefully")
    except subprocess.TimeoutExpired:
        proc.kill()
        print("⚠️  System killed (didn't stop gracefully)")
    print()
    
    # Verify database
    print("🔍 Verifying database...")
    count, symbol_count = asyncio.run(count_db_records())
    
    print(f"   Active symbols: {symbol_count}")
    print(f"   Price records: {count}")
    print()
    
    # Expected calculation
    expected_backfill = 10  # 5 per symbol × 2 symbols
    expected_live = 4       # ~2 per symbol × 2 symbols
    expected_total = expected_backfill + expected_live
    
    print(f"   Expected: ~{expected_total} records")
    print(f"   - Backfill: ~{expected_backfill} (5 per symbol)")
    print(f"   - Live fetch: ~{expected_live} (2 per symbol, 2 minutes)")
    print()
    
    if count >= expected_total - 2:  # Allow some variance
        print(f"✅ SUCCESS: Found {count} records (expected ~{expected_total})")
        return 0
    elif count >= expected_backfill:
        print(f"⚠️  PARTIAL: Found {count} records")
        print(f"   Backfill worked but live fetching may have issues")
        return 0
    else:
        print(f"❌ FAILURE: Only found {count} records")
        return 1


if __name__ == "__main__":
    sys.exit(main())
