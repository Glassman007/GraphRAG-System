import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  use: {
    baseURL: process.env.PHASE13_BASE_URL || process.env.PHASE12_BASE_URL || 'http://127.0.0.1:5174',
    trace: 'retain-on-failure',
  },
  reporter: [['list']],
})
