const { defineConfig } = require('@playwright/test');
module.exports = defineConfig({
  testDir: './scripts/e2e', timeout: 45000, expect: { timeout: 10000 },
  fullyParallel: false, workers: 1, retries: 0,
  reporter: 'list', use: { baseURL: process.env.E2E_URL || 'http://127.0.0.1:18080',
    browserName: 'chromium', channel: process.env.E2E_BROWSER_CHANNEL || undefined,
    headless: true, viewport: { width: 1440, height: 1000 }, trace: 'off', screenshot: 'off' },
});
