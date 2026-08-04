# OSSE — ORB Strength Score Engine (Base Reference)

## Project Overview

OSSE is a quantitative decision engine that computes an Opening Range Breakout (ORB) strength score (0–100) and strategy recommendations for Indian indices (NIFTY, BANKNIFTY, SENSEX, FINNIFTY) and NSE equities. It is a **statistical confidence filter**, not an automated trader — it never places live trades.

The engine evaluates intraday 1-minute market structure against 13 statistical features, higher-timeframe daily trends, Central Pivot Range (CPR), IV Rank, Delta Exposure (DEX), Gamma Exposure (GEX), and Volume Profile — outputting a unified score and actionable option strategy recommendations with delta-targeted strike selection.

## Architecture

Unidirectional pipeline — each stage feeds the next; no shared mutable state between stages:

1. **Data** (`src/osse/data/`): `collector.py` fetches 1-min OHLCV + India VIX + CPR. Falls back from DhanHQ to `yfinance` on missing credentials or rate limits. `db.py` persists to Parquet under `data/`; PostgreSQL is optional.
2. **Features** (`src/osse/features/`): `indicators.py` (TA-Lib) → `orb_builder.py` (09:15–09:30 ORB stats) → `engineering.py` (13 features, IV Rank, regime detection).
3. **Engine** (`src/osse/engine/`): `normalizer.py` → `scorer.py` (weighted sum) → `decision.py` (strategy mapping).
4. **Options** (`src/osse/options/`): `strike_selector.py` (5 variants), `synthetic_pricing.py` (Black-Scholes), `expiry_manager.py`.
5. **Outputs**: `api/app.py` (FastAPI), `dashboard/app.py` (Streamlit), `backtest/` (multi-day swing simulation).

### Unified Score

Unified score = 40% OSSE + 60% Confluence (DEX + Volume Profile confluence).

## Key Invariants

- **Scoring weights are config-driven.** All feature weights and normalization bounds live in `config/scoring_rules.yaml`; strike/lot rules in `config/strike_rules.yaml`. Change tuning there, not in code.
- **Never mix raw and normalized values in the scorer.** Normalization happens only in `normalizer.py`; `scorer.py` consumes only normalized values.
- **Secrets from env only.** `dhan_client_id` / `dhan_access_token` via `os.environ.get`. Empty credentials silently fall back to `yfinance`.
- **The live monitor never trades.** It extracts option-chain data, computes DEX/VP/confluence signals, and surfaces alerts. All execution remains manual.
- **Monitor polling respects market hours** (Mon–Fri 09:15–15:30 IST) unless `DHAN_MONITOR_IGNORE_HOURS=1` is set.
- **The Exposure Agent uses WebBridge exclusively.** `DhanMCPCollector` (Playwright) is for historical data only and is not a fallback in the Exposure Agent. If the WebBridge daemon is unreachable, the agent returns an `ERROR` immediately.
- **`scripts/` are throwaway research/backtest harnesses.** CSVs at repo root are their output artifacts, not source data.

## Project Structure

