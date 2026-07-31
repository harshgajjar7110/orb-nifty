import os
import sys
import pandas as pd
import numpy as np
import yfinance as yf

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from osse.features.indicators import IndicatorEngine
from osse.features.orb_builder import ORBBuilder
from osse.features.engineering import FeatureEngineering
from osse.engine.scorer import ScoringEngine
from osse.engine.decision import DecisionEngine

def test_5m_rules_breakdown():
    print("==========================================================")
    print("   AUTHENTIC 5-MINUTE INTRADAY DATA: RULES BREAKDOWN AUDIT ")
    print("==========================================================")
    
    ticker = yf.Ticker("^NSEI")
    df_5m = ticker.history(period="60d", interval="5m")
    df_5m.index = pd.to_datetime(df_5m.index)
    
    unique_dates = sorted(list(set(df_5m.index.strftime('%Y-%m-%d'))))
    
    scorer = ScoringEngine()
    sessions = []
    
    for i, date_str in enumerate(unique_dates):
        day_5m = df_5m[df_5m.index.strftime('%Y-%m-%d') == date_str].copy()
        if len(day_5m) < 15:
            continue
            
        day_5m_ind = IndicatorEngine.add_indicators(day_5m)
        
        prev_close = float(day_5m['Open'].iloc[0])
        if i > 0:
            prev_day = df_5m[df_5m.index.strftime('%Y-%m-%d') == unique_dates[i-1]]
            if not prev_day.empty:
                prev_close = float(prev_day['Close'].iloc[-1])
                
        daily_context = {
            "prev_close": prev_close,
            "vix": 13.5,
            "iv_rank": 30.0,
            "cpr_pivot": (float(day_5m['High'].max()) + float(day_5m['Low'].min()) + prev_close) / 3.0,
            "cpr_width": abs((float(day_5m['High'].max()) - float(day_5m['Low'].min())) / prev_close * 100.0 * 0.1),
            "daily_trend": 1.0
        }
        
        orb_stats = ORBBuilder.calculate_orb_stats(day_5m_ind, prev_close, orb_window_mins=15)
        if not orb_stats:
            continue
            
        raw_features = FeatureEngineering.extract_features(day_5m_ind, orb_stats, daily_context, orb_window_mins=15)
        regime = FeatureEngineering.detect_regime(raw_features, daily_context)
        score, breakdown = scorer.calculate_score_detailed(raw_features, regime=regime)
        decision = DecisionEngine.get_decision(score, regime=regime, iv_rank=30.0)
        
        orb_high = orb_stats['orb_high']
        orb_low = orb_stats['orb_low']
        orb_end_candle = day_5m_ind.between_time('09:15', '09:29').iloc[-1]
        
        candle_high = orb_end_candle['High']
        candle_low = orb_end_candle['Low']
        candle_open = orb_end_candle['Open']
        candle_close = orb_end_candle['Close']
        candle_range = max(1.0, candle_high - candle_low)
        upper_wick = candle_high - max(candle_open, candle_close)
        lower_wick = min(candle_open, candle_close) - candle_low
        wick_ratio = max(upper_wick, lower_wick) / candle_range
        is_wick_exhausted = wick_ratio > 0.40
        
        trade_data = day_5m.between_time('09:30', '15:15')
        triggered = False
        breakout_dir = "NONE"
        entry_price = 0.0
        exit_price = 0.0
        atr_val = orb_end_candle.get('ATR_14', 25.0)
        max_fav = 0.0
        max_adv = 0.0
        
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
                if breakout_dir == "UP":
                    max_fav = max(max_fav, r_bar['High'] - entry_price)
                    max_adv = max(max_adv, entry_price - r_bar['Low'])
                    if r_bar['Low'] < orb_low:
                        orb_opposite_triggered = True
                    if max_fav >= (1.5 * atr_val) and (r_bar['Close'] <= (entry_price + max_fav - (0.5 * atr_val))):
                        trailing_stop_triggered = True
                    exit_price = r_bar['Close']
                else:
                    max_fav = max(max_fav, entry_price - r_bar['Low'])
                    max_adv = max(max_adv, entry_price - r_bar['High'])
                    if r_bar['High'] > orb_high:
                        orb_opposite_triggered = True
                    if max_fav >= (1.5 * atr_val) and (r_bar['Close'] >= (entry_price - max_fav + (0.5 * atr_val))):
                        trailing_stop_triggered = True
                    exit_price = r_bar['Close']

        sessions.append({
            'date': date_str,
            'score': score,
            'decision': decision['decision'],
            'triggered': triggered,
            'direction': breakout_dir,
            'exit_price': exit_price,
            'orb_high': orb_high,
            'orb_low': orb_low,
            'is_wick_exhausted': is_wick_exhausted,
            'orb_opposite_triggered': orb_opposite_triggered,
            'trailing_stop_triggered': trailing_stop_triggered
        })

    net_credit_inr = 1750.0
    max_loss_inr = 4750.0
    
    # 1. BASELINE (EOD Exit, No Rules)
    pnl_base = []
    for s in sessions:
        if s['decision'] in ['TRADE', 'REDUCED SIZE'] and s['triggered']:
            win = (s['direction'] == "UP" and s['exit_price'] >= s['orb_high']) or (s['direction'] == "DOWN" and s['exit_price'] <= s['orb_low'])
            pnl_base.append(net_credit_inr if win else -max_loss_inr)
            
    # 2. RULE 2 + RULE 3 ONLY (No Rule 1)
    pnl_r2_r3 = []
    for s in sessions:
        if s['decision'] in ['TRADE', 'REDUCED SIZE'] and s['triggered']:
            if s['is_wick_exhausted']:
                pnl_r2_r3.append(0.0)
            elif s['trailing_stop_triggered']:
                pnl_r2_r3.append(1950.0)
            else:
                win = (s['direction'] == "UP" and s['exit_price'] >= s['orb_high']) or (s['direction'] == "DOWN" and s['exit_price'] <= s['orb_low'])
                pnl_r2_r3.append(net_credit_inr if win else -max_loss_inr)

    # 3. ALL 3 RULES COMBINED
    pnl_all = []
    for s in sessions:
        if s['decision'] in ['TRADE', 'REDUCED SIZE'] and s['triggered']:
            if s['is_wick_exhausted']:
                pnl_all.append(0.0)
            elif s['trailing_stop_triggered']:
                pnl_all.append(1950.0)
            elif s['orb_opposite_triggered']:
                pnl_all.append(-975.0)
            else:
                win = (s['direction'] == "UP" and s['exit_price'] >= s['orb_high']) or (s['direction'] == "DOWN" and s['exit_price'] <= s['orb_low'])
                pnl_all.append(net_credit_inr if win else -max_loss_inr)

    def print_summary(name, pnl_list):
        trades = [p for p in pnl_list if p != 0.0]
        wins = [p for p in trades if p > 0]
        wr = (len(wins) / len(trades) * 100.0) if trades else 0
        tot_pnl = sum(pnl_list)
        print(f"{name:32s} | Trades: {len(trades):2d} | Win Rate: {wr:6.2f}% | Net PnL: INR +{tot_pnl:,.2f}")

    print("-----------------------------------------------------------------------------------------")
    print_summary("1. Baseline (No Rules Active)", pnl_base)
    print_summary("2. Rule 2 + Rule 3 ONLY", pnl_r2_r3)
    print_summary("3. All 3 Rules Combined", pnl_all)
    print("-----------------------------------------------------------------------------------------\n")

if __name__ == "__main__":
    test_5m_rules_breakdown()
