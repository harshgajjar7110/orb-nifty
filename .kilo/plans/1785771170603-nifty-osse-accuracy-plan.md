# OSSE NIFTY 50 Accuracy Enhancement Plan

## 1. Context & Baseline

The OSSE engine evaluates the 09:15–09:30 Opening Range Breakout for NIFTY 50 and emits a 0–100 strength score, a trade decision, and option strategy recommendations. The current baseline on the existing `data/orb_strength_score.parquet` for `^NSEI` is:

| Metric | Current Value |
|---|---|
| Sessions | 458 |
| Approved trades | 253 (55.2%) |
| Win rate | 30.04% |
| Avg trade PnL | +2.32 index points |
| Avg MFE | 105.56 |
| Avg MAE | 96.42 |
| **MFE / MAE** | **1.09** |
| Score range | 25.8 – 92.5 |

The North Star for this plan is **MFE/MAE ratio**; the guardrail is **expectancy per approved trade must remain positive**. Improving MFE/MAE means the engine better distinguishes setups that have room to run from setups that immediately reverse.

## 2. Goal

Improve the OSSE score’s predictive accuracy for NIFTY 50 ORB trade outcomes through a **three-phase, sequentially validated** plan:

1. **Phase 1** — Fix data quality and simulation issues that distort the baseline.
2. **Phase 2** — Add free NSE web data and engineer new predictive features.
3. **Phase 3** — Calibrate the scoring model with a lightweight ML layer and regime-specific thresholds.

## 3. Decisions Already Resolved

| Decision | Choice |
|---|---|
| Accuracy definition | OSSE score → trade outcome accuracy (MFE/MAE + expectancy) |
| Primary metric | **MFE/MAE ratio** (North Star); expectancy is guardrail |
| Secondary metric | Expectancy per approved trade must remain > 0 |
| Execution style | Sequential validation; each phase must beat the previous baseline before proceeding |
| Symbols | **NIFTY 50 only** (`^NSEI` / `NIFTY`) |
| Additional data sources | **Free NSE web data** (public CSVs/HTML endpoints) plus existing yfinance feeds |
| Model architecture | **Lightweight ML calibration** blended with the existing weighted-sum OSSE score |
| Decision thresholds | **Regime-specific** thresholds allowed |
| Risk manager | Keep as-is; feed it the improved confidence/score |
| Validation strategy | Walk-forward expanding window (train on past, test on future, no leakage) |

## 4. Phase 1 — Data Quality & Simulation Fixes

### 4.1 Goals
- Remove silent feature failures that zero-out or NaN-out important inputs.
- Calibrate the trade simulator so MFE/MAE reflects the true quality of the OSSE signal, not simulator artifacts.
- Establish a trusted baseline before adding new features or model complexity.

### 4.2 Tasks

1. **Fix `relative_volume` for index data**
   - **File**: `src/osse/features/engineering.py`
   - **Issue**: The saved parquet shows `relative_volume = 0.0` for many `^NSEI` sessions even though `engineering.py` has an ATR-expansion fallback.
   - **Action**: Debug why the fallback is not persisted; ensure the feature is always a positive number for index symbols. Add a secondary fallback using the 20-day rolling median of the same 15-min ORB window if daily volume is zero.

2. **Fix `vwap_distance` NaNs**
   - **File**: `src/osse/features/engineering.py`, `src/osse/data/db.py`
   - **Issue**: `vwap_distance` is NaN in saved rows.
   - **Action**: Ensure VWAP is computed before the ORB slice and that the feature falls back to 0.0 only when VWAP is truly unavailable. Add a validation assertion in `FeatureEngineering.extract_features` that no NaN leaves the function.

3. **NaN/zero guard for all 13 features**
   - **File**: `src/osse/features/engineering.py`
   - **Action**: Add a post-extraction `assert`/`logger.error` check that every feature in the returned dict is a finite float. Default any missing feature to the midpoint of its normalization range, not 0.0, so the scorer does not silently punish the score.

4. **Calibrate stop-loss buffer for NIFTY 50**
   - **File**: `src/osse/backtest/simulation.py`
   - **Issue**: Current hardcoded `sl_buffer_pct = 0.001` (0.1%) is likely too tight for NIFTY 50 intraday noise, inflating MAE and causing premature exits.
   - **Action**: Make the SL buffer a function of `ATR_14 / spot_price` (e.g., 0.5 × 15-min ATR as % of spot) with a configurable floor/ceiling. Run a sensitivity sweep on recent 200 sessions to pick the value that maximizes MFE/MAE.

