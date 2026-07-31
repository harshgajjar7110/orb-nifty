/**
 * Dhan MCP Option Chain Extractor (Playwright / Node.js)
 *
 * Authenticates against the Dhan web platform, navigates to the option-chain
 * dashboard, extracts strike-level CE/PE data, and writes a JSON payload for
 * downstream OSSE analysis.
 *
 * Usage:
 *   node extract_option_chain.js [SYMBOL] [--mock]
 *
 * Environment:
 *   DHAN_CLIENT_ID, DHAN_PASSWORD  - login credentials (env only)
 *   HEADLESS=false                 - run browser visibly for debugging
 *   MOCK_OPTION_CHAIN=1            - write synthetic data without browsing
 */

const fs = require('fs');
const path = require('path');
const playwright = require('playwright');

const { getOrAuthenticateSession } = require('./auth_manager');

const OUTPUT_FILE = path.join(__dirname, '../../data/dhan_option_chain.json');
const OPTION_CHAIN_BASE_URL = 'https://web.dhan.co/option-chain';

function parseArgs(argv) {
    const symbol = argv.find(a => !a.startsWith('--')) || 'NIFTY';
    const useMock = argv.includes('--mock') || process.env.MOCK_OPTION_CHAIN === '1';
    return { symbol, useMock };
}

function generateMockChain(symbol = 'NIFTY') {
    const baseSpot = symbol === 'BANKNIFTY' ? 52000 : 24500;
    const step = symbol === 'BANKNIFTY' ? 100 : 50;
    const mockChain = [];

    for (let i = -10; i <= 10; i++) {
        const strike = baseSpot + (i * step);
        const dist = Math.abs(i);
        const ce_delta = Math.max(0.01, Math.min(0.99, 0.50 - (i * 0.04)));
        const pe_delta = -Math.max(0.01, Math.min(0.99, 0.50 + (i * 0.04)));

        mockChain.push({
            strike_price: strike,
            ce_oi: Math.round(100000 * Math.exp(-dist * 0.15)),
            ce_delta: parseFloat(ce_delta.toFixed(2)),
            ce_iv: 15.5,
            ce_volume: 50000,
            pe_oi: Math.round(120000 * Math.exp(-dist * 0.12)),
            pe_delta: parseFloat(pe_delta.toFixed(2)),
            pe_iv: 16.0,
            pe_volume: 60000
        });
    }

    return {
        symbol: symbol,
        timestamp: new Date().toISOString(),
        spot_price: baseSpot,
        option_chain: mockChain,
        source: 'mock'
    };
}

async function extractOptionChain(symbol = 'NIFTY') {
    const stateFile = await getOrAuthenticateSession(playwright);

    const browser = await playwright.chromium.launch({
        headless: process.env.HEADLESS !== 'false'
    });

    let payload = null;
    try {
        const context = await browser.newContext({ storageState: stateFile });
        const page = await context.newPage();

        const url = `${OPTION_CHAIN_BASE_URL}?symbol=${encodeURIComponent(symbol)}`;
        console.log(`[Dhan MCP] Navigating to option chain: ${url}`);
        await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 });

        // Wait for any plausible table-like structure to appear.
        await page.waitForSelector('table, .option-chain-table, [data-testid="option-chain-table"]', {
            timeout: 15000
        });

        // Allow dynamic data to settle.
        await page.waitForTimeout(2500);

        payload = await page.evaluate((sym) => {
            const spotElem = document.querySelector('.spot-price, .underlying-value, [data-testid="spot-price"]');
            const spotPrice = spotElem ? parseFloat(spotElem.innerText.replace(/[^0-9.]/g, '')) : null;

            const tables = Array.from(document.querySelectorAll('table'));
            const chainTable = tables.find(t => {
                const text = t.innerText || '';
                return /strike|call|put|oi|iv/i.test(text) && t.querySelectorAll('tr').length > 5;
            });

            const rows = chainTable
                ? Array.from(chainTable.querySelectorAll('tbody tr')).map(r => {
                    const cols = Array.from(r.querySelectorAll('td')).map(c => c.innerText.trim().replace(/,/g, ''));
                    if (cols.length < 7) return null;
                    return {
                        strike_price: parseFloat(cols[0]) || 0,
                        ce_oi: parseFloat(cols[1]) || 0,
                        ce_iv: parseFloat(cols[2]) || 0,
                        ce_ltp: parseFloat(cols[3]) || 0,
                        pe_ltp: parseFloat(cols[4]) || 0,
                        pe_iv: parseFloat(cols[5]) || 0,
                        pe_oi: parseFloat(cols[6]) || 0,
                        // Fallback aliases so downstream parsers can normalise
                        call_ltp: parseFloat(cols[3]) || 0,
                        call_iv: parseFloat(cols[2]) || 0,
                        call_oi: parseFloat(cols[1]) || 0,
                        put_ltp: parseFloat(cols[4]) || 0,
                        put_iv: parseFloat(cols[5]) || 0,
                        put_oi: parseFloat(cols[6]) || 0
                    };
                }).filter(Boolean)
                : [];

            return {
                symbol: sym,
                timestamp: new Date().toISOString(),
                spot_price: spotPrice,
                option_chain: rows,
                source: 'dhan_web'
            };
        }, symbol);

        console.log(`[Dhan MCP] Extracted ${payload.option_chain.length} strikes for ${symbol}.`);
    } catch (err) {
        console.error(`[Dhan MCP] Extraction failed: ${err.message}`);
        throw err;
    } finally {
        await browser.close();
    }

    return payload;
}

async function main() {
    const { symbol, useMock } = parseArgs(process.argv.slice(2));

    let payload;
    if (useMock) {
        payload = generateMockChain(symbol);
    } else {
        try {
            payload = await extractOptionChain(symbol);
        } catch (err) {
            console.warn('[Dhan MCP] Falling back to mock option chain.');
            payload = generateMockChain(symbol);
        }
    }

    fs.mkdirSync(path.dirname(OUTPUT_FILE), { recursive: true });
    fs.writeFileSync(OUTPUT_FILE, JSON.stringify(payload, null, 2));
    console.log(`[Dhan MCP] Option chain extracted for ${symbol} -> ${OUTPUT_FILE}`);
    return payload;
}

if (require.main === module) {
    main().catch(err => {
        console.error('[Dhan MCP] Fatal error:', err.message);
        process.exit(1);
    });
}

module.exports = { extractOptionChain, generateMockChain, OPTION_CHAIN_BASE_URL };
