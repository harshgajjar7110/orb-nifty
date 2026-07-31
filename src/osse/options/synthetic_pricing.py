import math
import logging
from typing import Dict, Tuple, Optional

logger = logging.getLogger(__name__)

def norm_cdf(x: float) -> float:
    """Standard Normal Cumulative Distribution Function N(x)"""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def norm_pdf(x: float) -> float:
    """Standard Normal Probability Density Function n(x)"""
    return (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * x * x)

class BlackScholesEngine:
    """
    Quantitative Black-Scholes-Merton (BSM) Option Pricing and Greeks Engine.
    Allows synthetic pricing of expired index options (NIFTY/BANKNIFTY/FINNIFTY/SENSEX)
    without requiring expensive historical option chain intraday tick datasets.
    """

    @staticmethod
    def get_skew_adjusted_iv(vix: float, strike: float, spot: float, option_type: str = "PE", skew_factor: float = 0.15) -> float:
        """
        Applies a parametric Volatility Skew adjustment to base VIX.
        OTM Puts typically exhibit elevated IV (Put Skew).
        """
        base_sigma = vix / 100.0
        if spot <= 0 or strike <= 0:
            return base_sigma

        moneyness = (spot - strike) / spot

        # Put skew: OTM Puts (strike < spot) have higher IV
        if option_type.upper() in ["PE", "PUT"]:
            if strike < spot:
                skew_adjustment = skew_factor * abs(moneyness)
                return max(0.05, base_sigma * (1.0 + skew_adjustment))
        # Call skew: ITM Calls or OTM Calls
        elif option_type.upper() in ["CE", "CALL"]:
            if strike > spot:
                skew_adjustment = (skew_factor * 0.5) * abs(moneyness)
                return max(0.05, base_sigma * (1.0 + skew_adjustment))

        return max(0.05, base_sigma)

    @staticmethod
    def calculate_d1_d2(S: float, K: float, T: float, r: float, sigma: float) -> Tuple[float, float]:
        """
        Calculates d1 and d2 for Black-Scholes equation.
        S: Spot price
        K: Strike price
        T: Time to expiry in years (e.g. 5 days / 365 = 0.0137)
        r: Risk-free rate (e.g. 0.065 for 6.5%)
        sigma: Implied Volatility (e.g. 0.15 for 15%)
        """
        if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
            return 0.0, 0.0

        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        return d1, d2

    @staticmethod
    def price_option(S: float, K: float, T: float, r: float = 0.065, sigma: float = 0.15, option_type: str = "PE") -> float:
        """
        Calculates Black-Scholes Call or Put price.
        """
        if T <= 0:
            # Intrinsic value at expiry
            if option_type.upper() in ["CE", "CALL"]:
                return max(0.0, S - K)
            else:
                return max(0.0, K - S)

        d1, d2 = BlackScholesEngine.calculate_d1_d2(S, K, T, r, sigma)

        if option_type.upper() in ["CE", "CALL"]:
            price = S * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)
        else: # Put
            price = K * math.exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1)

        return max(0.0, price)

    @staticmethod
    def calculate_delta(S: float, K: float, T: float, r: float = 0.065, sigma: float = 0.15, option_type: str = "PE") -> float:
        """
        Calculates Option Delta (rate of change of option price w.r.t. spot price).
        Call Delta: [0, +1], Put Delta: [-1, 0]
        """
        if T <= 0:
            if option_type.upper() in ["CE", "CALL"]:
                return 1.0 if S > K else 0.0
            else:
                return -1.0 if S < K else 0.0

        d1, _ = BlackScholesEngine.calculate_d1_d2(S, K, T, r, sigma)

        if option_type.upper() in ["CE", "CALL"]:
            return norm_cdf(d1)
        else:
            return norm_cdf(d1) - 1.0

    @staticmethod
    def calculate_greeks(S: float, K: float, T: float, r: float = 0.065, sigma: float = 0.15, option_type: str = "PE") -> Dict[str, float]:
        """
        Calculates Price, Delta, Gamma, Theta (per day), and Vega (per 1% IV change).
        """
        if T <= 0:
            price = max(0.0, S - K) if option_type.upper() in ["CE", "CALL"] else max(0.0, K - S)
            return {"price": price, "delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}

        d1, d2 = BlackScholesEngine.calculate_d1_d2(S, K, T, r, sigma)
        pdf_d1 = norm_pdf(d1)

        # Price
        price = BlackScholesEngine.price_option(S, K, T, r, sigma, option_type)

        # Delta
        delta = norm_cdf(d1) if option_type.upper() in ["CE", "CALL"] else norm_cdf(d1) - 1.0

        # Gamma (same for call and put)
        gamma = pdf_d1 / (S * sigma * math.sqrt(T))

        # Theta (annual converted to daily by dividing by 365)
        term1 = -(S * pdf_d1 * sigma) / (2.0 * math.sqrt(T))
        if option_type.upper() in ["CE", "CALL"]:
            theta_annual = term1 - r * K * math.exp(-r * T) * norm_cdf(d2)
        else:
            theta_annual = term1 + r * K * math.exp(-r * T) * norm_cdf(-d2)
        theta_daily = theta_annual / 365.0

        # Vega (change per 1% change in sigma, i.e., sigma + 0.01)
        vega_annual = S * math.sqrt(T) * pdf_d1
        vega_1pct = vega_annual / 100.0

        return {
            "price": round(price, 2),
            "delta": round(delta, 4),
            "gamma": round(gamma, 6),
            "theta": round(theta_daily, 2),
            "vega": round(vega_1pct, 2)
        }


class CreditSpreadPricer:
    """
    Synthetic Credit Spread Pricing Engine for Option Sellers.
    Models Bull Put Spreads (Sell OTM Put, Buy further OTM Put) and
    Bear Call Spreads (Sell OTM Call, Buy further OTM Call).
    """

    @staticmethod
    def select_strikes_by_delta(spot: float, T: float, vix: float, target_sell_delta: float = -0.20,
                                spread_width_pct: float = 0.01, option_type: str = "PE",
                                strike_step: int = 50, r: float = 0.065) -> Tuple[int, int]:
        """
        Finds the nearest exchange strike corresponding to target Delta.
        Example: NIFTY at 24000 -> Target Put Delta -0.20 -> Sell 23700 PE, Buy 23450 PE.
        """
        # Step down/up in strike increments (50 for NIFTY, 100 for BANKNIFTY)
        is_put = option_type.upper() in ["PE", "PUT"]
        step = -strike_step if is_put else strike_step

        best_sell_strike = int(round(spot / strike_step) * strike_step)
        closest_delta_diff = 999.0

        # Scan 20 strikes out
        for i in range(1, 25):
            candidate_strike = int(round((spot + i * step) / strike_step) * strike_step)
            sigma = BlackScholesEngine.get_skew_adjusted_iv(vix, candidate_strike, spot, option_type)
            delta = BlackScholesEngine.calculate_delta(spot, candidate_strike, T, r, sigma, option_type)

            diff = abs(delta - target_sell_delta)
            if diff < closest_delta_diff:
                closest_delta_diff = diff
                best_sell_strike = candidate_strike

        # Buy wing strike based on spread width
        width_points = spot * spread_width_pct
        hedge_step_multiplier = max(1, int(round(width_points / strike_step)))
        best_buy_strike = best_sell_strike - (hedge_step_multiplier * strike_step) if is_put else best_sell_strike + (hedge_step_multiplier * strike_step)

        return int(best_sell_strike), int(best_buy_strike)

    @staticmethod
    def calculate_credit_spread_quote(spot: float, sell_strike: float, buy_strike: float, T: float,
                                       vix: float, option_type: str = "PE", r: float = 0.065) -> Dict:
        """
        Prices a Credit Spread synthetically and returns net credit, max loss, risk-reward ratio, and net Greeks.
        """
        sell_sigma = BlackScholesEngine.get_skew_adjusted_iv(vix, sell_strike, spot, option_type)
        buy_sigma = BlackScholesEngine.get_skew_adjusted_iv(vix, buy_strike, spot, option_type)

        sell_greeks = BlackScholesEngine.calculate_greeks(spot, sell_strike, T, r, sell_sigma, option_type)
        buy_greeks = BlackScholesEngine.calculate_greeks(spot, buy_strike, T, r, buy_sigma, option_type)

        # Net Credit received = Premium(Sell) - Premium(Buy)
        net_credit = sell_greeks["price"] - buy_greeks["price"]

        # Spread Width
        width = abs(sell_strike - buy_strike)
        max_loss = max(0.0, width - net_credit)

        # Net Delta, Theta, Vega for position (Short sell leg, Long buy leg)
        net_delta = (-1.0 * sell_greeks["delta"]) + (1.0 * buy_greeks["delta"])
        net_theta = (-1.0 * sell_greeks["theta"]) + (1.0 * buy_greeks["theta"]) # Positive for option sellers!
        net_vega = (-1.0 * sell_greeks["vega"]) + (1.0 * buy_greeks["vega"])   # Negative (short volatility)

        return {
            "spot": spot,
            "sell_strike": sell_strike,
            "buy_strike": buy_strike,
            "sell_premium": sell_greeks["price"],
            "buy_premium": buy_greeks["price"],
            "net_credit": round(net_credit, 2),
            "max_loss": round(max_loss, 2),
            "risk_reward_ratio": round(max_loss / net_credit, 2) if net_credit > 0 else 0.0,
            "net_delta": round(net_delta, 4),
            "net_theta_daily": round(net_theta, 2),
            "net_vega": round(net_vega, 2)
        }