5. **Align simulator direction with OSSE score direction**
   - **File**: `src/osse/backtest/simulation.py`
   - **Issue**: `simulate_trade` takes the first breakout above `orb_high` or below `orb_low` regardless of whether the score is bullish or bearish.
   - **Action**: Use the score’s implied direction (e.g., `ema_alignment`, `htf_alignment`, sign of opening momentum) to decide which side to trade. If the score is neutral or conflicts with the breakout, skip the trade or mark it as direction-mismatched for analysis.

6. **Validate ORB window data integrity**
   - **File**: `src/osse/data/validator.py`
   - **Action**: Reject sessions with fewer than 12 of the 15 expected 1-min candles between 09:15–09:29. Reject sessions where the first candle open is outside 0.5% of the prior close (bad tick check).

7. **Tests**
   - **File**: `tests/test_features.py`, `tests/test_backtest_simulation.py` (create if missing)
   - Add unit tests for: NaN guard, index volume fallback, VWAP computation, SL buffer sensitivity, and direction alignment.

### 4.3 Phase 1 Success Criteria
- Run `run_30d_backtest.py` and `run_1y_backtest.py` on `^NSEI`.
- `relative_volume` must be non-zero for all index sessions.
- No NaN in saved feature columns.
- **MFE/MAE > 1.09** (baseline) on the same 458-session dataset.
- Expectancy remains > 0 index points per approved trade.

## 5. Phase 2 — Feature Engineering & Free NSE Data

### 5.1 Goals
- Add externally validated signals that improve the signal-to-noise ratio of the 09:15–09:30 window.
- Keep all features interpretable and config-driven.

### 5.2 New Data Sources (free NSE web / yfinance)

Implement fetchers in a new module `src/osse/data/market_context.py` with pure-function helpers and no hardcoded credentials. Cache daily values to Parquet (`data/market_context.parquet`).

| Source | What to fetch | Frequency |
|---|---|---|
| NSE India public CSVs | Advance-Decline ratio, NIFTY 50 deliverable volume / turnover | Daily |
| NSE sectoral indices | Nifty Bank, Nifty IT, Nifty Financial Services, Nifty Auto 1-min or daily via yfinance | Daily / intraday |
| NSE pre-open | Indicative equilibrium price (IEP) and volume for NIFTY 50 | Daily |
| yfinance | USDINR=X, crude oil (BRENT or CL=F), gold (GC=F), India VIX term structure proxy | Daily |
| yfinance | SGX Nifty / GIFT Nifty proxy (e.g., `^NSEI` pre-market move vs prior US/EU session) | Daily |

### 5.3 New Features to Engineer

Add to `src/osse/features/engineering.py` as additional keys in the raw feature dict. Add normalization bounds to `config/scoring_rules.yaml`.

1. **`orb_volume_vs_20d_median`**
   - Compare current ORB volume (when available) to the 20-day median of the same 15-min window. More robust than daily-volume fraction for indices.

2. **`orb_break_volume_spike`**
   - Volume of the 09:30 candle relative to the average 1-min volume during 09:15–09:29. Captures whether the breakout is confirmed by volume.

3. **`gap_vs_atr`**
   - Overnight gap % divided by the 14-day ATR %. Normalizes gap size to recent volatility.

4. **`opening_drive_strength`**
   - Count of consecutive 1-min candles in the dominant direction during the ORB window. More consecutive candles = stronger directional commitment.

5. **`orb_mid_bias`**
   - Where the 09:29 close lies within the ORB range (0 = at low, 1 = at high). Adds directionality to the ORB width feature.

6. **`sectoral_breadth_score`**
   - Percentage of NSE sectoral indices whose 09:15–09:29 return has the same sign as NIFTY 50. Range 0–1.

7. **`advance_decline_ratio`**
   - NSE advance-decline ratio at market open (or prior close if open data unavailable).

8. **`vix_change_from_prior_close`**
   - `(current VIX - prior close VIX) / prior close VIX`. Captures volatility regime shift.

9. **`usd_inr_change`**
   - Overnight USD/INR return. FX moves often lead NIFTY sentiment.

