import { existsSync } from 'node:fs'
import { defineConfig, devices } from '@playwright/test'

/**
 * End-to-End-Tests gegen einen echt laufenden Stack (FastAPI + PostgreSQL + Vite).
 *
 * Pflicht: E2E_DATABASE_URL zeigt auf eine eigens dafür angelegte, leere oder
 * wegwerfbare PostgreSQL-Datenbank; Playwright migriert sie (alembic upgrade head)
 * und startet Backend und Frontend selbst. Jeder Test legt eigene Konten mit
 * eindeutigen E-Mail-Adressen an, die Datenbank muss zwischen Läufen nicht geleert werden.
 *
 * Optional:
 *   E2E_PYTHON         Python mit den Backend-Abhängigkeiten (Standard: python)
 *   E2E_BACKEND_PORT   Standard 8100
 *   E2E_FRONTEND_PORT  Standard 5180
 */
const databaseUrl = process.env.E2E_DATABASE_URL
if (!databaseUrl) {
  throw new Error(
    'E2E_DATABASE_URL fehlt, z. B. postgresql://casa:casa@localhost:5432/casa_e2e (nur eine Test-Datenbank verwenden!)',
  )
}

const python = process.env.E2E_PYTHON || 'python'
const backendPort = Number(process.env.E2E_BACKEND_PORT || 8100)
const frontendPort = Number(process.env.E2E_FRONTEND_PORT || 5180)
const baseURL = `http://localhost:${frontendPort}`
const isCI = !!process.env.CI

// Lokal vorinstalliertes Chromium nutzen, falls vorhanden (z. B. in Sandboxes ohne
// `playwright install`). Die CI installiert den passenden Browser selbst.
const localChromium = '/opt/pw-browsers/chromium'
const launchOptions = !isCI && existsSync(localChromium) ? { executablePath: localChromium } : {}

export default defineConfig({
  testDir: './e2e',
  // Wenige, längere Journeys; seriell ist bei einem Dev-Server am verlässlichsten
  fullyParallel: false,
  workers: 1,
  forbidOnly: isCI,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: isCI ? [['list'], ['html', { open: 'never' }]] : [['list']],
  use: {
    baseURL,
    locale: 'de-CH',
    timezoneId: 'Europe/Zurich',
    serviceWorkers: 'block',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], launchOptions },
    },
  ],
  webServer: [
    {
      name: 'backend',
      command: `${python} -m alembic upgrade head && ${python} -m uvicorn app.main:app --host 127.0.0.1 --port ${backendPort} --no-access-log`,
      cwd: '../backend',
      url: `http://127.0.0.1:${backendPort}/api/health`,
      timeout: 120_000,
      reuseExistingServer: false,
      stdout: 'ignore',
      stderr: 'pipe',
      env: {
        DATABASE_URL: databaseUrl,
        JWT_SECRET_KEY: process.env.E2E_JWT_SECRET_KEY || 'e2e-only-jwt-secret-key-not-for-real-use-0123456789',
        CORS_ORIGINS: baseURL,
        ENVIRONMENT: 'development',
        // Ohne SMTP: keine Bestätigungsmails, keine Pflicht-Zustimmung, kein Tarif-Limit
        MAIL_BACKEND: 'off',
        LEGAL_TERMS_REQUIRED: 'false',
        BILLING_ENABLED: 'false',
        ANTHROPIC_API_KEY: '',
        VAPID_PUBLIC_KEY: '',
        VAPID_PRIVATE_KEY: '',
        // Jeder Lauf registriert mehrere Konten von derselben IP (/register: 3/Stunde)
        RATE_LIMIT_ENABLED: 'false',
        RATE_LIMIT_STORAGE_URI: 'memory://',
        SOCKETIO_MESSAGE_QUEUE: '',
      },
    },
    {
      name: 'frontend',
      command: `npm run dev -- --port ${frontendPort} --strictPort`,
      url: baseURL,
      timeout: 120_000,
      reuseExistingServer: false,
      stdout: 'ignore',
      stderr: 'pipe',
      env: {
        CASA_API_PROXY_TARGET: `http://127.0.0.1:${backendPort}`,
      },
    },
  ],
})
