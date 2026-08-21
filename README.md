# ORB Strength Score Engine (OSSE)

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111+-green.svg)](https://fastapi.tiangolo.com/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.36+-red.svg)](https://streamlit.io/)

A quantitative decision engine and statistical confidence filter for **Opening Range Breakout (ORB)** setups on the **NIFTY 50** index.

The OSSE engine evaluates intraday 1-minute market structure against 13 statistical features, higher-timeframe daily trends, Central Pivot Range (CPR), and IV Rank — outputting a unified score (0–100) and actionable option strategy recommendations with delta-targeted strike selection.

---

## 🌟 Key Features

### Core Scoring Engine
- **13-Factor ORB Strength Score (0–100):** Dynamic multi-factor scoring across Relative Volume, ADX Trend Strength, ATR Expansion, VWAP Distance, EMA Alignment, ORB Width, Gap %, Candle Efficiency, Trend Consistency, Opening Momentum, HTF Alignment, IV Rank, and CPR Width.
- **Market Regime Detection:** Automatically classifies sessions and re-weights scoring features accordingly.
- **Config-Driven Weights:** All feature weights and normalization bounds live in `config/scoring_rules.yaml` — no hardcoded values in Python.

### Options Analytics
- **Strike Selection Logic (`decision.py`):** Option legs and strategy recommendations are built directly by the `DecisionEngine` using delta-targeted / moneyness heuristics with a synthetic Black-Scholes backdrop.
- **Expiry Handling:** Weekly / Next-Weekly / Monthly expiry metadata resolved inline.
- **Risk-Aware Recommendations:** Maps OSSE score + IV Rank + regime into explicit trade strategies.

### Risk Management
- Position sizing guidance and per-trade risk limits are encoded in `DecisionEngine` recommendations. Backtest metrics include Win Rate %, MFE, MAE, and Max Drawdown.

### Backtest Engine
- **Multi-Day Swing Backtester:** Replays historical sessions using real OHLCV data. Measures Win Rate %, Avg MFE (Maximum Favorable Excursion), Avg MAE (Maximum Adverse Excursion), and MFE/MAE Ratio.
- **Simulation Engine (`simulation.py`):** Generates trade simulations for strategy stress-testing.
- **Metrics (`metrics.py`):** Computes Win Rate, Max Drawdown, and per-month P&L breakdowns.
- **Available backtest scripts:** `scripts/run_30d_backtest.py`, `scripts/run_1y_backtest.py`, `scripts/run_2y_full_rules_backtest.py`.

### Data Pipeline
- **DataCollector (`collector.py`):** Fetches 1-min OHLCV + India VIX (`^INDIAVIX`) + daily CPR context from the three supported sources (see **Data Sources** below).
- **Spot-quote fetcher (`DataCollector.fetch_spot_quote`):** Delayed NIFTY 50 spot price via yfinance (`^NSEI`, ~15-min Yahoo delay) with a jugaad-data `NSELive` near-real-time fallback; exposed as `GET /api/v1/quote` and the `scripts/fetch_spot_price.py` polling CLI.
- **DataValidator (`validator.py`):** Validates intraday and daily context data before scoring; returns structured error decisions for invalid inputs.
- **DatabaseManager (`db.py`):** Persists scores, features, and monitor snapshots to local Parquet files under `data/`. Optional PostgreSQL backend (`scripts/init_osse_db.sql`).

---

## 📡 Data Sources

OSSE sources all market data from **three sanctioned channels only** — there is no live broker feed and no web scraping:

1. **Internal datasets (offline, authoritative).** Local Parquet files shipped with the repository — e.g. `data/nifty_1min_august_2026.parquet` and `data/nifty_15min.parquet`. These are used first, with no network required.
2. **Y Finance (`yfinance`).** The primary network source for 1-minute OHLCV, daily history, and India VIX.
3. **jugaad-data.** A fallback source for Indian-equity / index daily history.

> **Removed:** The previous DhanHQ API integration and all browser / web-fetch collectors (Kimi WebBridge, Chrome DevTools, `DhanMCP`) have been fully removed. OSSE no longer depends on any broker subscription or headless-browser scraping. The engine runs entirely on Y Finance, jugaad-data, and the bundled internal datasets.

---

## 🛠️ Architecture

```
Data Sources
  ├── Internal Datasets (Parquet / CSV) ──┐
  ├── Y Finance (yfinance) ───────────────┼──► DataCollector
  └── jugaad-data (Indian markets) ───────┘
                                            │
                                       IndicatorEngine (TA-Lib)
                                            │
                                       FeatureEngineering (13 features)
                                            │
                                       ORBBuilder
                                            │
                                  ScoringEngine (0-100)
                                            │
                                  DecisionEngine
                                  + StrategyVariantSelector
                                  + RiskManager
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
TA-Lib is a required dependency. On Windows you can install a pre-built wheel matching your Python version (e.g. `TA_Lib-0.4.28-cp311-cp311-win_amd64.whl`) or use `pip install TA-Lib` if a compatible binary is available.

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
The engine runs without any credentials — it sources data from Y Finance, jugaad-data, and the bundled internal datasets. Only fill in the optional PostgreSQL block if you want to use the Postgres backend instead of local Parquet.

```env
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

Set `include_explanation: true` to attach a natural-language narrative generated by the template-based chart explainer (`analysis/ai_chart_explainer.py`).

### `GET /api/v1/quote`
Delayed NIFTY 50 spot quote. Sources, in order: yfinance (`^NSEI`, ~15-minute Yahoo delay) → jugaad-data `NSELive` (near-real-time NSE feed). Returns `503` when both sources fail, `422` for unsupported symbols. Every response carries the `source` and quote `timestamp` (ISO-8601, Asia/Kolkata) so consumers know the data's freshness.

**Query params:** `symbol` (optional, default `^NSEI`; only `^NSEI` / `NIFTY` aliases accepted).

**Response:**
```json
{
  "symbol": "^NSEI",
  "price": 24850.35,
  "change": 123.45,
  "percent_change": 0.5,
  "open": 24750.0,
  "high": 24900.0,
  "low": 24700.0,
  "previous_close": 24726.9,
  "timestamp": "2026-08-21T11:00:00+05:30",
  "source": "yfinance",
  "delayed": true
}
```

`previous_close`, `change`, and `percent_change` are omitted when the previous close cannot be resolved. For continuous polling, use the CLI (keep intervals ≥ 30s — NSE blocks aggressive polling):

```bash
PYTHONPATH=src python scripts/fetch_spot_price.py --interval 60 --source auto
```

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

Backtest results are saved to CSV files. Metrics include Win Rate %, MFE, MAE, MFE/MAE Ratio, and Max Drawdown. Use `scripts/fetch_history_job.py` to pre-fetch and cache 1-minute data for the dashboard's dynamic simulation.

---

## ⚙️ Configuration

### `config/scoring_rules.yaml`
Controls feature weights (total = 120, normalised to 100%), normalization bounds, and market regime weight overrides.

Key sections:
- `features` — per-feature `weight` and `normalization` bounds
- `regimes` — per-regime feature weight overrides (`TRENDING`, `RANGING`, `GAP`)

---

## 📂 Project Structure

```
orb-nifty/
├── .env.example                 # Credential template (Postgres only)
├── .gitignore
├── AGENT.md                     # Agent instructions
├── README.md
├── requirements.txt
├── run_dashboard.py             # Dashboard launcher (auto-detects venv)
├── config/
│   └── scoring_rules.yaml       # Feature weights & regime overrides
├── data/                       # Internal datasets (Parquet) + local DB
├── docs/
│   └── osse_architecture.md
├── scripts/                     # Backtest / history-fetch harnesses
│   ├── run_30d_backtest.py
│   ├── run_1y_backtest.py
│   ├── run_2y_full_rules_backtest.py
│   ├── fetch_history_job.py
│   ├── analyze_reversals_and_trades.py
│   ├── audit_intraday_vs_daily.py
│   ├── audit_zeros.py
│   ├── compare_3_rules_backtest.py
│   ├── compare_rules_2_and_3.py
│   ├── test_rules_breakdown.py
│   └── init_osse_db.sql         # PostgreSQL schema
├── src/osse/
│   ├── __init__.py
│   ├── api/app.py               # FastAPI REST API (/api/v1/score)
│   ├── config_validator.py      # YAML config validation at startup
│   ├── dashboard/app.py         # Streamlit dashboard
│   ├── analysis/
│   │   ├── ai_chart_explainer.py
│   │   └── correlation.py
│   ├── backtest/
│   │   ├── engine.py
│   │   ├── metrics.py
│   │   └── simulation.py
│   ├── data/
│   │   ├── collector.py         # yfinance + jugaad + internal dataset fetcher
│   │   ├── db.py                # Parquet / PostgreSQL persistence
│   │   └── validator.py         # Data validation before scoring
│   ├── engine/
│   │   ├── decision.py          # DecisionEngine + pros/cons generator
│   │   ├── normalizer.py        # Bounded normalization
│   │   └── scorer.py            # ScoringEngine (13 features → 0-100)
│   ├── features/
│   │   ├── engineering.py       # 13-feature extraction
│   │   ├── indicators.py        # TA-Lib wrapper (EMA, ADX, ATR, RSI, VWAP)
│   │   ├── orb_builder.py       # 09:15–09:30 ORB stats
│   │   └── volume_profile.py    # 70% Value Area (POC, VAH, VAL, HVN, LVN)
│   └── reporting/
│       └── generator.py         # JSON + CSV report exporter
└── tests/                       # PyTest test modules
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

Test modules cover: engine scoring, normalizer, feature extraction, ORB builder, options pricing, strike selector, backtest metrics, data collection, API endpoints, config validator, and AI chart explainer.

---

## 🔧 Troubleshooting

- **No data for a date / empty intraday frame.** OSSE first checks the bundled internal datasets (which only cover certain windows, e.g. August 2026 NIFTY). If the requested date is outside those windows it falls back to Y Finance — ensure you have network access and that `yfinance` is installed. For Indian-market daily history, `jugaad-data` is used as a secondary fallback.
- **India VIX unavailable.** `^INDIAVIX` is fetched via Y Finance and falls back to a neutral 15.0 / 50% IV Rank if unreachable.
- **TA-Lib import errors.** Install the matching pre-built wheel (`TA_Lib-0.4.28-cp311-cp311-win_amd64.whl`) on Windows, or the C library + pip package on Linux/macOS.
- **PostgreSQL connection errors.** The engine defaults to local Parquet storage. Only set the `DB_*` env vars if you have provisioned the schema via `scripts/init_osse_db.sql`.
- **Module not found (`No module named 'osse'`).** Run commands with `PYTHONPATH=src` (or activate `venv/`, which the launchers configure automatically).

---

## 🔐 Security

- **Never commit real credentials.** Use `.env` (already in `.gitignore`). `.env.example` contains only placeholder values.
- All secrets (PostgreSQL) are read via `os.environ.get(...)` — no hardcoded secrets anywhere in the codebase.
- The engine performs **no live trading** and performs **no web scraping or broker API calls**. Data sourcing is limited to Y Finance, jugaad-data, and bundled internal datasets.

---

## 📄 License

This project is licensed under the MIT License.