```
orb-nifty/
├── config/
│   ├── scoring_rules.yaml       # Feature weights, normalization bounds, regime overrides
│   ├── strike_rules.yaml        # Strike selection rules, lot sizes, exposure-driven rules
│   ├── chrome_targets.yaml      # Chrome DevTools extraction targets
│   └── webbridge_targets.yaml   # WebBridge page targets
├── docs/
│   ├── osse_architecture.md     # Architecture diagram and module definitions
│   └── PRD_DEX_VP_OSSE_v3_consistent.md
├── scripts/                     # Throwaway research/backtest harnesses
│   ├── run_exposure_agent.py
│   ├── run_30d_backtest.py
│   ├── run_1y_backtest.py
│   ├── run_2y_full_rules_backtest.py
│   ├── fetch_history_job.py
│   ├── init_osse_db.sql
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

## Configuration

### `config/scoring_rules.yaml`

Controls feature weights (total = 120, normalised to 100%), normalization bounds, market regime weight overrides, and the unified score split (40% OSSE / 60% Confluence).

13 features with weights:
| Feature | Weight | Normalization |
|---|---|---|
| relative_volume | 20 | bounded (0.8–2.5) |
| adx | 15 | bounded (10–40) |
| vwap_distance | 15 | bounded (0.0–0.4) |
| orb_width | 15 | bounded (0.1–0.6) |
| htf_alignment | 15 | bounded (0.0–1.0) |
| atr_expansion | 10 | bounded (0.2–1.5) |
| opening_momentum | 10 | bounded (0.0–0.5) |
| ema_alignment | 10 | bounded (0.0–1.0) |
| iv_rank | 10 | bounded (10–80) |
| gap_percent | 5 | bounded (0.0–1.0) |
| candle_efficiency | 5 | bounded (0.0–0.8) |
| trend_consistency | 5 | bounded (0.0–0.5) |
| cpr_width | 5 | bounded (0.6–0.05, inverse) |

Regime overrides: `TRENDING`, `RANGING`, `GAP` — per-regime feature weight adjustments.

Confluence weights: `dex_wall_at_vp_boundary` (40), `poc_near_dex_flip` (30), `vah_val_near_dex` (20), `volume_confirmation` (10).

### `config/strike_rules.yaml`

Controls strike selection per symbol and strategy. Key sections:
- `symbols` — per-index `step_size`, `lot_size`, `default_otm_steps`
- `delta_targets` — short/long leg delta bounds for credit spreads, debit spreads, straddles
- `premium_targets` — premium % of spot bounds for credit spreads
- `dex_vp_strategy_rules` — Value Area %, risk limits, confluence tier thresholds
- `exposure_driven_rules` — GEX/DEX aligned variant config and priority ordering for support/resistance anchors

### `config/chrome_targets.yaml` / `config/webbridge_targets.yaml`

Chrome DevTools MCP and Kimi WebBridge page targets and extraction selectors for the Dhan dashboard.

## Scoring Pipeline Detail

### Feature Engineering (`engineering.py`)

Extracts 13 raw features at the ORB close time (09:29 for 15-min ORB):
1. ORB Width % — from `orb_builder.py`
2. Relative Volume — ORB volume vs expected volume fraction
3. VWAP Distance — % distance from VWAP at ORB close
4. EMA Alignment — 1.0 if Close > EMA20 > EMA50 (or reverse), 0.5 if partial
5. ATR Expansion — ORB width / ATR_14
6. ADX — from TA-Lib at ORB close
7. Gap % — |Open_09:15 - Prev Close| / Prev Close
8. Candle Efficiency — net body / sum of ranges
9. Trend Consistency — |RSI - 50| / 50
10. Opening Momentum — |Close - Open_09:15| / Open_09:15
11. IV Rank — from daily context
12. CPR Width — from daily context
13. HTF Alignment — 1.0 if intraday trend aligns with daily EMA20, 0.5 if at VWAP, 0.0 if conflicting

### Regime Detection (`engineering.py:detect_regime`)

- `GAP` — gap_percent > 0.6
- `DIRECTIONAL_BREAKOUT` — ADX >= 22 and htf_alignment == 1.0
- `PREMIUM_SELL_RANGE` — ADX < 20 and IV Rank >= 40
- `TRENDING` — ADX > 25
- `RANGING` — ADX < 20
- `NEUTRAL` — fallback

### Normalization (`normalizer.py`)

Methods: `bounded` (linear scale to 0–1 using min_val/max_val from YAML, supports inverse scaling when min_val > max_val), `min_max`, `rolling_z` (Z-score mapped from [-3,3] to [0,1]), `historical_percentile` (quartile-based linear interpolation).

### Scoring (`scorer.py`)

Weighted sum: `score = Sum(weight * normalized_feature) / Sum(weights) * 100`. Regime overrides merge into feature rules before normalization.

### Decision (`decision.py`)

Score tiers:
- ≥75: Exceptional / TRADE
- 65–74: High / TRADE
- 55–64: Tradable / REDUCED SIZE
- 45–54: Weak / NO TRADE
- <45: Reject / NO TRADE

Strategy recommendation maps score + IV Rank + regime to: Directional Credit Spread, Directional Debit Spread, Iron Condor / Short Strangle, Short Straddle / Iron Fly, or No Trade.

### Confluence Engine (`confluence.py`)

Combines DEX walls/flips with Volume Profile (POC, VAH, VAL, HVN, LVN) into a Confluence Score (0–100). Alignment rules R1–R6 provide strike guidance. Unified Score = 40% OSSE + 60% Confluence.

### Strike Selection (`strike_selector.py`)

5 variants:
1. `MONEYNESS` — fixed OTM steps from ATM
2. `DELTA_TARGETED` — legs anchored to target delta (default)
3. `OI_WALL` — positioned at OI walls
4. `EXPECTED_MOVE` / `PREMIUM_TARGETED — strikes at 1-SD expected move boundary or premium % of spot
5. `CPR_PIVOT` — anchored to CPR boundaries
6. `GEX_DEX_ALIGNED` — anchored to live exposure structural levels (WebBridge-driven)