10. **`gift_nifty_premarket_move`**
    - Pre-market move of a GIFT Nifty proxy vs prior close. Used as a gap-quality filter.

11. **`htf_ema_alignment_score`**
    - Extend current daily EMA20 alignment to a 3-level score using EMA5/EMA10/EMA20 stack alignment (0, 0.33, 0.66, 1.0).

12. **`cpr_position`**
    - Where the open lies relative to prior-day CPR (below BC, between BC and TC, above TC). Adds directionality to CPR width.

13. **`pre_open_imbalance`**
    - `(IEP - prior close) / prior close`. If NSE pre-open data is available.

### 5.4 Feature Selection & Importance

- **File**: `src/osse/analysis/feature_importance.py` (new)
- Compute Spearman correlation and mutual information between each feature and the target variable (`trade_pnl` or `mfe_mae_ratio`) on the walk-forward training set.
- Keep only features with positive out-of-sample correlation to MFE/MAE or expectancy.
- Document all dropped features and why.

### 5.5 Tests

- Add unit tests for each new feature with mocked market-context data.
- Add integration test that runs the feature pipeline on a single historical date and returns finite values.

### 5.6 Phase 2 Success Criteria
- At least 5 new features are productionized and config-driven.
- All new features have finite values in the backtest output.
- Walk-forward validation shows **MFE/MAE > Phase 1 result** on the hold-out test set.
- Expectancy remains positive.
- Feature importance report identifies the top 5 drivers of MFE/MAE.

## 6. Phase 3 — Lightweight ML Calibration & Regime-Specific Thresholds

### 6.1 Goals
- Convert the OSSE score from a hand-tuned weighted sum into a calibrated probability of a profitable ORB trade.
- Adjust decision thresholds per regime so we reject more marginal trades in low-edge regimes.

### 6.2 Tasks

1. **Build a calibration model**
   - **File**: `src/osse/engine/calibration.py` (new)
   - Use a simple, interpretable model: **logistic regression** or a small **GradientBoostingClassifier** (max 3–4 depth, max 50 trees).
   - Target: binary `1` if the simulated trade has positive PnL, `0` otherwise.
   - Inputs: all 13 original features + Phase 2 features + regime label.
   - Output: `ml_prob_profit` ∈ [0, 1].

2. **Blend with OSSE score**
   - New calibrated score: `score_calibrated = 0.70 * OSSE_score + 0.30 * ml_prob_profit * 100`.
   - Make blend weights configurable in `config/scoring_rules.yaml` under `calibration_weights`.

3. **Regime-specific decision thresholds**
   - **File**: `config/scoring_rules.yaml`, `src/osse/engine/decision.py`
   - Add a `regime_thresholds` section:
     ```yaml
     regime_thresholds:
       TRENDING:
         trade: 65
         reduced_size: 55
       RANGING:
         trade: 70
         reduced_size: 60
       GAP:
         trade: 68
         reduced_size: 58
       PREMIUM_SELL_RANGE:
         trade: 72
         reduced_size: 62
     ```
   - Update `DecisionEngine.get_decision` to read thresholds from config instead of hardcoded 75/65/55/45.

4. **Regime-specific feature weight overrides**
   - Extend the existing `regimes` section in `scoring_rules.yaml` so low-edge regimes can down-weight noisy features (e.g., reduce `vwap_distance` weight in GAP regimes, boost `relative_volume` in RANGING).

5. **Calibration tracking**
   - Persist `ml_prob_profit`, `score_calibrated`, and `regime_threshold_used` in `DatabaseManager.save_analysis` and backtest parquet.

6. **Walk-forward training script**
   - **File**: `scripts/calibrate_model.py` (new)
   - Train on an expanding window (e.g., train on months 1–N, predict month N+1, roll forward).
   - Save trained models per fold to `data/calibration_models/`.
   - Reject features that change sign or magnitude wildly across folds.

7. **Tests**
   - Add unit tests for calibration blending, threshold lookup, and regime overrides.
   - Add a test that the calibrated score is monotonic with raw OSSE score when ML probability is held constant.

