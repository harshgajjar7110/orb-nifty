import pytest
from osse.options.synthetic_pricing import BlackScholesEngine, CreditSpreadPricer, norm_cdf, norm_pdf

def test_norm_functions():
    assert round(norm_cdf(0.0), 2) == 0.50
    assert round(norm_cdf(1.96), 3) == 0.975
    assert round(norm_pdf(0.0), 4) == 0.3989

def test_black_scholes_pricing():
    # Spot 24000, ATM 24000 PE, 5 days to expiry (5/365), r=6.5%, IV=15%
    S = 24000.0
    K = 24000.0
    T = 5.0 / 365.0
    r = 0.065
    sigma = 0.15

    call_p = BlackScholesEngine.price_option(S, K, T, r, sigma, "CE")
    put_p = BlackScholesEngine.price_option(S, K, T, r, sigma, "PE")

    assert call_p > 0
    assert put_p > 0
    # Call Delta should be approx 0.50 for ATM
    call_delta = BlackScholesEngine.calculate_delta(S, K, T, r, sigma, "CE")
    put_delta = BlackScholesEngine.calculate_delta(S, K, T, r, sigma, "PE")

    assert 0.45 <= call_delta <= 0.58
    assert -0.55 <= put_delta <= -0.42

def test_credit_spread_pricing():
    S = 24000.0
    T = 4.0 / 365.0 # 4 DTE
    vix = 14.5

    # Target -0.20 Delta Put Spread
    sell_k, buy_k = CreditSpreadPricer.select_strikes_by_delta(S, T, vix, target_sell_delta=-0.20, option_type="PE", strike_step=50)

    assert sell_k < S
    assert buy_k < sell_k

    quote = CreditSpreadPricer.calculate_credit_spread_quote(S, sell_k, buy_k, T, vix, option_type="PE")

    assert quote["net_credit"] > 0
    assert quote["max_loss"] > 0
    assert quote["net_theta_daily"] > 0 # Positive Theta decay for option seller!
