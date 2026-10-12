/**
 * Response-Interceptor des API-Clients: 403 NOT_HOUSEHOLD_MEMBER auf den aktuellen
 * Haushalt löst eine Prüfung der Mitgliedschaft aus (CASA-49).
 */
import type {} from 'vitest'

const { authStore } = vi.hoisted(() => ({
  authStore: { token: 'access', currentHouseholdId: 'hh-1', revalidateMembership: vi.fn(), refresh: vi.fn(), logout: vi.fn() },
}))

vi.mock('../../stores/auth', () => ({ useAuthStore: () => authStore }))

import api from '../client'

type Rejected = (error: unknown) => Promise<unknown>

function rejectedHandler(): Rejected {
  const handlers = (api.interceptors.response as unknown as { handlers: { rejected: Rejected }[] }).handlers
  return handlers[0].rejected
}

function forbidden(url: string, code: string) {
  return { config: { url }, response: { status: 403, data: { detail: { code } } } }
}

beforeEach(() => {
  vi.resetAllMocks()
  authStore.currentHouseholdId = 'hh-1'
})

test('403 NOT_HOUSEHOLD_MEMBER auf den aktuellen Haushalt → Mitgliedschaft prüfen, Fehler bleibt', async () => {
  const error = forbidden('/api/households/hh-1/todos/', 'NOT_HOUSEHOLD_MEMBER')
  await expect(rejectedHandler()(error)).rejects.toBe(error)
  expect(authStore.revalidateMembership).toHaveBeenCalledTimes(1)
})

test('anderer Haushalt oder anderer 403-Code → keine Prüfung', async () => {
  await expect(rejectedHandler()(forbidden('/api/households/hh-2/todos/', 'NOT_HOUSEHOLD_MEMBER'))).rejects.toBeDefined()
  await expect(rejectedHandler()(forbidden('/api/households/hh-1/members/x', 'ADMIN_REQUIRED'))).rejects.toBeDefined()
  expect(authStore.revalidateMembership).not.toHaveBeenCalled()
})
