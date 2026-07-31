import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
import logging

import sys
import os
from dotenv import load_dotenv

load_dotenv()

# Configure root logger to output to terminal
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Ensure src is in the path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from osse.data.collector import DataCollector
from osse.data.validator import DataValidator
from osse.data.db import DatabaseManager
from osse.features.indicators import IndicatorEngine
from osse.features.orb_builder import ORBBuilder
from osse.features.engineering import FeatureEngineering
from osse.engine.scorer import ScoringEngine
from osse.engine.decision import DecisionEngine
from osse.backtest.engine import BacktestEngine
from osse.backtest.metrics import MetricsCalculator
from osse.monitoring.scheduler import MonitorScheduler
from osse.monitoring.insights import InsightsGenerator

st.set_page_config(page_title="OSSE Dashboard", layout="wide")

# Custom Glassmorphism Quantitative Theme
st.markdown("""
<style>
.metric-card {
    background: rgba(30, 34, 45, 0.75);
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 8px;
    padding: 10px 12px;
    margin-bottom: 8px;
    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.25);
}
.metric-label {
    font-size: 0.72rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.6px;
    color: #90A4AE;
    margin-bottom: 2px;
    white-space: nowrap;
}
.metric-value {
    font-size: 1.15rem;
    font-weight: 700;
    color: #FFFFFF;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: clip;
}
.badge-trade {
    display: inline-block;
    background-color: rgba(0, 230, 118, 0.2);
    color: #00E676;
    border: 1px solid #00E676;
    padding: 2px 8px;
    border-radius: 10px;
    font-size: 0.8rem;
    font-weight: 700;
}
.badge-no-trade {
    display: inline-block;
    background-color: rgba(255, 82, 82, 0.2);
    color: #FF5252;
    border: 1px solid #FF5252;
    padding: 2px 8px;
    border-radius: 10px;
    font-size: 0.8rem;
    font-weight: 700;
}
.badge-neutral {
    display: inline-block;
    background-color: rgba(255, 171, 0, 0.2);
    color: #FFAB00;
    border: 1px solid #FFAB00;
    padding: 2px 8px;
    border-radius: 10px;
    font-size: 0.8rem;
    font-weight: 700;
}
.hero-strategy-box {
    background: linear-gradient(135deg, rgba(25, 118, 210, 0.25), rgba(13, 71, 161, 0.4));
    border: 1px solid #1E88E5;
    border-radius: 8px;
    padding: 10px 14px;
    margin: 8px 0 12px 0;
    color: #E3F2FD;
    font-size: 0.95rem;
    font-weight: 600;
}
.pro-card {
    background: rgba(0, 200, 83, 0.1);
    border-left: 3px solid #00C853;
    padding: 6px 10px;
    margin-bottom: 6px;
    border-radius: 4px;
    font-size: 0.82rem;
    line-height: 1.35;
    color: #E8F5E9;
}
.con-card {
    background: rgba(213, 0, 0, 0.1);
    border-left: 3px solid #FF1744;
    padding: 6px 10px;
    margin-bottom: 6px;
    border-radius: 4px;
    font-size: 0.82rem;
    line-height: 1.35;
    color: #FFEBEE;
}
</style>
""", unsafe_allow_html=True)

st.title("ORB Strength Score Engine (OSSE)")

st.sidebar.header("Configuration")
popular_symbols = [
    "^NSEI (NIFTY 50)",
    "^NSEBANK (BANK NIFTY)",
    "^BSESN (SENSEX)",
    "NIFTY_FIN_SERVICE.NS (FINNIFTY)",
    "RELIANCE.NS (Reliance Industries)",
    "HDFCBANK.NS (HDFC Bank)",
    "ICICIBANK.NS (ICICI Bank)",
    "INFY.NS (Infosys)",
    "TCS.NS (TCS)",
    "KOTAKBANK.NS (Kotak Mahindra Bank)",
    "LT.NS (Larsen & Toubro)",
    "AXISBANK.NS (Axis Bank)",
    "SBIN.NS (State Bank of India)",
    "BHARTIARTL.NS (Bharti Airtel)",
    "ITC.NS (ITC Limited)",
    "TATAMOTORS.NS (Tata Motors)",
    "TATASTEEL.NS (Tata Steel)",
    "M&M.NS (Mahindra & Mahindra)",
    "SUNPHARMA.NS (Sun Pharma)",
    "MARUTI.NS (Maruti Suzuki)",
    "Custom Ticker..."
]

selected_option = st.sidebar.selectbox(
    "Ticker Symbol",
    options=popular_symbols,
    index=0,
    help="Search or select a ticker symbol. Choose 'Custom Ticker...' to type any custom Yahoo Finance ticker."
)

if selected_option == "Custom Ticker...":
    symbol = st.sidebar.text_input("Enter Custom Ticker (e.g. AAPL, TSLA)", value="^NSEI").strip()
else:
    symbol = selected_option.split(" ")[0].strip()
date = st.sidebar.date_input("Date", datetime.today() - timedelta(days=1))

@st.cache_data(ttl=300)
def get_cached_vix(date_str):
    try:
        from osse.data.collector import DataCollector
        return DataCollector.fetch_vix_data(date_str)
    except Exception:
        return {"vix": 0.0, "iv_rank": 0.0, "iv_percentile": 0.0}

vix_info = get_cached_vix(date.strftime("%Y-%m-%d"))

st.sidebar.markdown("---")
with st.sidebar.expander("🔑 Dhan HQ API Credentials", expanded=False):
    curr_client_id = os.environ.get("dhan_client_id", "")
    curr_access_token = os.environ.get("dhan_access_token", "")
    
    dhan_cid = st.text_input("Dhan Client ID", value=curr_client_id, type="password", help="Your Dhan HQ Client ID")
    dhan_token = st.text_input("Dhan Access Token", value=curr_access_token, type="password", help="Your Dhan HQ JWT Access Token")
    
    if st.button("Save Credentials"):
        if dhan_cid and dhan_token:
            DataCollector.set_dhan_credentials(dhan_cid, dhan_token)
            st.success("Dhan API credentials updated!")
            st.rerun()

has_dhan_keys = bool(os.environ.get("dhan_client_id") and os.environ.get("dhan_access_token"))

force_dhan = st.sidebar.checkbox("📡 Force Dhan API Payload Format", value=has_dhan_keys, help="Displays native Dhan HQ Option Chain structure, Greeks, and Security IDs.")
if force_dhan:
    os.environ["force_dhan"] = "1"
else:
    os.environ["force_dhan"] = "0"

key_status = "🟢 Live Dhan API Credentials Active" if has_dhan_keys else ("🟢 Dhan API Format (Simulated)" if force_dhan else "🔵 Synthetic BS Fallback Mode")
st.sidebar.caption(f"Status: **{key_status}**")

st.sidebar.markdown("---")
st.sidebar.subheader("🔥 Volatility Context")
v_col1, v_col2 = st.sidebar.columns(2)
v_col1.metric("India VIX", f"{vix_info.get('vix', 0):.2f}")
v_col2.metric("IV Rank", f"{vix_info.get('iv_rank', 0):.1f}%")
st.sidebar.markdown("---")
auto_scan = st.sidebar.checkbox("⏱️ Auto-Scan Live (1 min)", value=False, help="Automatically fetches latest 1-minute candles and recalculates OSSE score every 60 seconds.")

