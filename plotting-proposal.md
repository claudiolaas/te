# Plotting Feature Proposal

## Overview

Add visualization capabilities to the trading system for price data analysis, strategy performance monitoring, and debugging. This enhances the system's usability for traders and developers.

---

## Goals

1. **Price Visualization**: View historical and real-time price data
2. **Strategy Analysis**: Visualize trading signals and positions
3. **Performance Metrics**: Track PnL, drawdown, and other key metrics
4. **Debugging Aid**: Help developers understand strategy behavior
5. **Export Capabilities**: Save charts for reporting and sharing

---

## Proposed Features

### Phase 1: Core Price Charts (MVP)

#### 1.1 Symbol Price Chart API
```
GET /charts/symbols/{symbol}
```
Generate OHLCV candlestick charts for any registered symbol.

**Query Parameters:**
- `timeframe`: 1m, 5m, 15m, 1h, 1d (default: 1m)
- `start_time`: ISO datetime
- `end_time`: ISO datetime
- `format`: png, svg, html (default: png)

**Use Cases:**
- Quick price check via browser
- Generate charts for external reports
- Debugging price data quality

#### 1.2 Multi-Symbol Comparison
```
GET /charts/compare
```
Overlay multiple symbols on the same chart for correlation analysis.

**Query Parameters:**
- `symbols`: Comma-separated list (e.g., "BTC/USDT,ETH/USDT")
- `normalized`: Boolean (normalize to percentage change)

---

### Phase 2: Strategy Visualization (Post-MVP)

#### 2.1 Strategy Performance Chart
```
GET /charts/strategies/{strategy_id}/performance
```

**Visual Elements:**
- Price line (candlestick or line)
- Entry/exit markers (buy/sell signals)
- Position holding periods (colored background)
- Equity curve (PnL over time)

#### 2.2 Strategy Metrics Dashboard
```
GET /charts/strategies/{strategy_id}/metrics
```

**Metrics to Display:**
- Total Return
- Sharpe Ratio
- Maximum Drawdown
- Win Rate
- Profit Factor
- Average Trade Duration

---

### Phase 3: Real-Time Monitoring (Advanced)

#### 3.1 WebSocket Live Chart
```
WS /ws/charts/{symbol}
```
Real-time streaming chart updates as new prices arrive.

#### 3.2 System Health Dashboard
```
GET /charts/system/health
```
Visual metrics for system operations:
- Heartbeat latency over time
- API request success/failure rates
- Database query performance
- Memory/CPU usage (if available)

---

## Technical Options

### Option A: Matplotlib (Recommended for MVP)

**Pros:**
- Mature, stable library
- Excellent static image generation
- Wide format support (PNG, SVG, PDF)
- Good for server-side rendering

**Cons:**
- Limited interactivity
- Static output only

**Best For:** API endpoints generating chart images

### Option B: Plotly

**Pros:**
- Interactive charts (zoom, pan, hover tooltips)
- Can generate both static and HTML outputs
- Modern visualization capabilities

**Cons:**
- Larger dependency footprint
- HTML output requires serving JS files

**Best For:** Interactive dashboards and rich HTML reports

### Option C: Lightweight SVG Generation

**Pros:**
- No heavy dependencies
- Fast rendering
- Easy to embed in web pages

**Cons:**
- Limited chart types
- Manual implementation required

**Best For:** Simple sparklines and mini-charts

---

## Recommended Architecture

```
┌─────────────────┐
│  REST API       │  /charts/* endpoints
│  (FastAPI)      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  ChartService   │  Orchestrates chart generation
└────────┬────────┘
         │
    ┌────┴────┐
    ▼         ▼
┌─────────┐ ┌─────────────┐
│ Matplotlib│ │  Plotly    │  (Pluggable backends)
└────┬────┘ └──────┬──────┘
     │             │
     ▼             ▼
┌─────────┐    ┌──────────┐
│  PNG    │    │  HTML    │
│  SVG    │    │          │
└─────────┘    └──────────┘
```

---

## API Design

### Chart Generation Endpoint

```python
@app.get("/charts/symbols/{symbol:path}")
async def get_symbol_chart(
    symbol: str,
    timeframe: str = "1m",
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    chart_type: ChartType = ChartType.CANDLESTICK,
    format: ChartFormat = ChartFormat.PNG,
    width: int = 1200,
    height: int = 600,
    db: DatabaseManager = Depends(get_db),
) -> Response:
    """Generate a price chart for a symbol."""
```

### Response Types

**PNG/SVG:** Binary image data with appropriate Content-Type

**HTML:** Interactive Plotly HTML page

**JSON:** Chart data for client-side rendering
```json
{
  "symbol": "BTC/USDT",
  "timeframe": "1m",
  "data": {
    "timestamps": [...],
    "open": [...],
    "high": [...],
    "low": [...],
    "close": [...],
    "volume": [...]
  }
}
```

---

## Implementation Plan

### Phase 1: Core Charts (1-2 days)

1. **Add matplotlib dependency**
   ```toml
   [project.optional-dependencies]
   plotting = ["matplotlib>=3.8.0"]
   ```

2. **Create ChartService**
   - Data fetching from PriceRepository
   - Chart generation with matplotlib
   - Caching (optional)

3. **Add API endpoints**
   - `GET /charts/symbols/{symbol}`
   - `GET /charts/symbols/{symbol}/sparkline` (mini chart)

4. **Tests**
   - Unit tests for chart generation
   - API integration tests

### Phase 2: Enhanced Features (2-3 days)

1. **Add Plotly support** (optional)
2. **Multi-symbol comparison**
3. **Technical indicators overlay** (SMA, EMA)
4. **Volume subplot**

### Phase 3: Advanced Visualization (Future)

1. **Strategy performance charts**
2. **Real-time WebSocket streaming**
3. **Dashboard UI**

---

## Example Usage

### CLI/Browser Quick Check
```bash
# View last 24 hours of BTC price
curl http://localhost:8000/charts/symbols/BTC%2FUSDT > btc_chart.png
open btc_chart.png
```

### In Strategy Development
```python
# Python script to analyze strategy performance
import requests

response = requests.get(
    "http://localhost:8000/charts/strategies/my_strategy/performance",
    params={"start_time": "2024-01-01", "end_time": "2024-01-31"}
)
with open("strategy_performance.png", "wb") as f:
    f.write(response.content)
```

### Embedded in External Dashboard
```html
<img src="http://localhost:8000/charts/symbols/BTC%2FUSDT?width=400&height=200" 
     alt="BTC Price">
```

---

## Open Questions

1. **Caching**: Should generated charts be cached? For how long?
2. **Rate Limiting**: Should chart generation be rate-limited?
3. **Storage**: Save generated charts to disk or generate on-the-fly?
4. **Real-time**: How important is real-time charting vs. historical?

---

## Recommendation

**Start with Phase 1 (Matplotlib-based)**:
- Minimal dependencies
- Fast to implement
- Covers 80% of use cases
- Easy to test and maintain

**Skip for now**:
- Real-time WebSocket charts (complexity vs. value)
- Interactive HTML dashboards (can use Swagger UI for basic exploration)

---

## Estimated Effort

| Phase | Tasks | Est. Time |
|-------|-------|-----------|
| Phase 1 | Core chart API | 1-2 days |
| Phase 2 | Enhanced features | 2-3 days |
| Phase 3 | Real-time + UI | 3-5 days |

**Total MVP**: 1-2 days for basic chart generation
