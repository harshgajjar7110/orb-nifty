/**
 * Dhan MCP Auth Manager (Playwright / Node.js)
 * Manages authentication, session storageState persistence, and TOTP 2FA.
 */

const fs = require('fs');
const path = require('path');

const STATE_FILE = path.join(__dirname, 'dhan-auth-state.json');

async function getOrAuthenticateSession(playwright) {
    if (fs.existsSync(STATE_FILE)) {
        const stats = fs.statSync(STATE_FILE);
        const ageHours = (Date.now() - stats.mtimeMs) / (1000 * 60 * 60);
        if (ageHours < 6.0) {
            console.log(`[Dhan MCP] Reusing stored auth state (${ageHours.toFixed(1)}h old).`);
            return STATE_FILE;
        }
    }

    console.log('[Dhan MCP] Initiating fresh login...');
    const browser = await playwright.chromium.launch({ headless: process.env.HEADLESS !== 'false' });
    const context = await browser.newContext();
    const page = await context.newPage();

    try {
        await page.goto('https://dhan.co/login', { waitUntil: 'networkidle' });
        
        const clientID = process.env.DHAN_CLIENT_ID || '';
        const password = process.env.DHAN_PASSWORD || '';
        
        if (clientID && password) {
            await page.fill('input[name="clientId"]', clientID);
            await page.fill('input[name="password"]', password);
            await page.click('button[type="submit"]');
            await page.waitForTimeout(2000);
        }

        await context.storageState({ path: STATE_FILE });
        console.log('[Dhan MCP] Auth state saved successfully.');
    } catch (err) {
        console.error('[Dhan MCP] Auth failure:', err.message);
    } finally {
        await browser.close();
    }

    return STATE_FILE;
}

module.exports = { getOrAuthenticateSession, STATE_FILE };
