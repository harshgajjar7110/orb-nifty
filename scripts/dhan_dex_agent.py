#!/usr/bin/env python3
"""Dhan DEX Agent — Deterministic Workflow Script (PID: DHAN-DEX-AGENT-v1)

Executes a fixed, deterministic sequence of Kimi Web Bridge commands
with OpenRouter LLM integration for parsing and structuring.
No exploration, no retries, no branching.

Usage:
    python scripts/dhan_dex_agent.py [--strike-selection]

Flags:
    --strike-selection  Also compute GEX_DEX_ALIGNED strikes after extraction.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import argparse
import logging

import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("dhan-dex-agent")

# ---------------------------------------------------------------------------
# Constants — no configuration, no env lookups at runtime beyond startup
# ---------------------------------------------------------------------------

BRIDGE_URL = "http://127.0.0.1:10086"
SESSION = "dhan-dex-check-v2"
DASHBOARD_URL = "https://dext.dhan.co/dashboard"
BRIDGE_START_CMD = [os.path.expanduser("~/.kimi-webbridge/bin/kimi-webbridge"), "start"]
BRIDGE_TIMEOUT = 30

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = "inclusionai/ling-3.0-flash:free"
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_TIMEOUT = 30

# --- Step 2: Summary extraction ---
SUMMARY_JS = """(() => {
  const labels = Array.from(document.querySelectorAll("body *")).filter(
    el => el.children.length === 0 && /(Total Call|Total Put|Total Net|DEX Ratio|Nifty 50|Spot Price)/.test(el.textContent)
  );
  const summary = {};
  labels.forEach(el => {
    const parent = el.parentElement?.textContent?.trim();
    if (!parent) return;
    const m = parent.match(/(Total Call|Total Put|Total Net|DEX Ratio|Nifty 50|Spot Price)[:\\s]*(.+)/);
    if (m) summary[m[1]] = m[2].trim();
  });
  return JSON.stringify(summary);
})()"""

# --- Step 3: Expiry selector detection ---
EXPIRY_JS = """(() => {
  const sel = document.querySelector("select.appearance-none");
  if (sel) return JSON.stringify({type:"native", options: Array.from(sel.options).map(o => ({text: o.text, value: o.value}))});
  const btn = document.querySelector("button.global-dropdown-button");
  if (btn) return JSON.stringify({type:"custom-button", text: btn.textContent.trim()});
  return JSON.stringify({type:"not-found"});
})()"""

# --- Step 4 & 6: Table extraction ---
TABLE_JS = """(() => {
  const container = document.querySelector("[class*=greeks-table-scroll-wrap]");
  if (!container) return JSON.stringify([]);
  const rows = Array.from(container.querySelectorAll("[class*=greeks-exposure-table-row]"));
  return JSON.stringify(rows.map(r => {
    // Extract text from each child cell for clean column alignment
    const cells = Array.from(r.children).map(c => c.textContent.trim());
    if (cells.length === 0) return r.textContent.trim().replace(/\\s+/g, " ");
    return cells.join(" | ");
  }));
})()"""

# --- Step 5: Gamma tab click ---
GAMMA_TAB_JS = """(() => {
  const tabs = Array.from(document.querySelectorAll("button")).filter(el => /Gamma Exposure/.test(el.textContent));
  if (tabs.length) { tabs[0].click(); return "clicked"; }
  return "not found";
})()"""

# ---------------------------------------------------------------------------
# LLM Prompts (fixed, deterministic)
# ---------------------------------------------------------------------------

LLM_1_SYSTEM = """You are a data parser. Extract clean values from the raw Dhan DEX summary JSON.

Return ONLY a valid JSON object with these keys:
- spot_price: float (the Nifty spot price, first numeric value)
- total_call: string (e.g. "86,77,078.94 Cr")
- total_put: string (e.g. "-75,58,897.06 Cr")
- total_net: string (e.g. "11,18,181.88 Cr")
- dex_ratio: string (e.g. "0.87")
- dex_sentiment: string (e.g. "Bullish" or "Bearish")"""

LLM_2_SYSTEM = """You are a data parser. Parse the raw Dhan DEX exposure table rows into structured JSON.

Each input row is a space-separated string: strike callExposure putExposure netExposure [tags...]

Return ONLY a valid JSON array of objects with these keys:
- strike: string (e.g. "24400")
- call_exposure: string (e.g. "6,03,721.34 Cr")
- put_exposure: string (e.g. "-3,21,477.65 Cr")
- net_exposure: string (e.g. "2,82,243.69 Cr")
- tags: array of strings (e.g. ["Delta Flip"])"""

LLM_4_SYSTEM = """You are a report formatter. Assemble the Dhan DEX dashboard data into the final output format.

