# Architekturplan: Offline-Ready State Management

**Erstellt:** 2026-08-05
**Status:** Entwurf
**Epic:** Offline-Readiness Vorbereitung
**Priorität:** Hoch (architektonische Grundlage)

---

## 1. Problemanalyse

### Kern-Use-Case
> "Im Supermarkt Einkaufsliste abhaken" — Migros Untergeschoss, Coop Tiefgarage, kein Mobilnetz.

### Ist-Zustand: 4 strukturelle Blocker

#### Blocker 1: Keine Optimistic Updates
```
// shopping.ts — addItem()
await api.post(...)  // ← blockiert bis Server antwortet
// Kommentar Zeile 37: "KEIN lokales State-Patching — Socket-Event macht das"
```
**Konsequenz:** Kein Netz → kein UI-Feedback → App wirkt tot.

#### Blocker 2: Kein lokaler State-Cache
```
const items = ref<ShoppingItem[]>([])  // ← nur im Memory
```
**Konsequenz:** Page-Refresh oder App-Neustart → leere Liste bis Server antwortet.

#### Blocker 3: Keine Operation-Queue
Mutations gehen direkt an `api.post/patch/delete`. Es gibt kein Konzept von
"ausstehende Operationen", die bei Reconnect nachgeholt werden könnten.

#### Blocker 4: Kein Error-Recovery
```
async function toggleChecked(itemId: string) {
  await api.patch(...)  // ← kein catch, kein retry, kein rollback
}
```
**Konsequenz:** Netzwerkfehler = unhandled rejection, inkonsistenter State.

---

## 2. Zielarchitektur: Repository Pattern mit Offline-Hooks

### Schichtenmodell

```
┌─────────────────────────────────────────────────┐
│  Vue Components (ShoppingList.vue, TodoList.vue) │
│  - Lesen aus Store (computed)                    │
│  - Rufen Store-Actions auf                       │
└──────────────────────┬──────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────┐
│  Pinia Stores (shopping.ts, todos.ts)            │
│  - Optimistic State Updates (sofort)             │
│  - Rollback bei Fehler                           │
│  - Socket-Handler für Server-Korrekturen         │
└──────────────────────┬──────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────┐
│  Repository Layer (NEU)                          │
│  - shoppingRepository.ts                         │
│  - todosRepository.ts                            │
│  - Abstrahiert Datenzugriff                      │
│  - JETZT: Direkter API-Call                      │
│  - SPÄTER: IndexedDB + SyncQueue + API-Call      │
└──────────────────────┬──────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
   ┌─────────┐  ┌───────────┐  ┌──────────────┐
   │ API      │  │ Socket.IO │  │ SPÄTER:      │
   │ (Axios)  │  │ (Events)  │  │ IndexedDB    │
   │          │  │           │  │ + SyncQueue  │
   └─────────┘  └───────────┘  └──────────────┘
```

### Warum Repository Pattern?

| Alternative | Problem |
|---|---|
| Direkt IndexedDB in Stores | Vermischt Persistenz mit Business-Logik |
| Service Worker allein | Kann nur GET-Requests cachen, keine Mutations |
| Alles in Composables | Kein klarer Contract, schwer testbar |
| **Repository Pattern** | **Klarer Seam für späteren IndexedDB-Swap** |

---

## 3. Detailplan pro Schicht

### 3.1 Repository Layer (neu: `frontend/src/repositories/`)

```typescript
// frontend/src/repositories/shoppingRepository.ts

import api from '../api/client'
import type { ShoppingItem } from '../types'

export interface ShoppingRepository {
  fetchAll(householdId: string): Promise<ShoppingItem[]>
  create(householdId: string, data: { name: string; quantity?: string; category?: string }): Promise<ShoppingItem>
  update(householdId: string, itemId: string, data: Partial<ShoppingItem>): Promise<ShoppingItem>
  remove(householdId: string, itemId: string): Promise<void>
}

// Phase 1: Online-Only Implementierung
export function createOnlineShoppingRepository(): ShoppingRepository {
  return {
    async fetchAll(householdId) {
      const { data } = await api.get<ShoppingItem[]>(
        `/api/households/${householdId}/shopping-items/`,
        { params: { include_checked: true } }
      )
      return data
    },
    async create(householdId, payload) {
      const { data } = await api.post<ShoppingItem>(
        `/api/households/${householdId}/shopping-items/`,
        { name: payload.name, quantity: payload.quantity ?? null, category: payload.category ?? null }
      )
      return data
    },
    async update(householdId, itemId, payload) {
      const { data } = await api.patch<ShoppingItem>(
        `/api/households/${householdId}/shopping-items/${itemId}`,
        payload
      )
      return data
    },
    async remove(householdId, itemId) {
      await api.delete(`/api/households/${householdId}/shopping-items/${itemId}`)
    }
  }
}
```