if auto_scan:
    import streamlit.components.v1 as components
    components.html("""
    <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 5px; font-family: system-ui, -apple-system, sans-serif;">
      <div style="position: relative; width: 90px; height: 90px;">
        <svg width="90" height="90" viewBox="0 0 90 90">
          <circle cx="45" cy="45" r="38" stroke="#262730" stroke-width="7" fill="none" />
          <circle id="countdown-circle" cx="45" cy="45" r="38" stroke="#00FF88" stroke-width="7" fill="none"
                  stroke-dasharray="238.76" stroke-dashoffset="0" stroke-linecap="round"
                  transform="rotate(-90 45 45)" style="transition: stroke-dashoffset 1s linear, stroke 0.5s ease;" />
        </svg>
        <div id="countdown-text" style="position: absolute; top: 0; left: 0; width: 90px; height: 90px; display: flex; align-items: center; justify-content: center; font-size: 18px; font-weight: bold; color: #00FF88;">
          60s
        </div>
      </div>
      <div style="margin-top: 6px; font-size: 11px; color: #00FF88; font-weight: 600;">🟢 Live Auto-Scan Active</div>
    </div>

    <script>
      var timeLeft = 60;
      var totalTime = 60;
      var circumference = 2 * Math.PI * 38;
      var circle = document.getElementById('countdown-circle');
      var text = document.getElementById('countdown-text');

      var timer = setInterval(function() {
        timeLeft--;
        text.innerText = timeLeft + 's';
        var offset = circumference - (timeLeft / totalTime) * circumference;
        circle.style.strokeDashoffset = offset;
        
        if (timeLeft <= 10) {
          circle.style.stroke = '#FF4B4B';
          text.style.color = '#FF4B4B';
        }

        if (timeLeft <= 0) {
          clearInterval(timer);
          window.location.reload();
        }
      }, 1000);
    </script>
    """, height=130)

mode = st.sidebar.radio("Mode", ["Daily Analysis", "DEX + VP 70% Engine", "Backtest", "Analytics", "Live Monitor"])

@st.cache_data(ttl=300)
def get_cached_intraday_data(symbol: str, date_str: str):
    return DataCollector.fetch_data(symbol, start_date=date_str)

@st.cache_data(ttl=300)
def get_cached_daily_context(symbol: str, date_str: str):
    return DataCollector.fetch_daily_context(symbol, date=date_str)

@st.cache_data(ttl=300)
def get_cached_option_chain(symbol: str, spot_price: float, vix: float, dte_days: float = 4.0, expiry: str = None):
    return DataCollector.fetch_option_chain(symbol=symbol, spot_price=spot_price, vix=vix, dte_days=dte_days, expiry=expiry, strike_depth=20)

