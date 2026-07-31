import pandas as pd
import logging
from datetime import time

logger = logging.getLogger(__name__)

class DataValidator:
    """
    Handles missing or invalid data gracefully (FR-011).
    Validates that the required trading session is present.
    """

    @staticmethod
    def validate_intraday_data(df: pd.DataFrame) -> bool:
        """
        Validate 1-minute OHLCV data.
        Ensures the dataframe is not empty and covers the Opening Range.
        """
        if df is None or df.empty:
            logger.error("Data validation failed: DataFrame is empty or None.")
            return False
            
        required_columns = ['Open', 'High', 'Low', 'Close', 'Volume']
        if not all(col in df.columns for col in required_columns):
            logger.error(f"Data validation failed: Missing required columns. Found {df.columns}")
            return False

        # Ensure we have data for the ORB window (09:15 - 09:30)
        # Indian markets open at 09:15
        orb_data = df.between_time('09:15', '09:29')
        if orb_data.empty:
            logger.error("Data validation failed: No data found for the ORB window (09:15-09:30).")
            return False

        # Basic check for NaNs in ORB window
        if orb_data.isnull().values.any():
            logger.warning("Data validation warning: NaNs found in ORB window. Forward filling.")
            df.ffill(inplace=True)
            
        return True

    @staticmethod
    def validate_daily_context(context: dict) -> bool:
        """
        Validate that the daily context (previous close, etc.) is valid.
        """
        if not context:
            logger.error("Daily context validation failed: Context is empty.")
            return False
            
        required_keys = ['prev_close', 'prev_high', 'prev_low', 'daily_volume']
        if not all(key in context for key in required_keys):
            logger.error(f"Daily context validation failed: Missing keys. Found {context.keys()}")
            return False
            
        return True

