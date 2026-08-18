# DEX + Volume Profile + OSSE Options Strategy Engine
## Production Requirements Document v3.1 — Codebase-Aligned Revision

**Date:** 2026-07-29  
**Author:** OSSE Engineering Team  
**Classification:** Internal — Strategy, Engineering & AI Architecture  
**Status:** Prototype Implemented — Production Hardening Required

---

## 1. Executive Summary

### 1.1 Purpose
Build an options strategy research and recommendation engine that fuses **Delta Exposure (DEX)** positioning data, **Volume Profile 70% Value Area**, and the existing **OSSE (ORB Strength Score Engine)** to generate multi-variant Strangle, Credit Spread, Iron Condor, and Ratio Spread setups for Nifty 50 and Bank Nifty. The system is intentionally a **decision-support and research tool** — it does not place automated live trades.

### 1.2 Core Hypothesis
When DEX positioning aligns with Volume Profile Value Area boundaries, strike selection produces higher expected precision. A future AI reasoning layer can augment this quantitative base by flagging regime anomalies and suggesting adaptive parameter adjustments.

### 1.3 Integration Context
- **Existing Asset:** OSSE repository (FastAPI + Streamlit, Black-Scholes Greeks, strike selection, backtesting). The prototype has core modules implemented and unit-tested.
- **Data Sources:** Bundled internal datasets (offline), `yfinance` (primary network source for OHLCV/VIX), and `jugaad-data` (Indian-market daily history fallback). The DhanHQ REST API and any Chrome DevTools / Kimi WebBridge / DhanMCP browser collectors have been removed.
- **AI Layer:** Currently a template-based chart explainer (`analysis/ai_chart_explainer.py`). External LLM integration is a **Phase 2 roadmap item**, not implemented.
- **Target Users:** Retail option sellers, prop-desk analysts, SEBI-registered RAs, algo-strategy developers.

### 1.4 Current State vs. Vision
| Area | Current State (Prototype) | Target State |
|------|---------------------------|--------------|
| OSSE scoring | Implemented, config-driven weights, unit-tested | Same |
| DEX calculator | Implemented, unit-tested | Same |
| Volume Profile 70% | Implemented, unit-tested | Same |
| Confluence engine | Implemented, but weights **hardcoded**; config exists but is ignored | Make fully config-driven |
| Strategy variants | 5 variants implemented, unit-tested | Add AI calibration layer |
| Risk manager | Implemented (sizing, drawdown, stops, hedges), unit-tested | Wire into live monitoring |
| MCP/Chrome automation | **Removed** — DhanMCPCollector, WebBridge, and Chrome collectors retired | n/a |
| Reasoning overlay | Template explainer only | Integrated reasoning engine |
| Live execution | **Not implemented by design** | One-tap order links + human confirmation |
| PostgreSQL | Schema exists, not used by code | Optional production sink |

### 1.5 Expected Outcome
A deployable **research and recommendation system** that:
1. Ingests market data via `yfinance` / `jugaad-data` and bundled internal datasets.
2. Computes OSSE score, DEX, Volume Profile, and confluence deterministically.
3. Outputs 3–5 strategy variants per session with pre-calculated strikes, Greeks, and risk metrics.
4. Presents results via FastAPI and Streamlit with human-readable explanations.
5. Leaves execution to human confirmation or one-tap broker URLs.

---

## 2. Glossary

| Term | Definition |
|------|------------|
| **DEX** | Delta Exposure — aggregate delta of outstanding options at each strike, indicating dealer directional risk. |
| **Volume Profile 70%** | Price range containing 70% of traded volume; bounded by Value Area High (VAH) and Value Area Low (VAL). |
| **VAH / VAL** | Upper / lower boundary of the 70% volume zone. |
| **POC** | Point of Control — price level with highest traded volume. |
| **HVN / LVN** | High / Low Volume Node — price levels with significant / thin volume accumulation. |
| **Call Wall** | Strike with maximum positive call delta exposure. |
| **Put Support** | Strike with maximum negative put delta exposure. |
| **Delta Flip** | Price level where aggregate net delta changes sign. |
| **Strangle** | Sell OTM call + Sell OTM put; profit from range-bound action, collect theta. |
| **Credit Spread** | Sell ATM/ITM option + Buy further OTM option; capped risk, directional bias. |
| **OSSE** | ORB Strength Score Engine — existing quantitative repository with ORB, CPR, VWAP, EMA, RSI, ATR scoring. |
| **MCP** | Model Context Protocol — open standard for AI-to-tool communication. Planned for future browser automation integration. |
| **Reasoning overlay** | External reasoning engine planned as future strategy brain. Not currently wired. |
| **ORB** | Opening Range Breakout — 15-minute range (9:15–9:30 AM IST) for directional bias. |

