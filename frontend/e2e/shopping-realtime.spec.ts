import { expect, test } from '@playwright/test'
import { createSharedHousehold, expectLiveSync, type Household } from './helpers'

let household: Household | undefined

test.beforeEach(async ({ browser }) => {
  household = await createSharedHousehold(browser)
})

test.afterEach(async () => {
  await household?.close()
})

test('Einkaufsliste synchronisiert live zwischen zwei Geräten', async () => {
  const { pageA, pageB } = household!
  const itemName = `Hafermilch ${Date.now().toString(36)}`

  // A legt die erste Liste an (neue Haushalte haben noch keine)
  await pageA.goto('/shopping')
  await pageA.getByRole('button', { name: 'Erste Liste erstellen' }).click()
  const newListDialog = pageA.getByRole('dialog', { name: 'Neue Liste' })
  await newListDialog.getByRole('textbox').fill('Wocheneinkauf')
  await newListDialog.getByRole('button', { name: 'Hinzufügen' }).click()
  await expect(pageA.getByRole('button', { name: 'Wocheneinkauf (0)' })).toBeVisible()

  // B öffnet die Liste; beide sind live mit dem Haushaltsraum verbunden
  await pageB.goto('/shopping')
  await expect(pageB.getByRole('button', { name: 'Wocheneinkauf (0)' })).toBeVisible()
  await expectLiveSync(pageA)
  await expectLiveSync(pageB)

  // A fügt einen Artikel hinzu → erscheint bei B ohne Neuladen
  await pageA.getByRole('textbox', { name: 'Artikel hinzufügen…' }).fill(itemName)
  await pageA.getByRole('button', { name: 'Hinzufügen', exact: true }).click()
  await expect(pageA.getByRole('checkbox', { name: itemName })).toHaveAttribute('aria-checked', 'false')

  const itemAtB = pageB.getByRole('checkbox', { name: itemName })
  await expect(itemAtB).toBeVisible()
  await expect(pageB.getByRole('button', { name: 'Wocheneinkauf (1)' })).toBeVisible()

  // B hakt ab → bei A wandert der Artikel ohne Neuladen in „Erledigt“
  await itemAtB.click()
  await expect(pageB.getByRole('button', { name: 'Erledigt (1)' })).toBeVisible()

  await expect(pageA.getByRole('checkbox', { name: itemName })).toHaveCount(0)
  await expect(pageA.getByRole('button', { name: 'Wocheneinkauf (0)' })).toBeVisible()
  await pageA.getByRole('button', { name: 'Erledigt (1)' }).click()
  await expect(pageA.getByRole('checkbox', { name: itemName })).toHaveAttribute('aria-checked', 'true')
})
