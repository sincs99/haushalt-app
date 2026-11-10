import { expect, test } from '@playwright/test'
import { expectOnDashboard, login, PASSWORD, register, uniqueUser } from './helpers'

test('Registrieren gründet einen Haushalt; Anmelden auf einem zweiten Gerät übersteht ein Neuladen', async ({ page, browser }) => {
  const user = uniqueUser('Clara')

  await register(page, user, { householdName: 'E2E-Familie' })

  // Sitzung bleibt nach dem Neuladen bestehen (Refresh-Cookie), keine Umleitung auf /login
  await page.reload()
  await expectOnDashboard(page, user)

  // Zweites Gerät ohne Cookies: geschützte Seite → Login → zurück zum Ziel
  const otherDevice = await browser.newContext()
  try {
    const page2 = await otherDevice.newPage()
    await page2.goto('/dashboard')
    await expect(page2).toHaveURL(/\/login\?redirect=/)

    await login(page2, user)
    await page2.reload()
    await expectOnDashboard(page2, user)

    // Der bei der Registrierung gegründete Haushalt ist aktiv
    await page2.goto('/household')
    await expect(page2.getByRole('textbox', { name: 'Haushaltsname' })).toHaveValue('E2E-Familie')
  } finally {
    await otherDevice.close()
  }
})

test('Abgelehnte Anmeldung zeigt eine Fehlermeldung und behält die E-Mail-Adresse', async ({ page }) => {
  const user = uniqueUser('Dora')
  await register(page, user, { householdName: 'E2E-Fehlversuch' })
  await page.context().clearCookies()
  await page.goto('/login')

  await page.getByLabel('E-Mail').fill(user.email)
  await page.getByLabel('Passwort', { exact: true }).fill('falsches-Passwort-1')
  await page.getByRole('button', { name: 'Anmelden' }).click()

  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page).toHaveURL(/\/login/)
  await expect(page.getByLabel('E-Mail')).toHaveValue(user.email)

  // Der zweite Versuch mit dem richtigen Passwort funktioniert aus demselben Formular
  await page.getByLabel('Passwort', { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Anmelden' }).click()
  await expectOnDashboard(page, user)
})

test('Abgelehnte Registrierung zeigt eine Fehlermeldung und behält die Eingaben', async ({ page }) => {
  const existing = uniqueUser('Emil')
  await register(page, existing, { householdName: 'E2E-Doppelt' })
  await page.context().clearCookies()
  await page.goto('/register')

  // Dieselbe E-Mail-Adresse noch einmal: der Server lehnt ab
  await page.getByLabel('E-Mail').fill(existing.email)
  await page.getByLabel('Passwort', { exact: true }).fill(PASSWORD)
  await page.getByLabel('Anzeigename').fill('Emil Zwei')
  await page.getByLabel('Haushaltsname').fill('E2E-Doppelt-2')
  await page.getByRole('button', { name: 'Registrieren' }).click()

  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page).toHaveURL(/\/register/)
  await expect(page.getByLabel('E-Mail')).toHaveValue(existing.email)
  await expect(page.getByLabel('Anzeigename')).toHaveValue('Emil Zwei')
})
