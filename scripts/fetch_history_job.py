import os
import sys
import pandas as pd
from datetime import datetime, timedelta
import logging
import time

# Ensure src is in PYTHONPATH
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(base_dir, 'src'))

from osse.data.collector import DataCollector
from osse.data.db import DatabaseManager
from osse.features.indicators import IndicatorEngine
from osse.features.orb_builder import ORBBuilder
from osse.features.engineering import FeatureEngineering
from osse.engine.scorer import ScoringEngine
from osse.engine.decision import DecisionEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_historical_job_batch(days=365, symbol="^NSEI", sl_buffer_pct=0.003):
    logger.info(f"Starting BATCH historical fetch job for {days} days...")
    
    DatabaseManager._initialize_paths()
    score_file = DatabaseManager._score_file
    cache_file = os.path.join(os.path.dirname(score_file), 'intraday_cache.parquet')
    
    # 1. Delete old database to prevent pollution
    if os.path.exists(score_file):
        import shutil
        backup_score = f"{score_file}.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy2(score_file, backup_score)
        logger.info(f"Created backup of database at {backup_score}")
        os.remove(score_file)
        logger.info(f"Deleted old database at {score_file}")
    if os.path.exists(cache_file):
        import shutil
        backup_cache = f"{cache_file}.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy2(cache_file, backup_cache)
        logger.info(f"Created backup of cache at {backup_cache}")
        os.remove(cache_file)
        logger.info(f"Deleted old cache at {cache_file}")
        
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=days)
    
    # 2. Fetch up to 1 year of daily data for context (to avoid 365 API calls).
    #    Source: Y Finance (yfinance) — no broker/DhanHQ dependency.
    try:
        import yfinance as yf

        yf_symbol = DataCollector._yfinance_symbol(symbol)
        raw_daily = yf.Ticker(yf_symbol).history(
            start=(start_dt - timedelta(days=30)).strftime("%Y-%m-%d"),  # Extra history for daily context
            end=end_dt.strftime("%Y-%m-%d"),
            interval="1d",
        )
        daily_df_full = raw_daily[["Open", "High", "Low", "Close", "Volume"]].copy()
        daily_df_full.index.name = "Datetime"
        daily_df_full['date_str'] = daily_df_full.index.strftime('%Y-%m-%d')
    except Exception as e:
        logger.error(f"Failed to fetch daily history: {e}")
        daily_df_full = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    chunk_days = 30
    current_start = start_dt
    
    scorer = ScoringEngine()
    all_chunks = []
    
    # Process in 30-day chunks to respect API limits but guarantee warmup
    while current_start <= end_dt:
        # We need a 7-day lookback for TA-Lib indicators warmup
        fetch_start = current_start - timedelta(days=7)
        
        current_end = current_start + timedelta(days=chunk_days)
        if current_end > end_dt:
            current_end = end_dt
            
        # DataCollector.fetch_data ALREADY fetches 7 days prior implicitly! 
        # So we just pass chunk_start_str and chunk_end_str
        chunk_df = DataCollector.fetch_data(symbol, start_date=current_start.strftime("%Y-%m-%d"), end_date=current_end.strftime("%Y-%m-%d"))
        if chunk_df.empty:
            current_start = current_end + timedelta(days=1)
            continue
            
        # Add indicators to the entire chunk at once (thousands of rows)
        chunk_df = IndicatorEngine.add_indicators(chunk_df)
        
        # Cache the raw 1-minute data for dynamic simulation in dashboard
        cache_chunk = chunk_df.copy()
        cache_chunk['symbol'] = symbol
        all_chunks.append(cache_chunk)
        
        # Get unique days inside the actual target chunk (ignoring the 7-day warmup)
        chunk_df['date_str'] = chunk_df.index.strftime('%Y-%m-%d')
        target_df = chunk_df[(chunk_df['date_str'] >= current_start.strftime('%Y-%m-%d')) & (chunk_df['date_str'] <= current_end.strftime('%Y-%m-%d'))]
        unique_days = target_df['date_str'].unique()
        
        for date in unique_days:
            try:
                day_df = target_df[target_df['date_str'] == date].copy()
                
                # Build Daily Context manually from daily_df_full
                prev_daily = daily_df_full[daily_df_full['date_str'] < date]
                if prev_daily.empty:
                    continue
                last_day = prev_daily.iloc[-1]
                daily_context = {
                    "prev_close": float(last_day['Close']),
                    "prev_high": float(last_day['High']),
                    "prev_low": float(last_day['Low']),
                    "daily_volume": float(last_day['Volume'])
                }
                
                # ORB Builder
                orb_stats = ORBBuilder.calculate_orb_stats(day_df, daily_context['prev_close'])
                if not orb_stats:
                    continue
                    
                # Feature Engineering
                raw_features = FeatureEngineering.extract_features(day_df, orb_stats, daily_context)
                regime = FeatureEngineering.detect_regime(raw_features, daily_context)
                
                # Scorer
                hist_stats = DatabaseManager.get_historical_stats(date, symbol) # Might be empty on first run, that's fine
                score = scorer.calculate_score(raw_features, historical_stats=hist_stats, regime=regime)
                
                # Decision
                decision = DecisionEngine.get_decision(score)
                decision['market_regime'] = regime
                
                # Simulate Trade using unified simulation engine
                from osse.backtest.simulation import simulate_trade
                decision = simulate_trade(day_df, orb_stats, decision, sl_buffer_pct=sl_buffer_pct, score=score)
                
                # Save to Database
                DatabaseManager.save_analysis(date, symbol, raw_features, orb_stats, score, decision, run_id="BATCH", calibrated_score=score)
                logger.info(f"{date}: {symbol} - Score: {score:.2f} (ADX: {raw_features.get('adx', 0):.2f}, EMA Align: {raw_features.get('ema_alignment', 0)})")
                
            except Exception as e:
                logger.warning(f"Error processing {date}: {e}")
                
        # Move to next chunk
        current_start = current_end + timedelta(days=1)
        time.sleep(2) # Prevent rate limiting between chunk requests

    # 4. Save Cache
    if all_chunks:
        full_cache_df = pd.concat(all_chunks, ignore_index=False)
        full_cache_df = full_cache_df[~full_cache_df.index.duplicated(keep='last')]
        full_cache_df.to_parquet(cache_file)
        logger.info(f"Saved {len(full_cache_df)} rows to intraday cache.")

    # 5. Compute distributions after full backtest
    logger.info("Computing historical feature distributions...")
    dist_file = DatabaseManager._dist_file
    df = pd.read_parquet(score_file)
    if df.empty:
        return
        
    df = df[df['symbol'] == symbol].sort_values(by='date', ascending=True)
    df.set_index('date', inplace=True)
    
    # Dynamically include all features from scoring config that exist in the dataframe
    scorer = ScoringEngine()
    config_features = scorer.features_config.keys() if hasattr(scorer, 'features_config') else []
    features = [f for f in config_features if f in df.columns]
    if not features:
        features = ['relative_volume', 'atr', 'adx', 'ema_alignment', 'vwap_distance', 'candle_efficiency', 'orb_width']
    
    window = 60
    dist_records = []
    
    for i in range(window, len(df)):
        current_date = df.index[i]
        hist_window = df.iloc[i-window:i]
        for feature in features:
            if feature not in hist_window.columns:
                continue
            s = hist_window[feature]
            dist_records.append({
                'date': current_date,
                'symbol': symbol,
                'feature_name': feature,
                'mean_val': float(s.mean()),
                'std_val': float(s.std()),
                'percentile_25': float(s.quantile(0.25)),
                'percentile_50': float(s.quantile(0.50)),
                'percentile_75': float(s.quantile(0.75)),
                'created_at': pd.Timestamp.now()
            })
            
    if dist_records:
        new_dist_df = pd.DataFrame(dist_records)
        new_dist_df.to_parquet(dist_file, index=False)
        
    logger.info("Batch historical fetch complete.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--buffer', type=float, default=0.1)
    args = parser.parse_args()
    
    run_historical_job_batch(days=365, sl_buffer_pct=args.buffer/100.0) 