**Späterer Offline-Swap (Phase 2, nicht jetzt):**
```typescript
// Wird SPÄTER hinzugefügt — nur als Illustration der Architektur-Idee
export function createOfflineFirstShoppingRepository(
  online: ShoppingRepository,
  cache: IndexedDBCache,
  syncQueue: SyncQueue
): ShoppingRepository {
  return {
    async fetchAll(householdId) {
      try {
        const items = await online.fetchAll(householdId)
        await cache.putAll('shopping', householdId, items)
        return items
      } catch {
        return cache.getAll('shopping', householdId) // Offline-Fallback
      }
    },
    async create(householdId, data) {
      const tempItem = createTempItem(data)      // Lokale temp-ID
      await cache.put('shopping', tempItem)
      syncQueue.enqueue({ type: 'create', entity: 'shopping', householdId, data })
      return tempItem
    },
    // ...
  }
}
```

### 3.2 Pinia Store Refactoring (Optimistic Updates)

**Vorher (aktuell):**
```typescript
async function addItem(name: string) {
  await api.post(...)  // blockiert, kein lokaler State
}
```

**Nachher (Phase 1):**
```typescript
async function addItem(name: string, quantity?: string, category?: string) {
  const householdId = authStore.currentHouseholdId
  if (!householdId) return

  // 1. Optimistic: Sofort lokalen Temp-Eintrag erzeugen
  const tempId = crypto.randomUUID()
  const tempItem: ShoppingItem = {
    id: tempId,
    household_id: householdId,
    name,
    quantity: quantity ?? null,
    category: category ?? null,
    is_checked: false,
    added_by_user_id: authStore.user?.id ?? null,
    created_at: new Date().toISOString(),
    checked_at: null,
  }
  items.value.push(tempItem)

  try {
    // 2. Server-Call via Repository
    const serverItem = await repo.create(householdId, { name, quantity, category })
    // 3. Temp-ID durch Server-ID ersetzen
    const idx = items.value.findIndex(i => i.id === tempId)
    if (idx !== -1) items.value[idx] = serverItem
  } catch (error) {
    // 4. Rollback bei Fehler
    items.value = items.value.filter(i => i.id !== tempId)
    throw error  // Weiterwerfen für UI-Feedback
  }
}
```

**Vorher (toggleChecked):**
```typescript
async function toggleChecked(itemId: string) {
  await api.patch(...)  // blockiert
}
```

**Nachher:**
```typescript
async function toggleChecked(itemId: string) {
  const householdId = authStore.currentHouseholdId
  if (!householdId) return

  const item = items.value.find(i => i.id === itemId)
  if (!item) return

  // 1. Optimistic Toggle
  const previousState = item.is_checked
  item.is_checked = !item.is_checked
  item.checked_at = item.is_checked ? new Date().toISOString() : null

  try {
    // 2. Server-Call
    await repo.update(householdId, itemId, { is_checked: item.is_checked })
  } catch (error) {
    // 3. Rollback
    item.is_checked = previousState
    item.checked_at = previousState ? item.checked_at : null
    throw error
  }
}
```

### 3.3 Connectivity Service (neu: `frontend/src/composables/useConnectivity.ts`)

```typescript
import { ref, readonly } from 'vue'

const isOnline = ref(navigator.onLine)

window.addEventListener('online', () => { isOnline.value = true })
window.addEventListener('offline', () => { isOnline.value = false })

export function useConnectivity() {
  return {
    isOnline: readonly(isOnline),
  }
}
```

**UI-Indikator in App.vue:**
```vue
<div v-if="!isOnline" class="offline-banner">
  📡 Kein Netz – Änderungen werden synchronisiert, sobald du wieder online bist.
</div>
```

### 3.4 Socket-Handler: Idempotente Merges

Die Socket-Handler müssen mit Optimistic State koexistieren:

```typescript
function handleItemCreated(serverItem: ShoppingItem) {
  const existingIdx = items.value.findIndex(i => i.id === serverItem.id)
  if (existingIdx !== -1) {
    // Server-Daten überschreiben Optimistic-Daten (Server = Source of Truth)
    items.value[existingIdx] = serverItem
  } else {
    items.value.push(serverItem)
  }
}

function handleItemUpdated(serverItem: ShoppingItem) {
  const idx = items.value.findIndex(i => i.id === serverItem.id)
  if (idx !== -1) {
    items.value[idx] = serverItem  // Server gewinnt immer
  }
}
```

