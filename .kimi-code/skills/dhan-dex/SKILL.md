# Dhan Dext DEX Scraper Skill

Fast, reusable Dhan Dext (https://dext.dhan.co/dashboard) Delta/Gamma exposure extraction and strike recommendation.

## Quick Run

```bash
# Ensure daemon is up
~/.kimi-webbridge/bin/kimi-webbridge start

# Navigate
curl -s -X POST http://127.0.0.1:10086/command \
  -H 'Content-Type: application/json' \
  -d '{"action":"navigate","args":{"url":"https://dext.dhan.co/dashboard","newTab":true,"group_title":"Dhan DEX check"},"session":"dhan-dex-check"}'

# Wait 2-3s, then extract
```

## 1. Extract Summary

```javascript
(() => {
  const labels = Array.from(document.querySelectorAll("*")).filter(
    el => el.children.length === 0 && /(Total Call|Total Put|Total Net|DEX Ratio|Nifty 50)/.test(el.textContent)
  );
  const summary = {};
  labels.forEach(el => {
    const parent = el.parentElement?.textContent?.trim();
    if (!parent) return;
    const m = parent.match(/(Total Call|Total Put|Total Net|DEX Ratio|Nifty 50)[:\s]*([^\n]+)/);
    if (m) summary[m[1]] = m[2].trim();
  });
  return JSON.stringify(summary);
})()
```

Returns:
- `Nifty 50` → symbol text
- `Total Call` → e.g. `59,54,036.16 Cr`
- `Total Put` → e.g. `-57,07,756.76 Cr`
- `Total Net` → e.g. `2,46,279.40 Cr`
- `DEX Ratio` → e.g. `0.96 (Balanced)`

Spot price is in the SVG text as `Spot Price 24416.80`.

## 2. Extract Δ Exposure Table

```javascript
(() => {
  const rows = Array.from(document.querySelectorAll("[class*=\"greeks-exposure-table-row\"]"));
  return JSON.stringify(rows.map(r => r.textContent.trim().replace(/\s+/g, " ")));
})()
```

Row format: `strike callExposure putExposure netExposure tag`

Key tags to grep:
- `Peak -Delta exp`
- `Delta Flip`
- `Put Support`
- `Call Resistance`
- `Peak +Delta exp`

## 3. Switch to Γ Exposure

```javascript
(() => {
  const tabs = Array.from(document.querySelectorAll("button, [role=\"tab\"]")).filter(
    el => /Gamma Exposure/.test(el.textContent)
  );
  if (tabs.length) { tabs[0].click(); return "clicked"; }
  return "not found";
})()
```

Wait 2s, then repeat table extraction (step 2). Tags are similar: `Peak -Gamma exp`, `Put Support`, `Call Resistance Gamma Flip`, `Peak +Gamma exp`.

## 4. Compute GEX_DEX_ALIGNED Strikes

Use `src/osse/options/strike_selector.py` with variant `GEX_DEX_ALIGNED`.

```python
from osse.options.strike_selector import StrikeSelector

selector = StrikeSelector("config/strike_rules.yaml")

dex_data = {
    "put_support": 24300,
    "call_wall": 24400,
    "delta_flip": 24400,
}
gex_data = {
    "gamma_flip": 24400,
    "peak_neg_gamma_strike": 24200,
    "peak_pos_gamma_strike": 24500,
}

result = selector.select_strikes(
    strategy_name="Credit Spread",
    spot_price=24366.50,
    symbol="NIFTY",
    variant="GEX_DEX_ALIGNED",
    direction="UP",  # or "DOWN"
    dex_data=dex_data,
    gex_data=gex_data,
    vix=10.33,
)
```

### Strike selection logic

For **UP** (Put Credit Spread):
- Priority candidates (from `config/strike_rules.yaml` → `up_direction_priority`): `put_support`, `delta_flip`, `gamma_flip`, `peak_neg_gamma_strike`
- Anchor = `max(valid candidates)`
- `short_k = round(anchor / step) * step`; clamped so short PE is ≤ `spot − step`
- `long_k  = round((short_k − 2 × step) / step) * step`

For **DOWN** (Call Credit Spread):
- Priority candidates (from `down_direction_priority`): `call_wall`, `peak_pos_gamma_strike`, `delta_flip`, `gamma_flip`
- Anchor = `min(valid candidates)`
- `short_k = round(anchor / step) * step`; clamped so short CE is ≥ `spot + step`
- `long_k  = round((short_k + 2 × step) / step) * step`

Both strikes are always rounded to the symbol `step_size` (NIFTY = 50). If either computed strike is absent from the supplied option chain a `ValueError` is raised — widen `strike_depth` or verify the exposure levels.

## 5. Output Template

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

Strikes:
- UP: SELL PE <short> / BUY PE <long> → credit ~<pts> pts
- DOWN: SELL CE <short> / BUY CE <long> → credit ~<pts> pts

No order placed. Confirm direction + qty to execute.
```

## 6. Notes

- Dhan Dext lot size shown is 65 for NIFTY, but `config/strike_rules.yaml` uses 75. Update config if P&L must match Dhan.
- Do not auto-place orders; always ask for explicit direction + quantity confirmation.
- If daemon is not reachable, run `~/.kimi-webbridge/bin/kimi-webbridge start` first.
