import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  // Test directory
  testDir: './tests',

  // Run tests sequentially (important for free LLM demo)
  fullyParallel: false,

  // Fail fast on first failure per file
  forbidOnly: false,

  // No retries at Playwright level
  // Retries handled by our Agent C loop
  retries: 0,

  // Single worker for stability
  workers: 1,

  // Reporter configuration
  reporter: [
    ['list'],
    ['json', { outputFile: 'reports/playwright_results.json' }],
    ['html', { outputFolder: 'reports/playwright_html', open: 'never' }]
  ],

  use: {
    // Base URL from environment variable
    // Set by Agent B before running tests
    baseURL: process.env.BASE_URL || 'https://the-internet.herokuapp.com',

    // Browser settings
    headless: true,
    screenshot: 'on',
    video: 'off',

    // Timeouts
    actionTimeout: 10000,
    navigationTimeout: 30000,
  },

  // Timeout per test
  timeout: 30000,

  // Only Chromium for demo
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  // Output folder for test artifacts
  outputDir: 'reports/test-results',
});
