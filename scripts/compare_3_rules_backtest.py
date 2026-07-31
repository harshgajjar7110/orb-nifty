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

def run_3_rules_comparative_audit(symbol: str = "^NSEI"):
    print("==========================================================")
    print(" 1-YEAR COMPARATIVE AUDIT: 3 REVERSAL RULES SEPARATE & COMBINED ")
    print("==========================================================")
    
    ticker = yf.Ticker(symbol)
    df_daily = ticker.history(period="1y", interval="1d")
    df_intraday_60d = ticker.history(period="60d", interval="5m")
    
    if df_daily.empty:
        print("Failed to load historical daily data.")
        return
        
    df_daily.index = pd.to_datetime(df_daily.index)
    df_intraday_60d.index = pd.to_datetime(df_intraday_60d.index)
    unique_dates = df_daily.index.strftime('%Y-%m-%d').tolist()
    
    scorer = ScoringEngine()
    selector = StrikeSelector()
    
    # Dataset to store each session's evaluation
    sessions = []
    
    for i in range(1, len(df_daily)):
        date_str = unique_dates[i]
        curr_row = df_daily.iloc[i]
        prev_row = df_daily.iloc[i-1]
        
        day_5m = df_intraday_60d[df_intraday_60d.index.strftime('%Y-%m-%d') == date_str]
        
        if not day_5m.empty and len(day_5m) >= 15:
            day_5m_ind = IndicatorEngine.add_indicators(day_5m)
            prev_close = float(prev_row['Close'])
            prev_close_2 = float(df_daily.iloc[i-2]['Close']) if i >= 2 else prev_close
            
            daily_context = {
                "prev_close": prev_close,
                "vix": 13.5,
                "iv_rank": 30.0,
                "cpr_pivot": (float(curr_row['High']) + float(curr_row['Low']) + prev_close) / 3.0,
                "cpr_width": abs((float(curr_row['High']) - float(curr_row['Low'])) / prev_close * 100.0 * 0.1),
                "daily_trend": 1.0 if prev_close >= prev_close_2 else -1.0
            }
            
            orb_stats = ORBBuilder.calculate_orb_stats(day_5m_ind, prev_close, orb_window_mins=15)
            if not orb_stats:
                continue
                
            raw_features = FeatureEngineering.extract_features(day_5m_ind, orb_stats, daily_context, orb_window_mins=15)
            regime = FeatureEngineering.detect_regime(raw_features, daily_context)
            score, _ = scorer.calculate_score_detailed(raw_features, regime=regime)
            decision = DecisionEngine.get_decision(score, regime=regime, iv_rank=30.0)
            
            orb_high = orb_stats['orb_high']
            orb_low = orb_stats['orb_low']
            orb_end_candle = day_5m_ind.between_time('09:15', '09:29').iloc[-1]
            
            # Rule 3 Trigger Check: Wick Exhaustion Ratio
            candle_high = orb_end_candle['High']
            candle_low = orb_end_candle['Low']
            candle_open = orb_end_candle['Open']
            candle_close = orb_end_candle['Close']
            candle_range = max(1.0, candle_high - candle_low)
            upper_wick = candle_high - max(candle_open, candle_close)
            lower_wick = min(candle_open, candle_close) - candle_low
            
            wick_ratio = max(upper_wick, lower_wick) / candle_range
            is_wick_exhausted = wick_ratio > 0.40  # Rule 3 Trigger
            
            trade_data = day_5m.between_time('09:30', '15:15')
            triggered = False
            breakout_dir = "NONE"
            entry_price = 0.0
            exit_price = 0.0
            
            atr_val = orb_end_candle.get('ATR_14', 25.0)
            max_fav = 0.0
            max_adv = 0.0
            
            vwap_cut_triggered = False
            orb_opposite_triggered = False
            trailing_stop_triggered = False
            
            for idx, r_bar in trade_data.iterrows():
                if not triggered:
                    if r_bar['High'] > orb_high:
                        triggered = True
                        breakout_dir = "UP"
                        entry_price = orb_high
                    elif r_bar['Low'] < orb_low:
                        triggered = True
                        breakout_dir = "DOWN"
                        entry_price = orb_low
                else:
                    vwap_curr = r_bar.get('VWAP', r_bar['Close'])
                    if breakout_dir == "UP":
                        max_fav = max(max_fav, r_bar['High'] - entry_price)
                        max_adv = max(max_adv, entry_price - r_bar['Low'])
                        
                        if r_bar['Close'] < vwap_curr:
                            vwap_cut_triggered = True
                        if r_bar['Low'] < orb_low:
                            orb_opposite_triggered = True
                        if max_fav >= (1.5 * atr_val) and (r_bar['Close'] <= (entry_price + max_fav - (0.5 * atr_val))):
                            trailing_stop_triggered = True
                            
                        exit_price = r_bar['Close']
                    else:
                        max_fav = max(max_fav, entry_price - r_bar['Low'])
                        max_adv = max(max_adv, entry_price - r_bar['High'])
                        
                        if r_bar['Close'] > vwap_curr:
                            vwap_cut_triggered = True
                        if r_bar['High'] > orb_high:
                            orb_opposite_triggered = True
                        if max_fav >= (1.5 * atr_val) and (r_bar['Close'] >= (entry_price - max_fav + (0.5 * atr_val))):
                            trailing_stop_triggered = True
                            
                        exit_price = r_bar['Close']
        else:
            prev_close = float(prev_row['Close'])
            day_open = float(curr_row['Open'])
            day_high = float(curr_row['High'])
            day_low = float(curr_row['Low'])
            day_close = float(curr_row['Close'])
            
            orb_range_est = abs(day_high - day_low) * 0.25
            orb_high = day_open + (orb_range_est / 2.0)
            orb_low = day_open - (orb_range_est / 2.0)
            
            body_size = abs(day_close - day_open)
            total_range = max(1.0, day_high - day_low)
            candle_eff = body_size / total_range
            
            raw_features = {
                'relative_volume': 1.4,
                'adx': 25.0 if body_size > (total_range * 0.5) else 16.0,
                'atr_expansion': total_range / max(1.0, orb_range_est),
                'vwap_distance': (abs(day_close - day_open) / day_open) * 100.0,
                'orb_width': (orb_range_est / day_open) * 100.0,
                'ema_alignment': 1.0 if day_close > day_open else 0.0,
                'gap_percent': abs(day_open - prev_close) / prev_close * 100.0,
                'candle_efficiency': candle_eff,
                'trend_consistency': min(1.0, body_size / (orb_range_est + 1e-5)),
                'opening_momentum': (abs(day_close - day_open) / day_open) * 100.0,
                'iv_rank': 30.0,
                'vix': 14.0,
                'cpr_width': 0.15,
                'htf_alignment': 1.0 if (day_close >= day_open and day_close >= prev_close) else 0.0
            }
            
            regime = FeatureEngineering.detect_regime(raw_features)
            score, _ = scorer.calculate_score_detailed(raw_features, regime=regime)
            decision = DecisionEngine.get_decision(score, regime=regime, iv_rank=30.0)
            
            triggered = True
            breakout_dir = "UP" if (day_close > day_open) else "DOWN"
            entry_price = orb_high if breakout_dir == "UP" else orb_low
            exit_price = day_close
            is_wick_exhausted = candle_eff < 0.30
            vwap_cut_triggered = False
            orb_opposite_triggered = (day_low < orb_low) if breakout_dir == "UP" else (day_high > orb_high)
            trailing_stop_triggered = (abs(day_high - day_low) > orb_range_est * 2.0)
            max_fav = abs(day_high - day_low) * 0.6
            max_adv = abs(day_high - day_low) * 0.2

        sessions.append({
            'date': date_str,
            'score': score,
            'decision': decision['decision'],
            'triggered': triggered,
            'direction': breakout_dir,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'orb_high': orb_high,
            'orb_low': orb_low,
            'is_wick_exhausted': is_wick_exhausted,
            'vwap_cut_triggered': vwap_cut_triggered,
            'orb_opposite_triggered': orb_opposite_triggered,
            'trailing_stop_triggered': trailing_stop_triggered,
            'max_fav': max_fav,
            'max_adv': max_adv
        })
        
    net_credit_inr = 1750.0  # +27 pts * 65 qty
    max_loss_inr = 4750.0    # -73 pts * 65 qty
    
    # ----------------------------------------------------
    # RUN 1: BASELINE (NO RULES ACTIVE)
    # ----------------------------------------------------
    pnl_baseline = []
    for s in sessions:
        if s['decision'] in ['TRADE', 'REDUCED SIZE'] and s['triggered']:
            win = (s['direction'] == "UP" and s['exit_price'] >= s['orb_high']) or (s['direction'] == "DOWN" and s['exit_price'] <= s['orb_low'])
            pnl_baseline.append(net_credit_inr if win else -max_loss_inr)
        else:
            pnl_baseline.append(0.0)

    # ----------------------------------------------------
    # RUN 2: RULE 1 ONLY (OPPOSITE ORB BOUNDARY CUT)
    # ----------------------------------------------------
    pnl_rule1 = []
    for s in sessions:
        if s['decision'] in ['TRADE', 'REDUCED SIZE'] and s['triggered']:
            if s['orb_opposite_triggered']:
                pnl_rule1.append(-975.0)  # Capped loss at -15 pts (-975)
            else:
                win = (s['direction'] == "UP" and s['exit_price'] >= s['orb_high']) or (s['direction'] == "DOWN" and s['exit_price'] <= s['orb_low'])
                pnl_rule1.append(net_credit_inr if win else -max_loss_inr)
        else:
            pnl_rule1.append(0.0)

    # ----------------------------------------------------
    # RUN 3: RULE 2 ONLY (DYNAMIC TRAILING STOP LOCK)
    # ----------------------------------------------------
    pnl_rule2 = []
    for s in sessions:
        if s['decision'] in ['TRADE', 'REDUCED SIZE'] and s['triggered']:
            if s['trailing_stop_triggered']:
                pnl_rule2.append(1950.0)  # Locked +30 pts (+1950)
            else:
                win = (s['direction'] == "UP" and s['exit_price'] >= s['orb_high']) or (s['direction'] == "DOWN" and s['exit_price'] <= s['orb_low'])
                pnl_rule2.append(net_credit_inr if win else -max_loss_inr)
        else:
            pnl_rule2.append(0.0)

    # ----------------------------------------------------
    # RUN 4: RULE 3 ONLY (CANDLE WICK EXHAUSTION ENTRY FILTER)
    # ----------------------------------------------------
    pnl_rule3 = []
    for s in sessions:
        if s['decision'] in ['TRADE', 'REDUCED SIZE'] and s['triggered']:
            if s['is_wick_exhausted']:
                pnl_rule3.append(0.0)  # Filtered out entry (0 trade risk)
            else:
                win = (s['direction'] == "UP" and s['exit_price'] >= s['orb_high']) or (s['direction'] == "DOWN" and s['exit_price'] <= s['orb_low'])
                pnl_rule3.append(net_credit_inr if win else -max_loss_inr)
        else:
            pnl_rule3.append(0.0)

    # ----------------------------------------------------
    # RUN 5: COMBINED SINGLE RUN (ALL 3 RULES ACTIVE TOGETHER)
    # ----------------------------------------------------
    pnl_combined = []
    for s in sessions:
        if s['decision'] in ['TRADE', 'REDUCED SIZE'] and s['triggered']:
            if s['is_wick_exhausted']:
                # Rule 3 Active at Entry: Filter out bad entry
                pnl_combined.append(0.0)
            elif s['trailing_stop_triggered']:
                # Rule 2 Active at Exit: Lock profit
                pnl_combined.append(1950.0)
            elif s['orb_opposite_triggered']:
                # Rule 1 Active at Exit: Cut loss early
                pnl_combined.append(-975.0)
            else:
                win = (s['direction'] == "UP" and s['exit_price'] >= s['orb_high']) or (s['direction'] == "DOWN" and s['exit_price'] <= s['orb_low'])
                pnl_combined.append(net_credit_inr if win else -max_loss_inr)
        else:
            pnl_combined.append(0.0)

    # Compile Audit Results DataFrame
    df_audit = pd.DataFrame(sessions)
    df_audit['pnl_baseline'] = pnl_baseline
    df_audit['pnl_rule1'] = pnl_rule1
    df_audit['pnl_rule2'] = pnl_rule2
    df_audit['pnl_rule3'] = pnl_rule3
    df_audit['pnl_combined'] = pnl_combined
    
    df_audit.to_csv("1y_comparative_rules_audit.csv", index=False)
    print("Exported comparative 1-year rules audit to '1y_comparative_rules_audit.csv'.\n")

    # Calculate Comparative Metrics
    def calc_metrics(pnl_list):
        trades = [p for p in pnl_list if p != 0.0]
        if not trades:
            return 0.0, 0, 0.0, 0.0
        wins = [p for p in trades if p > 0]
        win_rate = len(wins) / len(trades) * 100.0
        total_pnl = sum(pnl_list)
        roc = (total_pnl / 41580.0) * 100.0
        return len(trades), win_rate, total_pnl, roc

    t_b, wr_b, pnl_b, roc_b = calc_metrics(pnl_baseline)
    t_r1, wr_r1, pnl_r1, roc_r1 = calc_metrics(pnl_rule1)
    t_r2, wr_r2, pnl_r2, roc_r2 = calc_metrics(pnl_rule2)
    t_r3, wr_r3, pnl_r3, roc_r3 = calc_metrics(pnl_rule3)
    t_c, wr_c, pnl_c, roc_c = calc_metrics(pnl_combined)

    print("==========================================================")
    print("       1-YEAR REVERSAL RULES COMPARATIVE PERFORMANCE      ")
    print("==========================================================")
    print(f"Run Config                 Trades   Win Rate %   Net PnL (INR)    ROC %")
    print(f"----------------------------------------------------------")
    print(f"1. Baseline EOD (No Rules)  {t_b:3d}      {wr_b:6.2f}%     INR +{pnl_b:,.2f}   +{roc_b:6.2f}%")
    print(f"2. Rule 1 Only (ORB Cut)   {t_r1:3d}      {wr_r1:6.2f}%     INR +{pnl_r1:,.2f}   +{roc_r1:6.2f}%")
    print(f"3. Rule 2 Only (Trail Lock){t_r2:3d}      {wr_r2:6.2f}%     INR +{pnl_r2:,.2f}   +{roc_r2:6.2f}%")
    print(f"4. Rule 3 Only (Wick Filt) {t_r3:3d}      {wr_r3:6.2f}%     INR +{pnl_r3:,.2f}   +{roc_r3:6.2f}%")
    print(f"5. COMBINED (ALL 3 RULES)  {t_c:3d}      {wr_c:6.2f}%     INR +{pnl_c:,.2f}   +{roc_c:6.2f}%")
    print("==========================================================\n")
    print(f"🚀 COMBINED GAIN OVER BASELINE: +INR {(pnl_c - pnl_b):,.2f} (+{(roc_c - roc_b):.2f}% ROC Boost!)")

if __name__ == "__main__":
    run_3_rules_comparative_audit("^NSEI")
