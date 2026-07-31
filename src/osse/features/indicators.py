import pandas as pd
import numpy as np
import logging

try:
    import talib
    HAS_TALIB = True
except ImportError:
    talib = None
    HAS_TALIB = False

logger = logging.getLogger(__name__)

class IndicatorEngine:
    """
    Calculates technical indicators using TA-Lib with pure pandas fallback (FR-002).
    """
    
    @staticmethod
    def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculates EMA, ATR, RSI, ADX, Bollinger Bands on the DataFrame.
        Assumes df has 'Open', 'High', 'Low', 'Close', 'Volume' columns.
        """
        if df.empty:
            return df
            
        try:
            logger.info(f"Calculating technical indicators for {len(df)} rows of intraday data...")
            df = df.copy()
            close_prices = df['Close'].values
            high_prices = df['High'].values
            low_prices = df['Low'].values
            
            if HAS_TALIB:
                # EMA
                df['EMA_20'] = talib.EMA(close_prices, timeperiod=20)
                df['EMA_50'] = talib.EMA(close_prices, timeperiod=50)
                df['EMA_200'] = talib.EMA(close_prices, timeperiod=200)
                
                # ATR
                df['ATR_14'] = talib.ATR(high_prices, low_prices, close_prices, timeperiod=14)
                
                # RSI
                df['RSI_14'] = talib.RSI(close_prices, timeperiod=14)
                
                # ADX
                df['ADX_14'] = talib.ADX(high_prices, low_prices, close_prices, timeperiod=14)
                
                # Bollinger Bands
                upperband, middleband, lowerband = talib.BBANDS(close_prices, timeperiod=20, nbdevup=2, nbdevdn=2, matype=0)
                df['BB_UPPER'] = upperband
                df['BB_MIDDLE'] = middleband
                df['BB_LOWER'] = lowerband
            else:
                # Pure Pandas/Numpy Fallback
                df['EMA_20'] = df['Close'].ewm(span=20, adjust=False).mean()
                df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()
                df['EMA_200'] = df['Close'].ewm(span=200, adjust=False).mean()
                
                # ATR 14
                tr = np.maximum(high_prices - low_prices, np.maximum(abs(high_prices - np.roll(close_prices, 1)), abs(low_prices - np.roll(close_prices, 1))))
                df['ATR_14'] = pd.Series(tr, index=df.index).rolling(14, min_periods=1).mean()
                
                # RSI 14
                delta = df['Close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(14, min_periods=1).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(14, min_periods=1).mean()
                rs = gain / loss.replace(0, 1e-9)
                df['RSI_14'] = 100 - (100 / (1 + rs))
                
                # ADX 14
                up = df['High'].diff()
                down = -df['Low'].diff()
                plus_dm = np.where((up > down) & (up > 0), up, 0)
                minus_dm = np.where((down > up) & (down > 0), down, 0)
                atr = df['ATR_14'].replace(0, 1e-9)
                plus_di = 100 * (pd.Series(plus_dm, index=df.index).rolling(14, min_periods=1).mean() / atr)
                minus_di = 100 * (pd.Series(minus_dm, index=df.index).rolling(14, min_periods=1).mean() / atr)
                dx = 100 * (abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, 1e-9))
                df['ADX_14'] = dx.rolling(14, min_periods=1).mean()
                
                # BBANDS
                sma20 = df['Close'].rolling(20, min_periods=1).mean()
                std20 = df['Close'].rolling(20, min_periods=1).std().fillna(0)
                df['BB_UPPER'] = sma20 + 2 * std20
                df['BB_MIDDLE'] = sma20
                df['BB_LOWER'] = sma20 - 2 * std20
            
            # VWAP (Calculated manually as TA-Lib doesn't have native intraday VWAP easily)
            # VWAP = Cumulative(Typical Price * Volume) / Cumulative(Volume)
            # Resets every day
            typical_price = (df['High'] + df['Low'] + df['Close']) / 3
            df['TP_Vol'] = typical_price * df['Volume']
            
            # Group by date to calculate daily VWAP
            df['Date_Only'] = df.index.date
            df['Cum_Vol'] = df.groupby('Date_Only')['Volume'].cumsum()
            df['Cum_TP_Vol'] = df.groupby('Date_Only')['TP_Vol'].cumsum()
            
            # If intraday volume is 0 (Index feeds like ^NSEI), fallback to Time-Weighted Typical Price Average (TWAP)
            if df['Cum_Vol'].sum() == 0:
                df['VWAP'] = df.groupby('Date_Only')['High'].transform(
                    lambda s: typical_price.groupby(df['Date_Only']).expanding().mean().reset_index(level=0, drop=True)
                )
            else:
                df['VWAP'] = df['Cum_TP_Vol'] / df['Cum_Vol']
            
            # Clean up temporary columns
            df.drop(['TP_Vol', 'Cum_Vol', 'Cum_TP_Vol', 'Date_Only'], axis=1, inplace=True)
            
            # Forward fill then backward fill to eliminate all NaNs safely
            indicator_cols = ['EMA_20', 'EMA_50', 'EMA_200', 'ATR_14', 'RSI_14', 'ADX_14', 'BB_UPPER', 'BB_MIDDLE', 'BB_LOWER', 'VWAP']
            for col in indicator_cols:
                if col in df.columns:
                    df[col] = df[col].ffill().bfill().fillna(0)
            
            return df
            
        except Exception as e:
            logger.error(f"Error calculating indicators: {str(e)}")
            raise

