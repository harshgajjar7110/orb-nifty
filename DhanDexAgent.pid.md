# Dhan DEX Agent — Process ID (PID) Document

## Identity

| Field | Value |
|---|---|
| **PID** | `DHAN-DEX-AGENT-v1` |
| **Name** | Dhan DEX DOM Extraction Agent |
| **Owner** | orb-nifty |
| **Trigger** | User request to extract Dhan DEX dashboard data |
| **Determinism** | Fully deterministic — same session state → same steps → same output |

## Prerequisites

1. `kimi-webbridge` daemon must be installed at `~/.kimi-webbridge/bin/kimi-webbridge`
2. Network access to `https://dext.dhan.co/dashboard`
3. Valid Dhan session cookies in the browser profile managed by kimi-webbridge
4. `curl` available on the host
5. `OPENROUTER_API_KEY` environment variable must be set (see `.env.example`)
6. Python `requests` library available (already a project dependency)

## OpenRouter LLM Configuration

The agent uses OpenRouter for LLM access between extraction steps (parsing, reasoning, structured output).

| Field | Value |
|---|---|
| **Provider** | OpenRouter |
| **Model** | `inclusionai/ling-3.0-flash:free` |
| **API Key** | `OPENROUTER_API_KEY` environment variable |
| **Base URL** | `https://openrouter.ai/api/v1` |
| **Timeout** | 30 seconds per call |

The API key is read from the environment at startup. If `OPENROUTER_API_KEY` is not set, the agent terminates with error `LLM_API_KEY_MISSING`. No hardcoded keys anywhere.

## LLM Integration Points

The LLM is invoked at specific integration points between deterministic steps. Each LLM call has a fixed prompt and a fixed expected output schema. The LLM does not alter the workflow order — it only assists with parsing and structuring.

| Integration Point | Between Steps | Purpose |
|---|---|---|
| **LLM-1** | Steps 2 → 3 | Parse messy summary text into clean key-value pairs (extract spot price from chart labels) |
| **Delta** | Steps 4 → 5 | Deterministic `parse_table()` — no LLM call. Split on `" | "`, strip `" Cr"`, map `-` to `0 Cr`, collect tags |
| **Gamma** | Steps 6 → 7 | Deterministic `parse_table()` — no LLM call (same logic as Delta parsing) |
| **LLM-4** | Step 7 | Compile final output from structured data |
| **LLM-5** | After LLM-4 | Suggest option selling strikes based on DEX ratio, delta/gamma levels, and key exposure tags |

Each LLM call uses the same request format:

```python
{
    "model": "inclusionai/ling-3.0-flash:free",
    "messages": [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": USER_PROMPT}
    ],
    "temperature": 0.0,
    "max_tokens": 16384
}
```

**temperature is always 0.0** — deterministic output, no randomness. LLM calls are made only for LLM-1 (summary parsing), LLM-4 (compilation), and LLM-5 (strike suggestion). Table parsing (Delta + Gamma) is fully deterministic via `parse_table()` — no LLM required.

## Deterministic Workflow

The agent executes steps **in order, exactly once, no branching**. If a step fails, it falls back to the defined fallback (if any) or terminates with a structured error. No retries, no exploration. LLM calls (LLM-1, LLM-4, LLM-5) are integration points that assist with parsing and reasoning — they do not alter the workflow order. Table parsing (Delta + Gamma) is fully deterministic via `parse_table()` — no LLM required.

### Step 0: Ensure Daemon Running

```bash
~/.kimi-webbridge/bin/kimi-webbridge start
```

- **Expected output**: `kimi-webbridge daemon is already running` or `started`
- **On failure**: terminate with error `DAEMON_START_FAILED`
- **No retries**

### Step 1: Navigate to Dashboard

```bash
session="dhan-dex-check-v2"
curl -s -X POST http://127.0.0.1:10086/command \
  -H 'Content-Type: application/json' \
  -d '{"action":"navigate","args":{"url":"https://dext.dhan.co/dashboard","newTab":false,"group_title":"Dhan DEX check"},"session":"dhan-dex-check-v2"}'
```

- **Expected output**: `{"ok":true,"data":{"success":true,"url":"https://dext.dhan.co/dashboard","tabId":<number>}}`
- **On failure**: terminate with error `NAVIGATE_FAILED`
- **Wait**: 3 seconds after navigation (page is a React app; DOM needs render time)

### Step 2: Extract Summary Cards (raw)

```bash
curl -s -X POST http://127.0.0.1:10086/command \
  -H 'Content-Type: application/json' \
  -d '{"action":"evaluate","args":{"code":"(() => { const labels = Array.from(document.querySelectorAll(\"body *\")).filter( el => el.children.length === 0 && /(Total Call|Total Put|Total Net|DEX Ratio|Nifty 50|Spot Price)/.test(el.textContent) ); const summary = {}; labels.forEach(el => { const parent = el.parentElement?.textContent?.trim(); if (!parent) return; const m = parent.match(/(Total Call|Total Put|Total Net|DEX Ratio|Nifty 50|Spot Price)[:\\\\s]*(.+)/); if (m) summary[m[1]] = m[2].trim(); }); return JSON.stringify(summary); })()"},"session":"dhan-dex-check-v2"}'
```