## Key Technologies

- **Python 3.11** — primary language
- **TA-Lib** — technical indicators (with pandas/numpy fallback)
- **FastAPI** — REST API (`POST /api/v1/score`, `/api/v1/dex`, `/api/v1/volume-profile`, `/api/v1/confluence`, `/api/v1/strategy-variants`, `/api/v1/explain`, `/api/v1/exposure-strikes`)
- **Streamlit** — dashboard (http://localhost:8501)
- **PyTest** — 18 test modules, no `conftest.py` or `pytest.ini`
- **pandas, numpy, scipy, pyyaml, python-dotenv** — core dependencies
- **dhanhq** — Dhan API SDK (optional, falls back to yfinance)
- **Parquet** — local persistence under `data/`
- **PostgreSQL** — optional backend (`scripts/init_osse_db.sql`)

## Setup

- No `setup.py`/`pyproject` — package lives under `src/`. Set `PYTHONPATH=src` for imports, or activate `venv/`.
- TA-Lib on Windows: pre-built wheel at `TA_Lib-0.4.28-cp311-cp311-win_amd64.whl` (Python 3.11 only).
- Credentials: copy `.env.example` to `.env` and fill in values. Empty `dhan_client_id` / `dhan_access_token` silently falls back to `yfinance`.

## Commands

```bash
# Run all tests
PYTHONPATH=src python -m pytest

# Run a single test module
PYTHONPATH=src python -m pytest tests/test_engine.py -v

# Streamlit dashboard
python run_dashboard.py          # http://localhost:8501

# FastAPI server
PYTHONPATH=src python -m uvicorn osse.api.app:app --host 0.0.0.0 --port 8000

# Live monitor (single poll)
PYTHONPATH=src python -m osse.monitoring.scheduler --once --ignore-hours

# Live monitor (background poll)
PYTHONPATH=src python -m osse.monitoring.scheduler --symbols NIFTY,BANKNIFTY --interval 180

# Backtests
PYTHONPATH=src python scripts/run_1y_backtest.py
PYTHONPATH=src python scripts/run_30d_backtest.py
```

## Coding Conventions

- PEP 8 standard for Python code
- 4-space indentation
- `snake_case` for functions and variables
- `PascalCase` for classes
- `ALL_CAPS` for constants
- Config files: `kebab-case` / `snake_case` `.yaml`
- No hardcoded scoring weights in Python — all weights in YAML
- Secrets from env only via `os.environ.get`
- No `setup.py`/`pyproject` — `PYTHONPATH=src` required

## Testing

- 18 PyTest modules in `tests/` — no `conftest.py` or `pytest.ini`
- Tests rely on `PYTHONPATH=src`
- Run a single test: `PYTHONPATH=src python -m pytest tests/test_engine.py::test_feature_normalizer`

## Existing Instruction Files

- `AGENTS.md` (plural) — Kilo instruction file, most up-to-date commands including scheduler
- `AGENT.md` (singular) — older Kilo instruction file
- `CLAUDE.md` — Claude Code guidance, concise architecture and invariants
- `GEMINI.md` — Gemini collaboration guide, includes coding conventions
- `base.md` — this file, distilled foundational reference