### 6.3 Phase 3 Success Criteria
- Out-of-sample (last 15% of sessions by date) **MFE/MAE > Phase 2 result**.
- Out-of-sample expectancy per approved trade > 0 and higher than Phase 2.
- Win rate improves or remains stable; the gain comes from better trade selection, not merely tighter stops.
- Feature-importance and model weights are stable across walk-forward folds (variance < 20%).
- All new thresholds and weights are config-driven; no hardcoded values in Python.

## 7. Validation Strategy (Walk-Forward Expanding Window)

1. **Dataset**: all historical NIFTY 50 sessions available in `data/orb_strength_score.parquet` and any newly fetched data.
2. **Split**: Use an expanding window. Train on the first 70% of sessions, validate on the next 15%, final test on the last 15%.
3. **For each phase**:
   - Re-run the backtest scripts (`scripts/run_30d_backtest.py`, `scripts/run_1y_backtest.py`).
   - Compute `MetricsCalculator.calculate_summary` and additionally compute MFE/MAE by regime and by score decile.
   - Compare to the previous phase baseline. Phase only advances if MFE/MAE improves and expectancy stays positive.
4. **Leakage prevention**:
   - No features computed using future data.
   - ML model is re-trained only up to the fold boundary; no peeking.
   - Historical stats for normalizer use a rolling 60-day window ending the day before the target session.
5. **Overfitting guardrails**:
   - Maximum 20 total tunable parameters across all phases (SL buffer, weights, thresholds, ML hyperparameters).
   - Track the number of parameters in the plan file.
   - If Phase 3 validation improves but final test degrades, halt and roll back to Phase 2.

## 8. Success Criteria (Overall)

| Metric | Target vs Baseline |
|---|---|
| MFE/MAE | > 1.09 (baseline) after Phase 1; > 1.25 after Phase 2; > 1.40 after Phase 3 |
| Expectancy per approved trade | > 0 at every phase; higher than baseline by Phase 3 |
| Win rate | Improve or remain stable; do not sacrifice win rate for marginal MFE gains |
| Approved trade rate | Expected to drop as we filter marginal setups; target 30–45% (vs current 55%) |
| Data quality | Zero NaN/0 in production features; all features finite in backtest output |
| Config-driven | All new weights, thresholds, and blend ratios live in YAML, not Python |
| Tests | New tests for every new module and every bug fix; all 18+ existing tests pass |

## 9. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Free NSE web data becomes unavailable or changes HTML layout | Abstract fetchers behind an interface; fall back to yfinance proxies; add retry and parse-error logging. |
| Overfitting the walk-forward folds | Cap tunable parameters, use expanding window, require final hold-out test. |
| ML calibration is unstable across regimes | Use regularized logistic regression as the default; restrict tree complexity. Drop features with high fold-to-fold variance. |
| SL buffer optimization overfits to recent volatility | Use a 60-day rolling median of ATR, not the current day ATR, to set the buffer. |
| New features add latency to live monitor | Pre-fetch market-context data once per day before 09:15; cache in Parquet. |
| Existing tests break due to threshold changes | Keep tests threshold-agnostic by reading from `config/scoring_rules.yaml`; add a test-data fixture. |

## 10. Out of Scope

- Adding a new paid API or broker integration beyond free NSE web data.
- Changing the options strike selection, expiry, or synthetic pricing models (except feeding them a better score).
- Live trading or automated execution; the system remains a decision-support filter.
- Multi-symbol optimization in this iteration; NIFTY 50 only.
- Major UI/UX changes to the Streamlit dashboard or FastAPI endpoints (minor additions to expose calibrated score are allowed).

## 11. Implementation Notes

- All new code must follow the existing project conventions: `PYTHONPATH=src`, config-driven weights, secrets from env only, `snake_case`, PEP 8.
- Do not create `setup.py`/`pyproject`.
- Update `AGENTS.md` and `base.md` only if commands or invariants change; otherwise keep documentation minimal.
- Each phase should be implemented as one or more focused pull requests with passing tests and a backtest report.

## 12. Open Questions (to be resolved during implementation if needed)

1. Which exact NSE public endpoints are stable enough for daily scraping? The implementation should discover and document them in `src/osse/data/nse_web_sources.md`.
2. Does the current DhanHQ fallback provide cleaner index volume than yfinance? If yes, prioritize DhanHQ data when credentials are present.
3. Should the `FeatureNormalizer` use historical percentile bounds by default instead of bounded min/max? If Phase 3 shows instability, revisit this.
