import os
import math
import yaml
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
from osse.options.expiry_manager import ExpiryManager

logger = logging.getLogger(__name__)

class StrikeSelector:
    """
    Quantitative Multi-Variant Strike Selection Engine.
    Consumes live option chain data from Dhan API (or synthetic Black-Scholes generator)
    and selects precise option strike legs for quantitative strategies.
    """

    def __init__(self, config_path: str = None):
        if config_path is None:
            # Default location
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
            config_path = os.path.join(base_dir, "config", "strike_rules.yaml")

        self.config = self._load_config(config_path)

    def _load_config(self, path: str) -> dict:
        """Loads strike rules config with fallback defaults if missing."""
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    return yaml.safe_load(f)
            except Exception as e:
                logger.warning(f"Failed to load strike_rules.yaml: {e}. Using fallback defaults.")

        return {
            "default_variant": "DELTA_TARGETED",
            "dhan_strike_depth": 20,
            "symbols": {
                "NIFTY": {"step_size": 50, "lot_size": 75},
                "BANKNIFTY": {"step_size": 100, "lot_size": 30},
                "FINNIFTY": {"step_size": 50, "lot_size": 25},
                "SENSEX": {"step_size": 100, "lot_size": 10},
                "DEFAULT": {"step_size": 50, "lot_size": 75}
            },
            "delta_targets": {
                "credit_spread": {"short_target": 0.20, "long_target": 0.08},
                "debit_spread": {"long_target": 0.55, "short_target": 0.30},
                "straddle_strangle": {"delta_target": 0.50}
            }
        }

    def _get_symbol_metadata(self, symbol: str) -> dict:
        symbols_config = self.config.get("symbols", {})
        sym_upper = symbol.upper()
        
        if "NIFTY" in sym_upper and "BANK" not in sym_upper and "FIN" not in sym_upper:
            return symbols_config.get("NIFTY", {"step_size": 50, "lot_size": 75})
        elif "BANK" in sym_upper:
            return symbols_config.get("BANKNIFTY", {"step_size": 100, "lot_size": 30})
        elif "FIN" in sym_upper:
            return symbols_config.get("FINNIFTY", {"step_size": 50, "lot_size": 25})
        elif "SENSEX" in sym_upper:
            return symbols_config.get("SENSEX", {"step_size": 100, "lot_size": 10})

        if sym_upper in symbols_config:
            return symbols_config[sym_upper]
        clean_sym = sym_upper.split(".")[0].replace("^", "").strip()
        if clean_sym in symbols_config:
            return symbols_config[clean_sym]

        return symbols_config.get("DEFAULT", {"step_size": 50, "lot_size": 75})

    def _ensure_chain(self, symbol: str, spot_price: float, option_chain: Optional[dict], vix: float = 15.0) -> dict:
        """Ensures option chain is available; generates synthetic if missing."""
        if option_chain and "chain" in option_chain and option_chain["chain"]:
            return option_chain
        from osse.data.collector import DataCollector
        return DataCollector.generate_synthetic_option_chain(spot_price, symbol, vix=vix, strike_depth=20)

    # ----------------------------------------------------
    # VARIANT 1: MONEYNESS / DISTANCE-BASED
    # ----------------------------------------------------
    def select_by_moneyness(self, strategy_name: str, spot_price: float, chain_data: dict, symbol: str, direction: str = "UP") -> dict:
        meta = self._get_symbol_metadata(symbol)
        step = meta.get("step_size", 50)
        atm = round(spot_price / step) * step
        
        chain_map = {item["strike"]: item for item in chain_data.get("chain", [])}

        def get_leg_info(strike: float, opt_type: str, action: str):
            if strike in chain_map:
                opt = chain_map[strike][opt_type.lower()]
                return {
                    "action": action,
                    "option_type": opt_type.upper(),
                    "strike": float(strike),
                    "ltp": opt.get("ltp", 0.0),
                    "delta": opt.get("delta", 0.0),
                    "theta": opt.get("theta", 0.0),
                    "gamma": opt.get("gamma", 0.0),
                    "vega": opt.get("vega", 0.0),
                    "iv": opt.get("iv", 0.0),
                    "oi": opt.get("oi", 0),
                    "security_id": opt.get("security_id", 0),
                    "source": chain_data.get("data_source", "dhan_live_feed")
                }
            else:
                # Black-Scholes estimate if strike falls outside chain range
                from osse.options.synthetic_pricing import BlackScholesEngine
                price = BlackScholesEngine.price_option(spot_price, strike, T=4.0/365.0, sigma=0.15, option_type=opt_type)
                delta = BlackScholesEngine.calculate_delta(spot_price, strike, T=4.0/365.0, sigma=0.15, option_type=opt_type)
                return {
                    "action": action,
                    "option_type": opt_type.upper(),
                    "strike": float(strike),
                    "ltp": round(price, 2),
                    "delta": round(delta, 3),
                    "oi": 0,
                    "source": "synthetic_bs_engine"
                }

        legs = []
        if "Credit Spread" in strategy_name:
            if direction.upper() == "UP":  # Bullish -> Sell PE Spread
                short_k = atm - step
                long_k = atm - (3 * step)
                legs = [get_leg_info(short_k, "PE", "SELL"), get_leg_info(long_k, "PE", "BUY")]
            else:  # Bearish -> Sell CE Spread
                short_k = atm + step
                long_k = atm + (3 * step)
                legs = [get_leg_info(short_k, "CE", "SELL"), get_leg_info(long_k, "CE", "BUY")]

        elif "Debit" in strategy_name or "Breakout Swing" in strategy_name:
            if direction.upper() == "UP":  # Bullish -> Buy CE Spread
                long_k = atm
                short_k = atm + (2 * step)
                legs = [get_leg_info(long_k, "CE", "BUY"), get_leg_info(short_k, "CE", "SELL")]
            else:  # Bearish -> Buy PE Spread
                long_k = atm
                short_k = atm - (2 * step)
                legs = [get_leg_info(long_k, "PE", "BUY"), get_leg_info(short_k, "PE", "SELL")]

        elif "Iron Condor" in strategy_name or "Strangle" in strategy_name:
            # Sell OTM PE + Buy Far OTM PE, Sell OTM CE + Buy Far OTM CE
            sp_pe, lp_pe = atm - (2 * step), atm - (4 * step)
            sp_ce, lp_ce = atm + (2 * step), atm + (4 * step)
            legs = [
                get_leg_info(sp_pe, "PE", "SELL"), get_leg_info(lp_pe, "PE", "BUY"),
                get_leg_info(sp_ce, "CE", "SELL"), get_leg_info(lp_ce, "CE", "BUY")
            ]
        else: # Straddle / Iron Fly
            legs = [
                get_leg_info(atm, "CE", "SELL"), get_leg_info(atm, "PE", "SELL"),
                get_leg_info(atm + (2 * step), "CE", "BUY"), get_leg_info(atm - (2 * step), "PE", "BUY")
            ]

        return legs

    # ----------------------------------------------------
    # VARIANT 2: DELTA-TARGETED
    # ----------------------------------------------------
    def select_by_delta(self, strategy_name: str, spot_price: float, chain_data: dict, symbol: str, direction: str = "UP") -> dict:
        chain = chain_data.get("chain", [])
        if not chain:
            return self.select_by_moneyness(strategy_name, spot_price, chain_data, symbol, direction)

        def find_closest_delta_strike(opt_type: str, target_abs_delta: float, condition=None):
            best_item = None
            best_diff = 999.0
            for item in chain:
                k = item["strike"]
                opt = item[opt_type.lower()]
                delta_val = abs(opt.get("delta", 0.0))
                
                if condition and not condition(k):
                    continue

                diff = abs(delta_val - target_abs_delta)
                if diff < best_diff:
                    best_diff = diff
                    best_item = (k, opt)

            if best_item:
                k, opt = best_item
                return {
                    "strike": k,
                    "ltp": opt.get("ltp", 0.0),
                    "delta": opt.get("delta", 0.0),
                    "theta": opt.get("theta", 0.0),
                    "gamma": opt.get("gamma", 0.0),
                    "vega": opt.get("vega", 0.0),
                    "iv": opt.get("iv", 0.0),
                    "oi": opt.get("oi", 0),
                    "security_id": opt.get("security_id", 0),
                    "source": chain_data.get("data_source", "dhan_live_feed")
                }
            return None

        legs = []
        if "Credit Spread" in strategy_name:
            if direction.upper() == "UP": # Sell Put Credit Spread
                # Short PE target delta = 0.20 (strike < spot), Long PE target delta = 0.08
                short_leg = find_closest_delta_strike("PE", 0.20, lambda k: k < spot_price)
                long_leg = find_closest_delta_strike("PE", 0.08, lambda k: short_leg and k < short_leg["strike"])
                if short_leg and long_leg:
                    legs = [
                        {"action": "SELL", "option_type": "PE", **short_leg},
                        {"action": "BUY", "option_type": "PE", **long_leg}
                    ]
            else: # Sell Call Credit Spread
                short_leg = find_closest_delta_strike("CE", 0.20, lambda k: k > spot_price)
                long_leg = find_closest_delta_strike("CE", 0.08, lambda k: short_leg and k > short_leg["strike"])
                if short_leg and long_leg:
                    legs = [
                        {"action": "SELL", "option_type": "CE", **short_leg},
                        {"action": "BUY", "option_type": "CE", **long_leg}
                    ]

        elif "Debit" in strategy_name or "Breakout Swing" in strategy_name:
            if direction.upper() == "UP": # Buy Call Debit Spread
                long_leg = find_closest_delta_strike("CE", 0.55, lambda k: k <= spot_price * 1.005)
                short_leg = find_closest_delta_strike("CE", 0.30, lambda k: long_leg and k > long_leg["strike"])
                if long_leg and short_leg:
                    legs = [
                        {"action": "BUY", "option_type": "CE", **long_leg},
                        {"action": "SELL", "option_type": "CE", **short_leg}
                    ]
            else: # Buy Put Debit Spread
                long_leg = find_closest_delta_strike("PE", 0.55, lambda k: k >= spot_price * 0.995)
                short_leg = find_closest_delta_strike("PE", 0.30, lambda k: long_leg and k < long_leg["strike"])
                if long_leg and short_leg:
                    legs = [
                        {"action": "BUY", "option_type": "PE", **long_leg},
                        {"action": "SELL", "option_type": "PE", **short_leg}
                    ]

        if not legs: # Fallback to moneyness if delta search finds no match
            return self.select_by_moneyness(strategy_name, spot_price, chain_data, symbol, direction)

        return legs

    # ----------------------------------------------------
    # VARIANT 3: OPEN INTEREST (OI) WALL ALIGNED
    # ----------------------------------------------------
    def select_by_oi_walls(self, strategy_name: str, spot_price: float, chain_data: dict, symbol: str, direction: str = "UP") -> dict:
        chain = chain_data.get("chain", [])
        if not chain:
            return self.select_by_moneyness(strategy_name, spot_price, chain_data, symbol, direction)

        max_ce_oi, max_ce_strike = 0, spot_price * 1.02
        max_pe_oi, max_pe_strike = 0, spot_price * 0.98

        for item in chain:
            k = item["strike"]
            ce_oi = item["ce"].get("oi", 0)
            pe_oi = item["pe"].get("oi", 0)

            if k >= spot_price and ce_oi > max_ce_oi:
                max_ce_oi = ce_oi
                max_ce_strike = k

            if k <= spot_price and pe_oi > max_pe_oi:
                max_pe_oi = pe_oi
                max_pe_strike = k

        meta = self._get_symbol_metadata(symbol)
        step = meta.get("step_size", 50)
        chain_map = {item["strike"]: item for item in chain}

        def make_leg(strike: float, opt_type: str, action: str):
            if strike in chain_map:
                opt = chain_map[strike][opt_type.lower()]
                return {
                    "action": action, "option_type": opt_type.upper(), "strike": float(strike),
                    "ltp": opt.get("ltp", 0.0), "delta": opt.get("delta", 0.0), "oi": opt.get("oi", 0),
                    "source": chain_data.get("data_source", "synthetic_bs_engine")
                }
            else:
                return {
                    "action": action, "option_type": opt_type.upper(), "strike": float(strike),
                    "ltp": 15.0, "delta": 0.05, "oi": 0, "source": "synthetic_bs_engine"
                }

        legs = []
        if "Credit Spread" in strategy_name:
            if direction.upper() == "UP": # Put Credit Spread -> Position Short PE at or below Put OI wall
                short_k = max_pe_strike
                long_k = short_k - (2 * step)
                legs = [make_leg(short_k, "PE", "SELL"), make_leg(long_k, "PE", "BUY")]
            else: # Call Credit Spread -> Position Short CE at or above Call OI wall
                short_k = max_ce_strike
                long_k = short_k + (2 * step)
                legs = [make_leg(short_k, "CE", "SELL"), make_leg(long_k, "CE", "BUY")]
        else:
            return self.select_by_delta(strategy_name, spot_price, chain_data, symbol, direction)

        return legs

    # ----------------------------------------------------
    # VARIANT 4: PREMIUM & EXPECTED MOVE TARGET ($1\sigma$)
    # ----------------------------------------------------
    def select_by_premium_or_expected_move(self, strategy_name: str, spot_price: float, chain_data: dict, symbol: str, vix: float = 15.0, direction: str = "UP") -> dict:
        # Expected Move = Spot * (VIX / 100) * sqrt(1/365)
        em = spot_price * (vix / 100.0) * math.sqrt(1.0 / 365.0)
        upper_em = spot_price + em
        lower_em = spot_price - em

        meta = self._get_symbol_metadata(symbol)
        step = meta.get("step_size", 50)

        chain_map = {item["strike"]: item for item in chain_data.get("chain", [])}

        def make_leg(strike: float, opt_type: str, action: str):
            if strike in chain_map:
                opt = chain_map[strike][opt_type.lower()]
                return {
                    "action": action, "option_type": opt_type.upper(), "strike": float(strike),
                    "ltp": opt.get("ltp", 0.0), "delta": opt.get("delta", 0.0), "oi": opt.get("oi", 0),
                    "source": chain_data.get("data_source", "synthetic_bs_engine")
                }
            else:
                return {
                    "action": action, "option_type": opt_type.upper(), "strike": float(strike),
                    "ltp": 10.0, "delta": 0.04, "oi": 0, "source": "synthetic_bs_engine"
                }

        legs = []
        if direction.upper() == "UP":
            # Put Credit Spread outside lower 1-SD Expected Move
            short_k = round(lower_em / step) * step
            long_k = short_k - (2 * step)
            legs = [make_leg(short_k, "PE", "SELL"), make_leg(long_k, "PE", "BUY")]
        else:
            # Call Credit Spread outside upper 1-SD Expected Move
            short_k = round(upper_em / step) * step
            long_k = short_k + (2 * step)
            legs = [make_leg(short_k, "CE", "SELL"), make_leg(long_k, "CE", "BUY")]

        return legs

    # ----------------------------------------------------
    # VARIANT 5: TECHNICAL CPR & PIVOT ALIGNED
    # ----------------------------------------------------
    def select_by_pivot_levels(self, strategy_name: str, spot_price: float, chain_data: dict, symbol: str, daily_context: dict = None, direction: str = "UP") -> dict:
        ctx = daily_context or {}
        cpr_bc = ctx.get("cpr_bc", spot_price * 0.99)
        cpr_tc = ctx.get("cpr_tc", spot_price * 1.01)

        meta = self._get_symbol_metadata(symbol)
        step = meta.get("step_size", 50)

        chain_map = {item["strike"]: item for item in chain_data.get("chain", [])}

        def make_leg(strike: float, opt_type: str, action: str):
            if strike in chain_map:
                opt = chain_map[strike][opt_type.lower()]
                return {
                    "action": action, "option_type": opt_type.upper(), "strike": float(strike),
                    "ltp": opt.get("ltp", 0.0), "delta": opt.get("delta", 0.0), "oi": opt.get("oi", 0),
                    "source": chain_data.get("data_source", "synthetic_bs_engine")
                }
            else:
                return {
                    "action": action, "option_type": opt_type.upper(), "strike": float(strike),
                    "ltp": 12.0, "delta": 0.05, "oi": 0, "source": "synthetic_bs_engine"
                }

        legs = []
        if direction.upper() == "UP":
            # Put Credit Spread: Short strike at or below CPR BC
            short_k = math.floor(min(cpr_bc, spot_price - step) / step) * step
            long_k = short_k - (2 * step)
            legs = [make_leg(short_k, "PE", "SELL"), make_leg(long_k, "PE", "BUY")]
        else:
            # Call Credit Spread: Short strike at or above CPR TC
            short_k = math.ceil(max(cpr_tc, spot_price + step) / step) * step
            long_k = short_k + (2 * step)
            legs = [make_leg(short_k, "CE", "SELL"), make_leg(long_k, "CE", "BUY")]

        return legs

    # ----------------------------------------------------
    # VARIANT 6: GEX + DEX ALIGNED
    # ----------------------------------------------------
    def select_by_gex_dex_aligned(
        self,
        strategy_name: str,
        spot_price: float,
        chain_data: dict,
        symbol: str = "NIFTY",
        direction: str = "UP",
        dex_data: Optional[dict] = None,
        gex_data: Optional[dict] = None,
    ) -> dict:
        """
        Selects strikes by aligning with Delta/Gamma exposure levels scraped
        from Dhan Dext.  Short legs are placed just inside dealer support /
        resistance zones; long legs are the standard 2-step OTM hedge.
        """
        meta = self._get_symbol_metadata(symbol)
        step = meta.get("step_size", 50)
        dex = dex_data or {}
        gex = gex_data or {}

        exposure_rules = self.config.get("exposure_driven_rules", {})
        min_otm_steps = exposure_rules.get("min_otm_steps", 1)
        hedge_mult = exposure_rules.get("hedge_step_multiplier", 2)

        # UP = Bullish / Put Credit Spread -> short PE at support.
        if direction.upper() == "UP":
            candidates = [
                dex.get("put_support"),
                dex.get("delta_flip"),
                gex.get("gamma_flip"),
                gex.get("peak_neg_gamma_strike"),
            ]
            valid = [c for c in candidates if isinstance(c, (int, float)) and c > 0]
            anchor = max(valid) if valid else round(spot_price / step) * step
            short_k = round(anchor / step) * step
            # Ensure short PE is at least min_otm_steps below spot.
            max_support = spot_price - (min_otm_steps * step)
            if short_k >= max_support:
                short_k = max_support
            long_k = short_k - (hedge_mult * step)
            opt_type = "PE"
            action = "SELL"
            hedge_action = "BUY"
        else:
            # DOWN = Bearish / Call Credit Spread -> short CE at resistance.
            candidates = [
                dex.get("call_wall"),
                gex.get("peak_pos_gamma_strike"),
                dex.get("delta_flip"),
                gex.get("gamma_flip"),
            ]
            valid = [c for c in candidates if isinstance(c, (int, float)) and c > 0]
            anchor = min(valid) if valid else round(spot_price / step) * step
            short_k = round(anchor / step) * step
            # Ensure short CE is at least min_otm_steps above spot.
            min_resistance = spot_price + (min_otm_steps * step)
            if short_k <= min_resistance:
                short_k = min_resistance
            long_k = short_k + (hedge_mult * step)
            opt_type = "CE"
            action = "SELL"
            hedge_action = "BUY"

        chain_map = {item["strike"]: item for item in chain_data.get("chain", [])}

        def make_leg(strike: float, act: str):
            if strike in chain_map:
                opt = chain_map[strike][opt_type.lower()]
                return {
                    "action": act,
                    "option_type": opt_type.upper(),
                    "strike": float(strike),
                    "ltp": opt.get("ltp", 0.0),
                    "delta": opt.get("delta", 0.0),
                    "theta": opt.get("theta", 0.0),
                    "gamma": opt.get("gamma", 0.0),
                    "vega": opt.get("vega", 0.0),
                    "iv": opt.get("iv", 0.0),
                    "oi": opt.get("oi", 0),
                    "security_id": opt.get("security_id", 0),
                    "source": chain_data.get("data_source", "dhan_live_feed"),
                }
            from osse.options.synthetic_pricing import BlackScholesEngine
            price = BlackScholesEngine.price_option(
                spot_price, strike, T=4.0 / 365.0, sigma=0.15, option_type=opt_type
            )
            delta = BlackScholesEngine.calculate_delta(
                spot_price, strike, T=4.0 / 365.0, sigma=0.15, option_type=opt_type
            )
            return {
                "action": act,
                "option_type": opt_type.upper(),
                "strike": float(strike),
                "ltp": round(price, 2),
                "delta": round(delta, 3),
                "oi": 0,
                "source": "synthetic_bs_engine",
            }

        return [make_leg(short_k, action), make_leg(long_k, hedge_action)]

    # ----------------------------------------------------
    # MASTER ENTRYPOINT
    # ----------------------------------------------------
    def select_strikes(
        self,
        strategy_name: str,
        spot_price: float,
        option_chain: Optional[dict] = None,
        daily_context: Optional[dict] = None,
        symbol: str = "NIFTY",
        variant: str = "DELTA_TARGETED",
        expiry_type: str = "WEEKLY",
        trade_date: Optional[str] = None,
        direction: str = "UP",
        vix: float = 15.0,
        dex_data: Optional[dict] = None,
        gex_data: Optional[dict] = None,
    ) -> dict:
        """
        Master selection method executing the designated strike selection variant & expiry selection.
        Returns a complete quantitative payload with leg details, credit/debit calculation, expiry date, and DTE.
        """
        # Expiry Selection Calculation
        expiries = ExpiryManager.calculate_all_expiries(trade_date or datetime.now().strftime("%Y-%m-%d"), symbol)
        e_type_upper = expiry_type.upper() if expiry_type.upper() in expiries else "WEEKLY"
        selected_exp_info = expiries[e_type_upper]

        # Pass DTE to synthetic chain if chain is empty
        chain_data = self._ensure_chain(symbol, spot_price, option_chain, vix=vix)
        v_upper = variant.upper()

        if v_upper == "MONEYNESS":
            legs = self.select_by_moneyness(strategy_name, spot_price, chain_data, symbol, direction)
        elif v_upper == "OI_WALL":
            legs = self.select_by_oi_walls(strategy_name, spot_price, chain_data, symbol, direction)
        elif v_upper == "EXPECTED_MOVE" or v_upper == "PREMIUM_TARGET":
            legs = self.select_by_premium_or_expected_move(strategy_name, spot_price, chain_data, symbol, vix=vix, direction=direction)
        elif v_upper == "CPR_PIVOT":
            legs = self.select_by_pivot_levels(strategy_name, spot_price, chain_data, symbol, daily_context, direction)
        elif v_upper == "GEX_DEX_ALIGNED":
            legs = self.select_by_gex_dex_aligned(
                strategy_name, spot_price, chain_data, symbol, direction,
                dex_data=dex_data, gex_data=gex_data
            )
        else:  # Default to DELTA_TARGETED
            legs = self.select_by_delta(strategy_name, spot_price, chain_data, symbol, direction)

        # Calculate Net Credit / Debit & Max Risk Metrics
        net_premium = 0.0
        for leg in legs:
            if leg["action"] == "SELL":
                net_premium += leg["ltp"]
            else:
                net_premium -= leg["ltp"]

        meta = self._get_symbol_metadata(symbol)
        lot_size = meta.get("lot_size", 75)

        is_credit = net_premium > 0
        net_amount = abs(net_premium)

        # Calculate exact Wing Widths by Option Type (CE vs CE, PE vs PE)
        call_sells = [leg["strike"] for leg in legs if leg["action"] == "SELL" and leg["option_type"] == "CE"]
        call_buys = [leg["strike"] for leg in legs if leg["action"] == "BUY" and leg["option_type"] == "CE"]
        put_sells = [leg["strike"] for leg in legs if leg["action"] == "SELL" and leg["option_type"] == "PE"]
        put_buys = [leg["strike"] for leg in legs if leg["action"] == "BUY" and leg["option_type"] == "PE"]

        call_wing = max([abs(s - b) for s in call_sells for b in call_buys], default=0.0)
        put_wing = max([abs(s - b) for s in put_sells for b in put_buys], default=0.0)
        wing_width = max(call_wing, put_wing)

        if is_credit:
            # Credit Strategy (Credit Spread, Iron Condor, Iron Fly)
            max_profit_pts = net_amount
            if wing_width > 0:
                max_loss_pts = max(0.0, wing_width - net_amount)
            else:
                max_loss_pts = spot_price * 0.10  # Fallback estimate for naked short
        else:
            # Debit Strategy (Debit Spread, Long Options)
            max_loss_pts = net_amount
            if wing_width > 0:
                max_profit_pts = max(0.0, wing_width - net_amount)
            else:
                max_profit_pts = net_amount * 2.0

        max_profit_inr = round(max_profit_pts * lot_size, 2)
        max_loss_inr = round(max_loss_pts * lot_size, 2)
        rr_ratio = round(max_loss_inr / max_profit_inr, 2) if max_profit_inr > 0 else 0.0

        # Estimated NSE/Dhan SPAN + Exposure Margin Required for Option Spreads (~₹41,580 for NIFTY)
        base_margin = 35000.0 if "BANK" in symbol else 41580.0
        margin_required = max(base_margin, max_loss_inr + (wing_width * lot_size * 0.5))

        # Return on Capital & Risk on Capital percentages (Sensibull / Dhan Standard)
        max_profit_pct = round((max_profit_inr / margin_required * 100.0), 2)
        max_loss_pct = round((max_loss_inr / margin_required * 100.0), 2)

        # Breakeven Calculation
        # Breakeven Calculation
        short_strikes = [leg["strike"] for leg in legs if leg["action"] == "SELL"]
        short_strike = short_strikes[0] if short_strikes else spot_price

        if direction.upper() == "UP":
            breakeven = short_strike - net_amount if is_credit else short_strike + net_amount
        else:
            breakeven = short_strike + net_amount if is_credit else short_strike - net_amount

        breakeven_dist_pct = abs(spot_price - breakeven) / spot_price * 100.0

        # Probability of Profit (POP) Calculation via BSM CDF
        from osse.options.synthetic_pricing import norm_cdf
        dte_days = selected_exp_info["dte_days"]
        T = max(1.0 / 365.0, dte_days / 365.0)
        sigma = max(0.05, vix / 100.0)
        
        if breakeven > 0 and spot_price > 0:
            d2 = (math.log(spot_price / breakeven) + (0.065 - 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
            pop_pct = norm_cdf(d2) * 100.0 if direction.upper() == "UP" else norm_cdf(-d2) * 100.0
        else:
            pop_pct = 70.0

        return {
            "variant_used": v_upper,
            "expiry_type": e_type_upper,
            "expiry_date": selected_exp_info["expiry_date"],
            "expiry_formatted": selected_exp_info["formatted_date"],
            "dte_days": selected_exp_info["dte_days"],
            "available_expiries": expiries,
            "symbol": symbol,
            "spot_price": spot_price,
            "lot_size": lot_size,
            "strategy": strategy_name,
            "direction": direction,
            "data_source": chain_data.get("data_source", "synthetic_bs_engine"),
            "legs": legs,
            "net_premium_pts": round(net_premium, 2),
            "net_premium_inr": round(net_premium * lot_size, 2),
            "is_credit": is_credit,
            "max_profit_inr": max_profit_inr,
            "max_profit_pct": max_profit_pct,
            "max_loss_inr": max_loss_inr,
            "max_loss_pct": max_loss_pct,
            "margin_required": round(margin_required, 2),
            "risk_reward_ratio": rr_ratio,
            "pop_percent": round(pop_pct, 2),
            "breakeven": round(breakeven, 2),
            "breakeven_dist_pct": round(breakeven_dist_pct, 2),
            "strike_depth_used": chain_data.get("strike_depth", 20)
        }
