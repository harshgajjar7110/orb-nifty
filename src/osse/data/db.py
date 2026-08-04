import os
import logging
import math
from typing import Optional
import pandas as pd
from datetime import datetime

logger = logging.getLogger(__name__)

def _sanitize(value, default=0.0):
    try:
        if value is None:
            return default
        v = float(value)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except (TypeError, ValueError):
        return default

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
    def save_analysis(date_str: str, symbol: str, raw_features: dict, orb_stats: dict, score: float, decision: dict, run_id: str = "DAILY", calibrated_score: float = None, confluence_score: float = None, unified_score: float = None, ml_probability: float = None):
        """
        Appends an analysis record into the Parquet file.
        Persists raw features, orb stats, score, decision, and new Phase 2/3 fields.
        """
        DatabaseManager._initialize_paths()
        
        new_row = {
            'timestamp': pd.to_datetime(f"{date_str} 09:30:00"),
            'date': date_str,
            'symbol': symbol,
            'run_id': run_id,
            'orb_high': _sanitize(orb_stats.get('orb_high', 0)),
            'orb_low': _sanitize(orb_stats.get('orb_low', 0)),
            'orb_width': _sanitize(orb_stats.get('orb_width', 0)),
            'orb_percent': _sanitize(raw_features.get('orb_width', 0)),
            'relative_volume': _sanitize(raw_features.get('relative_volume', 0)),
            'atr': _sanitize(raw_features.get('atr_expansion', 0)),
            'adx': _sanitize(raw_features.get('adx', 0)),
            'ema_alignment': _sanitize(raw_features.get('ema_alignment', 0)),
            'vwap_distance': _sanitize(raw_features.get('vwap_distance', 0)),
            'candle_efficiency': _sanitize(raw_features.get('candle_efficiency', 0)),
            'normalized_score': _sanitize(score, 0.0),
            'calibrated_score': _sanitize(calibrated_score),
            'confluence_score': _sanitize(confluence_score),
            'unified_score': _sanitize(unified_score),
            'ml_probability': _sanitize(ml_probability),
            'decision': decision.get('decision', 'NO TRADE'),
            'trade_pnl': _sanitize(decision.get('trade_pnl')),
            'mfe': _sanitize(decision.get('mfe')),
            'mae': _sanitize(decision.get('mae')),
            'market_regime': decision.get('market_regime'),
            'created_at': pd.Timestamp.now()
        }
        
        try:
            new_df = pd.DataFrame([new_row])
            if os.path.exists(DatabaseManager._score_file):
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
            "vix": float(summary.get("vix") or 0.0),
            "pcr_oi": float(summary.get("pcr_oi") or 1.0),
            "total_oi": float(summary.get("total_oi") or 0.0),
            "call_wall": float(dex.get("call_wall") or 0.0),
            "put_support": float(dex.get("put_support") or 0.0),
            "delta_flip": float(dex.get("delta_flip") or 0.0),
            "poc": float(vp.get("poc") or 0.0),
            "vah": float(vp.get("vah") or 0.0),
            "val": float(vp.get("val") or 0.0),
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
