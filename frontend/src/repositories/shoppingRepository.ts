import api from '../api/client'
import type { ShoppingItem } from '../types'

export interface ShoppingRepository {
  fetchAll(householdId: string): Promise<ShoppingItem[]>
  create(
    householdId: string,
    data: { name: string; quantity?: string; category?: string },
  ): Promise<ShoppingItem>
  update(
    householdId: string,
    itemId: string,
    data: Partial<ShoppingItem>,
  ): Promise<ShoppingItem>
  remove(householdId: string, itemId: string): Promise<void>
}

export function createOnlineShoppingRepository(): ShoppingRepository {
  return {
    async fetchAll(householdId) {
      const { data } = await api.get<ShoppingItem[]>(
        `/api/households/${householdId}/shopping-items/`,
        { params: { include_checked: true } },
      )
      return data
    },

    async create(householdId, payload) {
      const { data } = await api.post<ShoppingItem>(
        `/api/households/${householdId}/shopping-items/`,
        {
          name: payload.name,
          quantity: payload.quantity ?? null,
          category: payload.category ?? null,
        },
      )
      return data
    },

    async update(householdId, itemId, payload) {
      const { data } = await api.patch<ShoppingItem>(
        `/api/households/${householdId}/shopping-items/${itemId}`,
        payload,
      )
      return data
    },

    async remove(householdId, itemId) {
      await api.delete(
        `/api/households/${householdId}/shopping-items/${itemId}`,
      )
    },
  }
}
