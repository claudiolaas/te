"""
Binance API Research Script

Experiments with CCXT to understand:
- Klines/OHLCV data fetching (for backfill)
- Current price fetching
- Wallet/balance inspection
- Rate limits and pagination
- Testnet vs live differences
"""

import asyncio
import os
from datetime import UTC, datetime

import ccxt.async_support as ccxt
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")


async def test_exchange_setup():
    """Test basic exchange connection and markets."""
    print("=" * 60)
    print("1. EXCHANGE SETUP & MARKETS")
    print("=" * 60)

    exchange = ccxt.binance({
        'apiKey': API_KEY,
        'secret': API_SECRET,
        'enableRateLimit': True,
        'options': {
            'defaultType': 'spot',  # spot trading
        }
    })

    try:
        await exchange.load_markets()
        print(f"✓ Exchange loaded: {exchange.name}")
        print(f"✓ Markets loaded: {len(exchange.markets)} pairs")
        print(f"✓ Time: {exchange.iso8601(exchange.milliseconds())}")

        # Show some popular pairs
        popular = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT']
        print("\nPopular pairs available:")
        for symbol in popular:
            if symbol in exchange.markets:
                market = exchange.markets[symbol]
                print(f"  - {symbol}: min_amount={market['limits']['amount']['min']}, "
                      f"precision={market['precision']['price']}")

        return exchange
    except Exception as e:
        print(f"✗ Error: {e}")
        return None


async def test_fetch_ohlcv(exchange):
    """Test fetching OHLCV (klines) data - critical for backfill."""
    print("\n" + "=" * 60)
    print("2. FETCH OHLCV (KLINES) - BACKFILL DATA")
    print("=" * 60)

    symbol = 'BTC/USDT'
    timeframe = '1m'  # 1 minute candles
    limit = 10  # Last 10 candles

    try:
        # Fetch recent candles
        ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        print(f"✓ Fetched {len(ohlcv)} candles for {symbol}")
        print("\nFormat: [timestamp, open, high, low, close, volume]")
        print("\nLast 5 candles:")
        for candle in ohlcv[-5:]:
            ts = datetime.fromtimestamp(candle[0] / 1000, tz=UTC)
            print(f"  {ts.isoformat()} | O: {candle[1]:.2f} | H: {candle[2]:.2f} | "
                  f"L: {candle[3]:.2f} | C: {candle[4]:.2f} | V: {candle[5]:.4f}")

        # Test since parameter (for backfill from specific time)
        print("\n--- Backfill simulation (last 5 minutes) ---")
        now = exchange.milliseconds()
        five_min_ago = now - (5 * 60 * 1000)  # 5 minutes in ms

        ohlcv_backfill = await exchange.fetch_ohlcv(symbol, timeframe, since=five_min_ago)
        print(f"✓ Backfill fetch: {len(ohlcv_backfill)} candles since 5 min ago")

        # Demonstrate the candle timestamp alignment
        if ohlcv_backfill:
            first_candle_ts = ohlcv_backfill[0][0]
            first_candle_dt = datetime.fromtimestamp(first_candle_ts / 1000, tz=UTC)
            print(f"  First candle timestamp: {first_candle_dt.isoformat()}")
            print("  Candle interval: 1 minute")

        return ohlcv
    except Exception as e:
        print(f"✗ Error fetching OHLCV: {e}")
        return None


async def test_fetch_ticker(exchange):
    """Test fetching current price/ticker."""
    print("\n" + "=" * 60)
    print("3. FETCH CURRENT PRICE (TICKER)")
    print("=" * 60)

    symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']

    try:
        # Single ticker
        ticker = await exchange.fetch_ticker('BTC/USDT')
        print("✓ BTC/USDT ticker:")
        print(f"  Last: {ticker['last']}")
        print(f"  Bid: {ticker['bid']}, Ask: {ticker['ask']}")
        print(f"  24h Volume: {ticker['quoteVolume']}")
        print(f"  Timestamp: {exchange.iso8601(ticker['timestamp'])}")

        # Multiple tickers (more efficient)
        print("\n✓ Multiple tickers:")
        tickers = await exchange.fetch_tickers(symbols)
        for symbol in symbols:
            if symbol in tickers:
                print(f"  {symbol}: {tickers[symbol]['last']}")

        return tickers
    except Exception as e:
        print(f"✗ Error fetching tickers: {e}")
        return None


async def test_wallet_balance(exchange):
    """Test fetching wallet/balance information."""
    print("\n" + "=" * 60)
    print("4. WALLET & BALANCE INSPECTION")
    print("=" * 60)

    try:
        balance = await exchange.fetch_balance()
        print("✓ Balance fetched")
        print("\nNon-zero balances:")

        total_value = 0
        for currency, amounts in balance['total'].items():
            if amounts and amounts > 0:
                free = balance['free'].get(currency, 0)
                used = balance['used'].get(currency, 0)
                print(f"  {currency}: total={amounts:.6f}, free={free:.6f}, used={used:.6f}")

                # Rough USD estimate for major coins
                if currency == 'USDT':
                    total_value += amounts
                elif currency == 'BTC':
                    total_value += amounts * 100000  # rough price
                elif currency == 'ETH':
                    total_value += amounts * 3000

        print(f"\n  Info timestamp: {balance.get('timestamp')}")

        return balance
    except Exception as e:
        print(f"✗ Error fetching balance: {e}")
        print("  (This is expected if using testnet or no balance)")
        return None


