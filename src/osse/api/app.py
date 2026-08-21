from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, field_validator, AfterValidator
from typing import List, Optional, Dict, Any, Annotated
import time
import logging
import asyncio

from osse.data.collector import DataCollector
from osse.data.validator import DataValidator
from osse.features.indicators import IndicatorEngine
from osse.features.orb_builder import ORBBuilder
from osse.features.engineering import FeatureEngineering
from osse.engine.scorer import ScoringEngine
from osse.engine.decision import DecisionEngine

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="ORB Strength Score Engine (NIFTY 50)", version="1.0")
scorer = ScoringEngine()

def validate_nifty_symbol_value(v: str) -> str:
    if not DataCollector.is_supported_symbol(v):
        raise ValueError("Only NIFTY 50 aliases (^NSEI / NIFTY) are supported")
    return v

NiftySymbol = Annotated[str, AfterValidator(validate_nifty_symbol_value)]

class ScoreRequest(BaseModel):
    symbol: str
    date: str
    spot_price: float = None
    vix: float = 15.0
    include_explanation: bool = False

    @field_validator("symbol")
    @classmethod
    def validate_nifty_symbol(cls, v: str) -> str:
        return validate_nifty_symbol_value(v)

class ScoreResponse(BaseModel):
    score: float
    confidence: str
    decision: str
    regime: str
    recommended_strategy: Optional[str] = ""
    pros: List[str] = []
    cons: List[str] = []
    ai_explanation: Optional[str] = ""

class QuoteResponse(BaseModel):
    symbol: str
    price: float
    change: Optional[float] = None
    percent_change: Optional[float] = None
    open: float
    high: float
    low: float
    previous_close: Optional[float] = None
    timestamp: Optional[str] = None
    source: str
    delayed: bool = True

@app.post("/api/v1/score", response_model=ScoreResponse)
async def generate_score(request: ScoreRequest):
    start_time = time.time()
    logger.info(f"Received request for {request.symbol} on {request.date}")
    
    try:
        # 1. Fetch Data
        intraday_df = await asyncio.to_thread(DataCollector.fetch_data, request.symbol, start_date=request.date)
        daily_context = await asyncio.to_thread(DataCollector.fetch_daily_context, request.symbol, date=request.date)
        
        # 2. Validate Data
        if not DataValidator.validate_intraday_data(intraday_df):
            decision = DecisionEngine.get_error_decision("Invalid Intraday Data")
            return ScoreResponse(score=0.0, confidence=decision["confidence"], decision=decision["decision"], regime="UNKNOWN")
            
        if not DataValidator.validate_daily_context(daily_context):
            decision = DecisionEngine.get_error_decision("Invalid Daily Context")
            return ScoreResponse(score=0.0, confidence=decision["confidence"], decision=decision["decision"], regime="UNKNOWN")

        # 3. Indicators
        intraday_df = IndicatorEngine.add_indicators(intraday_df)
        
        # 4. ORB Builder
        orb_stats = ORBBuilder.calculate_orb_stats(intraday_df, daily_context.get('prev_close'))
        if not orb_stats:
            decision = DecisionEngine.get_error_decision("Failed to build ORB")
            return ScoreResponse(score=0.0, confidence=decision["confidence"], decision=decision["decision"], regime="UNKNOWN")

        # 5. Feature Engineering
        raw_features = FeatureEngineering.extract_features(intraday_df, orb_stats, daily_context)
        
        # 6. Scorer
        final_score = scorer.calculate_score(raw_features)
        
        # 7. Decision with Full Context
        last_spot = request.spot_price
        if not last_spot:
            try:
                last_spot = float(intraday_df['Close'].iloc[-1])
            except Exception:
                last_spot = 24500.0

        adx_val = 0.0
        if isinstance(raw_features, dict):
            try:
                adx_val = float(raw_features.get('adx', 0))
            except Exception:
                pass
        regime = "TREND" if adx_val > 20 else "RANGE"

        iv_rank = 50.0
        if isinstance(daily_context, dict) and 'iv_rank' in daily_context:
            try:
                iv_rank = float(daily_context['iv_rank'])
            except Exception:
                pass
        elif isinstance(raw_features, dict) and 'iv_rank' in raw_features:
            try:
                iv_rank = float(raw_features['iv_rank'])
            except Exception:
                pass

        vix_val = 15.0
        if request.vix:
            try:
                vix_val = float(request.vix)
            except Exception:
                pass
        elif isinstance(daily_context, dict) and 'vix' in daily_context:
            try:
                vix_val = float(daily_context['vix'])
            except Exception:
                pass

        decision = DecisionEngine.get_decision(
            score=final_score,
            regime=regime,
            iv_rank=iv_rank,
            spot_price=last_spot,
            daily_context=daily_context if isinstance(daily_context, dict) else {},
            symbol=request.symbol,
            vix=vix_val
        )
        
        pros, cons = DecisionEngine.generate_pros_cons(
            score=final_score,
            regime=regime,
            raw_features=raw_features,
            daily_context=daily_context,
            recommended_strategy=decision.get("recommended_strategy", "")
        )

        ai_expl = None
        if request.include_explanation:
            from osse.analysis.ai_chart_explainer import AIChartExplainer
            ai_expl = AIChartExplainer.explain_market_setup(
                symbol=request.symbol,
                spot_price=last_spot,
                osse_score=final_score,
                feature_breakdown=raw_features,
                strategy_recommendation=decision
            )

        elapsed = (time.time() - start_time) * 1000
        logger.info(f"Score generated in {elapsed:.2f} ms")

        return ScoreResponse(
            score=final_score,
            confidence=decision["confidence"],
            decision=decision["decision"],
            regime=regime,
            recommended_strategy=decision.get("recommended_strategy"),
            pros=pros,
            cons=cons,
            ai_explanation=ai_expl
        )

    except Exception as e:
        logger.exception("Error processing score request")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/v1/quote", response_model=QuoteResponse)
async def get_quote(symbol: NiftySymbol = "^NSEI"):
    """Delayed NIFTY 50 spot quote (yfinance primary, jugaad-data fallback)."""
    logger.info(f"Received quote request for {symbol}")

    try:
        quote = await asyncio.to_thread(DataCollector.fetch_spot_quote, symbol)
    except Exception:
        logger.exception("Error fetching spot quote")
        raise HTTPException(status_code=500, detail="Internal server error")

    if not quote:
        raise HTTPException(status_code=503, detail="Both quote sources failed")

    return QuoteResponse(**quote)



