import os
import math
import pandas as pd
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pre-existing internally provided datasets.
#
# These are local files shipped with the repository (Parquet under ``data/`` and
# the root ``NIFTY 50.csv``). They take priority over any network source so the
# engine can run fully offline against known-good data.
# ---------------------------------------------------------------------------
_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data")
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# NIFTY 50 is the only supported index.
NIFTY_ALIASES = {"^NSEI", "NIFTY"}

# Symbol -> candidate internal dataset files (checked in order, first hit wins).
INTERNAL_DATASETS = {
    "^NSEI": ["nifty_1min_august_2026.parquet", "nifty_15min.parquet", os.path.join(_REPO_ROOT, "NIFTY 50.csv")],
    "NIFTY": ["nifty_1min_august_2026.parquet", "nifty_15min.parquet", os.path.join(_REPO_ROOT, "NIFTY 50.csv")],
}


class DataCollector:
    """
    Responsible for sourcing 1-minute historical / intraday OHLCV and daily
    context data for the NIFTY 50 index only.

    Data sourcing is restricted to the three supported channels:

    1. **Internal datasets** — local Parquet / CSV files shipped with the repo.
    2. **Y Finance (``yfinance``)** — the primary sanctioned network source.
    3. **jugaad-data** — fallback for Indian-equity / index daily history.
    """

    @staticmethod
    def is_supported_symbol(symbol: str) -> bool:
        """Return True if ``symbol`` is a supported NIFTY 50 alias."""
        return symbol.upper() in NIFTY_ALIASES

    @staticmethod
    def _yfinance_symbol(symbol: str) -> str:
        if not DataCollector.is_supported_symbol(symbol):
            raise ValueError(f"Unsupported symbol '{symbol}'. Only NIFTY 50 (^NSEI / NIFTY) is supported.")
        return "^NSEI"

    # ------------------------------------------------------------------
    # Internal datasets
    # ------------------------------------------------------------------
    @staticmethod
    def _load_internal_intraday(symbol: str, start_date: str, end_date: str, interval: str) -> pd.DataFrame:
        """Load intraday candles for ``symbol`` from a bundled local dataset.

        Returns an empty DataFrame when no internal dataset is available for the
        symbol or when the requested date range is outside the dataset.
        """
        candidates = INTERNAL_DATASETS.get(symbol, [])
        for rel in candidates:
            path = rel if os.path.isabs(rel) else os.path.join(_DATA_DIR, rel)
            if not os.path.exists(path):
                continue
            try:
                if path.lower().endswith(".parquet"):
                    df = pd.read_parquet(path)
                else:
                    df = pd.read_csv(path)

                # Normalise to the OSSE standard frame.
                df = DataCollector._normalise_frame(df)

                # Filter to the requested window.
                start_dt = pd.Timestamp(start_date)
                # Internal datasets may only cover a limited window.
                mask = (df.index >= start_dt) & (df.index <= (pd.Timestamp(end_date) + timedelta(days=1)))
                window = df.loc[mask]
                if window.empty:
                    continue

                if interval != "1m" and interval not in ("1min",):
                    rule = {"5m": "5min", "5min": "5min", "15m": "15min", "15min": "15min"}.get(interval, "1min")
                    window = window.resample(rule).agg({
                        "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"
                    }).dropna()

                return window
            except Exception as e:
                logger.warning(f"Failed to load internal dataset {path}: {e}")
                continue
        return pd.DataFrame()

    @staticmethod
    def _normalise_frame(df: pd.DataFrame) -> pd.DataFrame:
        """Coerce a raw internal dataset into the OSSE OHLCV frame."""
        df = df.copy()
        # Resolve a datetime index from common column names.
        date_col = None
        for cand in ("Datetime", "datetime", "Date", "date", "TIMESTAMP", "timestamp"):
            if cand in df.columns:
                date_col = cand
                break
        if date_col is not None:
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
            df = df.set_index(date_col)

        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index, errors="coerce")

        rename = {}
        for col in df.columns:
            low = str(col).strip().lower()
            if low in ("open",) and "Open" not in df.columns:
                rename[col] = "Open"
            elif low in ("high",) and "High" not in df.columns:
                rename[col] = "High"
            elif low in ("low",) and "Low" not in df.columns:
                rename[col] = "Low"
            elif low in ("close",) and "Close" not in df.columns:
                rename[col] = "Close"
            elif low in ("volume",) and "Volume" not in df.columns:
                rename[col] = "Volume"
        if rename:
            df = df.rename(columns=rename)

        keep = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
        df = df[keep]
        df = df.sort_index()
        if df.index.tz is None:
            try:
                df.index = df.index.tz_localize("Asia/Kolkata")
            except Exception:
                pass
        return df

    # ------------------------------------------------------------------
    # Y Finance (yfinance)
    # ------------------------------------------------------------------
    @staticmethod
    def _fetch_data_yfinance(symbol: str, start_date: str, end_date: str = None) -> pd.DataFrame:
        """Fetch 1-minute data using yfinance."""
        try:
            import yfinance as yf

            yf_symbol = DataCollector._yfinance_symbol(symbol)

            if end_date is None:
                end_date_dt = datetime.strptime(start_date, "%Y-%m-%d") + timedelta(days=1)
                end_date_str = end_date_dt.strftime("%Y-%m-%d")
            else:
                end_date_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
                end_date_str = end_date_dt.strftime("%Y-%m-%d")

            fetch_start_dt = datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=7)
            fetch_start_str = fetch_start_dt.strftime("%Y-%m-%d")

            ticker = yf.Ticker(yf_symbol)
            df = ticker.history(start=fetch_start_str, end=end_date_str, interval="1m")
            if df.empty:
                logger.warning(f"yfinance returned empty dataframe for {yf_symbol}")
                return pd.DataFrame()

            keep_cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
            df = df[keep_cols]
            if df.index.name != "Datetime":
                df.index.name = "Datetime"
            return df
        except Exception as e:
            logger.error(f"yfinance fetch failed for {symbol}: {e}")
            return pd.DataFrame()

    @staticmethod
    def _fetch_spot_yfinance(symbol: str) -> dict:
        """Fetch the delayed spot quote for ``symbol`` using yfinance (~15-min delay).

        Returns the canonical quote dict, or {} on any failure. Fields that
        cannot be resolved (e.g. previous_close) are omitted rather than
        invented.
        """
        try:
            import yfinance as yf

            yf_symbol = DataCollector._yfinance_symbol(symbol)
            ticker = yf.Ticker(yf_symbol)

            df = ticker.history(period="1d", interval="1m")
            if df is None or df.empty:
                logger.warning(f"yfinance returned empty dataframe for {yf_symbol} spot quote")
                return {}

            last_ts = pd.Timestamp(df.index[-1])
            if last_ts.tz is None:
                last_ts = last_ts.tz_localize("Asia/Kolkata")
            else:
                last_ts = last_ts.tz_convert("Asia/Kolkata")

            price = float(df["Close"].iloc[-1])
            quote = {
                "symbol": yf_symbol,
                "price": round(price, 2),
                "open": round(float(df["Open"].iloc[0]), 2),
                "high": round(float(df["High"].max()), 2),
                "low": round(float(df["Low"].min()), 2),
                "timestamp": last_ts.isoformat(),
                "source": "yfinance",
                "delayed": True,
            }

            # Resolve previous_close without inventing a value: fast_info first,
            # then the prior day's Close from 5d of daily history.
            previous_close = None
            try:
                fast_info = ticker.fast_info
                try:
                    previous_close = float(fast_info["previous_close"])
                except Exception:
                    previous_close = float(fast_info.previous_close)
            except Exception:
                previous_close = None

            if previous_close is None or math.isnan(previous_close):
                previous_close = None
                try:
                    daily_df = ticker.history(period="5d", interval="1d")
                    if daily_df is not None and not daily_df.empty and len(daily_df) >= 2:
                        previous_close = float(daily_df["Close"].iloc[-2])
                except Exception:
                    previous_close = None

            if previous_close is not None:
                change = price - previous_close
                quote["previous_close"] = round(previous_close, 2)
                quote["change"] = round(change, 2)
                if previous_close != 0:
                    quote["percent_change"] = round(change / previous_close * 100.0, 2)

            return quote
        except Exception as e:
            logger.error(f"yfinance spot quote failed for {symbol}: {e}")
            return {}

    @staticmethod
    def _fetch_daily_context_yfinance(symbol: str, date: str) -> dict:
        """Fetch daily context using yfinance."""
        try:
            import yfinance as yf

            yf_symbol = DataCollector._yfinance_symbol(symbol)
            end_dt = datetime.strptime(date, "%Y-%m-%d")
            start_dt = end_dt - timedelta(days=45)

            ticker = yf.Ticker(yf_symbol)
            daily_df = ticker.history(
                start=start_dt.strftime("%Y-%m-%d"),
                end=(end_dt + timedelta(days=1)).strftime("%Y-%m-%d"),
                interval="1d",
            )
            return DataCollector._extract_context_metrics(daily_df, date)
        except Exception as e:
            logger.error(f"yfinance daily context failed for {symbol}: {e}")
            return {}

    # ------------------------------------------------------------------
    # jugaad-data (Indian market daily history fallback)
    # ------------------------------------------------------------------
    @staticmethod
    def _fetch_daily_context_jugaad(symbol: str, date: str) -> dict:
        """Fetch daily context using jugaad-data (Indian markets)."""
        try:
            from jugaad_data.nse import index_history, stock_history
        except ImportError:
            logger.info("jugaad-data not installed; skipping jugaad daily fallback.")
            return {}

        try:
            end_dt = datetime.strptime(date, "%Y-%m-%d")
            start_dt = end_dt - timedelta(days=45)

            sym = "NIFTY 50"
            # Index series vs equity series handling.
            try:
                df = index_history(
                    symbol=sym,
                    from_date=start_dt.date(),
                    to_date=end_dt.date(),
                    series="EQ",
                )
            except Exception:
                df = stock_history(
                    symbol=sym,
                    from_date=start_dt.date(),
                    to_date=end_dt.date(),
                    series="EQ",
                )

            if df is None or df.empty:
                return {}

            df = df.rename(columns={c: c.capitalize() for c in df.columns})
            df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
            df = df.set_index("Date").sort_index()
            return DataCollector._extract_context_metrics(df, date)
        except Exception as e:
            logger.warning(f"jugaad daily context failed for {symbol}: {e}")
            return {}

    @staticmethod
    def _fetch_spot_jugaad(symbol: str) -> dict:
        """Fetch the near-real-time NIFTY 50 spot quote using jugaad-data.

        Returns the canonical quote dict, or {} when jugaad-data is not
        installed or the NSE call fails (NSE occasionally returns 403 / blocks
        aggressive polling).
        """
        try:
            from jugaad_data.nse import NSELive
        except ImportError:
            logger.info("jugaad-data not installed; skipping jugaad spot fallback.")
            return {}

        try:
            nifty = NSELive().live_index("NIFTY 50")
            rows = (nifty or {}).get("data") or []
            if not rows:
                logger.warning("jugaad live_index returned no data for NIFTY 50")
                return {}

            row = rows[0]
            price = float(row["lastPrice"])
            quote = {
                "symbol": DataCollector._yfinance_symbol(symbol),
                "price": round(price, 2),
                "open": round(float(row["open"]), 2),
                "high": round(float(row["dayHigh"]), 2),
                "low": round(float(row["dayLow"]), 2),
                "source": "jugaad",
                "delayed": True,
            }

            raw_ts = row.get("lastUpdateTime") or (nifty or {}).get("timestamp")
            if raw_ts:
                try:
                    ts = pd.Timestamp(datetime.strptime(raw_ts, "%d-%b-%Y %H:%M:%S"))
                    if ts.tz is None:
                        ts = ts.tz_localize("Asia/Kolkata")
                    else:
                        ts = ts.tz_convert("Asia/Kolkata")
                    quote["timestamp"] = ts.isoformat()
                except Exception as e:
                    logger.warning(f"Could not parse jugaad timestamp '{raw_ts}': {e}")

            previous_close = row.get("previousClose")
            if previous_close is not None:
                previous_close = float(previous_close)
                change = price - previous_close
                quote["previous_close"] = round(previous_close, 2)
                quote["change"] = round(change, 2)
                if previous_close != 0:
                    quote["percent_change"] = round(change / previous_close * 100.0, 2)

            return quote
        except Exception as e:
            logger.warning(f"jugaad spot quote failed for {symbol}: {e}")
            return {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @staticmethod
    def fetch_data(symbol: str, start_date: str, end_date: str = None, interval: str = "1m") -> pd.DataFrame:
        """
        Download 1-minute NIFTY 50 candles, preferring internal datasets, then Y Finance.

        Sources (in order):
          1. Internal bundled datasets (offline, authoritative).
          2. yfinance (primary network source).
        """
        if not DataCollector.is_supported_symbol(symbol):
            logger.error(f"Unsupported symbol '{symbol}'. Only NIFTY 50 (^NSEI / NIFTY) is supported.")
            return pd.DataFrame()

        # 1. Internal datasets (offline, no network required).
        df = DataCollector._load_internal_intraday(symbol, start_date, end_date or start_date, interval)
        if not df.empty:
            logger.info(f"Loaded intraday data from internal dataset for {symbol}")
            return df

        # 2. yfinance.
        logger.info(f"Fetching intraday data via yfinance for {symbol}")
        df = DataCollector._fetch_data_yfinance(symbol, start_date, end_date)
        return df

    @staticmethod
    def fetch_vix_data(date: str) -> dict:
        """
        Fetches 1-year India VIX data and calculates IV Rank and IV Percentile
        via yfinance.
        """
        try:
            import yfinance as yf

            end_dt = datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)
            start_dt = end_dt - timedelta(days=365)

            ticker = yf.Ticker("^INDIAVIX")
            vix_df = ticker.history(start=start_dt.strftime("%Y-%m-%d"), end=end_dt.strftime("%Y-%m-%d"), interval="1d")

            if vix_df.empty:
                return {"vix": 15.0, "iv_rank": 50.0, "iv_percentile": 50.0}

            closes = vix_df["Close"].dropna()
            if closes.empty:
                return {"vix": 15.0, "iv_rank": 50.0, "iv_percentile": 50.0}

            curr_vix = float(closes.iloc[-1])
            min_vix = float(closes.min())
            max_vix = float(closes.max())

            iv_rank = (curr_vix - min_vix) / (max_vix - min_vix) * 100.0 if max_vix > min_vix else 50.0
            iv_percentile = float((closes < curr_vix).mean() * 100.0)

            return {
                "vix": round(curr_vix, 2),
                "iv_rank": round(max(0.0, min(100.0, iv_rank)), 2),
                "iv_percentile": round(max(0.0, min(100.0, iv_percentile)), 2),
            }
        except Exception as e:
            logger.warning(f"Error fetching VIX data: {e}")
            return {"vix": 15.0, "iv_rank": 50.0, "iv_percentile": 50.0}

    @staticmethod
    def _extract_context_metrics(daily_df: pd.DataFrame, date: str) -> dict:
        """Helper to extract CPR, prev OHLCV, and daily trend from daily dataframe."""
        if daily_df is None or daily_df.empty:
            return {}

        last_day = daily_df.iloc[-1]
        h, l, c = float(last_day["High"]), float(last_day["Low"]), float(last_day["Close"])
        pivot = (h + l + c) / 3.0
        bc = (h + l) / 2.0
        tc = (pivot - bc) + pivot
        cpr_width = (abs(tc - bc) / pivot) * 100.0 if pivot > 0 else 0.0

        daily_closes = daily_df["Close"].values
        daily_ema20 = float(daily_closes[-20:].mean()) if len(daily_closes) >= 20 else c
        daily_trend = 1.0 if c >= daily_ema20 else -1.0

        vix_data = DataCollector.fetch_vix_data(date)

        return {
            "prev_close": c,
            "prev_high": h,
            "prev_low": l,
            "daily_volume": float(last_day["Volume"]),
            "cpr_pivot": round(pivot, 2),
            "cpr_tc": round(tc, 2),
            "cpr_bc": round(bc, 2),
            "cpr_width": round(cpr_width, 4),
            "daily_trend": daily_trend,
            "daily_ema20": round(daily_ema20, 2),
            **vix_data,
        }

    @staticmethod
    def fetch_daily_context(symbol: str, date: str) -> dict:
        """
        Fetch daily context (previous close, high, low, volume, CPR, VIX) for NIFTY 50.

        Sources (in order):
          1. Internal bundled datasets (offline).
          2. yfinance.
          3. jugaad-data (Indian market fallback).
        """
        if not DataCollector.is_supported_symbol(symbol):
            logger.error(f"Unsupported symbol '{symbol}'. Only NIFTY 50 (^NSEI / NIFTY) is supported.")
            return {}

        context = {}

        # 1. Internal datasets — reuse the intraday loader for daily context when
        #    a multi-day internal file is available (e.g. 15-min NIFTY history).
        internal_df = DataCollector._load_internal_intraday(symbol, date, date, "1d")
        if not internal_df.empty:
            context = DataCollector._extract_context_metrics(internal_df, date)

        # 2. yfinance.
        if not context:
            context = DataCollector._fetch_daily_context_yfinance(symbol, date)

        # 3. jugaad-data fallback.
        if not context:
            context = DataCollector._fetch_daily_context_jugaad(symbol, date)

        return context

    @staticmethod
    def fetch_spot_quote(symbol: str = "^NSEI") -> dict:
        """
        Fetch the delayed NIFTY 50 spot price.

        Sources (in order):
          1. yfinance (``^NSEI``, ~15-minute Yahoo delay).
          2. jugaad-data ``NSELive`` (near-real-time NSE index feed).

        Returns a canonical quote dict::

            {
              "symbol": str,            # "^NSEI"
              "price": float,
              "change": float,          # price - previous_close (omitted if unknown)
              "percent_change": float,  # omitted if previous_close unknown
              "open": float, "high": float, "low": float,
              "previous_close": float,  # omitted when unresolvable
              "timestamp": str,         # ISO-8601, Asia/Kolkata
              "source": str,            # "yfinance" | "jugaad"
              "delayed": True,
            }

        Returns {} when both sources fail or the symbol is unsupported.
        """
        if not DataCollector.is_supported_symbol(symbol):
            logger.error(f"Unsupported symbol '{symbol}'. Only NIFTY 50 (^NSEI / NIFTY) is supported.")
            return {}

        logger.info(f"Fetching spot quote via yfinance for {symbol}")
        quote = DataCollector._fetch_spot_yfinance(symbol)
        if quote:
            logger.info(f"Spot quote for {symbol} fetched via yfinance")
            return quote

        logger.info(f"yfinance spot quote unavailable; falling back to jugaad-data for {symbol}")
        quote = DataCollector._fetch_spot_jugaad(symbol)
        if quote:
            logger.info(f"Spot quote for {symbol} fetched via jugaad-data")
            return quote

        logger.error(f"Both quote sources failed for {symbol}")
        return {}
