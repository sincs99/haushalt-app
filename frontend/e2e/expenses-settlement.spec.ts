import { expect, test } from '@playwright/test'
import { createSharedHousehold, expectLiveSync, type Household } from './helpers'

let household: Household | undefined

test.beforeEach(async ({ browser }) => {
  household = await createSharedHousehold(browser)
})

test.afterEach(async () => {
  await household?.close()
})

// de-CH formatiert mit geschütztem Leerzeichen („CHF 25.00“) → \s
const chf = (amount: string) => new RegExp(`CHF\\s${amount.replace('.', '\\.')}`)

test('Ausgabe gleichmässig teilen und mit einer Ausgleichszahlung auf null bringen', async () => {
  const { pageA, pageB, userA, userB } = household!
  const description = `Grosseinkauf ${Date.now().toString(36)}`
  const debtLine = new RegExp(`${userB.displayName}\\s+zahlt\\s+${userA.displayName}:\\s+CHF\\s25\\.00`)

  await pageA.goto('/expenses')
  await pageB.goto('/expenses')
  await expectLiveSync(pageA)
  await expectLiveSync(pageB)

  // A erfasst 50.00, bezahlt von A, gleichmässig auf beide verteilt
  await pageA.getByRole('button', { name: 'Ausgabe erfassen' }).first().click()
  const dialog = pageA.getByRole('dialog')
  await dialog.getByLabel('Beschreibung').fill(description)
  await dialog.getByLabel('Betrag (CHF)').fill('50.00')
  await expect(dialog.getByLabel('Bezahlt von')).toHaveValue(/.+/)
  await expect(dialog.getByLabel('Bezahlt von').locator('option:checked')).toHaveText(userA.displayName)
  await expect(dialog.getByRole('checkbox', { name: userA.displayName })).toBeChecked()
  await expect(dialog.getByRole('checkbox', { name: userB.displayName })).toBeChecked()
  await dialog.getByRole('button', { name: 'Hinzufügen' }).click()
  await expect(dialog).toBeHidden()

  // Salden: A +25.00, B −25.00; Vorschlag „B zahlt A 25.00“ – bei A und live bei B
  for (const page of [pageA, pageB]) {
    await expect(page.getByText(description)).toBeVisible()
    await expect(page.getByText(/^\+\s*CHF\s25\.00$/)).toBeVisible()
    await expect(page.getByText(/^-\s*CHF\s25\.00$/)).toBeVisible()
    await expect(page.getByText(debtLine)).toBeVisible()
  }

  // B erfasst die Ausgleichszahlung über den Vorschlag (Werte sind vorausgefüllt)
  await pageB.getByRole('button', { name: 'Als bezahlt markieren' }).click()
  const settleDialog = pageB.getByRole('dialog', { name: 'Ausgleichszahlung erfassen' })
  await expect(settleDialog.getByLabel('Betrag (CHF)')).toHaveValue('25.00')
  await expect(settleDialog.getByLabel(/^Von\b/).locator('option:checked')).toHaveText(userB.displayName)
  await expect(settleDialog.getByLabel(/^An\b/).locator('option:checked')).toHaveText(userA.displayName)
  await settleDialog.getByRole('button', { name: 'Zahlung erfassen' }).click()
  await expect(settleDialog).toBeHidden()

  // Beide Geräte: alles ausgeglichen, kein offener Vorschlag mehr, Zahlung in der Liste
  for (const page of [pageB, pageA]) {
    await expect(page.getByText('Alles ausgeglichen')).toBeVisible()
    await expect(page.getByText(debtLine)).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Als bezahlt markieren' })).toHaveCount(0)
    await expect(page.getByText(/^\+\s*CHF\s25\.00$/)).toHaveCount(0)
    await expect(page.getByText(/^-\s*CHF\s25\.00$/)).toHaveCount(0)
    await expect(page.getByText(/^CHF\s0\.00$/)).toHaveCount(2)
    await expect(page.getByRole('heading', { name: 'Ausgleichszahlungen' })).toBeVisible()
  }

  // Nach dem Neuladen bleibt der Stand (Server, nicht nur lokaler Zustand)
  await pageA.reload()
  await expect(pageA.getByText('Alles ausgeglichen')).toBeVisible()
  await expect(pageA.getByText(chf('50.00')).first()).toBeVisible()
})
