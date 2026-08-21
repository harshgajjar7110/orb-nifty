import os
import sys
import time
import argparse
import logging
from datetime import datetime

# Ensure src is in PYTHONPATH
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(base_dir, 'src'))

from osse.data.collector import DataCollector

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("fetch_spot_price")


def format_quote_line(quote: dict) -> str:
    fetched_at = datetime.now().astimezone().isoformat(sep=" ", timespec="seconds")
    price = quote["price"]
    change = quote.get("change")
    percent = quote.get("percent_change")
    if change is not None and percent is not None:
        movement = f"({change:+,.2f}, {percent:+.2f}%)"
    else:
        movement = "(change n/a)"
    return (
        f"{fetched_at} | {quote['symbol']} {price:,.2f} {movement}"
        f" | src={quote['source']} | ts={quote.get('timestamp', 'n/a')}"
    )


def fetch_once(symbol: str, source: str) -> dict:
    if source == "yfinance":
        return DataCollector._fetch_spot_yfinance(symbol)
    if source == "jugaad":
        return DataCollector._fetch_spot_jugaad(symbol)
    return DataCollector.fetch_spot_quote(symbol)


def main():
    parser = argparse.ArgumentParser(
        description="Poll the delayed NIFTY 50 spot price (yfinance primary, jugaad-data fallback)."
    )
    parser.add_argument("--symbol", default="^NSEI", help="Supported NIFTY 50 alias (default: ^NSEI)")
    parser.add_argument("--interval", type=int, default=60,
                        help="Seconds between polls (default: 60). Keep >= 30 to avoid NSE blocking.")
    parser.add_argument("--count", type=int, default=0,
                        help="Number of polls before exiting (default: 0 = run forever)")
    parser.add_argument("--source", choices=["auto", "yfinance", "jugaad"], default="auto",
                        help="Force a quote source, or auto for the collector's fallback order (default: auto)")
    args = parser.parse_args()

    if not DataCollector.is_supported_symbol(args.symbol):
        parser.error(f"Unsupported symbol '{args.symbol}'. Only NIFTY 50 (^NSEI / NIFTY) is supported.")

    if args.interval <= 0:
        parser.error("--interval must be a positive number of seconds")
    if args.interval < 30:
        logger.warning("Intervals below 30s risk NSE rate-blocking; consider >= 30s.")

    polls = 0
    try:
        while True:
            quote = fetch_once(args.symbol, args.source)
            if quote:
                print(format_quote_line(quote), flush=True)
            else:
                logger.warning(f"Quote fetch failed for {args.symbol}; retrying in {args.interval}s")

            polls += 1
            if args.count > 0 and polls >= args.count:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