---

## 3. System Architecture

### 3.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     LAYER 1: INTERFACE & OUTPUTS                            │
│  ┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐ │
│  │ Streamlit Dashboard │  │ FastAPI REST API    │  │ Telegram Alerts     │ │
│  │ (Existing)          │  │ (Existing)          │  │ (Planned)           │ │
│  └─────────────────────┘  └─────────────────────┘  └─────────────────────┘ │
├─────────────────────────────────────────────────────────────────────────────┤
│                     LAYER 2: DECISION & RESEARCH ENGINE                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐       │
│  │ Decision    │  │ Confluence  │  │ Strategy    │  │ Risk        │       │
│  │ Engine      │  │ Engine      │  │ Variants    │  │ Manager     │       │
│  │             │  │             │  │             │  │             │       │
│  │ • Score →   │  │ • DEX+VP    │  │ • 5 variant │  │ • Sizing    │       │
│  │   decision  │  │   alignment │  │   rules     │  │ • Drawdown  │       │
│  │ • Strategy  │  │ • Unified   │  │ • Strike    │  │ • Stops     │       │
│  │   mapping   │  │   score     │  │   selection │  │ • Hedging   │       │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘       │
├─────────────────────────────────────────────────────────────────────────────┤
│                     LAYER 3: QUANTITATIVE FEATURES                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐       │
│  │ Indicators  │  │ ORB Builder │  │ DEX Calc    │  │ Volume      │       │
│  │ (TA-Lib)    │  │             │  │             │  │ Profile     │       │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘       │
├─────────────────────────────────────────────────────────────────────────────┤
│                     LAYER 4: DATA COLLECTION                                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐   │
│  │ Internal    │  │ yfinance    │  │ jugaad-data │  │ Synthetic       │   │
│  │ datasets    │  │ (Network)   │  │ (Fallback)  │  │ (Offline tests) │   │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Actual Implementation Boundaries

- **No live order execution.** The system generates recommendations, order previews, and (future) one-tap broker URLs. Humans execute.
- **No real-time WebSocket feed.** Data is fetched on demand from `yfinance` and `jugaad-data`, or loaded from bundled internal datasets.
- **No broker API dependency and no web scraping.** The DhanHQ REST integration and the Chrome DevTools / Kimi WebBridge / DhanMCP browser collectors have been fully removed.
- **No external LLM integration.** AI chart explainer is a deterministic string template.
- **Parquet persistence only.** PostgreSQL schema exists but is unused.

---

## 4. Data Collection Layer

### 4.1 Data Sources (Current)

`src/osse/data/collector.py` implements the data path across three sanctioned sources — **internal datasets** (offline, authoritative), **`yfinance`** (primary network source for OHLCV / VIX), and **`jugaad-data`** (Indian-market daily history fallback). The DhanHQ REST integration and the Chrome DevTools / Kimi WebBridge / DhanMCP browser collectors described in earlier revisions have been **removed**.

| Function | Source (priority order) | Fallback | Output |
|----------|------------------------|----------|--------|
| Intraday OHLCV | Internal dataset → `yfinance` | — | 1-min candles |
| India VIX | `^INDIAVIX` via `yfinance` | Neutral default | VIX time-series |
| Daily CPR context | Internal dataset → `yfinance` → `jugaad-data` | Synthetic | CPR pivot, TC, BC |

### 4.2 Synthetic Option Chain

`DataCollector.generate_synthetic_option_chain()` creates a full option chain from spot, VIX, and Black-Scholes for offline development and testing. This is the fallback used in unit tests.

---

## 5. Quantitative Engine

### 5.1 OSSE Scoring (Implemented)

- `features/indicators.py` → EMA 20/50/200, ATR, VWAP, RSI, ADX, BBands.
- `features/orb_builder.py` → 09:15–09:30 ORB high/low/width/candle efficiency.
- `features/engineering.py` → 13 raw features + regime detection.
- `engine/normalizer.py` → bounded, min_max, rolling_z, historical_percentile normalization.
- `engine/scorer.py` → config-driven weighted scoring (0–100) with regime overrides.

### 5.2 DEX Calculator (Implemented)

