import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

import pytest

from osse.data.greeks_parser import GreeksParser, GreeksExposure
from osse.data.webbridge_collector import WebBridgeCollector


@pytest.fixture
def delta_snapshot():
    path = "/tmp/dhan_dashboard_snapshot.json"
    if not os.path.exists(path):
        pytest.skip("Saved Delta snapshot not found")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def gamma_snapshot():
    path = "/tmp/dhan_gamma_snapshot.json"
    if not os.path.exists(path):
        pytest.skip("Saved Gamma snapshot not found")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_flatten_snapshot_text(delta_snapshot):
    wb = WebBridgeCollector(daemon_url="")
    texts = wb.flatten_snapshot_text(delta_snapshot)
    assert len(texts) > 100
    assert any("Delta Exposure" in t for t in texts)


def test_parse_delta_snapshot(delta_snapshot):
    wb = WebBridgeCollector(daemon_url="")
    texts = wb.flatten_snapshot_text(delta_snapshot)
    ge = GreeksParser.parse_snapshot_text(texts, exposure_type="delta", symbol_hint="NIFTY")

    assert isinstance(ge, GreeksExposure)
    assert ge.exposure_type == "delta"
    assert ge.symbol == "NIFTY"
    assert ge.spot_price is not None
    assert ge.spot_price > 23000
    assert ge.total_call is not None
    assert ge.total_call_unit == "Cr"
    assert ge.total_put is not None
    assert ge.ratio is not None
    assert ge.sentiment != ""
    assert "call_resistance" in ge.levels
    assert "put_support" in ge.levels


def test_parse_gamma_snapshot(gamma_snapshot):
    wb = WebBridgeCollector(daemon_url="")
    texts = wb.flatten_snapshot_text(gamma_snapshot)
    ge = GreeksParser.parse_snapshot_text(texts, exposure_type="gamma", symbol_hint="NIFTY")

    assert ge.exposure_type == "gamma"
    assert ge.symbol == "NIFTY"
    assert ge.spot_price is not None
    assert ge.total_call is not None
    assert ge.ratio is not None
    assert "peak_positive" in ge.levels
    assert "peak_negative" in ge.levels


def test_parse_page_text():
    text = """
    Nifty 50
    24317.15
    Total Call: 34,43,508.36 Cr
    Total Put: -28,14,502.27 Cr
    Total Net:  6,29,006.10 Cr
    DEX Ratio: 0.82 (Bullish)
    Peak -Delta exp 24050 - 91,936.73 Cr
    """
    ge = GreeksParser.parse_page_text(text, exposure_type="delta", symbol_hint="NIFTY")
    assert ge.symbol == "NIFTY"
    assert ge.spot_price == 24317.15
    assert ge.total_call == 3443508.36
    assert ge.total_put == -2814502.27
    assert ge.ratio == 0.82
    assert ge.sentiment == "Bullish"