- **Expected output**: JSON with keys `Total Call`, `Total Put`, `Total Net`, `DEX Ratio`, `Nifty 50`, `Spot Price`
- **Spot Price**: Raw value may include chart axis labels — LLM-1 will clean this.
- **On failure**: terminate with error `SUMMARY_EXTRACT_FAILED`

### LLM-1: Clean Summary Data

Send the raw summary JSON to OpenRouter with a fixed prompt to extract clean values:

- **Input**: Raw summary JSON from Step 2
- **Output**: Cleaned JSON with `spot_price` (float), `total_call`, `total_put`, `total_net`, `dex_ratio`, `dex_sentiment`
- **On failure**: terminate with error `LLM_PARSE_SUMMARY_FAILED`

### Step 3: Detect Expiry Selector

```bash
curl -s -X POST http://127.0.0.1:10086/command \
  -H 'Content-Type: application/json' \
  -d '{"action":"evaluate","args":{"code":"(() => { const sel = document.querySelector(\"select.appearance-none\"); if (sel) return JSON.stringify({type:\"native\", options: Array.from(sel.options).map(o => ({text: o.text, value: o.value}))}); const btn = document.querySelector(\"button.global-dropdown-button\"); if (btn) return JSON.stringify({type:\"custom-button\", text: btn.textContent.trim()}); return JSON.stringify({type: \"not-found\"}); })()"},"session":"dhan-dex-check-v2"}'
```

- **Expected output**: `{type: "native", options: [...]}` or `{type: "custom-button", text: "04 Aug 2026"}`
- **If `type: "not-found"`**: terminate with error `EXPIRY_SELECTOR_NOT_FOUND`
- **If `type: "custom-button"`**: the current expiry is the button text. No further action needed — the page is already on that expiry.
- **If `type: "native"`**: the page has a native `<select>`. To change expiry, use the JavaScript from the skill file (set `sel.value` + dispatch `change` event). Wait 3s after change.

### Step 4: Extract Delta Exposure Table (raw)

```javascript
(() => {
  const container = document.querySelector("[class*=greeks-table-scroll-wrap]");
  if (!container) return JSON.stringify([]);
  const rows = Array.from(container.querySelectorAll("[class*=greeks-exposure-table-row]"));
  return JSON.stringify(rows.map(r => {
    const cells = Array.from(r.children).map(c => c.textContent.trim());
    if (cells.length === 0) return r.textContent.trim().replace(/\s+/g, " ");
    return cells.join(" | ");
  }));
})()
```

- **Expected output**: JSON array of strings, each string = cell-separated by `" | "`: `strike | callExposure | putExposure | netExposure | tags`
- **Cell-by-cell extraction**: Each `<tr>` row's `<td>` or child cell is extracted individually via `r.children`, then joined with `" | "`. This isolates the "Cr" currency suffix within its own cell and prevents column misalignment.
- **Key tags to identify**: `Peak -Delta exp`, `Delta Flip`, `Put Support`, `Call Resistance`, `Peak +Delta exp`
- **On failure (empty array)**: terminate with error `DELTA_TABLE_EMPTY`

### LLM-2: Parse Delta Table (deterministic `parse_table`)

Uses the **deterministic** `parse_table()` function — no LLM call needed. The function splits on `" | "`, strips `" Cr"` suffixes, maps `-` (zero exposure placeholder) to `"0 Cr"`, and collects trailing non-numeric cells as tags.

- **Input**: Raw table rows JSON array (from Step 4)
- **Output**: Array of objects: `{strike, call_exposure, put_exposure, net_exposure, tags[]}`
- **On failure**: terminate with error `LLM_PARSE_DELTA_FAILED`

### Step 5: Switch to Gamma Exposure Tab

```bash
curl -s -X POST http://127.0.0.1:10086/command \
  -H 'Content-Type: application/json' \
  -d '{"action":"evaluate","args":{"code":"(() => { const tabs = Array.from(document.querySelectorAll(\"button\")).filter(el => /Gamma Exposure/.test(el.textContent)); if (tabs.length) { tabs[0].click(); return \"clicked\"; } return \"not found\"; })()"},"session":"dhan-dex-check-v2"}'
```

- **Expected output**: `"clicked"`
- **On failure (`"not found"`)**: terminate with error `GAMMA_TAB_NOT_FOUND`
- **Wait**: 2 seconds after click for data refresh

### Step 6: Extract Gamma Exposure Table (raw)