`engine/dex_calculator.py` computes:
- Net delta per strike from option chain.
- Call Wall, Put Support, Delta Flip.
- DEX clusters (strikes with concentrated delta).

Input: option-chain DataFrame with `ce_delta`, `pe_delta`, `strike_price`.

### 5.3 Volume Profile (Implemented)

`features/volume_profile.py` computes:
- Histogram-based Volume Profile from 1-min candles.
- POC, VAH, VAL (default 70% value area), HVN[], LVN[].

### 5.4 Confluence Engine (Implemented but Partially Hardcoded)

`engine/confluence.py` exists and computes a DEX+VP confluence score. However:
- `config/scoring_rules.yaml` declares `confluence_weights` and `unified_score_weights`.
- The code currently **hardcodes** `40/30/20/10` for confluence components and `0.4/0.6` for the unified score.

**Required fix:** Make `engine/confluence.py` read weights from `config/scoring_rules.yaml`.

### 5.5 Strategy Variants (Implemented)

`engine/strategy_variants.py` implements five DEX/VP-driven variants:

1. **DEX-VP Confluence Strangle** — non-directional theta harvest.
2. **Call Credit Spread** — mildly bearish / range-cap.
3. **Put Credit Spread** — mildly bullish / floor-capture.
4. **Iron Condor** — wide-range premium collection.
5. **LVN Momentum Ratio Spread** — directional asymmetric payoff.

These are selected based on confluence score, DEX/VP alignment, VIX, PCR, and spot position.

### 5.6 Strike Selection (Implemented)

`options/strike_selector.py` supports five selection modes:
- `MONEYNESS`
- `DELTA_TARGETED`
- `OI_WALL`
- `EXPECTED_MOVE`
- `CPR_PIVOT`

Includes expiry handling via `options/expiry_manager.py`, and Black-Scholes Greeks via `options/synthetic_pricing.py`.

**Known inconsistency:** `config/strike_rules.yaml` says NIFTY lot size `75`, BANKNIFTY `30`, but `options/strike_selector.py` fallback says NIFTY `65`, BANKNIFTY `15`. This must be reconciled.

### 5.7 Risk Manager (Implemented)

`engine/risk_manager.py` provides:
- Kelly Criterion and fixed-percent position sizing.
- Drawdown protocols (4 levels).
- Stop rules (hard, time, volatility, DEX shift, AI anomaly placeholder).
- Dynamic hedge calculations.

---

## 6. Decision Engine

### 6.1 Score-to-Decision Mapping

`engine/decision.py` maps OSSE score + IV rank + regime to a recommendation. Current thresholds:

| Score | Decision |
|-------|----------|
| ≥ 75 | STRONG |
| 65–74 | MODERATE |
| 55–64 | WEAK |
| 45–54 | WATCH |
| < 45 | NO TRADE |

**Note:** `docs/osse_architecture.md` documents different thresholds (`90-100 / 80-89 / 70-79 / <70`). The PRD and docs must be aligned to the code.

### 6.2 Strategy Recommendations

Decision engine returns:
- `decision` — TRADE / WATCH / NO TRADE.
- `recommended_action` — e.g., BULL_CALL_SPREAD, IRON_CONDOR.
- `strategy_type` — CREDIT_SPREAD, etc.
- `rationale` / `pros` / `cons`.
- Optional `strike_recommendation` when full context is provided.

---

## 7. API & Dashboard

### 7.1 FastAPI (`src/osse/api/app.py`)

Current endpoints:
- `POST /api/v1/score` — OSSE score.
- `GET /api/v1/dex` — DEX calculation.
- `GET /api/v1/volume-profile` — Volume Profile.
- `GET /api/v1/confluence` — Confluence score (hardcodes `osse_score=70.0`).
- `GET /api/v1/strategy-variants` — Variant selection (uses defaults for several inputs).

**Gaps:** `/api/v1/score` does not pass regime/IV rank/spot price, so it returns a basic decision. `/api/v1/confluence` should accept `osse_score` as a parameter.

### 7.2 Streamlit Dashboard (`src/osse/dashboard/app.py`)

Views:
- Daily Analysis — OSSE score, features, decision.
- DEX + VP Engine — confluence, variants, strike recommendations.
- Backtest — multi-day simulation.
- Analytics — performance metrics.

---

## 8. Risk Management Framework

### 8.1 Position Sizing

| Limit | Current Value | Notes |
|-------|---------------|-------|
| Max risk per trade | 2% of capital | Configurable via risk manager |
| Max risk per day | 5% of capital | Across open positions |
| Max correlated exposure | 3 variants | Same underlying |
| Margin utilization cap | 60% | Of available margin |

