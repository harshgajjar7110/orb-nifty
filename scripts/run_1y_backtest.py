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

def run_1y_enhanced_analysis(symbol: str = "^NSEI"):
    print("==========================================================")
    print("  OSSE 1-YEAR ENHANCED DUAL-REGIME QUANTITATIVE BACKTEST   ")
    print("==========================================================")
    
    ticker = yf.Ticker(symbol)
    df_daily = ticker.history(period="1y", interval="1d")
    
    if df_daily.empty:
        print("Failed to download yfinance historical daily data.")
        return
        
    df_daily.index = pd.to_datetime(df_daily.index)
    unique_dates = df_daily.index.strftime('%Y-%m-%d').tolist()
    
    df_intraday_60d = ticker.history(period="60d", interval="5m")
    df_intraday_60d.index = pd.to_datetime(df_intraday_60d.index)
    
    scorer = ScoringEngine()
    selector = StrikeSelector()
    records = []
    
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
            score, breakdown = scorer.calculate_score_detailed(raw_features, regime=regime)
            
            spot_close_eod = float(day_5m['Close'].iloc[-1])
            orb_high = orb_stats['orb_high']
            orb_low = orb_stats['orb_low']
            
            trade_data = day_5m.between_time('09:30', '15:15')
            triggered = False
            breakout_dir = "NONE"
            
            for idx, r_bar in trade_data.iterrows():
                if r_bar['High'] > orb_high:
                    triggered = True
                    breakout_dir = "UP"
                    break
                elif r_bar['Low'] < orb_low:
                    triggered = True
                    breakout_dir = "DOWN"
                    break
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
            
            spot_close_eod = day_close
            triggered = (day_high > orb_high) or (day_low < orb_low)
            breakout_dir = "UP" if (day_close > day_open) else "DOWN"

        # DUAL REGIME ADAPTIVE EXECUTION STRATEGY:
        # 1. High Score (>= 55.0): Directional Credit Spread (High conviction)
        # 2. Low Score (< 55.0) & Rangebound ADX < 22: Iron Condor / Delta Hedged Range Selling (Captures passive theta)
        # 3. Low Score & High ADX / Volatility Whipsaw: NO TRADE (Avoids fakeouts)
        
        adx = raw_features.get('adx', 20.0)
        net_credit_inr = 1750.0  # ~27 pts credit * 65 qty
        max_loss_inr = 4750.0    # ~73 pts risk * 65 qty
        
        if score >= 55.0:
            exec_mode = "DIRECTIONAL_SPREAD"
            if breakout_dir == "UP":
                pnl_inr = net_credit_inr if spot_close_eod >= orb_high else max(-max_loss_inr, net_credit_inr - ((orb_high - spot_close_eod) * 65))
            else:
                pnl_inr = net_credit_inr if spot_close_eod <= orb_low else max(-max_loss_inr, net_credit_inr - ((spot_close_eod - orb_low) * 65))
        elif adx < 22.0:
            exec_mode = "IRON_CONDOR_RANGE"
            # Iron Condor PnL: Full profit if price stays within wings, loss if huge breakout
            dist_from_open = abs(spot_close_eod - float(curr_row['Open']))
            if dist_from_open <= (orb_high - orb_low) * 1.2:
                pnl_inr = net_credit_inr  # Captures full theta decay on quiet days
            else:
                pnl_inr = max(-max_loss_inr, net_credit_inr - (dist_from_open * 40))
        else:
            exec_mode = "AVOID_WHIPSAW"
            pnl_inr = 0.0

        # Unfiltered Raw PnL
        if breakout_dir == "UP":
            raw_pnl_inr = net_credit_inr if spot_close_eod >= orb_high else max(-max_loss_inr, net_credit_inr - ((orb_high - spot_close_eod) * 65))
        else:
            raw_pnl_inr = net_credit_inr if spot_close_eod <= orb_low else max(-max_loss_inr, net_credit_inr - ((spot_close_eod - orb_low) * 65))

        records.append({
            'date': date_str,
            'osse_score': score,
            'exec_mode': exec_mode,
            'triggered': triggered,
            'direction': breakout_dir,
            'algo_pnl_inr': round(pnl_inr, 2),
            'raw_pnl_inr': round(raw_pnl_inr, 2),
            'is_win': pnl_inr > 0
        })
        
    df_res = pd.DataFrame(records)
    df_res.to_csv("1y_enhanced_backtest_results.csv", index=False)
    
    total_days = len(df_res)
    algo_traded = df_res[df_res['exec_mode'] != 'AVOID_WHIPSAW']
    algo_wins = algo_traded[algo_traded['is_win'] == True]
    algo_win_rate = (len(algo_wins) / len(algo_traded) * 100.0) if not algo_traded.empty else 0
    algo_total_pnl = algo_traded['algo_pnl_inr'].sum()
    
    raw_wins = df_res[df_res['raw_pnl_inr'] > 0]
    raw_win_rate = (len(raw_wins) / len(df_res) * 100.0)
    raw_total_pnl = df_res['raw_pnl_inr'].sum()
    
    print("==========================================================")
    print("   OSSE ENHANCED DUAL-REGIME 1-YEAR BACKTEST RESULTS       ")
    print("==========================================================")
    print(f"Total Sessions Evaluated: {total_days}")
    print(f"Directional Breakout Trades (Score >= 55): {len(df_res[df_res['exec_mode'] == 'DIRECTIONAL_SPREAD'])}")
    print(f"Rangebound Premium Decay Trades (ADX < 22): {len(df_res[df_res['exec_mode'] == 'IRON_CONDOR_RANGE'])}")
    print(f"Choppy Fakeouts Blocked (Score < 55 & High ADX): {len(df_res[df_res['exec_mode'] == 'AVOID_WHIPSAW'])}\n")
    
    print("----------------------------------------------------------")
    print("   ENHANCED OSSE ALGO vs UNFILTERED RAW BREAKOUTS (1 YEAR)")
    print("----------------------------------------------------------")
    print(f"Metric                         Enhanced OSSE      Unfiltered Raw")
    print(f"----------------------------------------------------------")
    print(f"Win Rate %                     {algo_win_rate:.2f}%            {raw_win_rate:.2f}%")
    print(f"Total Net PnL (INR / 65 Lot)   INR +{algo_total_pnl:,.2f}   INR {raw_total_pnl:,.2f}")
    print(f"Return on Capital (ROC %)      +{(algo_total_pnl / 41580.0 * 100.0):.2f}%         +{(raw_total_pnl / 41580.0 * 100.0):.2f}%")
    print("==========================================================\n")

if __name__ == "__main__":
    run_1y_enhanced_analysis("^NSEI")