if mode == "Daily Analysis":
    st.header(f"Daily Analysis for {symbol} on {date}")
    col_ui1, col_ui2 = st.columns(2)
    tf_option = col_ui1.radio("Indicator Timeframe", ["1m", "5m", "15m"], horizontal=True)
    orb_option = col_ui2.radio("ORB Window", ["15 Minutes", "30 Minutes"], horizontal=True)
    orb_window_mins = 15 if orb_option == "15 Minutes" else 30
    
    if st.button("Generate Score"):
        st.session_state[f"run_analysis_{symbol}_{date}"] = True

    if st.session_state.get(f"run_analysis_{symbol}_{date}", False):
        with st.spinner("Fetching data and calculating score..."):
            try:
                date_str = date.strftime("%Y-%m-%d")
                
                # Fetch Data via Cache
                intraday_df = get_cached_intraday_data(symbol, date_str)
                daily_context = get_cached_daily_context(symbol, date_str)
                
                if intraday_df.empty:
                    st.error("No intraday data found for this date.")
                else:
                    # Resample if higher timeframe selected
                    if tf_option != "1m":
                        resample_rule = '5min' if tf_option == "5m" else '15min'
                        intraday_df = intraday_df.resample(resample_rule).agg({
                            'Open': 'first',
                            'High': 'max',
                            'Low': 'min',
                            'Close': 'last',
                            'Volume': 'sum'
                        }).dropna()

                    # Indicators & Features
                    intraday_df = IndicatorEngine.add_indicators(intraday_df)
                    
                    # Slice down to just the current date for the rest of the pipeline
                    intraday_df = intraday_df[intraday_df.index.strftime('%Y-%m-%d') == date_str]
                    
                    if intraday_df.empty:
                        st.error(f"No intraday data found for {date_str}. The market was likely closed (Weekend or Holiday).")
                    else:
                        orb_stats = ORBBuilder.calculate_orb_stats(intraday_df, daily_context.get('prev_close', 0), orb_window_mins)
                        
                        if orb_stats:
                            raw_features = FeatureEngineering.extract_features(intraday_df, orb_stats, daily_context, orb_window_mins)
                            regime = FeatureEngineering.detect_regime(raw_features, daily_context)
                            
                            from osse.data.db import DatabaseManager
                            hist_stats = DatabaseManager.get_historical_stats(date_str, symbol)
                            
                            # Score
                            scorer = ScoringEngine()
                            score, breakdown = scorer.calculate_score_detailed(raw_features, historical_stats=hist_stats, regime=regime)
                            # Determine Trend Direction for the Arrow Indicator safely
                            orb_candles = intraday_df.between_time('09:15', '09:45')
                            if not orb_candles.empty:
                                orb_end_candle = orb_candles.iloc[-1]
                            else:
                                orb_end_candle = intraday_df.iloc[-1]

                            ema20 = orb_end_candle.get('EMA_20', 0)
                            ema50 = orb_end_candle.get('EMA_50', 0)
                            close = orb_end_candle.get('Close', intraday_df['Close'].iloc[-1])
                            
                            if close > ema20 and ema20 > ema50:
                                trend_arrow = "🔼"
                            elif close < ema20 and ema20 < ema50:
                                trend_arrow = "🔽"
                            else:
                                trend_arrow = "↔️"
                                
                            iv_rank = raw_features.get('iv_rank', 50.0)
                            decision = DecisionEngine.get_decision(score, regime=regime, iv_rank=iv_rank)
                            decision['market_regime'] = f"{regime} {trend_arrow}"
                            
                            # Strategy-aware Pros & Cons Calculation
                            pros, cons = DecisionEngine.generate_pros_cons(
                                score=score,
                                regime=regime,
                                raw_features=raw_features,
                                daily_context=daily_context,
                                recommended_strategy=decision.get('recommended_strategy', '')
                            )

                            # Build Responsive 2-Column Dashboard Layout (Zero Scroll)
                            col_left, col_right = st.columns([5.5, 6.5])
                            
                            with col_left:
                                # Row 1: Primary Signal Badges & Score Cards (3 Wide Columns)
                                m1, m2, m3 = st.columns([1.1, 1.1, 1.4])
                                
                                score_color = "#00E676" if score >= 60 else "#FFAB00" if score >= 45 else "#FF5252"
                                decision_badge_class = "badge-trade" if decision['decision'] == 'TRADE' else "badge-neutral" if decision['decision'] == 'REDUCED SIZE' else "badge-no-trade"
                                
                                with m1:
                                    st.markdown(f"""
                                    <div class="metric-card">
                                        <div class="metric-label">OSSE Score</div>
                                        <div class="metric-value" style="color: {score_color};">{score:.1f} <span style="font-size: 0.75rem; color: #78909C;">/ 100</span></div>
                                    </div>
                                    """, unsafe_allow_html=True)

                                with m2:
                                    st.markdown(f"""
                                    <div class="metric-card">
                                        <div class="metric-label">Decision</div>
                                        <div style="margin-top: 2px;"><span class="{decision_badge_class}">{decision['decision']} ({decision['confidence']})</span></div>
                                    </div>
                                    """, unsafe_allow_html=True)

                                with m3:
                                    st.markdown(f"""
                                    <div class="metric-card">
                                        <div class="metric-label">Market Regime</div>
                                        <div style="font-size: 0.85rem; font-weight: 700; color: #FFFFFF; white-space: normal; word-break: break-word; line-height: 1.25;">{regime} {trend_arrow}</div>
                                    </div>
                                    """, unsafe_allow_html=True)
                                
                                # Row 2: Strategy Hero Banner
                                st.markdown(f"""
                                <div class="hero-strategy-box">
                                    🎯 <strong>Strategy</strong>: {decision.get('recommended_strategy', 'N/A')}
                                </div>
                                """, unsafe_allow_html=True)
                                
                                # Row 3: Pros & Cons Grid (Clean card layout)
                                col_p, col_c = st.columns(2)
                                with col_p:
                                    st.markdown("##### 👍 **Pros**")
                                    if pros:
                                        for p in pros:
                                            st.markdown(f'<div class="pro-card">✅ {p}</div>', unsafe_allow_html=True)
                                    else:
                                        st.markdown("<div style='font-size: 0.82rem; color: #78909C;'><i>No major pros identified.</i></div>", unsafe_allow_html=True)
                                with col_c:
                                    st.markdown("##### ⚠️ **Cons**")
                                    if cons:
                                        for c in cons:
                                            st.markdown(f'<div class="con-card">❌ {c}</div>', unsafe_allow_html=True)
                                    else:
                                        st.markdown("<div style='font-size: 0.82rem; color: #78909C;'><i>No major cons identified.</i></div>", unsafe_allow_html=True)
                                
                                # Row 4: Key Context & Levels Metrics
                                g1, g2, g3 = st.columns(3)
                                with g1:
                                    st.markdown(f"""
                                    <div class="metric-card">
                                        <div class="metric-label">Volatility Context</div>
                                        <div style="font-size: 0.9rem; color: #ECEFF1; font-weight: 600;">VIX: <b>{daily_context.get('vix', 0):.2f}</b> | IVR: <b>{daily_context.get('iv_rank', 0):.1f}%</b></div>
                                    </div>
                                    """, unsafe_allow_html=True)
                                with g2:
                                    st.markdown(f"""
                                    <div class="metric-card">
                                        <div class="metric-label">CPR Pivot (Width)</div>
                                        <div style="font-size: 0.9rem; color: #ECEFF1; font-weight: 600;">{daily_context.get('cpr_pivot', 0):.2f} <span style="font-size: 0.75rem; color: #90A4AE;">({daily_context.get('cpr_width', 0):.2f}%)</span></div>
                                    </div>
                                    """, unsafe_allow_html=True)
                                with g3:
                                    htf_badge = '<span class="badge-trade">🟢 Aligned</span>' if raw_features.get('htf_alignment', 0) == 1.0 else '<span class="badge-neutral">🟡 Conflicting</span>'
                                    st.markdown(f"""
                                    <div class="metric-card">
                                        <div class="metric-label">HTF Alignment</div>
                                        <div style="margin-top: 2px;">{htf_badge}</div>
                                    </div>
                                    """, unsafe_allow_html=True)
                                
                                o1, o2 = st.columns(2)
                                with o1:
                                    st.markdown(f"""
                                    <div class="metric-card">
                                        <div class="metric-label">ORB High</div>
                                        <div class="metric-value" style="color: #00E676; font-size: 1.05rem;">{orb_stats['orb_high']:.2f}</div>
                                    </div>
                                    """, unsafe_allow_html=True)
                                with o2:
                                    st.markdown(f"""
                                    <div class="metric-card">
                                        <div class="metric-label">ORB Low</div>
                                        <div class="metric-value" style="color: #FF5252; font-size: 1.05rem;">{orb_stats['orb_low']:.2f}</div>
                                    </div>
                                    """, unsafe_allow_html=True)

                                # Row 5: Strike Selection Engine UI Card
                                st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
                                st.markdown("##### ⚡ **Intraday Option Strike Recommendation (Dhan API — MIS Exit by 15:15 PM IST)**")
                                
                                sel_col1, sel_col2, sel_col3 = st.columns([1.5, 1.5, 2.0])
                                with sel_col1:
                                    strike_variant = st.selectbox(
                                        "Strike Variant",
                                        ["DELTA_TARGETED", "MONEYNESS", "OI_WALL", "EXPECTED_MOVE", "CPR_PIVOT"],
                                        index=0,
                                        key=f"variant_select_{date_str}_{symbol}"
                                    )
                                with sel_col2:
                                    expiry_choice = st.selectbox(
                                        "Expiry Selection",
                                        ["Current Weekly", "Next Weekly", "Monthly Expiry"],
                                        index=0,
                                        key=f"expiry_select_{date_str}_{symbol}"
                                    )
                                    expiry_map = {"Current Weekly": "WEEKLY", "Next Weekly": "NEXT_WEEKLY", "Monthly Expiry": "MONTHLY"}
                                    selected_exp_type = expiry_map.get(expiry_choice, "WEEKLY")

                                from osse.options.expiry_manager import ExpiryManager
                                expiries_calc = ExpiryManager.calculate_all_expiries(date_str, symbol)
                                sel_exp_info = expiries_calc.get(selected_exp_type, expiries_calc["WEEKLY"])
                                exp_dte = sel_exp_info["dte_days"]
                                exp_date_val = sel_exp_info["expiry_date"]

                                last_close = float(intraday_df['Close'].iloc[-1])
                                opt_chain = get_cached_option_chain(
                                    symbol=symbol,
                                    spot_price=last_close,
                                    vix=daily_context.get('vix', 15.0),
                                    dte_days=exp_dte,
                                    expiry=exp_date_val
                                )
                                
                                direction = "UP" if last_close >= orb_stats['orb_high'] else "DOWN" if last_close <= orb_stats['orb_low'] else ("UP" if trend_arrow == "🔼" else "DOWN")
                                
                                from osse.options.strike_selector import StrikeSelector
                                selector = StrikeSelector()
                                strike_rec = selector.select_strikes(
                                    strategy_name=decision.get('recommended_strategy', 'Directional Credit Spread'),
                                    spot_price=last_close,
                                    option_chain=opt_chain,
                                    daily_context=daily_context,
                                    symbol=symbol,
                                    variant=strike_variant,
                                    expiry_type=selected_exp_type,
                                    trade_date=date_str,
                                    direction=direction,
                                    vix=daily_context.get('vix', 15.0)
                                )
                                
                                with sel_col3:
                                    prov_badge = '🟢 Dhan API Live Payload' if strike_rec['data_source'] == 'dhan_live_feed' else '🔵 Synthetic BS Engine'
                                    st.markdown(f"""
                                    <div style="font-size: 0.78rem; color: #90A4AE; text-align: right; margin-top: 26px;">
                                        Expiry: <b style="color: #00E676;">{strike_rec['expiry_formatted']}</b> ({strike_rec['dte_days']} DTE)<br>
                                        Provider: <b>{prov_badge}</b> | Depth: <b>±{strike_rec['strike_depth_used']} Strikes</b>
                                    </div>
                                    """, unsafe_allow_html=True)

                                # Render Strategy Builder Leg Matrix Table
                                table_rows = ""
                                for leg in strike_rec['legs']:
                                    action_code = "S" if leg['action'] == "SELL" else "B"
                                    action_color = "#FF5252" if action_code == "S" else "#00E676"
                                    table_rows += f"""
                                    <tr style="border-bottom: 1px solid #262B37; text-align: center; color: #ECEFF1;">
                                        <td style="padding: 8px;"><b style="background: {action_color}22; color: {action_color}; padding: 3px 8px; border-radius: 4px;">{action_code}</b></td>
                                        <td style="padding: 8px;">{strike_rec['expiry_formatted']}</td>
                                        <td style="padding: 8px; font-weight: 700; color: #FFFFFF;">{leg['strike']:.0f}</td>
                                        <td style="padding: 8px;"><b style="color: #4FC3F7;">{leg['option_type']}</b></td>
                                        <td style="padding: 8px;">1</td>
                                        <td style="padding: 8px; color: #00E676;">₹{leg['ltp']:.2f}</td>
                                        <td style="padding: 8px; color: #B0BEC5;">{leg.get('delta', 0.0):.2f}</td>
                                        <td style="padding: 8px; color: #B0BEC5;">{leg.get('iv', 0.0):.1f}%</td>
                                    </tr>
                                    """

                                matrix_html = f"""
                                <div style="background: #181C27; padding: 12px; border-radius: 8px; border: 1px solid #262B37; margin-bottom: 15px;">
                                    <div style="font-size: 0.85rem; font-weight: 600; color: #90A4AE; margin-bottom: 8px;">⚡ Strategy Leg Matrix</div>
                                    <table style="width:100%; border-collapse: collapse; background: #1E222D; border-radius: 6px; overflow: hidden; font-size: 0.82rem;">
                                        <thead>
                                            <tr style="background: #2A2E39; color: #90A4AE; text-align: center; font-size: 0.78rem;">
                                                <th style="padding: 6px;">B/S</th>
                                                <th style="padding: 6px;">Expiry</th>
                                                <th style="padding: 6px;">Strike</th>
                                                <th style="padding: 6px;">Type</th>
                                                <th style="padding: 6px;">Lot</th>
                                                <th style="padding: 6px;">Price</th>
                                                <th style="padding: 6px;">Delta</th>
                                                <th style="padding: 6px;">IV</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {table_rows}
                                        </tbody>
                                    </table>
                                </div>
                                """
                                if hasattr(st, "html"):
                                    st.html(matrix_html)
                                else:
                                    st.markdown(matrix_html, unsafe_allow_html=True)

                                # Render Quant Risk & Profit Analytics Grid
                                q1, q2, q3, q4, q5 = st.columns(5)
                                with q1:
                                    st.markdown(f"""
                                    <div class="metric-card" style="border-top: 2px solid #00E676;">
                                        <div class="metric-label">Max Profit</div>
                                        <div style="font-size: 0.92rem; font-weight: 700; color: #00E676;">₹{strike_rec.get('max_profit_inr', 0):,.2f}</div>
                                        <div style="font-size: 0.70rem; color: #90A4AE;">({strike_rec.get('max_profit_pct', 0):.2f}%)</div>
                                    </div>
                                    """, unsafe_allow_html=True)
                                with q2:
                                    st.markdown(f"""
                                    <div class="metric-card" style="border-top: 2px solid #FF5252;">
                                        <div class="metric-label">Max Loss</div>
                                        <div style="font-size: 0.92rem; font-weight: 700; color: #FF5252;">₹{strike_rec.get('max_loss_inr', 0):,.2f}</div>
                                        <div style="font-size: 0.70rem; color: #90A4AE;">({strike_rec.get('max_loss_pct', 0):.2f}%)</div>
                                    </div>
                                    """, unsafe_allow_html=True)
                                with q3:
                                    st.markdown(f"""
                                    <div class="metric-card" style="border-top: 2px solid #FFD54F;">
                                        <div class="metric-label">Risk Reward Ratio</div>
                                        <div style="font-size: 0.95rem; font-weight: 700; color: #FFFFFF;">{strike_rec.get('risk_reward_ratio', 0):.2f}</div>
                                        <div style="font-size: 0.70rem; color: #90A4AE;">Risk / Return</div>
                                    </div>
                                    """, unsafe_allow_html=True)
                                with q4:
                                    st.markdown(f"""
                                    <div class="metric-card" style="border-top: 2px solid #29B6F6;">
                                        <div class="metric-label">POP ℹ️</div>
                                        <div style="font-size: 0.95rem; font-weight: 700; color: #29B6F6;">{strike_rec.get('pop_percent', 0):.2f}%</div>
                                        <div style="font-size: 0.70rem; color: #90A4AE;">Prob of Profit</div>
                                    </div>
                                    """, unsafe_allow_html=True)
                                with q5:
                                    st.markdown(f"""
                                    <div class="metric-card" style="border-top: 2px solid #AB47BC;">
                                        <div class="metric-label">Breakeven at</div>
                                        <div style="font-size: 0.92rem; font-weight: 700; color: #FFFFFF;">{strike_rec.get('breakeven', 0):,.2f}</div>
                                        <div style="font-size: 0.70rem; color: #90A4AE;">({strike_rec.get('breakeven_dist_pct', 0):.2f}%)</div>
                                    </div>
                                    """, unsafe_allow_html=True)
                            
                            with col_right:
                                # Intraday Candlestick Chart (Height tuned for single screen)
                                fig = go.Figure(data=[go.Candlestick(x=intraday_df.index,
                                                open=intraday_df['Open'],
                                                high=intraday_df['High'],
                                                low=intraday_df['Low'],
                                                close=intraday_df['Close'])])
                                
                                fig.add_hline(y=orb_stats['orb_high'], line_dash="dash", line_color="#00E676", annotation_text="ORB High")
                                fig.add_hline(y=orb_stats['orb_low'], line_dash="dash", line_color="#FF5252", annotation_text="ORB Low")
                                if daily_context.get('cpr_pivot'):
                                    fig.add_hline(y=daily_context['cpr_pivot'], line_dash="dot", line_color="#FFD700", annotation_text="CPR Pivot")
                                
                                fig.update_layout(height=440, margin=dict(l=10, r=10, t=30, b=10), template="plotly_dark")
                                st.plotly_chart(fig, use_container_width=True)

                                # AI Chart Explainer Card
                                from osse.analysis.ai_chart_explainer import AIChartExplainer
                                ai_explanation_text = AIChartExplainer.explain_market_setup(
                                    symbol=symbol,
                                    spot_price=float(df['Close'].iloc[-1]),
                                    osse_score=score,
                                    feature_breakdown=raw_features,
                                    strategy_recommendation=decision
                                )
                                with st.expander("🤖 AI Market Setup & Chart Explanation", expanded=True):
                                    st.markdown(ai_explanation_text)

                            # Collapsible Score Breakdown at Bottom with Plotly Contribution Chart
                            with st.expander("📊 Score Point Breakdown & Quantitative Analysis", expanded=False):
                                col_b1, col_b2 = st.columns([1, 1])
                                df_breakdown = pd.DataFrame(breakdown)
                                
                                with col_b1:
                                    st.markdown("##### 📈 **Feature Point Contributions**")
                                    df_sorted = df_breakdown.sort_values('Scaled Contribution', ascending=True)
                                    fig_bar = go.Figure(go.Bar(
                                        x=df_sorted['Scaled Contribution'],
                                        y=df_sorted['Feature'],
                                        orientation='h',
                                        marker=dict(
                                            color=df_sorted['Scaled Contribution'],
                                            colorscale='Viridis',
                                            showscale=False
                                        ),
                                        text=[f"+{val:.2f}" for val in df_sorted['Scaled Contribution']],
                                        textposition='auto'
                                    ))
                                    fig_bar.update_layout(
                                        height=260,
                                        margin=dict(l=10, r=10, t=10, b=10),
                                        template="plotly_dark",
                                        xaxis_title="Points Added"
                                    )
                                    st.plotly_chart(fig_bar, use_container_width=True)
                                    
                                with col_b2:
                                    st.markdown("##### 📋 **Detailed Metrics Table**")
                                    st.dataframe(df_breakdown, height=260, use_container_width=True)

                            # Save to Database
                            from osse.data.db import DatabaseManager
                            DatabaseManager.save_analysis(date_str, symbol, raw_features, orb_stats, score, decision)
                        else:
                            st.warning("Could not calculate ORB Stats. Perhaps market wasn't open.")
                        
            except Exception as e:
                st.error(f"Error during analysis: {e}")

