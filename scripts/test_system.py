#!/usr/bin/env python3
"""End-to-end system test script."""

import argparse
import asyncio
import time

import aiohttp

BASE_URL = "http://localhost:8000"


async def check_health():
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{BASE_URL}/health", timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(f"✅ API healthy: {data}")
                    return True
        except Exception as e:
            print(f"❌ Cannot connect: {e}")
        return False


async def register_symbol(symbol: str):
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{BASE_URL}/symbols", json={"symbol": symbol}) as resp:
            data = await resp.json()
            if resp.status == 201:
                print(f"✅ Registered {symbol}")
                return True
            elif resp.status == 400:
                print(f"ℹ️  {symbol} already registered")
                return True
            else:
                print(f"❌ Failed: {data}")
                return False


async def list_symbols():
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{BASE_URL}/symbols") as resp:
            data = await resp.json()
            print(f"📊 {data['count']} symbols:")
            for s in data['symbols']:
                price = s.get('last_price')
                price_str = f"${price:,.2f}" if price else "N/A"
                print(f"   - {s['symbol']}: {price_str}")
            return data['symbols']


async def wait_for_prices(symbols, timeout=120):
    print(f"\n⏳ Waiting for prices (timeout: {timeout}s)...")
    start = time.time()
    while time.time() - start < timeout:
        async with aiohttp.ClientSession() as session:
            all_have = True
            for sym in symbols:
                enc = sym.replace("/", "%2F")
                async with session.get(f"{BASE_URL}/symbols/{enc}") as r:
                    d = await r.json()
                    if d.get('last_price') is None:
                        all_have = False
                        break
            if all_have:
                print(f"✅ Got prices in {time.time()-start:.1f}s")
                return True
        await asyncio.sleep(10)
    return False


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", default=["BTC/USDT", "ETH/USDT"])
    parser.add_argument("--wait", action="store_true", help="Wait for price fetching")
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()

    print("=" * 50)
    print("Trading System E2E Test")
    print("=" * 50)

    if not await check_health():
        print("\nStart the server first: python trading_system/main.py")
        return 1

    print("\n2️⃣ Registering symbols...")
    for s in args.symbols:
        await register_symbol(s)

    print("\n3️⃣ Listing symbols...")
    symbols = await list_symbols()

    if args.wait:
        print("\n4️⃣ Waiting for prices...")
        await wait_for_prices([s['symbol'] for s in symbols], args.timeout)
        print("\n5️⃣ Updated list:")
        await list_symbols()

    print(f"\n📈 Chart: {BASE_URL}/plot/prices")
    return 0


if __name__ == "__main__":
    asyncio.run(main())