async def test_rate_limits(exchange):
    """Test and display rate limit information."""
    print("\n" + "=" * 60)
    print("5. RATE LIMITS")
    print("=" * 60)

    print("Exchange rate limit settings:")
    print(f"  enableRateLimit: {exchange.enableRateLimit}")
    print(f"  rateLimit: {exchange.rateLimit} ms between requests")

    # Make multiple rapid requests to test rate limiting
    print("\nMaking 5 rapid OHLCV requests to test rate limiting...")
    symbol = 'BTC/USDT'
    start_time = exchange.milliseconds()

    for i in range(5):
        try:
            ohlcv = await exchange.fetch_ohlcv(symbol, '1m', limit=1)
            elapsed = exchange.milliseconds() - start_time
            print(f"  Request {i+1}: OK (elapsed: {elapsed}ms)")
        except Exception as e:
            print(f"  Request {i+1}: Error - {e}")

    total_elapsed = exchange.milliseconds() - start_time
    print(f"\nTotal time for 5 requests: {total_elapsed}ms")
    print(f"Average per request: {total_elapsed / 5:.0f}ms")


async def test_backfill_design(exchange):
    """Simulate the backfill operation design."""
    print("\n" + "=" * 60)
    print("6. BACKFILL DESIGN SIMULATION")
    print("=" * 60)

    symbol = 'BTC/USDT'
    backfill_minutes = 5

    print(f"Scenario: New symbol '{symbol}' registered")
    print(f"Backfill requirement: {backfill_minutes} minutes of historical data")

    # Simulate registration time
    now = exchange.milliseconds()
    now_dt = datetime.fromtimestamp(now / 1000, tz=UTC)
    print(f"\nCurrent time: {now_dt.isoformat()}")

    # Calculate backfill window
    # We want candles for: [now-5min, now-4min, now-3min, now-2min, now-1min]
    # Plus current minute (which may not be closed yet)
    backfill_start = now - (backfill_minutes * 60 * 1000)
    backfill_start_dt = datetime.fromtimestamp(backfill_start / 1000, tz=UTC)

    print(f"Backfill window: {backfill_start_dt.isoformat()} to {now_dt.isoformat()}")

    # Fetch the backfill data
    print(f"\nFetching {backfill_minutes} minutes of 1m candles...")
    ohlcv = await exchange.fetch_ohlcv(symbol, '1m', since=backfill_start, limit=backfill_minutes + 1)

    print(f"✓ Received {len(ohlcv)} candles")

    # Analyze what we got
    if ohlcv:
        print("\nCandle timestamps (UTC):")
        for candle in ohlcv:
            ts = candle[0]
            dt = datetime.fromtimestamp(ts / 1000, tz=UTC)
            close = candle[4]
            print(f"  {dt.strftime('%H:%M:%S')} | close: {close:.2f}")

        # Check for gaps
        if len(ohlcv) >= 2:
            expected_interval = 60 * 1000  # 1 minute in ms
            gaps = []
            for i in range(1, len(ohlcv)):
                diff = ohlcv[i][0] - ohlcv[i-1][0]
                if diff != expected_interval:
                    gaps.append((i, diff))

            if gaps:
                print("\n⚠ Gaps detected in data:")
                for idx, diff in gaps:
                    print(f"  Between candle {idx-1} and {idx}: {diff/1000:.0f}s gap")
            else:
                print("\n✓ No gaps detected in data")

    # Next heartbeat fetch timing
    next_minute = ((now // 60000) + 1) * 60000
    next_minute_dt = datetime.fromtimestamp(next_minute / 1000, tz=UTC)
    print(f"\nNext heartbeat should fetch from: {next_minute_dt.isoformat()}")

    return ohlcv


async def test_order_placement(exchange):
    """Test order placement (on testnet if available)."""
    print("\n" + "=" * 60)
    print("7. ORDER PLACEMENT (TEST)")
    print("=" * 60)

    print("Note: Testing order placement requires:")
    print("  - Sufficient balance")
    print("  - Using testnet for safety")
    print("\nSkipping actual order placement in research script.")
    print("\nOrder structure for market buy (example):")
    print("""
    order = await exchange.create_market_buy_order(
        symbol='BTC/USDT',
        amount=0.001  # BTC amount
    )
    # Returns:
    # {
    #     'id': '123456789',
    #     'symbol': 'BTC/USDT',
    #     'type': 'market',
    #     'side': 'buy',
    #     'amount': 0.001,
    #     'price': None,  # market order
    #     'cost': 45.23,  # total USDT spent
    #     'filled': 0.001,
    #     'status': 'closed',
    #     ...
    # }
    """)


async def main():
    """Run all experiments."""
    print("\n" + "=" * 60)
    print("BINANCE API RESEARCH WITH CCXT")
    print("=" * 60)
    print(f"Time: {datetime.now(UTC).isoformat()}")

    if not API_KEY or not API_SECRET:
        print("\n✗ ERROR: API keys not found in environment!")
        return

    exchange = await test_exchange_setup()
    if not exchange:
        return

    try:
        await test_fetch_ohlcv(exchange)
        await test_fetch_ticker(exchange)
        await test_wallet_balance(exchange)
        await test_rate_limits(exchange)
        await test_backfill_design(exchange)
        await test_order_placement(exchange)

        print("\n" + "=" * 60)
        print("RESEARCH COMPLETE")
        print("=" * 60)

    finally:
        await exchange.close()


if __name__ == "__main__":
    asyncio.run(main())
