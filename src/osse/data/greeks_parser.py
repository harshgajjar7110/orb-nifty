"""
Greeks Parser Module for OSSE.

Normalizes raw text extracted via Kimi WebBridge (or any DOM scraper) from the
Dhan Dext dashboard into a structured GreeksExposure snapshot.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class GreeksExposure:
    """Structured representation of Delta/Gamma exposure read from Dhan Dext."""

    exposure_type: str = ""  # "delta" or "gamma"
    symbol: str = ""
    spot_price: Optional[float] = None
    expiry: Optional[str] = None
    dte: Optional[int] = None
    atm_iv: Optional[float] = None
    atm_iv_chg_pct: Optional[float] = None
    pcr: Optional[float] = None
    market_lot: Optional[int] = None
    max_pain: Optional[float] = None

    total_call: Optional[float] = None
    total_call_unit: str = ""
    total_put: Optional[float] = None
    total_put_unit: str = ""
    total_net: Optional[float] = None
    total_net_unit: str = ""
    ratio: Optional[float] = None
    sentiment: str = ""

    levels: Dict[str, Any] = field(default_factory=dict)
    raw_texts: List[str] = field(default_factory=list)
    timestamp: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "exposure_type": self.exposure_type,
            "symbol": self.symbol,
            "spot_price": self.spot_price,
            "expiry": self.expiry,
            "dte": self.dte,
            "atm_iv": self.atm_iv,
            "atm_iv_chg_pct": self.atm_iv_chg_pct,
            "pcr": self.pcr,
            "market_lot": self.market_lot,
            "max_pain": self.max_pain,
            "total_call": self.total_call,
            "total_call_unit": self.total_call_unit,
            "total_put": self.total_put,
            "total_put_unit": self.total_put_unit,
            "total_net": self.total_net,
            "total_net_unit": self.total_net_unit,
            "ratio": self.ratio,
            "sentiment": self.sentiment,
            "levels": self.levels,
            "timestamp": self.timestamp,
        }


class GreeksParser:
    """
    Parses flattened accessibility text from the Dhan Dext dashboard into
    ``GreeksExposure`` objects.
    """

    # Symbol detection helpers
    SYMBOL_PATTERNS = {
        "NIFTY": re.compile(r"Nifty 50|NIFTY 50", re.IGNORECASE),
        "BANKNIFTY": re.compile(r"BANKNIFTY|Bank Nifty|NIFTY BANK", re.IGNORECASE),
        "FINNIFTY": re.compile(r"FINNIFTY|Fin Nifty", re.IGNORECASE),
        "SENSEX": re.compile(r"SENSEX", re.IGNORECASE),
    }

    # Number formats: Indian grouping (34,43,508.36) and western (3,443,508.36)
    NUMBER_RE = re.compile(r"-?\s*[0-9,]+\.\d+|\s*-?\s*[0-9,]+")
    MONEY_RE = re.compile(r"(-?\s*[0-9,]+\.\d+|-?\s*[0-9,]+)\s*(Cr|Lakh|Lk|K)?", re.IGNORECASE)

    @staticmethod
    def _clean_number(text: str) -> str:
        return text.replace(",", "").replace(" ", "")

    @classmethod
    def _extract_number(cls, text: str) -> Optional[float]:
        m = cls.NUMBER_RE.search(text)
        if not m:
            return None
        try:
            return float(cls._clean_number(m.group(0)))
        except ValueError:
            return None

    @classmethod
    def _parse_money(cls, text: str) -> Tuple[Optional[float], str]:
        """
        Parses a money string such as ``"34,43,508.36 Cr"`` and returns the
        numeric value plus the unit (``Cr``, ``Lakh``, or ``raw``).
        """
        text = text.strip()
        m = cls.MONEY_RE.search(text)
        if not m:
            return None, "raw"
        num_str, unit = m.group(1), m.group(2)
        try:
            value = float(cls._clean_number(num_str))
        except ValueError:
            return None, "raw"
        unit = (unit or "raw").strip().capitalize()
        if unit.lower() in ("lk", "lakh"):
            unit = "Lakh"
        return value, unit

    @classmethod
    def _find_next_value(
        cls,
        texts: List[str],
        labels: List[str],
        start: int = 0,
    ) -> Tuple[Optional[str], int]:
        """
        Finds the value associated with one of ``labels``.

        Handles two accessibility-tree layouts:
          1. Label and value are separate text nodes.
          2. Label and value are in the same text node (e.g. ``"Total Call: 34,43,508.36 Cr"``).

        Longer labels are checked first to avoid substring false matches
        (e.g. ``"ATM IV:"`` matching ``"ATM IV Chg%:"``).
        """
        sorted_labels = sorted(
            [lbl.lower().replace(":", "").strip() for lbl in labels],
            key=len,
            reverse=True,
        )
        i = start
        while i < len(texts):
            t = texts[i].strip()
            t_clean = t.lower().replace(":", "").strip()

            matched_label = None
            for lbl in sorted_labels:
                if t_clean.startswith(lbl) or t_clean == lbl:
                    matched_label = lbl
                    break

            if matched_label is None:
                i += 1
                continue

            # Inline value: everything after the label in the same node.
            if len(t_clean) > len(matched_label):
                remainder_clean = t_clean[len(matched_label):].strip()
                if re.search(r"\d", remainder_clean):
                    # Return the original-cased remainder for sentiment parsing.
                    remainder_orig = t[len(matched_label):].strip()
                    return remainder_orig, i

            # Separate value node.
            for j in range(i + 1, min(i + 6, len(texts))):
                candidate = texts[j].strip()
                if re.search(r"\d", candidate):
                    return candidate, j
            return None, i

        return None, -1

    @classmethod
    def _detect_symbol(cls, texts: List[str]) -> str:
        for t in texts:
            for sym, pat in cls.SYMBOL_PATTERNS.items():
                if pat.search(t):
                    return sym
        return ""

    @classmethod
    def parse_snapshot_text(
        cls,
        texts: List[str],
        exposure_type: str = "delta",
        symbol_hint: str = "",
    ) -> GreeksExposure:
        """
        Parses a list of visible text strings (from a WebBridge accessibility
        snapshot) into a ``GreeksExposure``.
        """
        texts = [t.strip() for t in texts if t and t.strip()]
        exposure_type = exposure_type.lower()
        ge = GreeksExposure(
            exposure_type=exposure_type,
            symbol=symbol_hint or cls._detect_symbol(texts),
            raw_texts=texts[:200],  # keep a sample for debugging
        )

        # Spot price: first numeric following the symbol name
        if ge.symbol:
            pat = cls.SYMBOL_PATTERNS.get(ge.symbol)
            for i, t in enumerate(texts):
                if pat and pat.search(t):
                    for j in range(i + 1, min(i + 5, len(texts))):
                        val = cls._extract_number(texts[j])
                        if val is not None and val > 1000:
                            ge.spot_price = val
                            break
                    if ge.spot_price:
                        break

        # Generic scalar metrics
        metric_map = {
            "atm_iv": ["ATM IV:"],
            "atm_iv_chg_pct": ["ATM IV Chg%:"],
            "pcr": ["PCR:"],
            "market_lot": ["Market Lot:"],
            "dte": ["Days to Expiry:"],
            "max_pain": ["Max Pain:"],
        }
        for attr, labels in metric_map.items():
            val_text, _ = cls._find_next_value(texts, labels)
            if val_text:
                num = cls._extract_number(val_text)
                if num is not None:
                    setattr(ge, attr, num)

        # Totals
        call_label = ["Total Call:"]
        put_label = ["Total Put:"]
        net_label = ["Total Net:"]
        ratio_label = ["DEX Ratio:"] if exposure_type == "delta" else ["GEX Ratio:"]

        call_text, _ = cls._find_next_value(texts, call_label)
        if call_text:
            ge.total_call, ge.total_call_unit = cls._parse_money(call_text)

        put_text, _ = cls._find_next_value(texts, put_label)
        if put_text:
            ge.total_put, ge.total_put_unit = cls._parse_money(put_text)

        net_text, _ = cls._find_next_value(texts, net_label)
        if net_text:
            ge.total_net, ge.total_net_unit = cls._parse_money(net_text)

        ratio_text, _ = cls._find_next_value(texts, ratio_label)
        if ratio_text:
            # e.g. "0.82 (Bullish)"
            m = re.search(r"(\d+\.\d+)", ratio_text)
            if m:
                ge.ratio = float(m.group(1))
            sentiment_match = re.search(r"\(([^)]+)\)", ratio_text)
            if sentiment_match:
                ge.sentiment = sentiment_match.group(1).strip()

        # Key levels (best effort)
        level_labels = {
            "delta": {
                "peak_negative": "Peak -Delta exp",
                "call_resistance": "Call Resistance",
                "flip": "Delta Flip",
                "put_support": "Put Support",
                "peak_positive": "Peak +Delta exp",
            },
            "gamma": {
                "peak_negative": "Peak -Gamma exp",
                "put_support": "Put Support",
                "flip": "Gamma Flip",
                "call_resistance": "Call Resistance",
                "peak_positive": "Peak +Gamma exp",
            },
        }.get(exposure_type, {})

        ge.levels = cls._extract_levels(texts, level_labels)
        return ge

    @classmethod
    def _extract_levels(
        cls,
        texts: List[str],
        level_labels: Dict[str, str],
    ) -> Dict[str, Any]:
        """
        Extracts strike + exposure for labelled levels from the Dhan Dext
        accessibility tree.

        The tree interleaves duplicate labels and often splits a single value
        across nodes (e.g. ``"-91,936.73"``, ``"Cr"``).  The heuristic below
        picks the first pure integer as the strike, skips its duplicate and
        stray ``-`` / ``Cr`` tokens, then reads up to three money values that
        follow: the primary side exposure, the opposite-side exposure, and the
        net exposure.
        """
        levels: Dict[str, Any] = {}
        for key, label in level_labels.items():
            label_lower = label.lower()
            for i, t in enumerate(texts):
                if label_lower in t.lower():
                    strike: Optional[float] = None
                    exposures: List[Tuple[Optional[float], str]] = []
                    for j in range(i + 1, min(i + 14, len(texts))):
                        candidate = texts[j].strip()
                        if candidate in ("-", "Cr"):
                            continue

                        # Strike is the first pure integer after the label.
                        if strike is None and re.fullmatch(r"-?\s*[0-9,]+", candidate):
                            try:
                                strike = float(candidate.replace(",", ""))
                            except ValueError:
                                continue
                            continue

                        if strike is None:
                            continue

                        # Skip duplicate strike values and chart noise.
                        try:
                            if float(candidate.replace(",", "")) == strike:
                                continue
                        except ValueError:
                            pass

                        # Try to parse a money value; if the unit is split
                        # across the next node ("Cr"/"Lakh"), combine them.
                        peek = candidate
                        if j + 1 < len(texts):
                            nxt = texts[j + 1].strip()
                            if re.match(r"^(Cr|Lakh|Lk)$", nxt, re.IGNORECASE):
                                peek = f"{candidate} {nxt}"

                        val, unit = cls._parse_money(peek)
                        if val is not None and abs(val - strike) > 0.01:
                            exposures.append((val, unit))
                            if len(exposures) >= 3:
                                break

                    if strike is not None:
                        primary = exposures[0] if exposures else (None, "")
                        levels[key] = {
                            "strike": strike,
                            "exposure": primary[0],
                            "exposure_unit": primary[1],
                        }
                        if len(exposures) >= 3:
                            levels[key]["net_exposure"] = exposures[2][0]
                            levels[key]["net_exposure_unit"] = exposures[2][1]
                    break
        return levels

    @classmethod
    def parse_page_text(
        cls,
        page_text: str,
        exposure_type: str = "delta",
        symbol_hint: str = "",
    ) -> GreeksExposure:
        """
        Fallback parser that works on a plain string such as
        ``document.body.innerText``.
        """
        lines = [ln.strip() for ln in page_text.splitlines() if ln.strip()]
        return cls.parse_snapshot_text(lines, exposure_type, symbol_hint)

    @classmethod
    def parse_webbridge_response(
        cls,
        response: Dict[str, Any],
        exposure_type: str = "delta",
        symbol_hint: str = "",
    ) -> GreeksExposure:
        """
        Parses a WebBridge ``snapshot`` or ``evaluate`` response.  If the
        response contains an accessibility tree, it is flattened first;
        otherwise the ``value`` string is treated as raw page text.
        """
        data = response.get("data") or response
        if "tree" in data:
            from osse.data.webbridge_collector import WebBridgeCollector

            texts = WebBridgeCollector(daemon_url="").flatten_snapshot_text(response)
            return cls.parse_snapshot_text(texts, exposure_type, symbol_hint)

        value = data.get("value") or ""
        return cls.parse_page_text(str(value), exposure_type, symbol_hint)
