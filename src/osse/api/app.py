from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
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

app = FastAPI(title="ORB Strength Score Engine", version="1.0")
scorer = ScoringEngine()

class ScoreRequest(BaseModel):
    symbol: str
    date: str
    spot_price: float = None
    vix: float = 15.0
    include_explanation: bool = False

class ScoreResponse(BaseModel):
    score: float
    confidence: str
    decision: str
    regime: str
    recommended_strategy: Optional[str] = ""
    pros: List[str] = []
    cons: List[str] = []
    ai_explanation: Optional[str] = ""

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
                last_spot = float(intraday_df['close'].iloc[-1])
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


# -------------------------------------------------------------------
# DEX + Volume Profile 70% Endpoints (PRD v3.1)
# -------------------------------------------------------------------
from osse.engine.dex_calculator import DEXCalculator
from osse.features.volume_profile import VolumeProfileCalculator
from osse.engine.confluence import ConfluenceEngine
from osse.engine.strategy_variants import StrategyVariantSelector
from osse.engine.risk_manager import RiskManager
from osse.data.dhan_mcp import DhanMCPCollector

mcp_collector = DhanMCPCollector()

class SymbolRequest(BaseModel):
    symbol: str = "NIFTY"
    spot_price: float = 24500.0
    osse_score: float = 70.0

@app.post("/api/v1/dex")
async def get_dex_analysis(request: SymbolRequest):
    """Calculates Delta Exposure (DEX) positioning per strike."""
    try:
        chain_df = await asyncio.to_thread(mcp_collector.fetch_option_chain, request.symbol)
        dex_calc = DEXCalculator()
        result = dex_calc.calculate_dex(chain_df, spot_price=request.spot_price)
        return result
    except Exception as e:
        logger.exception("Error in /dex endpoint")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/v1/volume-profile")
async def get_volume_profile(request: SymbolRequest):
    """Calculates Volume Profile 70% Value Area (POC, VAH, VAL, HVN, LVN)."""
    try:
        candles_df = await asyncio.to_thread(mcp_collector.fetch_chart_candles, request.symbol)
        vp_calc = VolumeProfileCalculator()
        result = vp_calc.calculate_volume_profile(candles_df)
        return result
    except Exception as e:
        logger.exception("Error in /volume-profile endpoint")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/v1/confluence")
async def get_confluence_analysis(request: SymbolRequest):
    """Calculates Confluence Score & Unified Score from DEX, Volume Profile, and OSSE score."""
    try:
        chain_df = await asyncio.to_thread(mcp_collector.fetch_option_chain, request.symbol)
        candles_df = await asyncio.to_thread(mcp_collector.fetch_chart_candles, request.symbol)

        dex_calc = DEXCalculator()
        dex_res = dex_calc.calculate_dex(chain_df, spot_price=request.spot_price)

        vp_calc = VolumeProfileCalculator()
        vp_res = vp_calc.calculate_volume_profile(candles_df)

        step_size = 100.0 if request.symbol.upper() == "BANKNIFTY" else 50.0
        conf_engine = ConfluenceEngine(step_size=step_size)
        conf_res = conf_engine.calculate_confluence_score(
            dex_data=dex_res,
            vp_data=vp_res,
            spot_price=request.spot_price
        )
        unified_res = conf_engine.calculate_unified_score(
            osse_score=request.osse_score,
            confluence_score=conf_res.get("confluence_score", 0.0)
        )
        return {
            "symbol": request.symbol,
            "spot_price": request.spot_price,
            "confluence": conf_res,
            "unified_score": unified_res
        }
    except Exception as e:
        logger.exception("Error in /confluence endpoint")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/v1/strategy-variants")
