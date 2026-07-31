import pandas as pd
import logging

logger = logging.getLogger(__name__)

class ORBBuilder:
    """
    Builds Opening Range statistics (FR-003, FR-004).
    """

    @staticmethod
    def calculate_orb_stats(df: pd.DataFrame, prev_close: float, orb_window_mins: int = 15) -> dict:
        """
        Extracts the ORB range (15m or 30m) and calculates statistics.
        
        :param df: DataFrame with intraday data
        :param prev_close: Previous day's closing price
        :param orb_window_mins: Minutes for the ORB window (15 or 30)
        :return: Dictionary containing ORB statistics
        """
        try:
            end_time = '09:29' if orb_window_mins == 15 else '09:44'
            orb_data = df.between_time('09:15', end_time)
            
            if orb_data.empty:
                logger.error("No ORB data found.")
                return {}
                
            logger.info(f"Extracted {len(orb_data)} candles for ORB window. Calculating stats...")

            orb_high = orb_data['High'].max()
            orb_low = orb_data['Low'].min()
            orb_width = orb_high - orb_low
            
            # ORB % = Width / Previous Close
            orb_percent = (orb_width / prev_close) * 100 if prev_close else 0.0

            # Average Candle Size in the ORB
            candle_ranges = orb_data['High'] - orb_data['Low']
            avg_candle_size = candle_ranges.mean()

            # Candle Efficiency (Net movement / Sum of absolute movements)
            # Body = Abs(Close_0929 - Open_0915)
            # Range = Sum of all candle High - Low
            body = abs(orb_data.iloc[-1]['Close'] - orb_data.iloc[0]['Open'])
            total_range = candle_ranges.sum()
            candle_efficiency = body / total_range if total_range > 0 else 0.0

            return {
                "orb_high": orb_high,
                "orb_low": orb_low,
                "orb_width": orb_width,
                "orb_percent": orb_percent,
                "avg_candle_size": avg_candle_size,
                "candle_efficiency": candle_efficiency,
                "orb_volume": orb_data['Volume'].sum()
            }
            
        except Exception as e:
            logger.error(f"Error calculating ORB stats: {str(e)}")
            raise