Return ONLY the formatted string, no extra commentary."""

LLM_5_SYSTEM = """You are an options trading analyst. Based on the Dhan DEX dashboard data, suggest strikes for option selling.

Analyze the following data:
- Spot price and DEX ratio (call/put ratio) for directional bias
- Delta exposure table for key levels (put support, call resistance, delta flip)
- Gamma exposure table for gamma flip levels

Return ONLY a valid JSON object with these keys:
- direction: "bullish" or "bearish" based on DEX ratio (ratio > 1 = bullish, ratio <= 1 = bearish)
- sell_pe_strike: string — the strike to sell PE (put) at, chosen from put support or peak -delta exp level
- sell_ce_strike: string — the strike to sell CE (call) at, chosen from call resistance or peak +delta exp level
- confidence: string ("high", "medium", "low") based on how clear the levels are
- rationale: short explanation of why these strikes were chosen
- expected_credit_pts: string — estimated credit in points (e.g. "45-55 pts")"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_json_from_text(text: str) -> str:
    """Extract valid JSON from LLM response text, handling markdown fences and partial output."""
    import re
    text = text.strip()
    # Remove ```json ... ``` or ``` ... ``` fences
    text = re.sub(r"^```json?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text, flags=re.IGNORECASE)
    text = text.strip()
    # Try to find the first valid JSON object or array
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start_idx = text.find(start_char)
        if start_idx == -1:
            continue
        depth = 0
        for i in range(start_idx, len(text)):
            if text[i] == start_char:
                depth += 1
            elif text[i] == end_char:
                depth -= 1
                if depth == 0:
                    candidate = text[start_idx:i + 1]
                    try:
                        json.loads(candidate)
                        return candidate
                    except json.JSONDecodeError:
                        break
    # Fallback: return cleaned text as-is (let caller's json.loads fail with a clear error)
    return text


def _llm_call(system_prompt: str, user_prompt: str, max_tokens: int = 16384) -> str:
    """Call OpenRouter LLM with deterministic settings (temperature=0.0)."""
    if not OPENROUTER_API_KEY:
        log.error("LLM_API_KEY_MISSING — set OPENROUTER_API_KEY environment variable")
        sys.exit(1)

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.0,
        "max_tokens": max_tokens,
    }

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/orb-nifty",
        "X-Title": "Dhan DEX Agent",
    }

    try:
        log.info("LLM call: %s (max_tokens=%d)", system_prompt[:80].replace('\n', ' '), max_tokens)
        resp = requests.post(
            f"{OPENROUTER_BASE_URL}/chat/completions",
            json=payload,
            headers=headers,
            timeout=OPENROUTER_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        content = choice["message"].get("content")
        finish_reason = choice.get("finish_reason", "")

        # If content is null but reasoning exists, extract JSON from reasoning
        if content is None:
            reasoning = choice["message"].get("reasoning", "") or ""
            if reasoning:
                log.warning("LLM content was null, extracting from reasoning field (%d chars)", len(reasoning))
                content = reasoning
            elif finish_reason == "length":
                log.error("LLM response truncated (finish_reason=length). Increase max_tokens or reduce input size.")
                sys.exit(1)
            else:
                log.error("LLM returned null content. Full response: %s", json.dumps(data, indent=2)[:500])
                sys.exit(1)

        content = content.strip()
        result = _extract_json_from_text(content)
        log.info("LLM response extracted successfully (%d chars, finish_reason=%s)", len(result), finish_reason)
        return result
    except requests.exceptions.RequestException as e:
        log.error("LLM request failed: %s", e)
        sys.exit(1)
    except (KeyError, IndexError) as e:
        log.error("LLM response parse failed: %s", e)
        sys.exit(1)


def bridge_call(action: str, args: dict) -> dict:
    """Send a single command to kimi-webbridge and return parsed JSON."""
    payload = json.dumps({"action": action, "args": args, "session": SESSION})
    cmd = [
        "curl", "-s", "-X", "POST", BRIDGE_URL + "/command",
        "-H", "Content-Type: application/json",
        "-d", payload,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=BRIDGE_TIMEOUT)
    if result.returncode != 0:
        print(f"ERROR: curl failed (exit {result.returncode}): {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON from bridge: {e}\nRaw: {result.stdout[:500]}", file=sys.stderr)
        sys.exit(1)


def evaluate(js: str) -> str:
    """Run JavaScript in the browser and return the string result."""
    resp = bridge_call("evaluate", {"code": js})
    if not resp.get("ok"):
        log.warning("Bridge evaluate returned not ok")
        return ""
    data = resp.get("data", {})
    if data.get("type") == "string":
        return data.get("value", "")
    return ""


def _is_numeric(value: str) -> bool:
    """Check if a token is a numeric value (handles Indian comma grouping and negatives)."""
    stripped = value.replace(",", "").replace(".", "").replace("-", "")
    return stripped.isdigit() and value != "-"


def parse_table(rows_json: str) -> list[dict]:
    """Parse the table rows into structured dicts.

    TABLE_JS emits each row as cells joined by " | ", e.g.:
        "24500 | 6,03,721.34 Cr | -3,21,477.65 Cr | 2,82,243.69 Cr | Delta Flip"

    We split on " | " first so each column stays isolated. Then we strip the
    trailing " Cr" currency suffix from numeric columns. A bare "-" means zero
    exposure and is preserved as "0 Cr". Tags live in the last cell(s) and are
    collected as a list.
    """
    rows = json.loads(rows_json)
    result = []
    for row in rows:
        # Split on the cell delimiter so columns never bleed into each other
        cells = [c.strip() for c in row.split(" | ")]
        if len(cells) < 1:
            continue
        # Strip " Cr" suffix from each cell (case-insensitive)
        cleaned = []
        for c in cells:
            text = c.strip()
            if text.lower().endswith(" cr"):
                text = text[:-3].strip()
            cleaned.append(text)
        # First cell is always the strike
        strike = cleaned[0]
        # Remaining cells: numeric exposures + tags
        remainder = cleaned[1:]
        # Pop trailing non-numeric cells as tags
        tags = []
        while remainder and not _is_numeric(remainder[-1]):
            tags.append(remainder.pop())
        tags.reverse()  # restore original order
        # Map remaining numeric cells to columns in order
        exposures = [e if e != "-" else "0" for e in remainder]
        call_exp = exposures[0] if len(exposures) > 0 else ""
        put_exp = exposures[1] if len(exposures) > 1 else ""
        net_exp = exposures[2] if len(exposures) > 2 else ""
        # Re-attach " Cr" suffix for consistency with LLM expectations
        def _fmt(v: str) -> str:
            return f"{v} Cr" if v else ""
        result.append({
            "strike": strike,
            "call_exposure": _fmt(call_exp),
            "put_exposure": _fmt(put_exp),
            "net_exposure": _fmt(net_exp),
            "tags": tags,
        })
    return result


def find_tag(rows: list[dict], tag_pattern: str) -> str | None:
    """Find the strike associated with a tag pattern."""
    for r in rows:
        for t in r["tags"]:
            if tag_pattern in t:
                return r["strike"]
    return None


# ---------------------------------------------------------------------------
# Deterministic Steps (0 → 7)
# ---------------------------------------------------------------------------

def step_0_start_daemon() -> None:
    """Step 0: Ensure kimi-webbridge daemon is running."""
    log.info("Step 0: Ensuring kimi-webbridge daemon is running")
    result = subprocess.run(BRIDGE_START_CMD, capture_output=True, text=True, timeout=10)
    output = result.stdout + result.stderr
    if "already running" in output or "started" in output.lower():
        log.info("Step 0: Daemon is running")
        return
    log.error("Step 0: DAEMON_START_FAILED")
    sys.exit(1)


def step_1_navigate() -> None:
    """Step 1: Navigate to Dhan DEX dashboard."""
    log.info("Step 1: Navigating to %s", DASHBOARD_URL)
    resp = bridge_call("navigate", {
        "url": DASHBOARD_URL,
        "newTab": False,
        "group_title": "Dhan DEX check",
    })
    if not resp.get("ok") or not resp.get("data", {}).get("success"):
        log.error("Step 1: NAVIGATE_FAILED")
        sys.exit(1)
    log.info("Step 1: Navigation successful, waiting 3s for render")
    time.sleep(3)  # React app needs render time


def step_2_extract_summary() -> dict:
    """Step 2: Extract summary cards (raw)."""
    log.info("Step 2: Extracting summary cards")
    raw = evaluate(SUMMARY_JS)
    if not raw:
        log.error("Step 2: SUMMARY_EXTRACT_FAILED")
        sys.exit(1)
    log.info("Step 2: Summary extracted (%d chars)", len(raw))
    return raw  # raw JSON string — LLM-1 will clean it


def llm_1_clean_summary(raw_summary: str) -> dict:
    """LLM-1: Parse messy summary JSON into clean structured data."""
    log.info("LLM-1: Cleaning summary data")
    user_prompt = f"Raw summary JSON:\n{raw_summary}"
    result = _llm_call(LLM_1_SYSTEM, user_prompt)
    try:
        parsed = json.loads(result)
        log.info("LLM-1: Summary parsed successfully — keys: %s", list(parsed.keys()))
        return parsed
    except json.JSONDecodeError as e:
        log.error("LLM-1: LLM_PARSE_SUMMARY_FAILED: %s", e)
        sys.exit(1)


def step_3_detect_expiry() -> str:
    """Step 3: Detect expiry selector type and current expiry."""
    log.info("Step 3: Detecting expiry selector")
    raw = evaluate(EXPIRY_JS)
    if not raw:
        log.error("Step 3: EXPIRY_SELECTOR_NOT_FOUND")
        sys.exit(1)
    info = json.loads(raw)
    etype = info.get("type", "not-found")
    log.info("Step 3: Expiry selector type: %s", etype)
    if etype == "not-found":
        log.error("Step 3: EXPIRY_SELECTOR_NOT_FOUND")
        sys.exit(1)
    if etype == "custom-button":
        expiry = info.get("text", "unknown")
        log.info("Step 3: Current expiry (custom button): %s", expiry)
        return expiry
    if etype == "native":
        options = info.get("options", [])
        if options:
            expiry = options[0]["text"]
            log.info("Step 3: Current expiry (native select): %s", expiry)
            return expiry
        return "unknown"
    log.error("Step 3: EXPIRY_SELECTOR_NOT_FOUND")
    sys.exit(1)


def step_4_extract_delta_table() -> str:
    """Step 4: Extract Delta exposure table (raw)."""
    log.info("Step 4: Extracting Delta exposure table")
    raw = evaluate(TABLE_JS)
    if not raw or raw == "[]":
        log.error("Step 4: DELTA_TABLE_EMPTY")
        sys.exit(1)
    log.info("Step 4: Delta table extracted (%d chars, %d rows)", len(raw), len(json.loads(raw)))
    return raw  # raw JSON string — LLM-2 will parse it


def llm_2_parse_delta(raw_table: str) -> list[dict]:
    """LLM-2: Parse raw Delta table rows into structured JSON.

    Uses deterministic parse_table — the table format is consistent
    (strike callExposure putExposure netExposure [tags...]).
    """
    log.info("LLM-2: Parsing Delta table rows (deterministic)")
    parsed = parse_table(raw_table)
    log.info("LLM-2: Delta table parsed — %d rows", len(parsed))
    return parsed


def step_5_switch_gamma() -> None:
    """Step 5: Switch to Gamma Exposure tab."""
    log.info("Step 5: Switching to Gamma Exposure tab")
    result = evaluate(GAMMA_TAB_JS)
    if result != "clicked":
        log.error("Step 5: GAMMA_TAB_NOT_FOUND")
        sys.exit(1)
    log.info("Step 5: Gamma tab clicked, waiting 2s for data refresh")
    time.sleep(2)  # Wait for data refresh


def step_6_extract_gamma_table() -> str:
    """Step 6: Extract Gamma exposure table (raw)."""
    log.info("Step 6: Extracting Gamma exposure table")
    raw = evaluate(TABLE_JS)
    if not raw or raw == "[]":
        log.error("Step 6: GAMMA_TABLE_EMPTY")
        sys.exit(1)
    log.info("Step 6: Gamma table extracted (%d chars, %d rows)", len(raw), len(json.loads(raw)))
    return raw  # raw JSON string — LLM-3 will parse it


def llm_3_parse_gamma(raw_table: str) -> list[dict]:
    """LLM-3: Parse raw Gamma table rows into structured JSON.

    Uses deterministic parse_table — the table format is consistent
    (strike callExposure putExposure netExposure [tags...]).
    """
    log.info("LLM-3: Parsing Gamma table rows (deterministic)")
    parsed = parse_table(raw_table)
    log.info("LLM-3: Gamma table parsed — %d rows", len(parsed))
    return parsed


def llm_4_compile(summary: dict, delta_rows: list[dict], gamma_rows: list[dict], expiry: str) -> str:
    """LLM-4: Compile final formatted output from structured data."""
    log.info("LLM-4: Compiling final output")
    user_prompt = f"""Expiry: {expiry}

Summary: {json.dumps(summary, indent=2)}

Delta Table: {json.dumps(delta_rows, indent=2)}

Gamma Table: {json.dumps(gamma_rows, indent=2)}

Format the output exactly as specified in the PID document."""
    result = _llm_call(LLM_4_SYSTEM, user_prompt)
    log.info("LLM-4: Final output compiled (%d chars)", len(result))
    return result


def llm_5_suggest_strikes(summary: dict, delta_rows: list[dict], gamma_rows: list[dict], expiry: str) -> dict:
    """LLM-5: Suggest strikes for option selling based on ratios and levels.

    Uses the AI brain to analyze DEX ratio, delta/gamma exposure,
    and key levels to recommend option selling strikes.
    """
    log.info("LLM-5: Suggesting strikes for option selling")
    user_prompt = f"""Expiry: {expiry}

Summary: {json.dumps(summary, indent=2)}

Delta Table: {json.dumps(delta_rows, indent=2)}

Gamma Table: {json.dumps(gamma_rows, indent=2)}

Analyze the data and suggest strikes for option selling (SELL PE and SELL CE).
Focus on:
1. DEX ratio for directional bias
2. Put support / peak -delta exp levels for PE selling
3. Call resistance / peak +delta exp levels for CE selling
4. Gamma flip levels for risk management

Return ONLY a valid JSON object with keys: direction, sell_pe_strike, sell_ce_strike, confidence, rationale, expected_credit_pts."""
    result = _llm_call(LLM_5_SYSTEM, user_prompt)
    try:
        parsed = json.loads(result)
        log.info("LLM-5: Strike suggestions — direction=%s, PE=%s, CE=%s, confidence=%s",
                 parsed.get("direction"), parsed.get("sell_pe_strike"),
                 parsed.get("sell_ce_strike"), parsed.get("confidence"))
        return parsed
    except json.JSONDecodeError as e:
        log.error("LLM-5: LLM_PARSE_STRIKES_FAILED: %s", e)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Dhan DEX deterministic extraction agent")
    parser.add_argument("--strike-selection", action="store_true", help="Compute GEX_DEX_ALIGNED strikes after extraction")
    args = parser.parse_args()

    log.info("=" * 60)
    log.info("Dhan DEX Agent v1 — Deterministic Workflow Starting")
    log.info("=" * 60)

    # Pre-flight: verify OpenRouter API key
    if not OPENROUTER_API_KEY:
        log.error("LLM_API_KEY_MISSING — set OPENROUTER_API_KEY environment variable")
        sys.exit(1)
    log.info("Pre-flight: OPENROUTER_API_KEY present, model=%s", OPENROUTER_MODEL)

    # Deterministic steps — no branching, no retries
    log.info("--- Step 0: Daemon ---")
    step_0_start_daemon()

    log.info("--- Step 1: Navigate ---")
    step_1_navigate()

    log.info("--- Step 2: Extract Summary ---")
    raw_summary = step_2_extract_summary()

    log.info("--- LLM-1: Clean Summary ---")
    summary = llm_1_clean_summary(raw_summary)

    log.info("--- Step 3: Detect Expiry ---")
    expiry = step_3_detect_expiry()

    log.info("--- Step 4: Extract Delta Table ---")
    raw_delta = step_4_extract_delta_table()

    log.info("--- LLM-2: Parse Delta Table ---")
    delta_rows = llm_2_parse_delta(raw_delta)

    log.info("--- Step 5: Switch to Gamma Tab ---")
    step_5_switch_gamma()

    log.info("--- Step 6: Extract Gamma Table ---")
    raw_gamma = step_6_extract_gamma_table()

    log.info("--- LLM-3: Parse Gamma Table ---")
    gamma_rows = llm_3_parse_gamma(raw_gamma)

    log.info("--- LLM-4: Compile Output ---")
    output = llm_4_compile(summary, delta_rows, gamma_rows, expiry)
    print(output)

    log.info("--- LLM-5: Suggest Strikes for Option Selling ---")
    strikes = llm_5_suggest_strikes(summary, delta_rows, gamma_rows, expiry)

    print("\n" + "=" * 60)
    print("OPTION SELLING SUGGESTIONS")
    print("=" * 60)
    print(f"Direction     : {strikes.get('direction', 'N/A')}")
    print(f"Sell PE @     : {strikes.get('sell_pe_strike', 'N/A')}")
    print(f"Sell CE @     : {strikes.get('sell_ce_strike', 'N/A')}")
    print(f"Confidence    : {strikes.get('confidence', 'N/A')}")
    print(f"Rationale     : {strikes.get('rationale', 'N/A')}")
    print(f"Expected Credit: {strikes.get('expected_credit_pts', 'N/A')}")
    print("=" * 60)

    if args.strike_selection:
        # Deterministic: only runs if explicitly requested
        # Uses the extracted levels to feed StrikeSelector
        # (Implementation depends on osse.options.strike_selector — see PID doc)
        log.info("Strike selection requested — see PID doc for GEX_DEX_ALIGNED integration")


if __name__ == "__main__":
    main()