### 8.2 Stop Loss & Drawdown

| Type | Rule |
|------|------|
| Hard Stop | Spot closes beyond bought strike of spread |
| Time Stop | Close at 2 DTE |
| Volatility Stop | VIX spike >25% from entry |
| DEX Shift Stop | DEX wall shifts >1 strike |
| Drawdown Level 1 (5%) | Reduce size 50% for 5 sessions |
| Drawdown Level 2 (10%) | Pause new entries |
| Drawdown Level 3 (15%) | Close all; 10-session cooling |
| Drawdown Level 4 (20%) | Halt; manual review |

---

## 9. AI / LLM Layer (Planned)

### 9.1 Current State

`analysis/ai_chart_explainer.py` is a deterministic string-template explainer. It is **not wired** into the API or dashboard, and its expected input keys do not match `DecisionEngine` output keys.

### 9.2 Target State

Integrate an external reasoning engine (optional overlay) that:
- Interprets the quantitative signal bundle.
- Flags anomalies vs. historical distributions.
- Suggests parameter adjustments.
- Provides human-readable reasoning for every recommendation.

### 9.3 Guardrails (Future)

- Cannot override hard risk limits.
- Cannot bypass drawdown cooling periods.
- All live-trade recommendations require human confirmation.
- Every recommendation must include explainable reasoning.
- System falls back to rule-based decisions if AI is unavailable.

---

## 10. Browser Automation (Removed)

The Kimi WebBridge / Chrome DevTools / DhanMCP browser-automation roadmap described in earlier revisions has been **removed**. Market data is now sourced exclusively from `yfinance`, `jugaad-data`, and bundled internal datasets — no headless browser or broker web scraping is used.

---

## 11. Backtesting & Validation

### 11.1 Current Implementation

- `backtest/engine.py` — multi-day swing simulation.
- `backtest/metrics.py` — Win Rate, Profit Factor, Max Drawdown, Sharpe, Calmar, MFE/MAE.
- Scripts: `scripts/run_1y_backtest.py`, `scripts/run_2y_full_rules_backtest.py`.

### 11.2 Known Issues

- Stop-loss buffer is hardcoded to `0.1%` in `backtest/engine.py`.
- `scripts/fetch_history_job.py` uses a different configurable buffer.
- Dashboard simulation uses UI-configurable logic.
- **No shared simulation function.** Refactor needed.

### 11.3 Historical Data

- Minimum backtest period: 2 years target.
- Granularity: 1-min candles + EOD context.
- Current repo ships a few pre-built Parquet files; first-time users may have empty historical stats.

---

## 12. Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| Core engine | Python 3.11+ | Quantitative calculations |
| Web framework | FastAPI | REST API |
| Dashboard | Streamlit | UI |
| Data | pandas, numpy, yfinance, jugaad-data, internal datasets | OHLCV, VIX, CPR context |
| TA | TA-Lib + pandas fallback | Indicators |
| Pricing | Black-Scholes (`options/synthetic_pricing.py`) | Greeks, credit-spread pricing |
| Storage | Parquet (`data/db.py`) | Scores, feature distributions |
| Browser automation | **Removed** — WebBridge / Chrome / DhanMCP collectors retired | n/a |
| AI | Template-based explainer (`analysis/ai_chart_explainer.py`) | Deterministic narrative |
| Alerts | Telegram Bot API | Planned |

---

## 13. Compliance & Security

### 13.1 Regulatory

- System does **not** place automated live trades.
- SEBI RA registration required if signals are distributed to clients.
- Full algo-trading registration + audit trails required for any future automation.
- Position limits must be enforced before any live execution module.

### 13.2 Security

- Secrets via environment variables only (PostgreSQL credentials). No broker or scraper credentials exist.
- `.env` excluded from version control.
- Credentials masked in logs.
- MCP/AI layer must use TLS and scoped tokens if deployed remotely.

---

## 14. Implementation Roadmap (Revised)

### Phase 1: Config & Code Consistency (Week 1–2)
- [ ] Make `engine/confluence.py` read weights from `config/scoring_rules.yaml`.
- [ ] Make `engine/decision.py` thresholds match documentation (or update docs).
- [ ] Reconcile lot sizes in `strike_selector.py` with `config/strike_rules.yaml`.
- [ ] Read `dex_vp_strategy_rules` from `config/strike_rules.yaml` in `strategy_variants.py`.
- [ ] Add `__init__.py` files to all subpackages.

