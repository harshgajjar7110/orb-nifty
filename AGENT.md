# AGENTS.md

This file provides guidance to AI agents (including Kimi Code) when working with code in this repository.

## Project Overview

OSSE (ORB Strength Score Engine) is a quantitative decision engine that computes an Opening Range Breakout strength score (0–100) plus strategy recommendations for Indian indices (NIFTY, BANKNIFTY, SENSEX, FINNIFTY) and NSE equities. It is a statistical confidence **filter** for option-selling and swing strategies — it deliberately does NOT place automated live trades.

## Commands

The package lives under `src/` with no `setup.py`/`pyproject` — set `PYTHONPATH=src` (or activate the repo `venv`, which already has it importable) for anything importing `osse`.

```bash
# Run tests (single test: append tests/test_engine.py::test_feature_normalizer)
PYTHONPATH=src python -m pytest

# Streamlit dashboard (auto-detects venv python, sets PYTHONPATH itself)
python run_dashboard.py          # http://localhost:8501

# FastAPI server
PYTHONPATH=src python -m uvicorn osse.api.app:app --host 0.0.0.0 --port 8000

# Backtests / audits (ad-hoc research scripts, each writes CSVs to repo root)
PYTHONPATH=src python scripts/run_1y_backtest.py

# Dhan option-chain live monitor (single poll or background scheduler)
PYTHONPATH=src python src/osse/monitoring/scheduler.py --once --ignore-hours
PYTHONPATH=src python src/osse/monitoring/scheduler.py --symbols NIFTY,BANKNIFTY --interval 180
```

Note: TA-Lib on Windows installs from the checked-in wheel `TA_Lib-0.4.28-cp311-cp311-win_amd64.whl` (Python 3.11 only).

## Architecture

Unidirectional pipeline — each stage feeds the next; there is no shared mutable state between stages:

1. **Data** (`src/osse/data/`): `collector.py` fetches 1-min OHLCV, India VIX (`^INDIAVIX`), and daily CPR context. Data source falls back from DhanHQ to `yfinance` on rate limits or missing credentials. `db.py` persists scores/features to Parquet under `data/`; PostgreSQL is optional (`scripts/init_osse_db.sql`).
2. **Features** (`src/osse/features/`): `indicators.py` (TA-Lib: EMA 20/50/200, ATR, VWAP, RSI, ADX, BBands) → `orb_builder.py` (isolates the 09:15–09:30 window: ORB high/low, width, candle efficiency) → `engineering.py` (rolling stats, IV Rank/Percentile from 1y VIX, higher-timeframe alignment vs daily 20 EMA, regime detection).
3. **Engine** (`src/osse/engine/`): `normalizer.py` scales raw features → `scorer.py` applies weighted sum → `decision.py` maps score + IV Rank + regime to a strategy (credit spread, debit spread, iron condor, straddle, or NO TRADE).
4. **Options** (`src/osse/options/`): `strike_selector.py` (step/lot sizes from `config/strike_rules.yaml`), `synthetic_pricing.py` (Black-Scholes), `expiry_manager.py`.
5. **Outputs**: `api/app.py` (FastAPI, `POST /api/v1/score`), `dashboard/app.py` (Streamlit), `backtest/` (multi-day swing simulation with Win Rate, MFE/MAE metrics).

## Key Invariants

- **Scoring weights are config-driven.** All feature weights and normalization bounds live in `config/scoring_rules.yaml`; strike/lot rules in `config/strike_rules.yaml`. Change tuning there, not in code.
- **Never mix raw and normalized values in the scorer.** Normalization happens only in `normalizer.py` per the `normalization:` mode declared in the YAML (`bounded`, `min_max`, etc.); `scorer.py` consumes only normalized values.
- **Secrets come from env only** — `dhan_client_id` / `dhan_access_token` via `os.environ.get` (`.env` loaded with dotenv). Empty credentials must silently fall back to yfinance.
- **Monitor credentials are env-only too.** Dhan web login (`DHAN_CLIENT_ID`, `DHAN_PASSWORD`) is used only by the Node Playwright scripts; credentials are never persisted to the repo.
- **The live monitor never trades.** It extracts option-chain data, computes DEX/VP/confluence signals, and surfaces alerts in Streamlit. All execution remains manual.
- **Monitor polling respects market hours.** The scheduler only polls during Indian equity hours (Mon–Fri 09:15–15:30 IST) unless `DHAN_MONITOR_IGNORE_HOURS=1` is set.
- **Browser extraction falls back silently.** If Playwright/Dhan web extraction fails or returns invalid data, `DhanMCPCollector` falls back to synthetic option-chain/candle data and logs a warning.
- Scripts in `scripts/` are throwaway research/backtest harnesses; the CSVs at repo root are their output artifacts, not source data.
