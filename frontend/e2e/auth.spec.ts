import { expect, test } from '@playwright/test'
import { expectOnDashboard, login, register, uniqueUser } from './helpers'

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