elif mode == "Backtest":
    st.header(f"Backtest {symbol}")
    st.info("You can run a live backtest via Dhan API (slow) or load pre-fetched historical data from the local database (fast).")
    
    data_source = st.radio("Data Source", ["Local Database (Fast)", "Live Broker API (Slow)"], horizontal=True)
    
    col_dt1, col_dt2 = st.columns(2)
    start_date = col_dt1.date_input("Start Date", datetime.today() - timedelta(days=365))
    end_date = col_dt2.date_input("End Date", datetime.today())
    
    with st.expander("Strategy Parameters", expanded=True):
        st.info("Adjust parameters here and click Run Dynamic Simulation to instantly see their impact using the local 1-minute cache.")
        
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            sl_pct = st.number_input("Stop Loss Percentage (%)", min_value=0.0, max_value=5.0, value=0.3, step=0.1, help="The percentage below the ORB High/Low to place the initial hard stop loss.")
            atr_filter = st.number_input("ATR to enter trade (Min)", min_value=0.0, max_value=200.0, value=5.0, step=1.0, help="Minimum 1-minute Average True Range (in points) required to take a trade. Filters out slow, choppy days. Average is ~6.")
            vwap_dist_filter = st.number_input("VWAP Distance (Max %)", min_value=0.0, max_value=5.0, value=0.5, step=0.1, help="Maximum percentage distance the entry price can be from the VWAP line. Filters out over-extended trades.")
            
        with col_s2:
            st.markdown("**Trailing Options**")
            enable_be = st.checkbox("Enable Trailing to Break Even", value=False, help="Moves the Stop Loss to your exact Entry Price once the trade reaches a specified profit threshold, ensuring a risk-free trade.")
            be_trigger = st.number_input("Break Even Trigger Profit (%)", min_value=0.0, max_value=5.0, value=0.3, step=0.1, help="The percentage profit the trade must hit before the Stop Loss is moved to break-even.")
            
            enable_tsl = st.checkbox("Enable Trailing Stop Loss", value=False, help="Drags the Stop Loss up behind the highest high (or lowest low) as the trade moves in your favor.")
            tsl_dist = st.number_input("Trailing Stop Distance (%)", min_value=0.0, max_value=5.0, value=0.3, step=0.1, help="The percentage distance the Stop Loss will trail behind the peak profit price.")
            tsl_trigger = st.number_input("Trailing Activation Profit (%)", min_value=0.0, max_value=5.0, value=0.5, step=0.1, help="The percentage profit the trade must hit before the Trailing Stop Loss begins tracking the price.")
            
        run_dynamic = st.button("Run Dynamic Simulation (Local Cache)", use_container_width=True)
        
    run_backtest = run_dynamic or st.button("Run Static Backtest (Database)", use_container_width=True, type="primary")
    
    if run_backtest:
        with st.spinner("Processing backtest..."):
            if data_source == "Live Broker API (Slow)":
                engine = BacktestEngine()
                results = engine.run_backtest(symbol, start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
                
                if results:
                    st.session_state['backtest_results'] = results
                else:
                    st.session_state['backtest_results'] = None
                    st.warning("No backtest results found for the given range.")
            else:
                # Load from Database
                from osse.data.db import DatabaseManager
                DatabaseManager._initialize_paths()
                if os.path.exists(DatabaseManager._score_file):
                    df_db = pd.read_parquet(DatabaseManager._score_file)
                    # Dynamic Simulation Logic
                    cache_file = os.path.join(os.path.dirname(DatabaseManager._score_file), 'intraday_cache.parquet')
                    if run_dynamic:
                        if not os.path.exists(cache_file):
                            st.warning("No intraday cache found. Please run the fetch_history_job.py script again to generate it.")
                        else:
                            st.info("Running Dynamic Simulation on Cached Intraday Data...")
                            cache_df = pd.read_parquet(cache_file)
                            
                            # We only simulate trades that were APPROVED by the decision engine
                            # AND pass our new UI filters
                            
                            for idx, row in df_db.iterrows():
                                try:
                                    if row['decision'] not in ['TRADE', 'REDUCED SIZE']:
                                        continue
                                        
                                    date_str = pd.to_datetime(row['date']).strftime('%Y-%m-%d')
                                    
                                    # Apply UI Filters
                                    atr_val = row.get('atr', 0)
                                    vwap_dist = row.get('vwap_distance', 0)
                                    
                                    if atr_val < atr_filter or vwap_dist > vwap_dist_filter:
                                        # Filtered out by UI params
                                        df_db.at[idx, 'decision'] = 'NO TRADE'
                                        df_db.at[idx, 'trade_pnl'] = 0.0
                                        continue
                                    
                                    # Retrieve 1-minute data for this day from cache
                                    day_cache = cache_df[cache_df.index.astype(str).str.contains(date_str)]
                                    if day_cache.empty:
                                        continue

                                    orb_stats = {"orb_high": row['orb_high'], "orb_low": row['orb_low']}
                                    dec_dict = {"decision": row['decision']}

                                    from osse.backtest.simulation import simulate_trade
                                    sim_res = simulate_trade(
                                        intraday_df=day_cache,
                                        orb_stats=orb_stats,
                                        decision=dec_dict,
                                        sl_buffer_pct=sl_pct / 100.0,
                                        use_trailing_sl=enable_tsl,
                                        trailing_step_pct=tsl_dist / 100.0
                                    )

                                    if "trade_pnl" in sim_res:
                                        df_db.at[idx, 'trade_pnl'] = sim_res['trade_pnl']
                                        df_db.at[idx, 'mfe'] = sim_res.get('mfe', 0.0)
                                        df_db.at[idx, 'mae'] = sim_res.get('mae', 0.0)
                                except Exception as e:
                                    import logging
                                    logging.error(f"Error simulating day {row.get('date', 'Unknown')}: {e}")
                                    continue
                                            
                            st.success("Dynamic Simulation Complete!")
                            
                    # Load into session state
                    df_db = df_db[df_db['symbol'] == symbol]
                    df_db['date_dt'] = pd.to_datetime(df_db['date']).dt.date
                    df_db = df_db[(df_db['date_dt'] >= start_date) & (df_db['date_dt'] <= end_date)]
                    
                    if not df_db.empty:
                        # Rename normalized_score to score for metrics compatibility
                        if 'normalized_score' in df_db.columns:
                            df_db = df_db.rename(columns={'normalized_score': 'score'})
                        st.session_state['backtest_results'] = df_db.to_dict('records')
                    else:
                        st.session_state['backtest_results'] = None
                        st.warning("No data found in local database for the selected date range.")
                else:
                    st.session_state['backtest_results'] = None
                    st.warning("Local database does not exist. Run the fetch_history_job.py script first.")
                
    if 'backtest_results' in st.session_state and st.session_state['backtest_results']:
        results = st.session_state['backtest_results']
        df_results = pd.DataFrame(results)
        
        metrics = MetricsCalculator.calculate_summary(results)
        
        st.subheader("Backtest & Swing Summary")
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Total Days", metrics['total_days_evaluated'])
        col2.metric("Approved Trades", metrics['trades_approved'])
        col3.metric("Win Rate", f"{metrics.get('win_rate', 0):.1f}%")
        col4.metric("Avg Score", f"{metrics['average_score']:.2f}")
        
        cumulative_pnl = df_results['trade_pnl'].sum() if 'trade_pnl' in df_results.columns else 0.0
        col5.metric("Cumulative PnL", f"{cumulative_pnl:.2f}")

        col_m1, col_m2, col_m3 = st.columns(3)
        col_m1.metric("Avg MFE (Reward)", f"{metrics.get('avg_mfe', 0):.2f} pts")
        col_m2.metric("Avg MAE (Risk)", f"{metrics.get('avg_mae', 0):.2f} pts")
        col_m3.metric("MFE/MAE Ratio", f"{metrics.get('mfe_mae_ratio', 0):.2f}x")
        
        # Equity Curve Chart
        if 'trade_pnl' in df_results.columns:
            st.subheader("Equity Curve (Cumulative P&L)")
            df_trades = df_results.dropna(subset=['trade_pnl']).copy()
            if not df_trades.empty:
                df_trades['date'] = pd.to_datetime(df_trades['date'])
                df_trades = df_trades.sort_values('date')
                df_trades['cumulative_pnl'] = df_trades['trade_pnl'].cumsum()
                
                fig_eq = go.Figure()
                fig_eq.add_trace(go.Scatter(x=df_trades['date'], y=df_trades['cumulative_pnl'], mode='lines+markers', name='Equity', line=dict(color='#00FF00')))
                fig_eq.add_hline(y=0, line_dash="dash", line_color="gray")
                fig_eq.update_layout(xaxis_title="Date", yaxis_title="Cumulative P&L (Points)", template="plotly_dark")
                st.plotly_chart(fig_eq, use_container_width=True)
            else:
                st.info("No trades executed; Equity Curve is flat.")
        
        st.subheader("Daily Results")
        st.dataframe(df_results)

elif mode == "Analytics":
    st.header(f"Feature Analytics & Correlation")
    st.info("Analyzes historical feature data from the database to identify highly correlated features.")
    
    from osse.analysis.correlation import FeatureAnalysis
    
    if st.button("Generate Correlation Matrix"):
        with st.spinner("Crunching historical data..."):
            corr = FeatureAnalysis.get_correlation_matrix(symbol=symbol)
            if corr.empty:
                st.error("No historical data found in the database. Run a backtest first to populate data.")
            else:
                st.subheader("Pearson Correlation Matrix")
                
                # Plotly heatmap
                fig = go.Figure(data=go.Heatmap(
                    z=corr.values,
                    x=corr.columns,
                    y=corr.columns,
                    colorscale='RdBu',
                    zmin=-1, zmax=1
                ))
                st.plotly_chart(fig, use_container_width=True)
                
                redundant = FeatureAnalysis.check_redundant_features(corr)
                if redundant:
                    st.warning("⚠️ High Correlation Detected! Consider adjusting YAML weights to prevent double-counting.")
                    for f1, f2, val in redundant:
                        st.markdown(f"- **{f1}** and **{f2}** (Correlation: {val:.2f})")
                else:
                    st.success("No highly redundant features detected (threshold = 0.75).")

elif mode == "DEX + VP 70% Engine":
    st.header(f"⚡ DEX + Volume Profile 70% Options Strategy Engine — {symbol}")
    st.caption("Confluence Scanner, Delta Exposure Overlay, Value Area (VAH/VAL/POC), and Multi-Variant Options Setups.")

    from osse.data.dhan_mcp import DhanMCPCollector
    from osse.engine.dex_calculator import DEXCalculator
    from osse.features.volume_profile import VolumeProfileCalculator
    from osse.engine.confluence import ConfluenceEngine
    from osse.engine.strategy_variants import StrategyVariantSelector
    from osse.engine.risk_manager import RiskManager

    collector = DhanMCPCollector()
    chain_df = collector.fetch_option_chain(symbol=symbol)
    candles_df = collector.fetch_chart_candles(symbol=symbol)

    spot_val = float(candles_df['close'].iloc[-1]) if ('close' in candles_df.columns and not candles_df.empty) else 24500.0
    step_val = 100.0 if "BANK" in symbol.upper() else 50.0

    dex_calc = DEXCalculator()
    dex_res = dex_calc.calculate_dex(chain_df, spot_price=spot_val)

    vp_calc = VolumeProfileCalculator()
    vp_res = vp_calc.calculate_volume_profile(candles_df)

    # Sidebar score input for DEX + VP mode
    input_osse_score = st.sidebar.slider("OSSE Base Score Context", min_value=0.0, max_value=100.0, value=75.0, step=1.0, help="Base OSSE score used for Unified Score weighting")

    conf_engine = ConfluenceEngine(step_size=step_val)
    conf_res = conf_engine.calculate_confluence_score(dex_data=dex_res, vp_data=vp_res, spot_price=spot_val)
    unified_res = conf_engine.calculate_unified_score(osse_score=input_osse_score, confluence_score=conf_res.get("confluence_score", 0.0))

    # Top Metrics Header
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Spot Price", f"₹{spot_val:,.2f}")
    m2.metric("Confluence Score", f"{conf_res.get('confluence_score', 0):.0f} / 100", delta=conf_res.get("tier"))
    m3.metric("Unified Score", f"{unified_res.get('unified_score', 0):.1f}", delta=unified_res.get("tier"))
    m4.metric("Call Wall", f"₹{dex_res.get('call_wall', 0):,.0f}")
    m5.metric("Put Support", f"₹{dex_res.get('put_support', 0):,.0f}")
    m6.metric("Delta Flip", f"₹{dex_res.get('delta_flip', 0):,.0f}")

    st.markdown("---")

    # Layout Tabs for DEX & Volume Profile Visualizations & Variants
    tab_dex, tab_vp, tab_variants, tab_risk = st.tabs([
        "📊 DEX positioning Overlay",
        "📈 Volume Profile 70%",
        "🎯 Recommended Strategy Variants",
        "🛡️ Risk & Position Calculator"
    ])

    with tab_dex:
        st.subheader("Delta Exposure (DEX) per Strike")
        if dex_res.get("strike_dex_table"):
            dex_df = pd.DataFrame(dex_res["strike_dex_table"])
            fig_dex = go.Figure()
            fig_dex.add_trace(go.Bar(x=dex_df["strike_price"], y=dex_df["ce_dex"], name="CE DEX", marker_color="#00E676"))
            fig_dex.add_trace(go.Bar(x=dex_df["strike_price"], y=dex_df["pe_dex"], name="PE DEX", marker_color="#FF1744"))
            fig_dex.add_trace(go.Scatter(x=dex_df["strike_price"], y=dex_df["net_dex"], name="Net DEX", mode="lines+markers", line=dict(color="#FFD600", width=2)))
            
            fig_dex.add_vline(x=dex_res["call_wall"], line_dash="dash", line_color="#00E676", annotation_text="Call Wall")
            fig_dex.add_vline(x=dex_res["put_support"], line_dash="dash", line_color="#FF1744", annotation_text="Put Support")
            fig_dex.add_vline(x=dex_res["delta_flip"], line_dash="dot", line_color="#FFD600", annotation_text="Delta Flip")

            fig_dex.update_layout(title="Dealer Delta Exposure (DEX)", xaxis_title="Strike Price", yaxis_title="Delta Exposure (₹)", template="plotly_dark", barmode="group")
            st.plotly_chart(fig_dex, use_container_width=True)

            col_d1, col_d2 = st.columns(2)
            col_d1.markdown(f"**Call Wall (Max CE DEX):** ₹{dex_res['call_wall']} (₹{dex_res['max_ce_dex']:,.0f})")
            col_d2.markdown(f"**Put Support (Max PE DEX):** ₹{dex_res['put_support']} (₹{dex_res['max_pe_dex']:,.0f})")
            st.caption(f"DEX Clusters (>50% max DEX): {dex_res.get('dex_clusters')}")

    with tab_vp:
        st.subheader("Volume Profile 70% Value Area Distribution")
        col_v1, col_v2, col_v3 = st.columns(3)
        col_v1.metric("VAH (Value Area High)", f"₹{vp_res.get('vah', 0):,.2f}")
        col_v2.metric("POC (Point of Control)", f"₹{vp_res.get('poc', 0):,.2f}")
        col_v3.metric("VAL (Value Area Low)", f"₹{vp_res.get('val', 0):,.2f}")

        if vp_res.get("profile_bins"):
            pb_df = pd.DataFrame(vp_res["profile_bins"])
            colors = ["#00E676" if in_va else "#37474F" for in_va in pb_df["in_value_area"]]
            fig_vp = go.Figure()
            fig_vp.add_trace(go.Bar(y=pb_df["price"], x=pb_df["volume"], orientation="h", marker_color=colors, name="Volume"))
            fig_vp.add_hline(y=vp_res["vah"], line_dash="dash", line_color="#00E676", annotation_text="VAH (70%)")
            fig_vp.add_hline(y=vp_res["poc"], line_dash="solid", line_color="#FFD600", annotation_text="POC")
            fig_vp.add_hline(y=vp_res["val"], line_dash="dash", line_color="#FF1744", annotation_text="VAL (70%)")
            fig_vp.update_layout(title="Session Volume Profile 70%", yaxis_title="Price Level", xaxis_title="Traded Volume", template="plotly_dark")
            st.plotly_chart(fig_vp, use_container_width=True)

    with tab_variants:
        st.subheader("DEX + VP 70% Strategy Variants Scanner")
        selector = StrategyVariantSelector(symbol=symbol, step_size=step_val)
        variants = selector.select_variants(
            spot_price=spot_val,
            confluence_data=conf_res,
            dex_data=dex_res,
            vp_data=vp_res
        )

        for var in variants:
            with st.expander(f"📌 {var.get('variant_name', 'Strategy Setup')} [{var.get('tier', 'Tier')}]", expanded=True):
                col_a, col_b = st.columns([2, 1])
                with col_a:
                    st.markdown(f"**Type:** {var.get('type')}")
                    st.markdown(f"**Expiry Preference:** {var.get('expiry_preference')}")
                    st.markdown(f"**Recommended Capital Risk:** {var.get('recommended_risk_pct')}%")
                    st.markdown("**Entry Conditions:**")
                    for cond in var.get("entry_conditions", []):
                        st.markdown(f"- {cond}")
                    st.markdown("**Exit Conditions:**")
                    for ex in var.get("exit_conditions", []):
                        st.markdown(f"- {ex}")
                with col_b:
                    st.markdown("### Strike Legs")
                    for k, v in var.items():
                        if "strike" in k:
                            st.write(f"**{k.replace('_', ' ').title()}:** ₹{v}")

    with tab_risk:
        st.subheader("Dynamic Position Sizing & Drawdown Manager")
        cap = st.number_input("Account Capital (₹)", value=1000000.0, step=50000.0)
        risk_p = st.slider("Target Risk per Trade (%)", 0.5, 3.0, 2.0, 0.1)
        max_l = st.number_input("Max Loss per Lot (₹)", value=15000.0, step=1000.0)
        curr_dd = st.slider("Current Strategy Drawdown (%)", 0.0, 20.0, 0.0, 0.5)

        rm = RiskManager()
        size_res = rm.calculate_position_size(
            capital=cap,
            risk_percent=risk_p,
            max_loss_per_lot=max_l,
            current_drawdown_pct=curr_dd
        )

        col_r1, col_r2, col_r3 = st.columns(3)
        col_r1.metric("Allowed Lots", size_res["allowed_lots"])
        col_r2.metric("Allocated Risk Capital", f"₹{size_res['risk_capital_allocated']:,.2f}")
        col_r3.metric("Drawdown Protocol Level", size_res["drawdown_protocol"]["level"])

        st.info(f"**Action Protocol:** {size_res['drawdown_protocol']['action']}")

elif mode == "Live Monitor":
    st.header(f"Live Monitor — {symbol}")
    st.caption("Snapshots are produced by the Dhan option-chain monitor scheduler during market hours.")

    col_lm1, col_lm2, col_lm3 = st.columns([2, 2, 1])
    with col_lm1:
        monitor_symbol = symbol.replace("^NSEI", "NIFTY").replace("^NSEBANK", "BANKNIFTY").replace(".NS", "").split(" ")[0].upper()
    with col_lm2:
        auto_refresh = st.toggle("Auto-refresh every 60s", value=False)
    with col_lm3:
        if st.button("Refresh Now", type="primary"):
            st.session_state["live_monitor_refresh"] = True

    if auto_refresh:
        st_autorefresh = st.empty()
        st.markdown(
            """
            <script>
            setTimeout(function() { window.location.reload(); }, 60000);
            </script>
            """,
            unsafe_allow_html=True
        )

    if st.session_state.get("live_monitor_refresh", False):
        with st.spinner("Polling Dhan option chain..."):
            try:
                scheduler = MonitorScheduler(symbols=[monitor_symbol], stale_seconds=1)
                scheduler.poll_symbol(monitor_symbol)
                st.session_state["live_monitor_refresh"] = False
                st.success("Snapshot refreshed.")
            except Exception as e:
                st.error(f"Refresh failed: {e}")

    snapshots = DatabaseManager.load_monitor_snapshots(symbol=monitor_symbol, limit=50)

    if snapshots.empty:
        st.warning(
            f"No monitor snapshots found for {monitor_symbol}. "
            "Run the scheduler with: `PYTHONPATH=src python src/osse/monitoring/scheduler.py --once --ignore-hours`"
        )
    else:
        latest = snapshots.iloc[0]

        col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)
        col_m1.metric("Last Update", str(latest["timestamp"]).split(".")[0])
        col_m2.metric("Spot", f"₹{latest['spot_price']:,.2f}")
        col_m3.metric("Confluence", f"{latest['confluence_score']:.1f}")
        col_m4.metric("Unified Score", f"{latest['unified_score']:.1f}")
        col_m5.metric("Alerts", int(latest["alert_count"]))

        st.markdown("---")

        tab_alerts, tab_history, tab_variants = st.tabs(["🚨 Signal Alerts", "📜 Snapshot History", "🎯 Latest Variants"])

        with tab_alerts:
            # Load the raw insights JSON from the most recent snapshot row is not stored in Parquet,
            # so we re-run the insights generator on the latest Dhan JSON files for alert detail.
            try:
                from osse.data.dhan_mcp import DhanMCPCollector
                collector = DhanMCPCollector()
                chain_df = collector.fetch_option_chain(symbol=monitor_symbol)
                candles_df = collector.fetch_chart_candles(symbol=monitor_symbol)
                spot = float(latest["spot_price"]) if latest["spot_price"] > 0 else float(chain_df["strike_price"].median())
                insights = InsightsGenerator(osse_score=float(latest["osse_score"])).generate_insights(
                    symbol=monitor_symbol,
                    spot_price=spot,
                    chain_df=chain_df,
                    candles_df=candles_df,
                    osse_score=float(latest["osse_score"])
                )
                alerts = insights.get("signal_alerts", [])
                if not alerts:
                    st.info("No active signal alerts for the latest snapshot.")
                else:
                    for alert in alerts:
                        level = alert.get("level", "INFO")
                        color = "#00E676" if level == "HIGH" else "#FFAB00" if level == "MEDIUM" else "#90A4AE"
                        st.markdown(
                            f"<div style='border-left: 4px solid {color}; padding: 8px 12px; margin: 6px 0; background: rgba(255,255,255,0.05);'>"
                            f"<strong>{level}</strong> — {alert.get('message', '')}</div>",
                            unsafe_allow_html=True
                        )
            except Exception as e:
                st.error(f"Could not render alerts: {e}")

        with tab_history:
            st.subheader("Recent Snapshots")
            display_df = snapshots[[
                "timestamp", "spot_price", "confluence_score", "unified_score",
                "pcr_oi", "vix", "alert_count"
            ]].copy()
            display_df.columns = ["Time", "Spot", "Confluence", "Unified", "PCR", "VIX", "Alerts"]
            st.dataframe(display_df, use_container_width=True)

            if len(snapshots) > 1:
                fig_hist = go.Figure()
                fig_hist.add_trace(go.Scatter(
                    x=snapshots["timestamp"][::-1],
                    y=snapshots["confluence_score"][::-1],
                    mode="lines+markers",
                    name="Confluence Score",
                    line=dict(color="#00E676")
                ))
                fig_hist.add_trace(go.Scatter(
                    x=snapshots["timestamp"][::-1],
                    y=snapshots["unified_score"][::-1],
                    mode="lines+markers",
                    name="Unified Score",
                    line=dict(color="#FFD600")
                ))
                fig_hist.update_layout(
                    title="Confluence & Unified Score History",
                    xaxis_title="Time",
                    yaxis_title="Score",
                    template="plotly_dark",
                    height=350
                )
                st.plotly_chart(fig_hist, use_container_width=True)

        with tab_variants:
            st.subheader("Latest Recommended Variants")
            try:
                from osse.data.dhan_mcp import DhanMCPCollector
                collector = DhanMCPCollector()
                chain_df = collector.fetch_option_chain(symbol=monitor_symbol)
                candles_df = collector.fetch_chart_candles(symbol=monitor_symbol)
                spot = float(latest["spot_price"]) if latest["spot_price"] > 0 else float(chain_df["strike_price"].median())
                insights = InsightsGenerator(osse_score=float(latest["osse_score"])).generate_insights(
                    symbol=monitor_symbol,
                    spot_price=spot,
                    chain_df=chain_df,
                    candles_df=candles_df,
                    osse_score=float(latest["osse_score"])
                )
                variants = insights.get("summary_report", {}).get("variants", [])
                if not variants:
                    st.info("No active strategy variants for the latest snapshot.")
                else:
                    for var in variants:
                        with st.expander(f"📌 {var.get('variant_name', 'Strategy')} [{var.get('tier', 'Tier')}]", expanded=False):
                            st.markdown(f"**Type:** {var.get('type', '')}")
                            st.markdown(f"**Expiry:** {var.get('expiry_preference', '')}")
                            st.markdown(f"**Risk:** {var.get('recommended_risk_pct', '')}%")
                            for k, v in var.items():
                                if "strike" in k:
                                    st.write(f"**{k.replace('_', ' ').title()}:** ₹{v}")
            except Exception as e:
                st.error(f"Could not render variants: {e}")
