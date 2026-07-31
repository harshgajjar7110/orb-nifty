import pandas as pd
import logging
import time
from typing import List, Dict
from typing import List, Dict

from osse.data.collector import DataCollector
from osse.data.validator import DataValidator
from osse.features.indicators import IndicatorEngine
from osse.features.orb_builder import ORBBuilder
from osse.features.engineering import FeatureEngineering
from osse.engine.scorer import ScoringEngine
from osse.engine.decision import DecisionEngine

logger = logging.getLogger(__name__)

class BacktestEngine:
    """
    Backtesting loop that iterates through historical data dates and processes
    them through the OSSE pipeline sequentially.
    """

    def __init__(self):
        self.scorer = ScoringEngine()

    def run_backtest(self, symbol: str, start_date: str, end_date: str, sl_buffer_pct: float = 0.001, use_trailing_sl: bool = False) -> List[Dict]:
        """
        Runs the backtest over a specific date range.
        
        :param symbol: Ticker symbol (e.g. '^NSEI')
        :param start_date: 'YYYY-MM-DD'
        :param end_date: 'YYYY-MM-DD'
        :param sl_buffer_pct: Stop loss buffer percentage
        :param use_trailing_sl: Enable trailing stop loss logic
        :return: List of daily result dictionaries
        """
        import uuid
        run_id = f"BT-{symbol}-{start_date}-{str(uuid.uuid4())[:8]}"
        logger.info(f"Starting backtest for {symbol} from {start_date} to {end_date} (Run ID: {run_id})")
        
        # Fetch a list of trading days using Dhan historical daily data
        try:
            dhan = DataCollector._get_dhan_client()
            mapping = DataCollector.SYMBOL_MAP[symbol]
            response = dhan.historical_daily_data(
                security_id=mapping["security_id"],
                exchange_segment=mapping["exchange_segment"],
                instrument_type=mapping["instrument_type"],
                expiry_code=0,
                from_date=start_date,
                to_date=end_date
            )
            daily_df = DataCollector._convert_dhan_response_to_df(response)
            if daily_df.empty:
                logger.error("No daily data found for the date range.")
                return []
            
            # Extract unique dates in YYYY-MM-DD format
            trading_days = daily_df.index.strftime('%Y-%m-%d').unique().tolist()
        except Exception as e:
            logger.error(f"Failed to fetch trading days: {e}")
            return []
            
        results = []
        
        for date in trading_days:
            try:
                # Sleep briefly to avoid yfinance rate limiting
                time.sleep(1.5)
                
                # 1. Fetch Data
                intraday_df = DataCollector.fetch_data(symbol, start_date=date)
                daily_context = DataCollector.fetch_daily_context(symbol, date=date)
                
                # 2. Validate Data
                if not DataValidator.validate_intraday_data(intraday_df) or not DataValidator.validate_daily_context(daily_context):
                    continue
                    
                # 3. Indicators
                intraday_df = IndicatorEngine.add_indicators(intraday_df)
                
                # Slice down to just the current date for the rest of the pipeline
                intraday_df = intraday_df[intraday_df.index.strftime('%Y-%m-%d') == date]
                if intraday_df.empty:
                    continue
                
                # 4. ORB Builder
                orb_stats = ORBBuilder.calculate_orb_stats(intraday_df, daily_context.get('prev_close'))
                if not orb_stats:
                    continue
                    
                # 5. Feature Engineering
                raw_features = FeatureEngineering.extract_features(intraday_df, orb_stats, daily_context)
                
                # 5.2 Detect Regime
                regime = FeatureEngineering.detect_regime(raw_features, daily_context)
                
                # 5.5 Fetch Historical Distributions
                from osse.data.db import DatabaseManager
                hist_stats = DatabaseManager.get_historical_stats(date, symbol)
                
                # 6. Scorer
                score = self.scorer.calculate_score(raw_features, historical_stats=hist_stats, regime=regime)
                
                # 7. Decision
                decision = DecisionEngine.get_decision(score)
                decision['market_regime'] = regime
                
                # 7. Simulate Trade using unified simulation engine
                from osse.backtest.simulation import simulate_trade
                decision = simulate_trade(intraday_df, orb_stats, decision, sl_buffer_pct=sl_buffer_pct, use_trailing_sl=use_trailing_sl)
                
                # 10. Save to Database
                from osse.data.db import DatabaseManager
                DatabaseManager.save_analysis(date, symbol, raw_features, orb_stats, score, decision, run_id=run_id)
                
                # Store Result
                result = {
                    'date': date,
                    'symbol': symbol,
                    'score': score,
                    'decision': decision['decision'],
                    'confidence': decision['confidence'],
                    'trade_pnl': decision.get('trade_pnl'),
                    **orb_stats,
                    **raw_features
                }
                results.append(result)
                logger.info(f"{date}: {symbol} - Score: {score}, Decision: {decision['decision']}")
                
            except Exception as e:
                logger.warning(f"Error processing {date} for {symbol}: {e}")
                
        return results
