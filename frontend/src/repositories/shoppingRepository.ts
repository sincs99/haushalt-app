import api from '../api/client'
import type { ShoppingItem, ShoppingList, ShoppingListCreatePayload, ShoppingListUpdatePayload } from '../types'

export interface ShoppingRepository {
  // Lists
  fetchLists(householdId: string): Promise<ShoppingList[]>
  createList(householdId: string, data: ShoppingListCreatePayload): Promise<ShoppingList>
  updateList(householdId: string, listId: string, data: ShoppingListUpdatePayload): Promise<ShoppingList>
  deleteList(householdId: string, listId: string, force?: boolean): Promise<void>
  // Items
  fetchAll(householdId: string, listId?: string): Promise<ShoppingItem[]>
  create(
    householdId: string,
    data: { name: string; list_id: string; quantity?: string; category?: string; store?: string; assigned_to_user_id?: string },
  ): Promise<ShoppingItem>
  update(
    householdId: string,
    itemId: string,
    data: Partial<ShoppingItem>,
  ): Promise<ShoppingItem>
  remove(householdId: string, itemId: string): Promise<void>
  // Stores
  fetchStores(householdId: string): Promise<string[]>
  reassignStore(householdId: string, fromStore: string, toStore: string | null): Promise<{ updated: number }>
}

export function createOnlineShoppingRepository(): ShoppingRepository {
  return {
    // ── Lists ──
    async fetchLists(householdId) {
      const { data } = await api.get<ShoppingList[]>(
        `/api/households/${householdId}/shopping-lists/`,
      )
      return data
    },

    async createList(householdId, payload) {
      const { data } = await api.post<ShoppingList>(
        `/api/households/${householdId}/shopping-lists/`,
        payload,
      )
      return data
    },

    async updateList(householdId, listId, payload) {
      const { data } = await api.patch<ShoppingList>(
        `/api/households/${householdId}/shopping-lists/${listId}`,
        payload,
      )
      return data
    },

    async deleteList(householdId, listId, force = false) {
      await api.delete(
        `/api/households/${householdId}/shopping-lists/${listId}`,
        { params: force ? { force: true } : undefined },
      )
    },

    // ── Items ──
    async fetchAll(householdId, listId?) {
      const params: Record<string, any> = { include_checked: true }
      if (listId) params.list_id = listId
      const { data } = await api.get<ShoppingItem[]>(
        `/api/households/${householdId}/shopping-items/`,
        { params },
      )
      return data
    },

    async create(householdId, payload) {
      const { data } = await api.post<ShoppingItem>(
        `/api/households/${householdId}/shopping-items/`,
        {
          name: payload.name,
          list_id: payload.list_id,
          quantity: payload.quantity ?? null,
          category: payload.category ?? null,
          store: payload.store ?? null,
          assigned_to_user_id: payload.assigned_to_user_id ?? null,
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

    // ── Stores ──
    async fetchStores(householdId) {
      const { data } = await api.get<string[]>(
        `/api/households/${householdId}/shopping-items/stores`,
      )
      return data
    },

    async reassignStore(householdId, fromStore, toStore) {
      const { data } = await api.post<{ updated: number }>(
        `/api/households/${householdId}/shopping-items/reassign-store`,
        { from_store: fromStore, to_store: toStore },
      )
      return data
    },
  }
}
