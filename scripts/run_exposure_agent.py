"""
CLI runner for the Dhan Exposure Agent.

Example:
    .venv_py314/bin/python scripts/run_exposure_agent.py \
        --url "https://dext.dhan.co/dashboard" \
        --symbol NIFTY \
        --direction UP \
        --strategy "Directional Credit Spread"
"""

import argparse
import json
import logging
import sys

sys.path.insert(0, "src")

from osse.agent.exposure_agent import DhanExposureAgent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Dhan Exposure Agent CLI")
    parser.add_argument(
        "--url",
        default="https://dext.dhan.co/dashboard",
        help="Dhan Dext URL to navigate to",
    )
    parser.add_argument("--symbol", default="NIFTY", help="Underlying symbol")
    parser.add_argument(
        "--direction", default="UP", choices=["UP", "DOWN"], help="Trade direction"
    )
    parser.add_argument(
        "--strategy",
        default="Directional Credit Spread",
        help="Strategy name to pass to StrikeSelector",
    )
    parser.add_argument(
        "--variant", default="GEX_DEX_ALIGNED", help="Strike selection variant"
    )
    parser.add_argument("--expiry", default="WEEKLY", help="Expiry type")
    parser.add_argument(
        "--daemon-url",
        default="http://127.0.0.1:10086",
        help="Kimi WebBridge daemon URL",
    )
    parser.add_argument(
        "--no-mcp-fallback",
        action="store_true",
        help="Disable DhanMCPCollector fallback if WebBridge is unreachable",
    )
    parser.add_argument(
        "--output", default=None, help="Optional JSON file to write the result to"
    )

    args = parser.parse_args()

    agent = DhanExposureAgent(
        daemon_url=args.daemon_url,
        use_mcp_fallback=not args.no_mcp_fallback,
    )
    result = agent.run(
        url=args.url,
        strategy_name=args.strategy,
        direction=args.direction,
        symbol=args.symbol,
        variant=args.variant,
        expiry_type=args.expiry,
    )

    payload = result.to_dict()
    print(json.dumps(payload, indent=2, default=str))

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, default=str)
        logger.info(f"Result written to {args.output}")

    sys.exit(0 if result.status == "SUCCESS" else 1)


if __name__ == "__main__":
    main()