Same cell-by-cell `TABLE_JS` command as Step 4 (queries the `greeks-table-scroll-wrap` container, extracts `r.children` joined with `" | "`).

- **Expected output**: JSON array of strings (same `" | "`-delimited format as Delta table)
- **Key tags**: `Peak -Gamma exp`, `Gamma Flip`, `Put Support`, `Call Resistance Gamma Flip`, `Peak +Gamma exp`
- **On failure (empty array)**: terminate with error `GAMMA_TABLE_EMPTY`

### LLM-3: Parse Gamma Table (deterministic `parse_table`)

Same as LLM-2 — uses `parse_table()` deterministically. No LLM call.

- **On failure**: terminate with error `LLM_PARSE_GAMMA_FAILED`

### LLM-4: Compile Final Output

Send all structured data to OpenRouter with a fixed prompt to produce the final formatted output.

- **Input**: Cleaned summary + parsed Delta table + parsed Gamma table + expiry
- **Output**: Formatted string (see Output Format below)
- **On failure**: terminate with error `LLM_COMPILE_FAILED`

### LLM-5: Suggest Option Selling Strikes

Send all structured data to OpenRouter with a fixed prompt to analyze ratios and suggest option selling strikes.

- **Input**: Cleaned summary + parsed Delta table + parsed Gamma table + expiry
- **Output**: JSON with `direction`, `sell_pe_strike`, `sell_ce_strike`, `confidence`, `rationale`, `expected_credit_pts`
- **On failure**: terminate with error `LLM_PARSE_STRIKES_FAILED`

### Step 7: Return Result

Return the LLM-4 output and LLM-5 strike suggestions to the user chat. No further actions.

## Error Handling

| Error Code | Step | Action |
|---|---|---|
| `DAEMON_START_FAILED` | 0 | Terminate. Report to user. |
| `NAVIGATE_FAILED` | 1 | Terminate. Report to user. |
| `SUMMARY_EXTRACT_FAILED` | 2 | Terminate. Report to user. |
| `LLM_API_KEY_MISSING` | Pre-flight | Terminate. Report to user. |
| `LLM_PARSE_SUMMARY_FAILED` | LLM-1 | Terminate. Report to user. |
| `EXPIRY_SELECTOR_NOT_FOUND` | 3 | Terminate. Report to user. |
| `DELTA_TABLE_EMPTY` | 4 | Terminate. Report to user. |
| `LLM_PARSE_DELTA_FAILED` | LLM-2 | Terminate. Report to user. |
| `GAMMA_TAB_NOT_FOUND` | 5 | Terminate. Report to user. |
| `GAMMA_TABLE_EMPTY` | 6 | Terminate. Report to user. |
| `LLM_PARSE_GAMMA_FAILED` | LLM-3 | Terminate. Report to user. |
| `LLM_COMPILE_FAILED` | LLM-4 | Terminate. Report to user. |
| `LLM_PARSE_STRIKES_FAILED` | LLM-5 | Terminate. Report to user. |

**Rules:**
- No retries on any error.
- No fallback to alternative selectors (the page structure is known and stable).
- On any error, return a structured error message to the user with the error code and the step that failed.
- LLM calls use `temperature=0.0` for deterministic output.

## Output Format

### Dashboard Summary

```
DEX check — <expiry>
- Spot: <spot>
- Total Call Δ: <call>
- Total Put Δ: <put>
- Net Δ: <net>
- DEX Ratio: <ratio>
- Put Support: <strike>
- Call Resistance: <strike>
- Δ Flip: <strike>
- Γ Flip: <strike>
```

### Option Selling Suggestions (LLM-5)

```
OPTION SELLING SUGGESTIONS
Direction     : <bullish|bearish>
Sell PE @     : <strike>
Sell CE @     : <strike>
Confidence    : <high|medium|low>
Rationale     : <explanation>
Expected Credit: <pts> pts
```

If strike selection is not requested, omit the Strikes section.

## Determinism Guarantees

1. **No exploration**: The agent does not search for elements by guessing selectors. It uses the exact selectors defined in this PID.
2. **No retries**: Each step is attempted exactly once. On failure, it terminates.
3. **No branching**: Steps execute in fixed order (0 → 1 → Step 2 → LLM-1 → Step 3 → Step 4 → LLM-2 → Step 5 → Step 6 → LLM-3 → LLM-4 → LLM-5 → Step 7). There are no conditional branches based on intermediate results (except the expiry selector type in Step 3, which only determines whether to change the expiry — it does not change the extraction path).
4. **No state mutation**: The agent does not place orders, does not change settings, does not modify any config files.
5. **Idempotent**: Running the same PID twice with the same session state produces the same output.

## Session Management

- Session name is always `dhan-dex-check-v2`.
- The session is created on first navigate call and reused for all subsequent evaluate calls.
- The agent does not close the session or tab at the end. The user's browser remains open for manual inspection.
