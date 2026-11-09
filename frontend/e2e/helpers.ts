import { expect, type Browser, type Page } from '@playwright/test'

export const PASSWORD = 'e2e-Passwort-123'

export interface TestUser {
  email: string
  displayName: string
}

/** Eindeutiger Benutzer pro Lauf; die Test-Datenbank muss nicht geleert werden. */
export function uniqueUser(firstName: string): TestUser {
  const suffix = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`
  return {
    email: `e2e-${firstName.toLowerCase()}-${suffix}@example.com`,
    displayName: `${firstName} E2E`,
  }
}

/** Registriert über das Formular; ohne Einladungscode wird ein neuer Haushalt gegründet. */
export async function register(
  page: Page,
  user: TestUser,
  options: { householdName?: string; inviteCode?: string },
): Promise<void> {
  await page.goto('/register')
  if (options.inviteCode) {
    await page.getByRole('button', { name: 'Mit Code beitreten' }).click()
  }
  await page.getByLabel('E-Mail').fill(user.email)
  await page.getByLabel('Passwort', { exact: true }).fill(PASSWORD)
  await page.getByLabel('Anzeigename').fill(user.displayName)
  if (options.inviteCode) {
    await page.getByLabel('Einladungscode').fill(options.inviteCode)
  } else {
    await page.getByLabel('Haushaltsname').fill(options.householdName ?? 'E2E-Haushalt')
  }
  await page.getByRole('button', { name: 'Registrieren' }).click()
  await expectOnDashboard(page, user)
}

export async function login(page: Page, user: TestUser): Promise<void> {
  // Bereits auf /login (z. B. nach Umleitung mit ?redirect=): dort bleiben
  if (!new URL(page.url()).pathname.startsWith('/login')) await page.goto('/login')
  await page.getByLabel('E-Mail').fill(user.email)
  await page.getByLabel('Passwort', { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Anmelden' }).click()
  await expectOnDashboard(page, user)
}

/** Dashboard begrüsst mit dem Vornamen („Guten Morgen, Anna"). */
export async function expectOnDashboard(page: Page, user: TestUser): Promise<void> {
  await expect(page).toHaveURL(/\/dashboard$/)
  const firstName = user.displayName.split(' ')[0]
  await expect(page.getByRole('heading', { level: 1, name: new RegExp(`, ${firstName}$`) })).toBeVisible()
}

/** Einladungscode des aktuellen Haushalts aus der Haushaltsseite lesen. */
export async function readInviteCode(page: Page): Promise<string> {
  await page.goto('/household')
  const codeEl = page.getByTestId('invite-code')
  await expect(codeEl).toHaveText(/^[A-Za-z0-9-]{4,}$/)
  return (await codeEl.textContent())!.trim()
}

/**
 * Wartet, bis die Live-Verbindung steht und der Socket dem Haushaltsraum beigetreten ist
 * (der Sync-Punkt zeigt „Verbunden“ erst nach `join_household`).
 */
export async function expectLiveSync(page: Page): Promise<void> {
  await expect(page.getByRole('status', { name: 'Verbunden' }).first()).toBeAttached()
}

export interface Household {
  pageA: Page
  pageB: Page
  userA: TestUser
  userB: TestUser
  close: () => Promise<void>
}

/**
 * Zwei getrennte Browser-Kontexte (zwei Geräte): A gründet einen Haushalt,
 * B registriert sich mit dessen Einladungscode.
 */
export async function createSharedHousehold(browser: Browser): Promise<Household> {
  const contextA = await browser.newContext()
  const contextB = await browser.newContext()
  const pageA = await contextA.newPage()
  const pageB = await contextB.newPage()
  const userA = uniqueUser('Anna')
  const userB = uniqueUser('Ben')

  await register(pageA, userA, { householdName: 'E2E-WG' })
  const inviteCode = await readInviteCode(pageA)
  await register(pageB, userB, { inviteCode })

  return {
    pageA,
    pageB,
    userA,
    userB,
    close: async () => {
      await contextA.close()
      await contextB.close()
    },
  }
}
