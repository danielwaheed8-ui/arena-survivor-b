import { defineConfig } from '@playwright/test';
import fs from 'node:fs';

/**
 * Visual QA configuration. Runs the production build (`next start`) and
 * drives every screen at desktop, tablet and mobile sizes.
 *
 * The remote environment pre-installs a Chromium at /opt/pw-browsers/chromium;
 * fall back to Playwright's own resolution elsewhere.
 */
const PREINSTALLED_CHROMIUM = '/opt/pw-browsers/chromium';
const executablePath = fs.existsSync(PREINSTALLED_CHROMIUM) ? PREINSTALLED_CHROMIUM : undefined;

export default defineConfig({
  testDir: '.',
  testMatch: 'visual-qa.spec.ts',
  outputDir: './test-results',
  fullyParallel: false,
  workers: 2,
  timeout: 90_000,
  reporter: [['list'], ['json', { outputFile: 'artifacts/results.json' }]],
  use: {
    baseURL: 'http://127.0.0.1:4310',
    launchOptions: executablePath ? { executablePath } : {},
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1440, height: 900 } } },
    { name: 'tablet', use: { viewport: { width: 834, height: 1112 } } },
    { name: 'mobile', use: { viewport: { width: 390, height: 844 } } },
  ],
  webServer: {
    command: 'npm run start',
    url: 'http://127.0.0.1:4310',
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
