import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import yfinance as yf

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from osse.data.collector import DataCollector
from osse.features.indicators import IndicatorEngine
from osse.features.orb_builder import ORBBuilder
from osse.features.engineering import FeatureEngineering
from osse.engine.scorer import ScoringEngine
from osse.engine.decision import DecisionEngine
from osse.options.strike_selector import StrikeSelector

def run_30d_analysis(symbol: str = "^NSEI"):
    print("==========================================================")
    print("   OSSE 30-DAY INTRADAY QUANTITATIVE BACKTEST & AUDIT     ")
    print("==========================================================")
    
    # Download 60d of 5m intraday data for ^NSEI
    ticker = yf.Ticker(symbol)
    df_all = ticker.history(period="60d", interval="5m")
    
    if df_all.empty:
        print("Failed to download yfinance historical intraday data.")
        return
        
    df_all.index = pd.to_datetime(df_all.index)
    unique_dates = sorted(list(set(df_all.index.strftime('%Y-%m-%d'))))[-30:]
    print(f"Loaded {len(unique_dates)} trading sessions from {unique_dates[0]} to {unique_dates[-1]}.\n")
    
    scorer = ScoringEngine()
    selector = StrikeSelector()
    records = []
    
    for date_str in unique_dates:
        day_df = df_all[df_all.index.strftime('%Y-%m-%d') == date_str].copy()
        if len(day_df) < 15:
            continue
            
        # Add technical indicators
        day_df = IndicatorEngine.add_indicators(day_df)
        
        # Calculate daily context (prev close, etc)
        prev_idx = unique_dates.index(date_str) - 1
        if prev_idx >= 0:
            prev_date_str = unique_dates[prev_idx]
            prev_df = df_all[df_all.index.strftime('%Y-%m-%d') == prev_date_str]
            prev_close = float(prev_df['Close'].iloc[-1]) if not prev_df.empty else float(day_df['Open'].iloc[0])
            prev_close_2 = float(prev_df['Close'].iloc[0]) if not prev_df.empty else prev_close
        else:
            prev_close = float(day_df['Open'].iloc[0])
            prev_close_2 = prev_close
            
        daily_context = {
            "prev_close": prev_close,
            "vix": 13.5,
            "iv_rank": 25.0,
            "cpr_pivot": (float(day_df['High'].max()) + float(day_df['Low'].min()) + prev_close) / 3.0,
            "cpr_width": abs((float(day_df['High'].max()) - float(day_df['Low'].min())) / prev_close * 100.0 * 0.1),
            "daily_trend": 1.0 if prev_close >= prev_close_2 else -1.0
        }
        
        # Calculate ORB Stats
        orb_stats = ORBBuilder.calculate_orb_stats(day_df, prev_close, orb_window_mins=15)
        if not orb_stats:
            continue
            
        raw_features = FeatureEngineering.extract_features(day_df, orb_stats, daily_context, orb_window_mins=15)
        regime = FeatureEngineering.detect_regime(raw_features, daily_context)
        score, breakdown = scorer.calculate_score_detailed(raw_features, regime=regime)
        decision = DecisionEngine.get_decision(score, regime=regime, iv_rank=25.0)
        
        spot_close_eod = float(day_df['Close'].iloc[-1])
        orb_high = orb_stats['orb_high']
        orb_low = orb_stats['orb_low']
        
        # Determine Intraday Breakout Trigger
        trade_data = day_df.between_time('09:30', '15:15')
        triggered = False
        breakout_dir = "NONE"
        
        for idx, row in trade_data.iterrows():
            if row['High'] > orb_high:
                triggered = True
                breakout_dir = "UP"
                break
            elif row['Low'] < orb_low:
                triggered = True
                breakout_dir = "DOWN"
                break
                
        # Option Strategy Execution Simulation (Intraday Option Selling / Spreads)
        strike_rec = selector.select_strikes(
            strategy_name=decision['recommended_strategy'],
            spot_price=float(day_df['Open'].iloc[0]),
            daily_context=daily_context,
            symbol=symbol,
            variant="DELTA_TARGETED",
            expiry_type="WEEKLY",
            trade_date=date_str,
            vix=13.5,
            direction=breakout_dir if breakout_dir != "NONE" else "UP"
        )
        
        net_credit_inr = strike_rec['net_premium_inr']
        max_loss_inr = strike_rec['max_loss_inr']
        
        # Intraday Option PnL Logic:
        # If score >= 55 (Approved Trade):
        # - Credit Spread / Selling strategy captures net credit if breakout holds, or loses defined risk if reversed
        pnl_inr = 0.0
        if decision['decision'] in ['TRADE', 'REDUCED SIZE'] and triggered:
            if breakout_dir == "UP":
                # Bull Put Spread / Call Buying
                if spot_close_eod >= orb_high:
                    pnl_inr = net_credit_inr  # Max Profit
                else:
                    move_down = orb_high - spot_close_eod
                    pnl_inr = max(-max_loss_inr, net_credit_inr - (move_down * 65))
            else:
                # Bear Call Spread / Put Buying
                if spot_close_eod <= orb_low:
                    pnl_inr = net_credit_inr  # Max Profit
                else:
                    move_up = spot_close_eod - orb_low
                    pnl_inr = max(-max_loss_inr, net_credit_inr - (move_up * 65))
        elif decision['decision'] == 'NO TRADE' and triggered:
            # Calculate hypothetical PnL if trader took the trade without OSSE score filter
            if breakout_dir == "UP":
                pnl_inr = net_credit_inr if spot_close_eod >= orb_high else max(-max_loss_inr, net_credit_inr - ((orb_high - spot_close_eod) * 65))
            else:
                pnl_inr = net_credit_inr if spot_close_eod <= orb_low else max(-max_loss_inr, net_credit_inr - ((spot_close_eod - orb_low) * 65))

        records.append({
            'date': date_str,
            'osse_score': score,
            'decision': decision['decision'],
            'confidence': decision['confidence'],
            'recommended_strategy': decision['recommended_strategy'],
            'triggered': triggered,
            'direction': breakout_dir,
            'spot_eod': spot_close_eod,
            'net_credit_inr': net_credit_inr,
            'max_loss_inr': max_loss_inr,
            'actual_pnl_inr': round(pnl_inr, 2),
            'is_win': pnl_inr > 0
        })
        
    df_res = pd.DataFrame(records)
    df_res.to_csv("30d_backtest_audit_results.csv", index=False)
    
    # Compute Final Performance Metrics
    total_days = len(df_res)
    approved_trades = df_res[(df_res['decision'].isin(['TRADE', 'REDUCED SIZE'])) & (df_res['triggered'] == True)]
    rejected_trades = df_res[(df_res['decision'] == 'NO TRADE') & (df_res['triggered'] == True)]
    all_triggered = df_res[df_res['triggered'] == True]
    
    print("==========================================================")
    print("                30-DAY BACKTEST METRICS SUMMARY            ")
    print("==========================================================")
    print(f"Total Trading Sessions Evaluated: {total_days}")
    print(f"Raw Breakout Triggers: {len(all_triggered)} / {total_days}")
    print(f"OSSE Approved Signals (Score >= 55): {len(approved_trades)}")
    print(f"OSSE Rejected Signals (Score < 55): {len(rejected_trades)}\n")
    
    algo_wins = approved_trades[approved_trades['is_win'] == True]
    algo_win_rate = (len(algo_wins) / len(approved_trades) * 100.0) if not approved_trades.empty else 0
    algo_pnl_inr = approved_trades['actual_pnl_inr'].sum() if not approved_trades.empty else 0
    
    raw_wins = all_triggered[all_triggered['is_win'] == True]
    raw_win_rate = (len(raw_wins) / len(all_triggered) * 100.0) if not all_triggered.empty else 0
    raw_pnl_inr = all_triggered['actual_pnl_inr'].sum() if not all_triggered.empty else 0
    
    rejected_losses = rejected_trades[rejected_trades['is_win'] == False]
    fakeout_rejection_rate = (len(rejected_losses) / len(rejected_trades) * 100.0) if not rejected_trades.empty else 100.0
    
    print("----------------------------------------------------------")
    print("   OSSE ALGO TRADES vs UNFILTERED RAW BREAKOUTS COMPARISON ")
    print("----------------------------------------------------------")
    print(f"Metric                         OSSE Filtered      Unfiltered Raw")
    print(f"----------------------------------------------------------")
    print(f"Win Rate %                     {algo_win_rate:.2f}%            {raw_win_rate:.2f}%")
    print(f"Total Net PnL (INR / 65 Lot)   INR +{algo_pnl_inr:,.2f}     INR {raw_pnl_inr:,.2f}")
    print(f"False Breakout Avoidance Rate  {fakeout_rejection_rate:.2f}% (Choppy Fakeouts Blocked)")
    print("==========================================================\n")
    
    print("Recent Session Results Audit (Last 10 Days):")
    for idx, r in df_res.tail(10).iterrows():
        pnl_str = f"INR +{r['actual_pnl_inr']:,.2f}" if r['actual_pnl_inr'] >= 0 else f"INR -{abs(r['actual_pnl_inr']):,.2f}"
        status_icon = "PASS" if r['decision'] in ['TRADE', 'REDUCED SIZE'] else "AVOID"
        print(f"Date: {r['date']} | Score: {r['osse_score']} | Status: {status_icon:5s} | Strategy: {r['recommended_strategy']} | PnL: {pnl_str}")

if __name__ == "__main__":
    run_30d_analysis("^NSEI")
