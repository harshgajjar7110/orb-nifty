import logging
import os
import pandas as pd
from osse.data.db import DatabaseManager

logger = logging.getLogger(__name__)

class FeatureAnalysis:
    """
    Handles statistical validation of the OSSE features (FR-012), 
    such as identifying correlated/redundant features.
    """
    
    @staticmethod
    def get_correlation_matrix(symbol: str = '^NSEI', days: int = 60) -> pd.DataFrame:
        """
        Fetches the last `days` of features and returns a Pearson correlation matrix.
        """
        DatabaseManager._initialize_paths()
        score_file = DatabaseManager._score_file
        
        if not os.path.exists(score_file):
            logger.warning("Parquet data file not found. Cannot compute correlation.")
            return pd.DataFrame()
            
        try:
            df = pd.read_parquet(score_file)
            if df.empty:
                return pd.DataFrame()
                
            # Filter by symbol and sort by date descending
            df = df[df['symbol'] == symbol]
            df = df.sort_values(by='date', ascending=False)
            
            # Limit to the last `days` days
            df = df.head(days)
            
            # Select relevant columns for correlation
            cols_to_keep = ['date', 'relative_volume', 'atr', 'adx', 'ema_alignment', 'vwap_distance', 'candle_efficiency', 'orb_percent']
            # Make sure all columns exist
            cols_present = [c for c in cols_to_keep if c in df.columns]
            df = df[cols_present].copy()
            
            if 'orb_percent' in df.columns:
                df.rename(columns={'orb_percent': 'orb_width'}, inplace=True)
                
            df.set_index('date', inplace=True)
            # Compute Pearson Correlation
            corr = df.corr(method='pearson')
            return corr
        except Exception as e:
            logger.error(f"Error computing correlation matrix: {e}")
            return pd.DataFrame()

    @staticmethod
    def check_redundant_features(corr_matrix: pd.DataFrame, threshold: float = 0.75) -> list:
        """
        Returns a list of feature pairs that have a correlation higher than `threshold`.
        """
        redundant = []
        if corr_matrix.empty:
            return redundant
            
        cols = corr_matrix.columns
        for i in range(len(cols)):
            for j in range(i+1, len(cols)):
                c = corr_matrix.iloc[i, j]
                if abs(c) >= threshold:
                    redundant.append((cols[i], cols[j], c))
        return redundant

if __name__ == "__main__":
    corr = FeatureAnalysis.get_correlation_matrix()
    if not corr.empty:
        print("--- Correlation Matrix ---")
        print(corr.round(2))
        
        redundant = FeatureAnalysis.check_redundant_features(corr)
        if redundant:
            print("\nWARNING: High Correlation Detected!")
            for f1, f2, val in redundant:
                print(f"{f1} <-> {f2}: {val:.2f}")