---

## 4. Dateien-Übersicht (Was ändert sich?)

### Neue Dateien
| Datei | Zweck |
|---|---|
| `frontend/src/repositories/shoppingRepository.ts` | Repository für Shopping-Items |
| `frontend/src/repositories/todosRepository.ts` | Repository für Todos |
| `frontend/src/composables/useConnectivity.ts` | Online/Offline-Status |

### Geänderte Dateien
| Datei | Änderung |
|---|---|
| `frontend/src/stores/shopping.ts` | Optimistic Updates, Repository statt direktem API-Call |
| `frontend/src/stores/todos.ts` | Gleiche Umstellung wie Shopping |
| `frontend/src/App.vue` | Offline-Banner einbinden |
| `frontend/src/components/ShoppingList.vue` | Error-Feedback bei fehlgeschlagenen Mutations |

### Unverändert
| Datei | Grund |
|---|---|
| `frontend/src/api/client.ts` | Bleibt als Transport-Layer bestehen |
| `frontend/src/composables/useSocket.ts` | Bleibt — Socket ist der Realtime-Push-Kanal |
| Backend (komplett) | Keine Änderungen nötig |

---

## 5. Migrationspfad: Offline-First (Phase 2 — SPÄTER)

Wenn Phase 1 umgesetzt ist, kann Offline-First **ohne Rewrite** nachgerüstet werden:

```
Phase 1 (JETZT)          →  Phase 2 (SPÄTER)
─────────────────────────────────────────────
OnlineRepository          →  OfflineFirstRepository (wraps Online)
Optimistic Updates        →  + SyncQueue (IndexedDB)
useConnectivity           →  + Auto-Sync on Reconnect
Socket-Idempotent-Merge   →  + Conflict Resolution (Last-Write-Wins)
crypto.randomUUID()       →  + Temp-ID → Server-ID Mapping
```

### Was Phase 2 braucht (nur als Referenz):
1. **IndexedDB-Wrapper** (z.B. Dexie.js) für lokale Persistenz
2. **SyncQueue**: Pending-Mutations in IndexedDB speichern
3. **Sync-Worker**: Bei `online`-Event Queue abarbeiten
4. **Conflict Resolution**: Last-Write-Wins mit `updated_at` Timestamp
5. **Temp-ID-Mapping**: Lokale UUIDs → Server-UUIDs nach Sync

### Backend-Anpassungen für Phase 2:
- `updated_at` Feld auf allen Entities (für Conflict Resolution)
- Idempotency-Keys auf POST-Endpoints (Duplikat-Schutz bei Retry)
- Bulk-Sync-Endpoint: `POST /api/sync` (optional, Optimierung)

---

## 6. Risiken & Entscheidungen

| Thema | Entscheidung | Begründung |
|---|---|---|
| Temp-IDs | `crypto.randomUUID()` | Kollisionssicher, nativ in allen Browsern |
| Rollback-Strategie | State-Snapshot vor Mutation | Einfacher als Event-Sourcing |
| Server vs. Client Truth | **Server gewinnt immer** (via Socket-Events) | Vermeidet komplexe Merge-Logik in Phase 1 |
| Error-UI | Toast/Snackbar bei Rollback | User muss verstehen, warum Item verschwand |
| Repository-Instanziierung | Factory-Funktion, 1x in Store erstellt | Testbar (Mock-Repository injizierbar) |

---

## 7. Nicht-Ziele (explizit ausgeklammert)

- ❌ IndexedDB-Integration (Phase 2)
- ❌ Service Worker / PWA-Shell (Phase 2)
- ❌ Conflict Resolution UI (Phase 2)
- ❌ Backend-Änderungen (erst in Phase 2 nötig)
- ❌ Bulk-Sync-Endpoint (Phase 2)

---

## 8. Abnahmekriterien Phase 1

- [ ] Alle Pinia-Store-Actions nutzen Repository statt direktem `api.*`-Call
- [ ] `addItem`, `toggleChecked`, `deleteItem` haben Optimistic Updates + Rollback
- [ ] Socket-Handler sind idempotent (Merge statt Duplikat)
- [ ] Connectivity-Composable zeigt Online/Offline-Status
- [ ] Offline-Banner wird angezeigt wenn `navigator.onLine === false`
- [ ] Kein Rewrite nötig um später OfflineFirstRepository einzuführen
- [ ] Bestehende Funktionalität ist nicht gebrochen (Regression)
