import os
import sys
import pandas as pd
import numpy as np
import yfinance as yf

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from osse.data.collector import DataCollector
from osse.features.indicators import IndicatorEngine
from osse.features.orb_builder import ORBBuilder
from osse.features.engineering import FeatureEngineering
from osse.engine.scorer import ScoringEngine

def audit_features_zero_values(symbol: str = "^NSEI"):
    print("==========================================================")
    print("      AUDITING ALL 13 FEATURES FOR ZERO / MISSING VALUES   ")
    print("==========================================================")
    
    ticker = yf.Ticker(symbol)
    df_all = ticker.history(period="60d", interval="5m")
    
    if df_all.empty:
        print("Failed to fetch yfinance 60d 5m data.")
        return
        
    df_all.index = pd.to_datetime(df_all.index)
    unique_dates = sorted(list(set(df_all.index.strftime('%Y-%m-%d'))))
    print(f"Loaded {len(unique_dates)} sessions from {unique_dates[0]} to {unique_dates[-1]}.\n")
    
    feature_records = []
    
    for date_str in unique_dates:
        day_df = df_all[df_all.index.strftime('%Y-%m-%d') == date_str].copy()
        if len(day_df) < 15:
            continue
            
        day_df = IndicatorEngine.add_indicators(day_df)
        
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
        
        orb_stats = ORBBuilder.calculate_orb_stats(day_df, prev_close, orb_window_mins=15)
        if not orb_stats:
            continue
            
        raw_features = FeatureEngineering.extract_features(day_df, orb_stats, daily_context, orb_window_mins=15)
        raw_features['date'] = date_str
        feature_records.append(raw_features)
        
    df_feat = pd.DataFrame(feature_records)
    
    print("-----------------------------------------------------------------------------------------")
    print("Feature Name          | Min Value  | Max Value  | Mean Value | Zero Count | Zero Pct %")
    print("-----------------------------------------------------------------------------------------")
    
    cols = [c for c in df_feat.columns if c != 'date']
    for col in cols:
        vals = df_feat[col].astype(float)
        zero_cnt = (vals == 0.0).sum()
        zero_pct = (zero_cnt / len(vals)) * 100.0
        print(f"{col:21s} | {vals.min():10.4f} | {vals.max():10.4f} | {vals.mean():10.4f} | {zero_cnt:10d} | {zero_pct:9.2f}%")
        
    print("-----------------------------------------------------------------------------------------\n")

if __name__ == "__main__":
    audit_features_zero_values("^NSEI")
