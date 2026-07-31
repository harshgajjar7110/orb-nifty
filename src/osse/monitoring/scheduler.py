"""
Live Monitor Scheduler for OSSE.

Polls the Dhan option-chain dashboard during Indian market hours, generates
insights, and persists snapshots for the Streamlit dashboard.
"""

import os
import sys
import argparse
import logging
from datetime import datetime, time
from typing import List, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from osse.data.dhan_mcp import DhanMCPCollector
from osse.data.db import DatabaseManager
from osse.monitoring.insights import InsightsGenerator

logger = logging.getLogger(__name__)

INDIA_TZ = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)


class MonitorScheduler:
    """
    Schedules and runs Dhan option-chain monitoring during market hours.
    """

    DEFAULT_SYMBOLS = ["NIFTY", "BANKNIFTY"]
    DEFAULT_POLL_INTERVAL_SECONDS = 180

    def __init__(
        self,
        symbols: Optional[List[str]] = None,
        poll_interval_seconds: Optional[int] = None,
        stale_seconds: Optional[int] = None,
        osse_score: float = 50.0
    ):
        self.symbols = symbols or os.environ.get("DHAN_MONITOR_SYMBOLS", ",".join(self.DEFAULT_SYMBOLS)).split(",")
        self.poll_interval_seconds = poll_interval_seconds or int(
            os.environ.get("DHAN_POLL_INTERVAL_SECONDS", self.DEFAULT_POLL_INTERVAL_SECONDS)
        )
        self.stale_seconds = stale_seconds
        self.osse_score = osse_score
        self.collector = DhanMCPCollector(stale_seconds=self.stale_seconds)
        self.insights_generator = InsightsGenerator(osse_score=self.osse_score)

    @staticmethod
    def is_market_hours(now: Optional[datetime] = None) -> bool:
        """Returns True if now is within Indian equity market hours (Mon-Fri 09:15-15:30 IST)."""
        now = now or datetime.now(INDIA_TZ)
        if now.weekday() >= 5:  # Saturday=5, Sunday=6
            return False
        current_time = now.time()
        return MARKET_OPEN <= current_time <= MARKET_CLOSE

    def poll_symbol(self, symbol: str) -> Optional[dict]:
        """
        Fetches latest option-chain + candles for a symbol and generates insights.
        Returns the snapshot payload or None on failure.
        """
        logger.info(f"[MonitorScheduler] Polling {symbol}...")
        try:
            chain_df = self.collector.fetch_option_chain(symbol=symbol, force_refresh=True)
            candles_df = self.collector.fetch_chart_candles(symbol=symbol, force_refresh=True)

            spot_price = chain_df.get("strike_price").median() if not chain_df.empty else 0.0
            if "spot_price" in chain_df.columns:
                spot_price = float(chain_df["spot_price"].iloc[0]) if not pd.isna(chain_df["spot_price"].iloc[0]) else spot_price

            if spot_price <= 0:
                logger.warning(f"[MonitorScheduler] Could not determine spot price for {symbol}.")
                return None

            insights = self.insights_generator.generate_insights(
                symbol=symbol,
                spot_price=spot_price,
                chain_df=chain_df,
                candles_df=candles_df,
                osse_score=self.osse_score
            )

            DatabaseManager.save_monitor_snapshot(
                symbol=symbol,
                timestamp=datetime.now(INDIA_TZ),
                spot_price=spot_price,
                insights=insights
            )

            logger.info(
                f"[MonitorScheduler] {symbol} snapshot saved: "
                f"spot={spot_price:.2f}, alerts={len(insights.get('signal_alerts', []))}"
            )
            return insights

        except Exception as e:
            logger.error(f"[MonitorScheduler] Error polling {symbol}: {e}")
            return None

    def poll_once(self) -> List[dict]:
        """Runs one full polling cycle for all configured symbols."""
        if not self.is_market_hours() and os.environ.get("DHAN_MONITOR_IGNORE_HOURS") != "1":
            logger.info("[MonitorScheduler] Outside market hours; skipping poll.")
            return []

        results = []
        for symbol in self.symbols:
            symbol = symbol.strip().upper()
            if not symbol:
                continue
            result = self.poll_symbol(symbol)
            if result:
                results.append(result)
        return results

    def start(self) -> None:
        """Starts the blocking scheduler loop."""
        try:
            from apscheduler.schedulers.blocking import BlockingScheduler
        except ImportError as e:
            logger.error(
                "[MonitorScheduler] APScheduler is required for background polling. "
                "Install it with: pip install APScheduler"
            )
            raise e

        scheduler = BlockingScheduler(timezone=INDIA_TZ)
        scheduler.add_job(
            self.poll_once,
            "interval",
            seconds=self.poll_interval_seconds,
            id="dhan_monitor_poll",
            replace_existing=True
        )

        logger.info(
            f"[MonitorScheduler] Started. Symbols={self.symbols}, "
            f"interval={self.poll_interval_seconds}s, market hours only={os.environ.get('DHAN_MONITOR_IGNORE_HOURS') != '1'}"
        )
        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("[MonitorScheduler] Shutting down.")
            scheduler.shutdown()


def main():
    parser = argparse.ArgumentParser(description="OSSE Dhan Option-Chain Live Monitor")
    parser.add_argument("--symbols", default="NIFTY,BANKNIFTY", help="Comma-separated symbols to monitor")
    parser.add_argument("--interval", type=int, default=None, help="Poll interval in seconds")
    parser.add_argument("--stale", type=int, default=None, help="Max JSON file age before refresh")
    parser.add_argument("--osse-score", type=float, default=50.0, help="OSSE score to use in unified score")
    parser.add_argument("--once", action="store_true", help="Run one poll cycle and exit")
    parser.add_argument("--ignore-hours", action="store_true", help="Poll even outside market hours")
    args = parser.parse_args()

    if args.ignore_hours:
        os.environ["DHAN_MONITOR_IGNORE_HOURS"] = "1"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    scheduler = MonitorScheduler(
        symbols=args.symbols.split(","),
        poll_interval_seconds=args.interval,
        stale_seconds=args.stale,
        osse_score=args.osse_score
    )

    if args.once:
        results = scheduler.poll_once()
        if not results:
            logger.info("[MonitorScheduler] No snapshots produced.")
            sys.exit(0)
        for r in results:
            print(f"{r['symbol']}: {len(r['signal_alerts'])} alerts")
    else:
        scheduler.start()


if __name__ == "__main__":
    main()
