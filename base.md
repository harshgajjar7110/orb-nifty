# OSSE — ORB Strength Score Engine (Base Reference)

## Project Overview

OSSE is a quantitative decision engine that computes an Opening Range Breakout (ORB) strength score (0–100) and strategy recommendations for the **NIFTY 50** index. It is a **statistical confidence filter**, not an automated trader — it never places live trades.

The engine evaluates intraday 1-minute market structure against 13 statistical features, higher-timeframe daily trends, Central Pivot Range (CPR), IV Rank, Delta Exposure (DEX), Gamma Exposure (GEX), and Volume Profile — outputting a unified score and actionable option strategy recommendations with delta-targeted strike selection.

## Architecture

Unidirectional pipeline — each stage feeds the next; no shared mutable state between stages:

1. **Data** (`src/osse/data/`): `collector.py` fetches 1-min OHLCV + India VIX + CPR from three sanctioned sources — bundled internal datasets (offline), `yfinance`, and `jugaad-data`. `db.py` persists to Parquet under `data/`; PostgreSQL is optional.
2. **Features** (`src/osse/features/`): `indicators.py` (TA-Lib) → `orb_builder.py` (09:15–09:30 ORB stats) → `engineering.py` (13 features, IV Rank, regime detection).
3. **Engine** (`src/osse/engine/`): `normalizer.py` → `scorer.py` (weighted sum) → `decision.py` (strategy mapping).
4. **Options** (`src/osse/options/`): `strike_selector.py` (5 variants), `synthetic_pricing.py` (Black-Scholes), `expiry_manager.py`.
5. **Outputs**: `api/app.py` (FastAPI), `dashboard/app.py` (Streamlit), `backtest/` (multi-day swing simulation).

### Score

The engine outputs the **OSSE Score (0–100)** from the 13 normalized features via `scorer.py`. The earlier DEX / Gamma Exposure (GEX) confluence overlay depended on the removed live option-chain feed (WebBridge / Chrome / DhanMCP) and is no longer part of the shipped engine.

## Key Invariants

- **Scoring weights are config-driven.** All feature weights and normalization bounds live in `config/scoring_rules.yaml`; strike/lot rules in `config/strike_rules.yaml`. Change tuning there, not in code.
- **Never mix raw and normalized values in the scorer.** Normalization happens only in `normalizer.py`; `scorer.py` consumes only normalized values.
- **Secrets from env only.** PostgreSQL credentials are read via `os.environ.get`. There are no broker or scraper credentials — OSSE does not call any broker API or scrape the web.
- **The live monitor never trades.** It extracts option-chain data, computes DEX/VP/confluence signals, and surfaces alerts. All execution remains manual.
- **Monitor polling respects market hours** (Mon–Fri 09:15–15:30 IST) unless `OSSE_IGNORE_HOURS=1` is set.
- **`scripts/` are throwaway research/backtest harnesses.** CSVs at repo root are their output artifacts, not source data.

## Project Structure

```
orb-nifty/
├── config/
│   ├── scoring_rules.yaml       # Feature weights, normalization bounds, regime overrides
│   └── strike_rules.yaml        # Strike selection rules, lot sizes
├── docs/
│   ├── osse_architecture.md     # Architecture diagram and module definitions
│   └── PRD_DEX_VP_OSSE_v3_consistent.md
├── scripts/                     # Throwaway research/backtest harnesses
│   ├── run_30d_backtest.py
│   ├── run_1y_backtest.py
│   ├── run_2y_full_rules_backtest.py
│   ├── fetch_history_job.py
│   └── init_osse_db.sql
├── src/osse/
│   ├── api/app.py               # FastAPI REST API (/api/v1/score)
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
│   │   └── validator.py
│   ├── engine/
│   │   ├── scorer.py            # ScoringEngine (13 features → 0-100)
│   │   ├── normalizer.py        # Bounded normalization
│   │   └── decision.py          # DecisionEngine + pros/cons generator
│   ├── features/
│   │   ├── indicators.py        # TA-Lib wrapper (EMA, ADX, ATR, RSI, VWAP)
│   │   ├── engineering.py       # 13-feature extraction
│   │   ├── orb_builder.py        # 09:15–09:30 ORB stats
│   │   └── volume_profile.py    # 70% Value Area (POC, VAH, VAL, HVN, LVN)
│   └── reporting/
│       └── generator.py         # JSON + CSV report exporter
├── tests/                       # PyTest test modules
├── .env.example                 # Credential template (Postgres only)
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

### Strike Selection & Expiry (`decision.py`)

Strike legs are built by `DecisionEngine` using delta-targeted / moneyness logic with a synthetic Black-Scholes backdrop. Variants supported: `DELTA_TARGETED`, `MONEYNESS`, `OI_WALL`, `EXPECTED_MOVE`, `PREMIUM_TARGETED`, and `CPR_PIVOT`. Weekly / Next-Weekly / Monthly expiry metadata is resolved inline.

> The earlier DEX / Gamma Exposure (GEX) confluence engine and the `GEX_DEX_ALIGNED` variant depended on the live option-chain feed (WebBridge / Chrome / DhanMCP) and were retired with those collectors.

## Key Technologies

- **Python 3.11** — primary language
- **TA-Lib** — technical indicators (with pandas/numpy fallback)
- **FastAPI** — REST API (`POST /api/v1/score`)
- **Streamlit** — dashboard (http://localhost:8501)
- **PyTest** — test modules under `tests/`, no `conftest.py` or `pytest.ini`
- **pandas, numpy, scipy, pyyaml, python-dotenv** — core dependencies
- **yfinance** — primary network data source (OHLCV, VIX)
- **jugaad-data** — Indian-market daily history fallback
- **Parquet** — local persistence under `data/`
- **PostgreSQL** — optional backend (`scripts/init_osse_db.sql`)

## Setup

- No `setup.py`/`pyproject` — package lives under `src/`. Set `PYTHONPATH=src` for imports, or activate `venv/`.
- TA-Lib on Windows: pre-built wheel at `TA_Lib-0.4.28-cp311-cp311-win_amd64.whl` (Python 3.11 only).
- Credentials: copy `.env.example` to `.env`. The engine runs without any credentials — only fill in the optional PostgreSQL block if you want the Postgres backend. There are no broker or scraper credentials.

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

# Delayed spot quote (polling CLI; keep interval >= 30s)
PYTHONPATH=src python scripts/fetch_spot_price.py --symbol NIFTY --interval 180

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