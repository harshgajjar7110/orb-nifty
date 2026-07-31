import os
import logging
from typing import Optional
import pandas as pd
from datetime import datetime

logger = logging.getLogger(__name__)

class DatabaseManager:
    """
    Manages Parquet file connections and operations for OSSE.
    """
    _data_dir = None
    _score_file = None
    _dist_file = None
    _monitor_file = None

    @staticmethod
    def _initialize_paths():
        if DatabaseManager._data_dir is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
            DatabaseManager._data_dir = os.path.join(base_dir, 'data')
            os.makedirs(DatabaseManager._data_dir, exist_ok=True)
            
            DatabaseManager._score_file = os.path.join(DatabaseManager._data_dir, 'orb_strength_score.parquet')
            DatabaseManager._dist_file = os.path.join(DatabaseManager._data_dir, 'feature_distributions.parquet')
            DatabaseManager._monitor_file = os.path.join(DatabaseManager._data_dir, 'monitor_snapshots.parquet')

    @staticmethod
    def get_historical_stats(date_str: str, symbol: str) -> dict:
        """
        Fetches the pre-calculated feature distributions for a given date and symbol from Parquet.
        Returns a dict: { 'feature_name': {'mean_val': X, 'std_val': Y, ...} }
        """
        DatabaseManager._initialize_paths()
        if not os.path.exists(DatabaseManager._dist_file):
            return {}
            
        try:
            df = pd.read_parquet(DatabaseManager._dist_file)
            # Filter by date and symbol
            # Convert date_str to datetime object for comparison if needed, or leave as string
            mask = (df['date'] == date_str) & (df['symbol'] == symbol)
            filtered = df[mask]
            
            stats = {}
            for _, row in filtered.iterrows():
                stats[row['feature_name']] = row.to_dict()
            return stats
        except Exception as e:
            logger.error(f"Failed to read historical stats from Parquet: {e}")
            return {}

    @staticmethod
    def save_analysis(date_str: str, symbol: str, raw_features: dict, orb_stats: dict, score: float, decision: dict, run_id: str = "DAILY"):
        """
        Appends an analysis record into the Parquet file.
        """
        DatabaseManager._initialize_paths()
        
        # Extract features (fallback to 0)
        new_row = {
            'timestamp': pd.to_datetime(f"{date_str} 09:30:00"),
            'date': date_str,
            'symbol': symbol,
            'run_id': run_id,
            'orb_high': orb_stats.get('orb_high', 0),
            'orb_low': orb_stats.get('orb_low', 0),
            'orb_width': orb_stats.get('orb_width', 0),
            'orb_percent': raw_features.get('orb_width', 0),
            'relative_volume': raw_features.get('relative_volume', 0),
            'atr': raw_features.get('atr_expansion', 0),
            'adx': raw_features.get('adx', 0),
            'ema_alignment': raw_features.get('ema_alignment', 0),
            'vwap_distance': raw_features.get('vwap_distance', 0),
            'candle_efficiency': raw_features.get('candle_efficiency', 0),
            'normalized_score': score,
            'decision': decision.get('decision', 'NO TRADE'),
            'trade_pnl': decision.get('trade_pnl'),
            'mfe': decision.get('mfe'),
            'mae': decision.get('mae'),
            'market_regime': decision.get('market_regime'),
            'created_at': pd.Timestamp.now()
        }
        
        try:
            new_df = pd.DataFrame([new_row])
            if os.path.exists(DatabaseManager._score_file):
                # We could append using pyarrow or fastparquet directly, but reading and concating 
                # is fine for this scale (a few thousand rows).
                existing_df = pd.read_parquet(DatabaseManager._score_file)
                if not existing_df.empty:
                    combined = pd.concat([existing_df.dropna(how='all', axis=1), new_df.dropna(how='all', axis=1)], ignore_index=True)
                else:
                    combined = new_df
                combined.to_parquet(DatabaseManager._score_file, index=False)
            else:
                new_df.to_parquet(DatabaseManager._score_file, index=False)
                
            logger.info(f"Saved analysis record to Parquet for {symbol} on {date_str} (Run: {run_id}).")
        except Exception as e:
            logger.error(f"Failed to save record to Parquet: {e}")

    @staticmethod
    def save_monitor_snapshot(symbol: str, timestamp: datetime, spot_price: float, insights: dict):
        """
        Appends a live monitor snapshot (signal alerts + summary report) to Parquet.
        """
        DatabaseManager._initialize_paths()

        summary = insights.get("summary_report", {})
        confluence = summary.get("confluence", {})
        unified = summary.get("unified_score", {})
        dex = summary.get("dex", {})
        vp = summary.get("volume_profile", {})

        new_row = {
            "timestamp": pd.Timestamp(timestamp),
            "symbol": symbol,
            "spot_price": float(spot_price),
            "osse_score": float(summary.get("osse_score", 0.0)),
            "vix": float(summary.get("vix", 0.0)),
            "pcr_oi": float(summary.get("pcr_oi", 1.0)),
            "total_oi": float(summary.get("total_oi", 0.0)),
            "call_wall": float(dex.get("call_wall", 0.0)),
            "put_support": float(dex.get("put_support", 0.0)),
            "delta_flip": float(dex.get("delta_flip", 0.0)),
            "poc": float(vp.get("poc", 0.0)),
            "vah": float(vp.get("vah", 0.0)),
            "val": float(vp.get("val", 0.0)),
            "confluence_score": float(confluence.get("confluence_score", 0.0)),
            "confluence_tier": confluence.get("tier", ""),
            "unified_score": float(unified.get("unified_score", 0.0)),
            "alert_count": len(insights.get("signal_alerts", [])),
            "variants": str(summary.get("variants", [])),
            "created_at": pd.Timestamp.now()
        }

        try:
            new_df = pd.DataFrame([new_row])
            if os.path.exists(DatabaseManager._monitor_file):
                existing_df = pd.read_parquet(DatabaseManager._monitor_file)
                if not existing_df.empty:
                    combined = pd.concat([existing_df, new_df], ignore_index=True)
                else:
                    combined = new_df
                combined.to_parquet(DatabaseManager._monitor_file, index=False)
            else:
                new_df.to_parquet(DatabaseManager._monitor_file, index=False)

            logger.info(f"Saved monitor snapshot to Parquet for {symbol} at {timestamp}.")
        except Exception as e:
            logger.error(f"Failed to save monitor snapshot to Parquet: {e}")

    @staticmethod
    def load_monitor_snapshots(symbol: Optional[str] = None, limit: int = 100) -> pd.DataFrame:
        """
        Loads recent monitor snapshots from Parquet.
        """
        DatabaseManager._initialize_paths()
        if not os.path.exists(DatabaseManager._monitor_file):
            return pd.DataFrame()

        try:
            df = pd.read_parquet(DatabaseManager._monitor_file)
            if symbol:
                df = df[df["symbol"] == symbol]
            df = df.sort_values("timestamp", ascending=False).head(limit).reset_index(drop=True)
            return df
        except Exception as e:
            logger.error(f"Failed to load monitor snapshots: {e}")
            return pd.DataFrame()
