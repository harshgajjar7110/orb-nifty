# GEMINI.MD: AI Collaboration Guide

This document provides essential context for AI models interacting with this project. Adhering to these guidelines will ensure consistency and maintain code quality.

## 1. Project Overview & Purpose

* **Primary Goal:** The Opening Range Breakout Strength Score Engine (OSSE) is a quantitative decision and filtering engine for Indian market equity indices (NIFTY 50, BANKNIFTY, SENSEX, FINNIFTY) and equities. It calculates a statistical strength score (0–100) based on 15-minute ORB (09:15-09:30 AM), technical indicators (CPR, VWAP, EMA, RSI, ATR), IV Rank / VIX, and provides option strategy recommendations (Credit/Debit Spreads, Iron Condors, Straddles) along with strike selection rules.
* **Business Domain:** Algorithmic & Quantitative Financial Trading (Options Trading & Intraday/Swing Breakout Analysis for Indian Financial Markets).

## 2. Core Technologies & Stack

* **Languages:** Python 3.11
* **Frameworks & Runtimes:** Streamlit (Interactive Dashboard UI), FastAPI & Uvicorn (REST API), PyTest (Testing).
* **Databases:** Parquet local persistence under `data/`, Optional PostgreSQL (`scripts/init_osse_db.sql` schema provided).
* **Key Libraries/Dependencies:** pandas, numpy, TA-Lib (`TA_Lib-0.4.28-cp311-cp311-win_amd64.whl`), scipy (Black-Scholes pricing), yfinance (OHLCV / VIX), jugaad-data (Indian-market daily history), plotly, pyyaml, python-dotenv.
* **Package Manager(s):** `pip` (Virtual Environment in `venv/`).

## 3. Architectural Patterns

* **Overall Architecture:** Modular Unidirectional Pipeline Architecture. Data flows sequentially through dedicated stages without shared mutable state: Data Collection -> Feature Engineering -> Feature Normalization -> Scorer Engine -> Strategy Decision Engine -> Options Strike & Synthetic Pricing Engine -> Dashboard / REST API / Backtest Engine.
* **Directory Structure Philosophy:**
    * `/src/osse`: Primary source package containing all engine submodules (`data`, `features`, `engine`, `options`, `backtest`, `analysis`, `api`, `dashboard`, `reporting`).
    * `/config`: External YAML configuration files (`scoring_rules.yaml`, `strike_rules.yaml`) controlling scoring weights, normalization bounds, and strike selection logic.
    * `/scripts`: Research, backtesting, database initialization, and verification harnesses.
    * `/tests`: PyTest test suite covering engine logic, indicators, data pipelines, API endpoints, and options pricing.
    * `/docs`: System architecture documentation and data flow diagrams.

## 4. Coding Conventions & Style Guide

* **Formatting:** PEP 8 standard for Python code. 4-space indentation, clean docstrings, snake_case for functions and variables.
* **Naming Conventions:**
    * `variables`, `functions`, `modules`: `snake_case` (e.g., `calculate_orb_range`, `strike_selector`)
    * `classes`: `PascalCase` (e.g., `ORBScorer`, `BlackScholesEngine`)
    * `constants`: `ALL_CAPS` (e.g., `DEFAULT_NIFTY_LOT_SIZE`)
    * `config files`: `kebab-case` / `snake_case` `.yaml`
* **API Design:** RESTful API via FastAPI with Pydantic payload validation (`POST /api/v1/score`). Returns JSON response containing numeric OSSE scores, feature contributions, and strategy recommendations.
* **Error Handling:** Graceful fallback mechanism. Market data is sourced from bundled internal datasets, then `yfinance`, then `jugaad-data`; a missing network source never breaks execution.

## 5. Key Files & Entrypoints

* **Main Entrypoint(s):**
    * `run_dashboard.py` - Launch Streamlit UI (auto-detects virtualenv path and sets `PYTHONPATH`).
    * `src/osse/api/app.py` - FastAPI backend service (`uvicorn osse.api.app:app`).
    * `scripts/run_1y_backtest.py` / `scripts/run_2y_full_rules_backtest.py` - Backtesting execution scripts.
* **Configuration:**
    * `config/scoring_rules.yaml` - Feature weights, indicator parameters, normalization limits.
    * `config/strike_rules.yaml` - Strike offset rules, lot sizes, moneyness thresholds.
    * `.env` / `.env.example` - Optional PostgreSQL credentials and environment settings.
* **CI/CD Pipeline:** Local standard PyTest suite (`python -m pytest`).

## 6. Development & Testing Workflow

* **Local Development Environment:**
    1. Python 3.11 virtual environment in `./venv`.
    2. Set environment variable `PYTHONPATH=src`.
    3. Run Streamlit dashboard using `python run_dashboard.py` (opens at `http://localhost:8501`).
* **Testing:** Run all test cases via `PYTHONPATH=src python -m pytest`. Single test execution: `PYTHONPATH=src python -m pytest tests/test_engine.py`.
* **CI/CD Process:** Automated unit test verification across engine normalization, option pricing math, and feature computation.

## 7. Specific Instructions for AI Collaboration

* **Config-Driven Architecture:** All scoring weights and normalization parameters MUST remain in `config/scoring_rules.yaml` and `config/strike_rules.yaml`. Do NOT hardcode scoring weights inside Python source code.
* **Normalization Separation:** Raw metrics must only be normalized inside `src/osse/engine/normalizer.py`. `scorer.py` must only consume normalized values (0–100).
* **Data Sourcing:** All market data comes from sanctioned sources only — bundled internal datasets, `yfinance`, and `jugaad-data`. There is no broker API dependency and no web scraping. Do not reintroduce DhanHQ or browser/web-fetch collectors.
* **Imports & Module Paths:** Ensure `src` is in the Python path when importing `osse` modules.