### Phase 2: API & Dashboard Hardening (Week 3–4)
- [ ] Pass full context (regime, IV rank, spot, option chain) through `/api/v1/score`.
- [ ] Accept `osse_score` as parameter in `/api/v1/confluence`.
- [ ] Wire `analysis/ai_chart_explainer.py` into dashboard and API.
- [ ] Unify input/output keys between explainer and decision engine.

### Phase 3: Data Sourcing & Offline Support (Week 5–8)
- [ ] Expand bundled internal datasets and document their schema.
- [ ] Harden `yfinance` / `jugaad-data` fallback ordering and rate-limit handling.
- [ ] Add CSV/Parquet ingestion for user-provided historical data.
- [ ] Document the supported symbol → source mapping.

### Phase 4: AI Integration (Week 9–12)
- [ ] Design prompt templates for signal interpretation, anomaly detection, regime classification.
- [ ] Integrate an optional external reasoning overlay.
- [ ] Implement explainability and confidence calibration.
- [ ] Add AI guardrails and fallback to rule-based decisions.

### Phase 5: Risk & Execution (Week 13–16)
- [ ] Unify stop-loss / simulation logic across backtest, dashboard, and scripts.
- [ ] Implement paper trading simulator with realistic slippage.
- [ ] Add Telegram alerts and one-tap order URLs.
- [ ] Implement human confirmation gate for any live execution helper.

### Phase 6: Backtesting & Optimization (Week 17–22)
- [ ] Backfill 2 years of historical data.
- [ ] Implement walk-forward analysis.
- [ ] Validate win-rate / profit-factor / drawdown targets per variant.
- [ ] Optimize parameters per variant and regime.

### Phase 7: Production Deployment (Week 23+)
- [ ] PostgreSQL adapter option.
- [ ] Production scheduler/job runner.
- [ ] Live monitoring and alerting.
- [ ] Quarterly re-optimization cycle.

---

## 15. Success Metrics (Realistic)

| Metric | Target | Current Status |
|--------|--------|----------------|
| Unit test pass rate | 100% | Implemented for core modules |
| Test coverage | >80% | Missing backtest, dashboard, reporting tests |
| Config-driven weights | 100% | Partial — confluence hardcoded |
| Signal generation time | <60s | Feasible with current polling |
| Backtest profit factor | >1.5 | To be validated |
| Max drawdown | <15% annually | To be validated |
| CS correlation with win rate | Spearman >0.6 | To be validated |
| MCP data extraction success | >98% | Not yet implemented |
| AI reasoning latency | <2s | Not yet implemented |
| System uptime | >99.5% | Not yet productionized |

---

## 16. Appendices

### Appendix A: Known Inconsistencies Checklist
- [ ] Confluence weights in YAML vs. hardcoded values.
- [ ] Decision thresholds in docs vs. code.
- [ ] Lot sizes in YAML vs. `strike_selector.py` fallback.
- [ ] `/api/v1/score` missing full context.
- [ ] `/api/v1/confluence` hardcodes `osse_score=70.0`.
- [ ] AI chart explainer not wired and key mismatch.
- [ ] Duplicate stop-loss logic across backtest/scripts/dashboard.
- [ ] PostgreSQL schema unused.
- [ ] MCP/Node scripts not invoked from Python.

### Appendix B: File Inventory
- Core scoring: `src/osse/engine/scorer.py`, `src/osse/engine/normalizer.py`, `src/osse/features/`
- DEX/VP/Confluence: `src/osse/engine/dex_calculator.py`, `src/osse/features/volume_profile.py`, `src/osse/engine/confluence.py`
- Strategy/Risk: `src/osse/engine/strategy_variants.py`, `src/osse/engine/risk_manager.py`
- Options: `src/osse/options/strike_selector.py`, `src/osse/options/synthetic_pricing.py`, `src/osse/options/expiry_manager.py`
- Data: `src/osse/data/collector.py`, `src/osse/data/db.py`, `src/osse/data/validator.py`
- UI/API: `src/osse/dashboard/app.py`, `src/osse/api/app.py`
- Tests: `tests/`
- Config: `config/scoring_rules.yaml`, `config/strike_rules.yaml`

---

**Next Step Recommendation:** Proceed with **Phase 1 (Config & Code Consistency)** before adding new AI or MCP capabilities. A consistent configuration layer makes later AI and automation integration materially easier.
