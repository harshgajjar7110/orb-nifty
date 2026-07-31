# ORB Strength Score Engine (OSSE)

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-green.svg)](https://fastapi.tiangolo.com/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.36+-red.svg)](https://streamlit.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A quantitative decision engine and statistical confidence filter for **Opening Range Breakout (ORB)** setups on Indian equity markets — **NIFTY 50**, **BANK NIFTY**, **SENSEX**, **FINNIFTY**, and top NSE equities.

The OSSE engine evaluates intraday 1-minute market structure against 13 statistical features, higher-timeframe daily trends, Central Pivot Range (CPR), IV Rank, Delta Exposure (DEX), Gamma Exposure (GEX), and Volume Profile — outputting a unified score (0–100) and actionable option strategy recommendations with delta-targeted strike selection.

---

## 🌟 Key Features

### Core Scoring Engine
- **13-Factor ORB Strength Score (0–100):** Dynamic multi-factor scoring across Relative Volume, ADX Trend Strength, ATR Expansion, VWAP Distance, EMA Alignment, ORB Width, Gap %, Candle Efficiency, Trend Consistency, Opening Momentum, HTF Alignment, IV Rank, and CPR Width.
- **Market Regime Detection:** Automatically classifies sessions as `TRENDING`, `RANGING`, or `GAP` and re-weights scoring features accordingly.
- **Config-Driven Weights:** All feature weights and normalization bounds live in `config/scoring_rules.yaml` — no hardcoded values in Python.

### Greeks & Exposure Layer (DEX / GEX)
- **Delta Exposure (DEX) Calculator:** Aggregates net delta positioning per strike from the live Dhan option chain.
- **Gamma Exposure (GEX) Calculator:** Computes gamma exposure to identify dealer hedging levels, gamma flip points, and peak GEX strikes.
- **Confluence Engine:** Blends DEX wall/flip levels with Volume Profile value area (POC, VAH, VAL, HVN, LVN) into a tiered Confluence Score (0–100). Unified Score = 40% OSSE + 60% Confluence.
- **GEX/DEX Aligned Strike Selection:** Uses live exposure anchors (`put_support`, `call_wall`, `delta_flip`, `gamma_flip`) to place credit spread legs at meaningful structural levels.

### WebBridge & Chrome DevTools Data Collection
- **WebBridge Collector (`webbridge_collector.py`):** Connects to a running Kimi WebBridge daemon (`http://127.0.0.1:10086`) to navigate live Dhan Dext dashboard pages, extract DOM snapshots, and parse option chain / Greeks data without requiring a separate headless browser.
- **Chrome DevTools Collector (`chrome_collector.py`):** Directly drives Chrome via the DevTools Protocol (`chrome-devtools-mcp`) to extract live portfolio, option chain, and chart candle data from the Dhan web app.
- **DOM Parser (`dom_parser.py`):** Parses raw HTML snapshots from the Dhan Dext page into structured DataFrames.
- **Greeks Parser (`greeks_parser.py`):** Extracts per-strike Delta, Gamma, Theta, Vega, and IV from option chain snapshots.
- **DhanMCP Collector (`dhan_mcp.py`):** Playwright/Node.js backed collector using saved auth sessions (JSON storage state) — falls back from WebBridge when the daemon is unavailable.

### Options Analytics
- **Black-Scholes Synthetic Pricing (`synthetic_pricing.py`):** Computes theoretical option prices and Greeks (Delta, Gamma, Vega, Theta) using `scipy`.
- **Delta-Targeted Strike Selector (`strike_selector.py`):** Selects option legs based on configurable delta targets (`config/strike_rules.yaml`). Supports 5 selection variants:
  - `DELTA_TARGETED` — legs anchored to target delta (default)
  - `OTM_STEPS` — fixed OTM steps from ATM
  - `PREMIUM_TARGETED` — legs selected to hit a premium % of spot
  - `GEX_DEX_ALIGNED` — anchored to live exposure structural levels
  - `EXPECTED_MOVE` — strikes placed at 1-SD expected move boundary
- **Expiry Manager (`expiry_manager.py`):** Determines the correct NSE/BSE expiry date for `WEEKLY`, `NEXT_WEEKLY`, or `MONTHLY` options for all supported indices.
- **Strategy Variant Selector (`strategy_variants.py`):** Maps confluence tier + OSSE score + direction into the optimal spread variant with risk-sized position recommendations.

### Risk Management
- **Risk Manager (`risk_manager.py`):** Enforces per-trade and daily capital risk limits (`max_trade_risk_pct`, `max_daily_risk_pct`) and computes position sizing (lots) given capital and max loss per lot.

### Option Strategy Recommendations
Maps OSSE score + IV Rank + regime into explicit trade strategies:
| Score | IV Rank | Strategy |
|---|---|---|
| High (≥70) | High (≥60) | *Directional Credit Spread (Sell Put / Sell Call)* |
| High (≥70) | Low (<40) | *Directional Debit Spread / Long Futures* |
| Moderate (50–70) | High (≥60) | *Iron Condor / Short Strangle* |
| Low (<50) | High (≥60) | *Short Straddle / Iron Fly* |
| Low + High Risk | Any | *No Trade / Avoid* |

### Live Monitoring
- **Insights Generator (`insights.py`):** Produces signal alerts, DEX/GEX regime signals, and Volume Profile confluence alerts for live option-chain snapshots.
- **Monitor Scheduler (`scheduler.py`):** APScheduler-based background poller that runs during Indian market hours (09:15–15:30 IST, Mon–Fri). Configurable symbols and poll interval. Saves snapshots via `DatabaseManager` for the Streamlit dashboard.

### AI-Powered Explanation
- **AI Chart Explainer (`ai_chart_explainer.py`):** Generates natural language reasoning for any market setup, describing the OSSE score, key features, and strategy recommendation in plain English. Accessible via the `/api/v1/explain` endpoint or `POST /api/v1/score` with `include_explanation: true`.

### Dashboard
- **Zero-Scroll Single-Screen Streamlit UI** with animated circular 60-second SVG countdown timer, live 1-minute auto-scanning, side-by-side Pros ✅ / Cons ❌ trade reasoning cards, inline DEX/GEX bar charts, and a Dhan HQ credential panel.
- **Correlation Analyzer (`correlation.py`):** Identifies cross-symbol correlation patterns between NIFTY, BANKNIFTY, and sector indices.

### Backtest Engine
- **Multi-Day Swing Backtester:** Replays historical sessions using real OHLCV data. Measures Win Rate %, Avg MFE (Maximum Favorable Excursion), Avg MAE (Maximum Adverse Excursion), and MFE/MAE Ratio.
- **Simulation Engine (`simulation.py`):** Generates synthetic intraday candle sequences for strategy stress-testing.
- **Metrics (`metrics.py`):** Computes Sharpe Ratio, Max Drawdown, Profit Factor, and per-month P&L breakdowns.
- **Available backtest scripts:** `scripts/run_30d_backtest.py`, `scripts/run_1y_backtest.py`, `scripts/run_2y_full_rules_backtest.py`.

### Data Pipeline
- **DataCollector (`collector.py`):** Fetches 1-min OHLCV + India VIX (`^INDIAVIX`) + daily CPR context. Primary source: DhanHQ API → silent fallback to `yfinance` on missing credentials or rate limits.
- **DatabaseManager (`db.py`):** Persists scores, features, and monitor snapshots to local Parquet files under `data/`. Optional PostgreSQL backend (`scripts/init_osse_db.sql`).

---

## 🛠️ Architecture

```
Data Sources
  ├── DhanHQ API / yfinance  ──────► DataCollector
  ├── Chrome DevTools MCP ──────────► ChromeCollector
  └── Kimi WebBridge Daemon ────────► WebBridgeCollector
                                          │
                                     IndicatorEngine (TA-Lib)
                                          │
                                     FeatureEngineering (13 features)
                                          │
                                     ORBBuilder
                                          │
                              ┌─────── ScoringEngine (0-100) ──────────┐
                              │                                         │
                         DEX / GEX                              NormalizerEngine
                         Calculator                                     │
                              │                               DecisionEngine
                         VolumeProfile                        + StrategyVariantSelector
                         Calculator                                     │
                              │                              StrikeSelector (5 variants)
                         ConfluenceEngine                               │
                              │                              ExpiryManager + SyntheticPricing
                         UnifiedScore (0-100)                           │
                              │                              RiskManager
                              └──────────────────────────────────────────┘
                                          │
                       ┌──────────────────┼──────────────────┐
                  FastAPI REST         Streamlit          Backtest
                  API (port 8000)      Dashboard           Engine
                                       (port 8501)
```

---

## 🚀 Quickstart

### 1. Prerequisites
- Python 3.11+
- Virtual environment (`venv`)
- TA-Lib system library (see below)

### 2. Install TA-Lib (Windows)
A pre-built Windows wheel is included in the repo:
```bash
pip install TA_Lib-0.4.28-cp311-cp311-win_amd64.whl
```
On Linux/macOS, install the C library first then `pip install TA-Lib`.

### 3. Clone & Install
```bash
git clone https://github.com/harshgajjar7110/orb-nifty.git
cd orb-nifty

python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
```

### 4. Environment Configuration
```bash
cp .env.example .env
```
Edit `.env` and fill in your values:
```env
# DhanHQ API Credentials (optional — engine falls back to yfinance if empty)
dhan_client_id=YOUR_DHAN_CLIENT_ID
dhan_access_token=YOUR_DHAN_ACCESS_TOKEN

# PostgreSQL (optional — engine uses local Parquet by default)
DB_HOST=localhost
DB_PORT=5432
DB_NAME=osse_db
DB_USER=postgres
DB_PASSWORD=YOUR_DB_PASSWORD

PYTHONPATH=src
```

---

## 🖥️ Running the Application

### 1. Streamlit Dashboard
```bash
python run_dashboard.py
```
Opens at **http://localhost:8501** (or 8502 if port is busy).

### 2. FastAPI REST API
```bash
PYTHONPATH=src uvicorn osse.api.app:app --host 0.0.0.0 --port 8000
```
Interactive API docs: **http://localhost:8000/docs**

### 3. Live Monitor (Background Poller)
```bash
# Poll NIFTY + BANKNIFTY every 3 minutes during market hours
PYTHONPATH=src python -m osse.monitoring.scheduler --symbols NIFTY,BANKNIFTY --interval 180

# Run once and exit (useful for cron)
PYTHONPATH=src python -m osse.monitoring.scheduler --once --ignore-hours
```

---

## 🌐 REST API Reference

All endpoints accept and return JSON.

### `POST /api/v1/score`
Core OSSE score for a symbol + date.

**Request:**
```json
{
  "symbol": "NIFTY",
  "date": "2025-01-15",
  "spot_price": 24317.0,
  "vix": 13.5,
  "include_explanation": false
}
```

**Response:**
```json
{
  "score": 74.3,
  "confidence": "HIGH",
  "decision": "BUY_SIGNAL",
  "regime": "TREND",
  "recommended_strategy": "Directional Credit Spread",
  "pros": ["Strong ADX trend", "VWAP alignment confirmed"],
  "cons": ["Low relative volume"],
  "ai_explanation": ""
}
```

---

### `POST /api/v1/dex`
Delta Exposure (DEX) per strike from the live Dhan option chain.

**Request:** `{ "symbol": "NIFTY", "spot_price": 24317.0, "osse_score": 74.0 }`

---

### `POST /api/v1/volume-profile`
Volume Profile: POC, VAH, VAL, HVN/LVN nodes (70% value area).

**Request:** `{ "symbol": "NIFTY", "spot_price": 24317.0, "osse_score": 74.0 }`

---

### `POST /api/v1/confluence`
Confluence Score + Unified Score from DEX, Volume Profile, and OSSE.

**Request:** `{ "symbol": "NIFTY", "spot_price": 24317.0, "osse_score": 74.0 }`

**Response:**
```json
{
  "symbol": "NIFTY",
  "spot_price": 24317.0,
  "confluence": {
    "confluence_score": 82.0,
    "tier": "TIER1",
    "signals": [...]
  },
  "unified_score": { "unified_score": 79.0, "osse_weight": 0.4, "confluence_weight": 0.6 }
}
```

---

### `POST /api/v1/strategy-variants`
Evaluates active DEX + VP strategy variants with position sizing.

**Request:** `{ "symbol": "NIFTY", "spot_price": 24317.0, "osse_score": 74.0 }`

---

### `POST /api/v1/explain`
Returns a natural-language AI reasoning narrative for the current market setup.

**Request:** `{ "symbol": "NIFTY", "spot_price": 24317.0, "osse_score": 74.0 }`

**Response:** `{ "explanation": "NIFTY is showing a high-conviction ORB breakout setup..." }`

---

### `POST /api/v1/exposure-strikes`
Navigates to the Dhan Dext dashboard via WebBridge, extracts live DEX/GEX, and returns GEX/DEX-aligned strike recommendations.

**Request:**
```json
{
  "url": "https://dext.dhan.co/dashboard",
  "symbol": "NIFTY",
  "direction": "UP",
  "strategy_name": "Directional Credit Spread",
  "variant": "GEX_DEX_ALIGNED",
  "expiry_type": "WEEKLY"
}
```

**Response (excerpt):**
```json
{
  "status": "SUCCESS",
  "collector_used": "webbridge",
  "symbol": "NIFTY",
  "spot_price": 24317.15,
  "delta_exposure": { "total_call": 3443508.36, "total_put": -2814502.27, "ratio": 0.82 },
  "gamma_exposure": { "total_call": 3068860.42, "total_put": -2269369.73, "ratio": 0.74 },
  "strike_recommendation": {
    "variant_used": "GEX_DEX_ALIGNED",
    "legs": [
      { "action": "SELL", "option_type": "PE", "strike": 24450.0 },
      { "action": "BUY",  "option_type": "PE", "strike": 24350.0 }
    ]
  }
}
```

---

## 🤖 Exposure Agent CLI

Fetch live DEX/GEX from Dhan Dext and output GEX/DEX-aligned strikes from the command line.

**Prerequisite:** Kimi WebBridge must be running:
```bash
kimi-webbridge start
```

```bash
python scripts/run_exposure_agent.py \
  --url "https://dext.dhan.co/dashboard" \
  --symbol NIFTY \
  --direction UP \
  --strategy "Directional Credit Spread" \
  --variant GEX_DEX_ALIGNED \
  --expiry WEEKLY \
  --output result.json
```

| Option | Default | Description |
|---|---|---|
| `--url` | `https://dext.dhan.co/dashboard` | Dhan Dext URL |
| `--symbol` | `NIFTY` | `NIFTY`, `BANKNIFTY`, `FINNIFTY`, `SENSEX` |
| `--direction` | `UP` | `UP` (bullish) or `DOWN` (bearish) |
| `--strategy` | `Directional Credit Spread` | Strategy name |
| `--variant` | `GEX_DEX_ALIGNED` | Strike selection variant |
| `--expiry` | `WEEKLY` | `WEEKLY`, `NEXT_WEEKLY`, `MONTHLY` |
| `--daemon-url` | `http://127.0.0.1:10086` | Kimi WebBridge daemon URL |
| `--no-mcp-fallback` | — | Disable DhanMCPCollector fallback |
| `--output` | — | JSON file to write result to |

---

## 📈 Backtesting

```bash
# 30-day backtest
PYTHONPATH=src python scripts/run_30d_backtest.py

# 1-year backtest
PYTHONPATH=src python scripts/run_1y_backtest.py

# 2-year full rules backtest (all 3 scoring rule variants)
PYTHONPATH=src python scripts/run_2y_full_rules_backtest.py
```

Backtest results are saved to CSV files (e.g., `1y_backtest_audit_results.csv`). Metrics include Win Rate %, MFE, MAE, MFE/MAE Ratio, Sharpe Ratio, Max Drawdown, and Profit Factor.

---

## ⚙️ Configuration

### `config/scoring_rules.yaml`
Controls feature weights (total = 120, normalised to 100%), normalization bounds, market regime weight overrides, and the unified score split (40% OSSE / 60% Confluence).

Key sections:
- `features` — per-feature `weight` and `normalization` bounds
- `confluence_weights` — DEX wall, POC, VAH/VAL, and volume confirmation weights
- `unified_score_weights` — `osse_score_weight` / `confluence_score_weight`
- `regimes` — per-regime feature weight overrides (`TRENDING`, `RANGING`, `GAP`)

### `config/strike_rules.yaml`
Controls strike selection per symbol and strategy.

Key sections:
- `symbols` — per-index `step_size`, `lot_size`, `default_otm_steps`
- `delta_targets` — short/long leg delta bounds for credit spreads, debit spreads, straddles
- `premium_targets` — premium % of spot bounds for credit spreads
- `dex_vp_strategy_rules` — Value Area %, risk limits, confluence tier thresholds
- `exposure_driven_rules` — GEX/DEX aligned variant config and priority ordering for support/resistance anchors

### `config/chrome_targets.yaml`
Chrome DevTools MCP targets and CSS selectors for extracting data from the Dhan web app (option chain, portfolio, chart candles).

### `config/webbridge_targets.yaml`
Kimi WebBridge page targets and extraction selectors for the Dhan Dext dashboard.

---

## 📂 Project Structure

```
orb-nifty/
├── config/
│   ├── scoring_rules.yaml       # Feature weights & regime overrides
│   ├── strike_rules.yaml        # Strike selection rules & lot sizes
│   ├── chrome_targets.yaml      # Chrome DevTools extraction targets
│   └── webbridge_targets.yaml   # WebBridge page targets
├── docs/
│   ├── osse_architecture.md
│   └── PRD_DEX_VP_OSSE_v3_consistent.md
├── scripts/
│   ├── run_exposure_agent.py    # CLI for live DEX/GEX strike selection
│   ├── run_30d_backtest.py
│   ├── run_1y_backtest.py
│   ├── run_2y_full_rules_backtest.py
│   ├── fetch_history_job.py
│   ├── init_osse_db.sql         # PostgreSQL schema
│   └── dhan_mcp/                # Node.js Playwright auth + extraction scripts
├── src/osse/
│   ├── api/app.py               # FastAPI REST API (7 endpoints)
│   ├── dashboard/app.py         # Streamlit dashboard
│   ├── agent/
│   │   └── exposure_agent.py    # DhanExposureAgent (WebBridge → strikes)
│   ├── analysis/
│   │   ├── ai_chart_explainer.py
│   │   └── correlation.py
│   ├── backtest/
│   │   ├── engine.py
│   │   ├── metrics.py
│   │   └── simulation.py
│   ├── data/
│   │   ├── collector.py         # Dhan/yfinance OHLCV fetcher
│   │   ├── chrome_collector.py  # Chrome DevTools data collector
│   │   ├── webbridge_collector.py
│   │   ├── dhan_mcp.py          # Playwright-backed Dhan collector
│   │   ├── dom_parser.py
│   │   ├── greeks_parser.py
│   │   ├── db.py                # Parquet / PostgreSQL persistence
│   │   └── validator.py
│   ├── engine/
│   │   ├── scorer.py            # ScoringEngine (13 features → 0-100)
│   │   ├── normalizer.py        # Bounded normalization
│   │   ├── decision.py          # DecisionEngine + pros/cons generator
│   │   ├── confluence.py        # DEX + VP confluence scoring
│   │   ├── strategy_variants.py # Tier-based variant selector
│   │   ├── dex_calculator.py
│   │   ├── gamma_calculator.py
│   │   └── risk_manager.py
│   ├── features/
│   │   ├── indicators.py        # TA-Lib wrapper (EMA, ADX, ATR, RSI, VWAP)
│   │   ├── engineering.py       # 13-feature extraction
│   │   ├── orb_builder.py       # 09:15–09:30 ORB stats
│   │   └── volume_profile.py    # 70% Value Area (POC, VAH, VAL, HVN, LVN)
│   ├── monitoring/
│   │   ├── scheduler.py         # APScheduler market-hours poller
│   │   └── insights.py          # Signal alerts from live chain data
│   ├── options/
│   │   ├── strike_selector.py   # 5-variant delta-targeted selector
│   │   ├── synthetic_pricing.py # Black-Scholes pricing
│   │   └── expiry_manager.py    # NSE/BSE expiry date resolver
│   └── reporting/
│       └── generator.py         # JSON + CSV report exporter
├── tests/                       # 18 PyTest test modules
├── .env.example                 # Credential template
├── requirements.txt
└── run_dashboard.py             # Dashboard launcher (auto-detects venv)
```

---

## 🧪 Running Tests

```bash
PYTHONPATH=src python -m pytest tests/ -q
```

Run a specific test module:
```bash
PYTHONPATH=src python -m pytest tests/test_engine.py -v
```

18 test modules cover: engine scoring, normalizer, feature extraction, ORB builder, options pricing, strike selector, DEX/GEX calculators, confluence, strategy variants, risk manager, backtest metrics, data collection, API endpoints, Chrome collector, Greeks parser, and the exposure agent.

---

## 🔐 Security

- **Never commit real credentials.** Use `.env` (already in `.gitignore`).
- `.env.example` contains only placeholder values — copy it to `.env` and fill in your own keys.
- All API credentials are read via `os.environ.get(...)` — no hardcoded secrets anywhere in the codebase.
- If `dhan_client_id` / `dhan_access_token` are empty, the engine silently falls back to `yfinance`.

---

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