async def get_strategy_variants(request: SymbolRequest):
    """Evaluates and outputs active DEX + VP 70% Strategy Variants."""
    try:
        chain_df = await asyncio.to_thread(mcp_collector.fetch_option_chain, request.symbol)
        candles_df = await asyncio.to_thread(mcp_collector.fetch_chart_candles, request.symbol)

        dex_res = DEXCalculator().calculate_dex(chain_df, spot_price=request.spot_price)
        vp_res = VolumeProfileCalculator().calculate_volume_profile(candles_df)

        step_size = 100.0 if request.symbol.upper() == "BANKNIFTY" else 50.0
        conf_res = ConfluenceEngine(step_size=step_size).calculate_confluence_score(
            dex_data=dex_res,
            vp_data=vp_res,
            spot_price=request.spot_price
        )

        variants = StrategyVariantSelector(symbol=request.symbol, step_size=step_size).select_variants(
            spot_price=request.spot_price,
            confluence_data=conf_res,
            dex_data=dex_res,
            vp_data=vp_res,
            osse_score=request.osse_score
        )

        risk_mgr = RiskManager()
        for v in variants:
            if "recommended_risk_pct" in v:
                risk_info = risk_mgr.calculate_position_size(
                    capital=1_000_000.0,
                    risk_percent=v["recommended_risk_pct"],
                    max_loss_per_lot=15000.0
                )
                v["position_sizing_example"] = risk_info

        return {
            "symbol": request.symbol,
            "spot_price": request.spot_price,
            "confluence_score": conf_res.get("confluence_score", 0.0),
            "tier": conf_res.get("tier"),
            "variants": variants
        }
    except Exception as e:
        logger.exception("Error in /strategy-variants endpoint")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/v1/explain")
async def get_ai_explanation(request: SymbolRequest):
    """Generates natural language AI market reasoning explanation using real feature extraction."""
    try:
        from osse.analysis.ai_chart_explainer import AIChartExplainer

        # Fetch real intraday data & daily context
        intraday_df = await asyncio.to_thread(DataCollector.fetch_data, request.symbol, start_date=request.date)
        daily_context = await asyncio.to_thread(DataCollector.fetch_daily_context, request.symbol, date=request.date)

        if not intraday_df.empty and DataValidator.validate_intraday_data(intraday_df):
            intraday_df = IndicatorEngine.add_indicators(intraday_df)
            orb_stats = ORBBuilder.calculate_orb_stats(intraday_df, daily_context.get('prev_close'))
            raw_features = FeatureEngineering.extract_features(intraday_df, orb_stats, daily_context) if orb_stats else {}
            score = scorer.calculate_score(raw_features) if raw_features else request.osse_score
            decision = DecisionEngine.get_decision(score=score, spot_price=request.spot_price, daily_context=daily_context, symbol=request.symbol)
            spot = float(intraday_df['close'].iloc[-1]) if not intraday_df.empty else request.spot_price
        else:
            raw_features = {"orb_high": request.spot_price * 1.005, "orb_low": request.spot_price * 0.995, "orb_width": request.spot_price * 0.01, "vwap": request.spot_price, "vix": request.vix or 15.0, "iv_rank": 50.0}
            score = request.osse_score
            decision = DecisionEngine.get_decision(score=score, spot_price=request.spot_price, symbol=request.symbol)
            spot = request.spot_price

        explanation = AIChartExplainer.explain_market_setup(
            symbol=request.symbol,
            spot_price=spot,
            osse_score=score,
            feature_breakdown=raw_features,
            strategy_recommendation=decision
        )
        return {"explanation": explanation}
    except Exception as e:
        logger.exception("Error in /explain endpoint")
        raise HTTPException(status_code=500, detail="Internal server error")


# -------------------------------------------------------------------
# WebBridge-driven Dhan Exposure Strike Selection Endpoint
# -------------------------------------------------------------------
from osse.agent.exposure_agent import DhanExposureAgent

exposure_agent = DhanExposureAgent()

class ExposureStrikeRequest(BaseModel):
    url: str = "https://dext.dhan.co/dashboard"
    symbol: str = "NIFTY"
    direction: str = "UP"
    strategy_name: str = "Directional Credit Spread"
    variant: str = "GEX_DEX_ALIGNED"
    expiry_type: str = "WEEKLY"

@app.post("/api/v1/exposure-strikes")
async def get_exposure_strikes(request: ExposureStrikeRequest):
    """
    Navigates to the supplied Dhan Dext URL, extracts Delta/Gamma exposure,
    and returns a GEX/DEX-aligned strike recommendation.
    """
    try:
        result = exposure_agent.run(
            url=request.url,
            strategy_name=request.strategy_name,
            direction=request.direction,
            symbol=request.symbol,
            variant=request.variant,
            expiry_type=request.expiry_type,
        )
        if result.status != "SUCCESS":
            raise HTTPException(status_code=500, detail=result.reason)
        return result.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error processing exposure-strikes request")
        raise HTTPException(status_code=500, detail="Internal server error")



