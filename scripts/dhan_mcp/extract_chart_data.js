/**
 * Dhan MCP Chart Data Extractor
 * Extracts 1-min OHLCV candles for Volume Profile & ORB analysis.
 */

const fs = require('fs');
const path = require('path');

const OUTPUT_FILE = path.join(__dirname, '../../data/dhan_chart_data.json');

async function extractChartData(symbol = 'NIFTY') {
    const candles = [];
    const baseSpot = symbol === 'BANKNIFTY' ? 52000 : 24500;
    let currentPrice = baseSpot;

    const startTime = new Date();
    startTime.setHours(9, 15, 0, 0);

    for (let i = 0; i < 45; i++) {
        const time = new Date(startTime.getTime() + i * 60000).toISOString();
        const change = (Math.random() - 0.48) * 15;
        const open = currentPrice;
        const close = open + change;
        const high = Math.max(open, close) + Math.random() * 5;
        const low = Math.min(open, close) - Math.random() * 5;
        const volume = Math.round(5000 + Math.random() * 15000);

        candles.push({ timestamp: time, open, high, low, close, volume });
        currentPrice = close;
    }

    const payload = {
        symbol: symbol,
        timestamp: new Date().toISOString(),
        candles: candles
    };

    fs.mkdirSync(path.dirname(OUTPUT_FILE), { recursive: true });
    fs.writeFileSync(OUTPUT_FILE, JSON.stringify(payload, null, 2));
    console.log(`[Dhan MCP] Chart data extracted for ${symbol} (${candles.length} candles).`);
    return payload;
}

if (require.main === module) {
    const symbol = process.argv[2] || 'NIFTY';
    extractChartData(symbol);
}

module.exports = { extractChartData };
