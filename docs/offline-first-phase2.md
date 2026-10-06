# Designdokument: Offline-First Phase 2

**Erstellt:** 2026-10-05
**Status:** Freigegeben (Entscheidungen E1–E12 am 2026-10-06 gemäss Empfehlung getroffen) · M0 umgesetzt
**Epic:** Offline-First Phase 2
**Vorgänger:** [`offline-ready-architecture.md`](./offline-ready-architecture.md) (Phase 1: Repository Pattern + Optimistic Updates, umgesetzt)
**Priorität:** Hoch

---

## 0. Zusammenfassung

> "Im Supermarkt Einkaufsliste abhaken" — Migros Untergeschoss, Coop Tiefgarage, kein Mobilnetz.

Phase 1 hat den Seam gelegt: Stores sprechen nur noch mit Repositories, Mutationen sind
optimistisch mit Rollback. **Offline funktioniert trotzdem nichts**, weil (a) nach einem
App-Neustart ohne Netz keine Daten vorhanden sind und (b) jede Mutation ohne Netz
fehlschlägt und zurückgerollt wird.

Phase 2 ergänzt drei Bausteine:

1. **Lokaler Cache in IndexedDB** (Lesepfad, App startet offline mit letztem Stand)
2. **Outbox / Mutation-Queue in IndexedDB** (Schreibpfad, Änderungen überleben Neustart)
3. **Sync-Engine** mit Reconcile-Schritt („ausstehende Ops über Server-Snapshot legen“)

Kernempfehlungen dieses Dokuments:

| Thema | Empfehlung |
|---|---|
| Reihenfolge | Einkaufsliste-Items → Todos → Putzplan-Erledigungen. Alles andere bleibt online-only. |
| Speicher | IndexedDB über **`idb`** (dünner Promise-Wrapper), nicht Dexie |
| IDs | **Client-generierte UUIDs** (`crypto.randomUUID()`), Backend akzeptiert optionales `id` beim Create → kein Temp-ID-Mapping |
| Idempotenz | Create idempotent über `id`, PATCH mit absoluten Werten, DELETE: 404 = Erfolg. Keine generische Idempotency-Key-Tabelle in Phase 2 |
| Konflikte | Feldweises Last-Write-Wins (Reihenfolge der Ankunft beim Server) + `version`-Feld zum Erkennen veralteter Socket-Events |
| Deletes | Vorerst **keine Tombstones**: Reconcile über Full-Snapshot pro Modul (Datenmengen klein). Change-Cursor/Tombstones erst als spätere Optimierung |
| Service Worker | Bleibt App-Shell-only. **Kein Background Sync** in Phase 2 (iOS unterstützt es nicht, und der SW kommt nicht an die Tokens) → Sync bei App-Start, `online`, Socket-Connect, Sichtbarkeitswechsel |

---

## 1. Ist-Zustand (gegen den Code verifiziert)

### 1.1 Frontend

| Bereich | Stand | Datei |
|---|---|---|
| Repositories | Nur `createOnline…Repository()`-Factories, 16 Stück, alle direkt auf Axios | `frontend/src/repositories/*.ts` |
| Shopping-Store | Optimistic `addItem` (Temp-UUID → Swap mit Server-Item), `toggleChecked` (mit `pendingToggles`-Mutex), `toggleAssigned`, `deleteItem`. **Nicht** optimistisch: `updateItem`, alle Listen-Actions, `reassignStore` | `frontend/src/stores/shopping.ts` |
| Todos-Store | Optimistic `addTodo`, `toggleDone`, `updateTodo`, `deleteTodo`, `addReminder`, `deleteReminder` | `frontend/src/stores/todos.ts` |
| Chores-Store | Optimistic `removeChore`, `completeAssignment`, `uncompleteAssignment`. Nicht optimistisch: `createChore`, `updateChore` | `frontend/src/stores/chores.ts` |
| Socket-Handler | Shopping: idempotenter Merge per `id` („Server gewinnt immer“, ganzes Objekt wird ersetzt). Todos: `handleTodoCreated` hat zusätzlich einen `pendingTempIds`-Guard, der Events anderer User während eines eigenen Creates verwirft | `stores/*.ts` |
| TodosView | Lädt bei **jedem** `todo_*`-Socket-Event die komplette Liste neu (`handleSocketEvent → fetchTodos()`) | `frontend/src/views/TodosView.vue` |
| Reconnect | `App.vue → handleReconnect()` lädt bei Socket-Reconnect alle Module neu | `frontend/src/App.vue` |
| Connectivity | `useConnectivity()` = nur `navigator.onLine` + `online`/`offline`-Events | `frontend/src/composables/useConnectivity.ts` |
| Offline-Banner | Vorhanden, Text: „Kein Netz – Änderungen können aktuell nicht gespeichert werden.“ (`offline.banner`). Zusätzlich Sync-Dot mit `sync.connected/reconnecting/offline` | `App.vue`, `locales/de.json` |
| Auth offline | `initialize()` bleibt bei Netzwerkfehler „offline-eingeloggt“ (`hasOfflineSession`), hat aber keinen Access-Token, bis der erste 401 ihn per Cookie-Refresh holt; `user` und `households` bleiben `null`. `currentHouseholdId` kommt aus `localStorage` | `frontend/src/stores/auth.ts` |
| Tokens | Seit H-01: Access-Token nur im Speicher, Refresh-Token als HttpOnly-Cookie `casa_rt` (Path `/api/auth`). In `localStorage` liegt nur noch der Sitzungs-Marker `haushalt_session`. Ein Service Worker kann den Cookie bei `fetch` mitsenden (`credentials: 'include'`), aber nicht lesen | `frontend/src/services/tokenStorage.ts` |
| PWA | `vite-plugin-pwa`, `registerType: 'prompt'`, Workbox precacht nur die App-Shell (`**/*.{js,css,html,svg,png,ico,woff2}`), `/api/` und `/socket.io/` explizit ausgenommen, `push-sw.js` per `importScripts` | `frontend/vite.config.ts`, `frontend/src/pwa.ts` |
| IndexedDB | Wird nirgends verwendet | — |
| Tests | Vitest mit `environment: 'node'`, aktuell genau ein Test (`utils/__tests__/money.test.ts`) | `frontend/vitest.config.ts` |

### 1.2 Backend

| Bereich | Stand |
|---|---|
| IDs | Alle PKs `UUID`, serverseitig `default=uuid.uuid4`. Create-Schemas haben **kein** `id`-Feld; Pydantic ignoriert unbekannte Felder (Default `extra="ignore"`), ein mitgeschicktes `id` wird heute also stillschweigend verworfen |
| `updated_at` | Nur auf `Expense` und `Budget`. **Fehlt** auf `ShoppingList`, `ShoppingItem`, `Todo`, `TodoReminder`, `Chore`, `ChoreAssignment` |
| Version/Cursor | Kein `version`-Feld, kein Change-Feed, keine Tombstones |
| Deletes | Hard Deletes (`db.delete(...)`). Kaskaden: Liste löschen → Items weg (`ondelete="CASCADE"`), Chore löschen → Assignments weg |
| Idempotenz heute | `POST /chores/assignments/{id}/complete` und `/uncomplete` sind bereits idempotent (Kommentar „Idempotent: bereits erledigt → 200“). PATCH auf Items/Todos setzt absolute Werte → bei Wiederholung gleiches Ergebnis. `POST` Create erzeugt bei Retry ein Duplikat. `DELETE` antwortet beim zweiten Mal 404. `POST /todos/{id}/claim` antwortet 409, auch wenn bereits an einen selbst vergeben |
| Server-Zeitstempel | `checked_at`, `done_at`, `completed_at` werden serverseitig mit `now()` gesetzt — also zum Sync-Zeitpunkt, nicht zum Zeitpunkt der Offline-Aktion |
| Chore-Assignments | Werden serverseitig beim `GET /chores/assignments` materialisiert (`materialize_due_assignments`), Fenster Default heute −14 … +7 Tage |
| Socket.IO | `emit_to_household_sync(household_id, event, payload)` in Room `household_{id}`, kein Replay verpasster Events |
| DB / Migrationen | PostgreSQL 16 in Produktion, Alembic in `backend/migrations/versions` (aktueller Head: `s1t2u3v4w5x6`). Tests laufen gegen SQLite in-memory |

### 1.3 Konsequenzen aus dem Ist-Zustand

- Einkaufsliste lädt **alle** Items inklusive abgehakter (`include_checked: true`), und es gibt keine
  Funktion „Abgehakte löschen“. Die Datenmenge wächst also monoton — für den Full-Snapshot-Ansatz
  relevant (siehe Risiken).
- Die bestehenden Socket-Handler ersetzen das ganze Objekt. Mit ausstehenden Offline-Änderungen
  würde ein eingehendes Event lokale, noch nicht gesendete Änderungen überschreiben → Handler
  müssen auf „Rebase“ umgestellt werden (Kapitel 4.4).
- Der „Undo“-Toast nach dem Löschen in `ShoppingList.vue` legt ein **neues** Item an (neue ID).
  Mit Outbox kann Undo stattdessen den noch nicht gesendeten Delete aus der Queue entfernen.

---

## 2. Scope und Szenarien

### 2.1 Szenarien

| # | Szenario | Erwartung |
|---|---|---|
| S1 | App ist geöffnet, Netz bricht im Laden ab, User hakt 10 Artikel ab | Sofortiges UI-Feedback, Items als „ausstehend“ markiert, kein Fehler-Toast |
| S2 | App wurde im Hintergrund vom OS beendet, User öffnet sie im Keller neu | App startet aus Precache, zeigt letzten bekannten Stand aus IndexedDB |
| S3 | Wie S1, User fügt „Milch“ hinzu, löscht „Brot“ | Lokal sichtbar, in Outbox persistiert |
| S4 | User verlässt den Laden, Netz kommt zurück | Outbox wird automatisch abgearbeitet, Indikator verschwindet, andere Haushaltsmitglieder sehen die Änderungen via Socket |
| S5 | Partner hat zeitgleich zu Hause Artikel ergänzt / gelöscht | Nach Sync sind beide Änderungssätze sichtbar; Konflikte nach Kapitel 4 |
| S6 | Flaky Netz („1 Balken“): Requests hängen oder brechen mittendrin ab | Retry ohne Duplikate (Idempotenz), keine hängende UI |
| S7 | Putzplan-Aufgabe offline als erledigt markieren | Wird nach Reconnect übertragen |
| S8 | Offline Einstellungen, Ausgaben, Kalender etc. ändern | Klar kommuniziert „nur online“, Button deaktiviert oder Hinweis |

### 2.2 Empfohlene Reihenfolge der Module

| Prio | Modul / Aktion | Offline-Schreiben | Begründung |
|---|---|---|---|
| 1 | **Shopping-Items**: hinzufügen, abhaken, bearbeiten (Name/Menge/Kategorie/Laden), „ich kaufe das“ (`assigned_to_user_id`), löschen | ✅ | Kern-Use-Case, einfache flache Entität, Store ist schon am weitesten optimistisch |
| 1 | Shopping-Listen: lesen, aktive Liste wechseln | nur Lesen | Liste wählen muss offline gehen; Anlegen/Umbenennen ist selten |
| 2 | **Todos**: anlegen, erledigen, bearbeiten (Titel, Beschreibung, Fälligkeit, Tags, Zuweisung), löschen | ✅ | Zweithäufigster Unterwegs-Use-Case, ebenfalls flach |
| 3 | **Putzplan-Assignments**: erledigt / nicht erledigt | ✅ | Backend bereits idempotent, sehr kleiner Aufwand |
| — | Shopping-Listen anlegen/umbenennen/sortieren | später (optional) | Machbar mit Client-ID, aber geringer Nutzen |
| — | Shopping-Listen löschen, `reassign-store` (Bulk) | ❌ online-only | Kaskadierende bzw. Bulk-Semantik, Konflikte schwer erklärbar |
| — | Todo-Erinnerungen (`reminders`), Todo „claim“ | ❌ online-only | Reminder: Server validiert „remind_at in der Zukunft“, Push-Logik; Claim: absichtlich konfliktbehaftet (409) |
| — | Chores anlegen/ändern/löschen, Assignment neu zuweisen | ❌ online-only | Server berechnet `anchor_date`, Rotation, Materialisierung |
| — | Ausgaben, Abrechnungen, Budgets, Daueraufträge | ❌ online-only | Geldbeträge und Salden: lieber kein stilles Merge |
| — | Kalender, Abstimmungen, Notizen, Haustiere, Essen, Dateien, Haushalt/Mitglieder, Push | ❌ online-only | Kein Offline-Use-Case mit Priorität; ggf. später Lese-Cache |

„Online-only“ heisst: Aktion im UI deaktiviert oder mit Hinweis, solange offline, und
Fehler beim Absenden wie bisher per Toast + Rollback.

---

## 3. Lokale Speicherung

### 3.1 Technologieauswahl

| Option | Bewertung |
|---|---|
| `localStorage` | Synchron, ~5 MB, nur Strings, blockiert den Main-Thread. Bereits für Tokens und UI-Präferenzen genutzt — für Entitäten und Queue ungeeignet |
| IndexedDB nativ | Verfügbar in allen Zielbrowsern inkl. iOS Safari, aber Callback-API, fehleranfällig |
| **`idb`** (Jake Archibald) | ✅ **Empfehlung.** Sehr kleiner Promise-Wrapper (~1 kB gzip), TypeScript-Schema-Typen (`DBSchema`), native Upgrade-Semantik. Passt zur „schlanken“ Dependency-Liste des Projekts |
| Dexie.js | Komfortabel (Queries, `liveQuery`, Hooks), aber deutlich grösser und eigene Abstraktionsebene. Wir brauchen keine komplexen Queries: alle Abfragen sind „alle Entitäten eines Typs in Haushalt X“ |
| SQLite-WASM / OPFS | Overkill, iOS-Unterstützung von OPFS-Sync-Handles nur in neueren Versionen |
| Cache Storage (SW) | Speichert HTTP-Responses, nicht Entitäten; keine Mutationen. Ungeeignet als Datenhaltung |

Pinia bleibt die **reaktive** Quelle für die UI. IndexedDB ist Persistenz dahinter
(write-through). Es gibt kein `liveQuery`; Stores laden beim Start aus IndexedDB und
schreiben jede Änderung asynchron zurück.

### 3.2 Datenbank-Layout

**Eine Datenbank pro User:** `haushalt-offline-<userId>`. Damit sind Daten zweier User auf
demselben Gerät physisch getrennt und Logout = `deleteDB()`.

Innerhalb der DB wird pro Haushalt über ein Index-Feld `householdId` isoliert (ein User
kann mehreren Haushalten angehören; `switchHousehold()` existiert).

```typescript
// frontend/src/offline/db.ts (Skizze)
interface OfflineDB extends DBSchema {
  meta: {                       // Key-Value: schemaVersion, lastSyncAt pro Haushalt, me-Snapshot
    key: string
    value: unknown
  }
  shopping_lists: {
    key: string                 // list.id
    value: ShoppingList & { householdId: string }
    indexes: { by_household: string }
  }
  shopping_items: {
    key: string                 // item.id
    value: ShoppingItem & { householdId: string }
    indexes: { by_household: string; by_list: string }
  }
  todos: {
    key: string
    value: TodoItem & { householdId: string }
    indexes: { by_household: string }
  }
  chores: {                     // nur Lesen (Titel/Beschreibung für Assignment-Anzeige)
    key: string
    value: ChoreInfo & { householdId: string }
    indexes: { by_household: string }
  }
  chore_assignments: {
    key: string
    value: ChoreAssignmentInfo & { householdId: string }
    indexes: { by_household: string }
  }
  members: {                    // für Namen/Avatare offline
    key: [string, string]       // [householdId, userId]
    value: HouseholdMemberInfo & { householdId: string }
    indexes: { by_household: string }
  }
  outbox: {
    key: string                 // opId
    value: OutboxEntry
    indexes: { by_household_seq: [string, number]; by_entity: string }
  }
}
```

Gespeichert wird immer der **Server-Zustand** (letzter bestätigter Snapshot). Der angezeigte
Zustand ergibt sich als `Server-Snapshot + ausstehende Outbox-Ops` (Kapitel 4.2). Dadurch muss
nie „lokal geänderter Zustand“ von „Server-Zustand“ unterschieden werden, und ein Verwerfen der
Outbox stellt automatisch den Server-Stand wieder her.

Zusätzlich im `meta`-Store: ein Snapshot von `/api/auth/me` (User + Haushalte), damit
`authStore.user` und `households` beim Offline-Kaltstart nicht `null` sind (heute der Fall,
siehe 1.1). Ohne `user.id` könnten z. B. `added_by_user_id` und die „Ich kaufe das“-Logik
nicht korrekt dargestellt werden.

### 3.3 Versionierung und Migration

- `openDB(name, DB_VERSION, { upgrade(db, oldVersion, newVersion, tx) { … } })` mit einem
  `switch (oldVersion)` mit Fallthrough, wie bei Alembic: jede Version ist ein additiver Schritt.
- **Cache-Stores sind wegwerfbar.** Bei inkompatiblen Schemaänderungen eines Entity-Stores wird
  dieser geleert und beim nächsten Online-Start neu befüllt.
- **Die Outbox ist nicht wegwerfbar.** Änderungen am `OutboxEntry`-Format brauchen eine echte
  Migration im Upgrade-Callback (Felder ergänzen/umbenennen). Jeder Eintrag trägt zusätzlich
  `formatVersion`, damit die Sync-Engine alte Einträge erkennt.
- **App-Update während Ops ausstehen:** Der Service Worker nutzt `registerType: 'prompt'`;
  die neue Version wird erst nach Klick auf „Neu laden“ aktiv. Die neue App-Version muss Outbox-
  Einträge der Vorversion verarbeiten können (Abwärtskompatibilität mindestens eine Version).
- **Mehrere Tabs:** IndexedDB-`versionchange`-Event behandeln (`blocked`/`blocking`-Callbacks
  von `idb`): alter Tab schliesst seine Verbindung und zeigt „Bitte neu laden“.
- **Backend-API-Änderungen** (z. B. neues Pflichtfeld) können alte Outbox-Einträge ungültig
  machen → werden als permanenter Fehler (422) sichtbar gemacht, nicht still verworfen.

### 3.4 Isolation und Logout

| Ereignis | Verhalten |
|---|---|
| Haushalt wechseln | Nichts löschen. Stores laden aus `by_household`-Index des neuen Haushalts. Outbox-Ops des alten Haushalts werden trotzdem weiter synchronisiert (Op trägt eigene `householdId`) |
| Aus Haushalt entfernt (`household_member_removed`, `_handleRemoval`) | Alle Entitäten und Outbox-Einträge dieses Haushalts löschen (Server würde ohnehin 403 liefern) |
| Logout durch User, Outbox leer | `deleteDB('haushalt-offline-<userId>')` |
| Logout durch User, Outbox **nicht** leer | Dialog: „Es gibt N nicht synchronisierte Änderungen. Jetzt synchronisieren / Verwerfen und abmelden / Abbrechen.“ (→ Offene Entscheidung E5) |
| Logout `reason: 'expired'` (Refresh-Token abgelehnt) | DB **nicht** sofort löschen; nach erneutem Login desselben Users wird die Outbox weiter abgearbeitet. Login eines anderen Users öffnet seine eigene DB. Alte DBs werden nach Ablauf (z. B. 30 Tage, `meta.lastUsedAt`) aufgeräumt |
| Logout in anderem Tab (`storage`-Event in `_registerStorageListener`) | Verbindung schliessen, keine Ops mehr senden. Löschen übernimmt der auslösende Tab |

Hinweis Datenschutz: Daten liegen unverschlüsselt im Browser-Profil — gleiche Schutzklasse wie
der Refresh-Cookie im Cookie-Jar des Browsers. Für ein geteiltes Gerät ist der Logout-Pfad
entscheidend.

---

## 4. Outbox, Sync-Protokoll und Konfliktauflösung

### 4.1 Outbox-Format

```typescript
// frontend/src/offline/outbox.ts (Skizze)
type EntityType = 'shopping_item' | 'todo' | 'chore_assignment'

interface OutboxEntry {
  opId: string                 // crypto.randomUUID(); dient auch als Idempotency-Key-Header
  formatVersion: 1
  seq: number                  // monoton steigend pro Gerät (Reihenfolge), aus meta.nextSeq
  userId: string
  householdId: string
  entity: EntityType
  entityId: string             // Client-generierte UUID, auch bei Creates bekannt
  kind: 'create' | 'update' | 'delete' | 'action'
  action?: 'complete' | 'uncomplete'   // nur chore_assignment
  payload: Record<string, unknown>     // Create: alle Felder; Update: nur geänderte Felder
  baseVersion: number | null           // Version des Server-Snapshots zum Zeitpunkt der Änderung
  createdAt: string                    // Client-Zeit, nur für Anzeige/Diagnose
  status: 'pending' | 'inflight' | 'failed' | 'conflict'
  attempts: number
  nextAttemptAt: number                // epoch ms, für Backoff
  lastError?: { status?: number; code?: string; message: string }
}
```

### 4.2 Lese-/Schreibpfad im Repository

Die Phase-1-Idee `createOfflineFirstShoppingRepository(online, cache, outbox)` bleibt, mit zwei
Präzisierungen gegenüber der Skizze in `offline-ready-architecture.md` §3.1:

1. **Kein Temp-ID → Server-ID-Mapping.** Der Client erzeugt die endgültige UUID; das Backend
   übernimmt sie (4.6). Damit entfallen `pendingTempIds`, der Swap im Store und der
   Socket-Race-Workaround in `handleTodoCreated`.
2. **Mutationen werfen offline keinen Fehler mehr.** `create/update/remove` schreiben in die
   Outbox und resolven sofort. Fehler kommen asynchron über den Sync-Status (Kapitel 6) und
   nicht mehr als Promise-Rejection an die Komponente. Die Rollback-Logik in den Stores
   entfällt für offline-fähige Aktionen.

Angezeigter Zustand = `rebase(serverSnapshot, pendingOps)`:

```typescript
function rebase<T extends { id: string }>(snapshot: T[], ops: OutboxEntry[]): T[] {
  const byId = new Map(snapshot.map(e => [e.id, { ...e }]))
  for (const op of ops) {                     // nach seq sortiert
    if (op.kind === 'create') byId.set(op.entityId, { ...(op.payload as T), id: op.entityId })
    else if (op.kind === 'update') {
      const cur = byId.get(op.entityId)
      if (cur) Object.assign(cur, op.payload) // Feld-Ebene: nur geänderte Felder
    } else if (op.kind === 'delete') byId.delete(op.entityId)
    else if (op.kind === 'action') applyAction(byId, op)
  }
  return [...byId.values()]
}
```

Diese reine Funktion ist das Herzstück und wird isoliert unit-getestet.

### 4.3 Abarbeitung, Reihenfolge, Coalescing, Retry

**Reihenfolge:** Eine globale FIFO-Queue pro Gerät (nach `seq`), **genau ein Request gleichzeitig**.
Bei 3 Modulen und wenigen Dutzend Ops ist Parallelität unnötig und strikte Reihenfolge macht
„Create vor Update vor Delete“ trivial korrekt.

**Coalescing beim Einreihen** (reduziert Requests und Konfliktfläche):

| Vorhanden (pending, nicht inflight) | Neu | Ergebnis |
|---|---|---|
| `create X` | `update X` | `create X` mit gemergtem Payload |
| `create X` | `delete X` | beide entfernen (Server hat X nie gesehen) |
| `update X {a}` | `update X {b}` | ein `update X {a, b}` (spätere Werte gewinnen) |
| `update X` | `delete X` | nur `delete X` |
| `update X {is_checked: true}` | `update X {is_checked: false}` | Merge; entspricht der Wert dem Server-Snapshot → Op entfällt ganz |
| `action complete A` | `action uncomplete A` | entfällt, wenn Snapshot `uncompleted` war |

Ein Eintrag mit `status: 'inflight'` wird nie verändert; neue Ops werden dahinter eingereiht.

**Fehlerklassifikation pro Response:**

| Response | Klasse | Verhalten |
|---|---|---|
| 2xx | Erfolg | Op entfernen, Server-Antwort in Snapshot schreiben |
| Netzwerkfehler, Timeout, 502/503/504, 429 | transient | `attempts++`, Backoff, Queue pausiert (nachfolgende Ops warten) |
| 500 | transient (begrenzt) | wie transient, nach z. B. 5 Versuchen → `failed` |
| 401 | Auth | Bestehender Interceptor in `api/client.ts` versucht Refresh + Retry. Scheitert der Refresh mit 401 → Queue pausiert, Ops bleiben erhalten (kein Verwerfen) |
| 403 | permanent | Kein Zugriff mehr auf Haushalt → `failed`, Haushalt-Daten aufräumen (3.4) |
| 404 bei `delete` | Erfolg | Ziel ist bereits weg |
| 404 bei `update`/`action` | Konflikt „remote gelöscht“ | Op verwerfen, Info an User (Kapitel 6) |
| 409 | Konflikt | `status: 'conflict'`, sichtbar machen |
| 400 / 422 | permanent | `status: 'failed'`, sichtbar machen (z. B. Liste wurde gelöscht: `list_id does not belong to this household`) |

Ein `failed`/`conflict`-Eintrag **blockiert die Queue nicht**; nachfolgende Ops auf *anderen*
Entitäten laufen weiter. Ops auf *derselben* Entität hinter einem fehlgeschlagenen Eintrag
werden mit angehalten.

**Backoff:** exponentiell mit Jitter, `min(2s · 2^attempts, 5 min) ± 20 %`. Unbegrenzt viele
Versuche für transiente Fehler, solange die App offen ist — jeder Sync-Trigger (4.5) setzt
`nextAttemptAt` auf „jetzt“ zurück.

**Timeouts:** Axios hat heute **keinen** Timeout (`axios.create({ baseURL })`). Für Outbox-
Requests ist ein Timeout zwingend (Vorschlag 10 s), sonst blockiert ein hängender Request im
„1-Balken-Netz“ die Queue. Wegen Idempotenz ist ein Abbruch eines eigentlich erfolgreichen
Requests unkritisch.

**Single-Writer über Tabs:** Nur ein Tab arbeitet die Outbox ab. Umsetzung über die
Web Locks API (`navigator.locks.request('outbox', …)`), mit Fallback auf „jeder Tab darf,
Idempotenz fängt Doppelsendungen ab“. Andere Tabs werden per `BroadcastChannel` über
Änderungen informiert.

### 4.4 Interaktion mit Socket.IO

Heute ersetzen die Handler das ganze Objekt („Server gewinnt immer“). Neu:

1. Eingehendes Event → in den **Server-Snapshot** schreiben (IndexedDB + Store-Basis), nicht
   direkt in den angezeigten Zustand.
2. Angezeigter Zustand = `rebase(snapshot, pendingOps)` für die betroffene Entität. Lokale,
   noch nicht gesendete Änderungen bleiben sichtbar; Felder, die lokal nicht angefasst wurden,
   übernehmen den Server-Wert.
3. **Veraltete Events verwerfen:** Ist `event.version < snapshot.version`, wird das Event
   ignoriert. Das löst die heute nur heuristisch behandelten Rennen zwischen REST-Antwort und
   Socket-Event (`serverIdx !== -1 && tempIdx !== -1`) sauber.
4. **Echo eigener Ops:** Das Event zur eigenen Op trägt dieselbe `id` und eine höhere
   `version` → einfach übernehmen, idempotent.
5. `*_deleted`-Events: Entität aus Snapshot entfernen. Liegt lokal ein pending `update` vor,
   wird dieser beim Senden mit 404 beantwortet → „remote gelöscht“ (4.3).
6. `shopping_list_deleted`: Items dieser Liste aus dem Snapshot entfernen (Kaskade spiegeln);
   pending `create`s für diese Liste werden beim Senden mit 400 abgelehnt → User fragen
   (verschieben in andere Liste / verwerfen).
7. `TodosView.vue` lädt heute bei jedem Event alles neu. Das muss entfallen (doppelte Arbeit
   zu den Store-Handlern und überschreibt lokale Änderungen).

**Verpasste Events:** Socket.IO hat kein Replay. Nach Reconnect ist ein Abgleich nötig (4.5).
Das existiert heute bereits als `handleReconnect()` in `App.vue` und wird um das Abarbeiten
der Outbox ergänzt.

### 4.5 Sync-Ablauf und Trigger

**Trigger** (alle laufen in denselben Single-Flight-`sync()`):

- App-Start (nach `authStore.initialize()`)
- `online`-Event (unzuverlässig: `navigator.onLine === true` heisst nur „Netzwerkinterface aktiv“,
  nicht „Server erreichbar“ — Captive Portal, Funkloch mit Balken)
- Socket `connect` / Reconnect (zuverlässigstes Signal, dass der Server erreichbar ist)
- `visibilitychange` → `visible` (iOS-PWA aus dem Hintergrund zurückholen)
- Nach jeder neuen Op, wenn online
- Timer alle 30 s, solange Ops ausstehen

Ob wir „online“ sind, entscheidet am Ende der Erfolg eines Requests, nicht `navigator.onLine`.

**Ablauf von `sync(householdId)`:**

```
1. Outbox abarbeiten (FIFO, ein Request gleichzeitig) bis leer oder transienter Fehler
2. Snapshot holen: GET shopping-lists, shopping-items, todos, chores/assignments
   (dieselben Endpoints wie heute in handleReconnect)
3. Snapshot in IndexedDB ersetzen (pro Store: alle Einträge des Haushalts löschen + neu schreiben,
   in einer Transaktion)
4. Angezeigten Zustand neu berechnen: rebase(snapshot, verbleibende Ops)
5. meta.lastSyncAt setzen
```

Schritt 1 vor 2, damit der Snapshot die eigenen Änderungen bereits enthält und nicht
kurzzeitig der alte Zustand aufblitzt. Werden in Schritt 1 Ops nicht fertig (Netz weg), wird
Schritt 2 übersprungen und der vorhandene Cache bleibt Basis.

**Deletes ohne Tombstones:** Weil Schritt 3 den Snapshot pro Haushalt vollständig ersetzt,
verschwinden remote gelöschte Entitäten automatisch. Ein Change-Cursor mit Tombstones wird
damit für Phase 2 nicht benötigt (siehe 4.7).

### 4.6 Backend-Änderungen

| # | Änderung | Betroffen | Aufwand |
|---|---|---|---|
| B1 | **Client-ID beim Create:** `id: uuid.UUID | None = None` in `ShoppingItemCreate`, `TodoCreate` (optional `ShoppingListCreate`). Existiert die ID bereits **im selben Haushalt** → bestehendes Objekt mit `200` zurückgeben (kein zweites Socket-Event). Existiert sie in einem anderen Haushalt → `409` ohne Details (kein Daten-Leak). Fehlt `id` → wie heute serverseitig generieren (abwärtskompatibel) | `routers/shopping.py`, `routers/todos.py` | klein |
| B2 | **`updated_at` + `version`** auf `shopping_lists`, `shopping_items`, `todos`, `chore_assignments` (optional `chores`, `todo_reminders`). `version INTEGER NOT NULL DEFAULT 1`, bei jedem Update `+1`; `updated_at` mit `onupdate`. Beide in die Response-Schemas und damit auch in die Socket-Payloads | `models.py`, Response-Schemas | klein |
| B3 | **Alembic-Migration** für B2 (`down_revision = 's1t2u3v4w5x6'`), `server_default` für bestehende Zeilen (`version=1`, `updated_at=created_at`). Muss unter PostgreSQL laufen; die Tests nutzen `Base.metadata.create_all` auf SQLite | `backend/migrations/versions/` | klein |
| B4 | **DELETE idempotent machen?** Variante a) Client behandelt 404 als Erfolg (keine Backend-Änderung, **empfohlen**). Variante b) Backend antwortet 204 auch bei fehlender ID — verwischt echte Fehler | — | — |
| B5 | **Todo-Claim idempotent:** bereits an *mich* vergeben → 200 statt 409. Nur nötig, falls Claim später offline-fähig wird | `routers/todos.py` | sehr klein |
| B6 | **Optional: Konflikterkennung** über `If-Match: <version>` bzw. `base_version` im PATCH. Server könnte bei Abweichung 409 liefern. **Für Phase 2 nicht empfohlen** (siehe 4.7, LWW); Feld aber schon mitschicken, um später ohne Client-Update umschalten zu können | — | mittel |
| B7 | **Optional: Client-Zeitstempel** `checked_at` / `done_at` / `completed_at` aus dem Client übernehmen (mit Plausibilitätsgrenzen, z. B. nicht in der Zukunft, max. 7 Tage alt). Heute setzt der Server `now()` zum Sync-Zeitpunkt (→ Offene Entscheidung E4) | Router | klein |
| B8 | **Idempotency-Key-Header** (`Idempotency-Key: <opId>`) wird vom Client immer gesendet. Eine serverseitige Key-Tabelle (Response-Cache) ist in Phase 2 **nicht nötig**, weil B1 + absolute PATCH-Werte + 404-als-Erfolg alle Fälle abdecken. Header heute schon senden, damit eine spätere Tabelle ohne Client-Änderung greift | — | — |

Keine Änderungen nötig für `POST /chores/assignments/{id}/complete|uncomplete` — bereits
idempotent (verifiziert in `routers/chores.py`).

PATCH ist idempotent, **solange der Client absolute Werte schickt** (`{is_checked: true}`
statt „toggle“). Das ist heute schon so (`repo.update(..., { is_checked: item.is_checked })`)
und muss so bleiben.

### 4.7 Konfliktauflösung pro Entität

Grundsatz: **Feldweises Last-Write-Wins nach Ankunftsreihenfolge beim Server.** Der Client
schickt nur geänderte Felder (Coalescing in 4.3), dadurch überschreiben sich zwei Personen nur,
wenn sie *dasselbe Feld* derselben Entität geändert haben. Für einen Haushalt mit 2–5 Personen
ist das ausreichend und erklärbar; eine Konflikt-UI mit „Version A / Version B“ wäre
unverhältnismässig.

| Entität / Feld | Regel | Bemerkung |
|---|---|---|
| ShoppingItem `is_checked` | LWW | Typischer Fall: beide haken ab → gleiches Ergebnis. Einer hakt ab, der andere wieder auf → später ankommender gewinnt |
| ShoppingItem `name`, `quantity`, `category`, `store` | LWW pro Feld | Zwei verschiedene Felder werden zusammengeführt |
| ShoppingItem `assigned_to_user_id` | LWW | Optional später „first wins“ analog Todo-Claim |
| ShoppingItem gelöscht vs. offline bearbeitet | **Delete gewinnt** | Update → 404 → verwerfen, Info-Hinweis „‚Brot‘ wurde inzwischen gelöscht“ |
| ShoppingItem offline gelöscht vs. remote bearbeitet | Delete gewinnt | Kein Hinweis nötig |
| ShoppingItem offline angelegt, Liste remote gelöscht | Fehler 400 | User fragen: in andere Liste verschieben oder verwerfen |
| Zwei Personen legen offline „Milch“ an | Beide bleiben | Keine automatische Duplikat-Zusammenführung (→ Offene Entscheidung E6) |
| Todo `is_done`, `title`, `description`, `due_date`, `assigned_to_user_id` | LWW pro Feld | `description` wird nicht textuell gemergt |
| Todo `tags` | LWW auf ganze Liste | Kein Set-Merge in Phase 2 |
| Todo gelöscht vs. bearbeitet | Delete gewinnt | wie Shopping |
| ChoreAssignment complete/uncomplete | LWW | Server-Endpoints idempotent; `completed_by_user_id` = wer zuletzt erledigt hat |
| ChoreAssignment offline erledigt, Chore remote gelöscht | 404 → verwerfen | Info-Hinweis |

`version` wird in Phase 2 zum **Erkennen** genutzt (veraltete Socket-Events, Diagnose,
optional Hinweis „wurde zwischenzeitlich von X geändert“), nicht zum **Ablehnen** von Writes.

**Warum kein Change-Cursor / keine Tombstones jetzt?** Ein Delta-Sync (`GET /sync?since=<cursor>`)
bräuchte für Deletes eine Tombstone-Tabelle, die *alle* Löschpfade inklusive DB-Kaskaden
(Liste → Items, Chore → Assignments, Haushalt → alles) korrekt befüllt. Das ist fehleranfällig.
Die Datenmengen pro Haushalt sind klein; der Full-Snapshot über die bestehenden Endpoints ist
einfacher und robust. Umstieg erst, wenn Messungen das rechtfertigen (Risiko R3).

---

## 5. Service Worker / PWA

### 5.1 Caching-Strategie

| Ressource | Heute | Phase 2 |
|---|---|---|
| App-Shell (HTML, JS-Chunks inkl. Lazy-Routes, CSS, Fonts `woff2`, Icons) | Precache via Workbox `globPatterns` | unverändert; offline Kaltstart prüfen (Abnahme) |
| Navigation | `navigateFallback: '/index.html'`, `/api/` und `/socket.io/` ausgenommen | unverändert |
| API-Daten (`/api/*`) | nicht gecacht | **weiterhin nicht im SW cachen.** Datenhaltung liegt in IndexedDB im App-Kontext. Ein zweiter HTTP-Cache im SW würde mit dem Outbox-Rebase konkurrieren und auth-abhängige Responses über Logout hinweg halten |
| Geschützte Bilder (`/api/files/...`) | nicht gecacht | online-only (Haustierfotos etc. sind nicht im Scope) |
| `push-sw.js` | via `importScripts` | unverändert |

Zusätzlich: `navigator.storage.persist()` nach erstem erfolgreichen Sync anfragen, damit der
Browser IndexedDB nicht bei Speicherdruck räumt (Chromium entscheidet heuristisch, Safari
unterstützt die API in neueren Versionen; Ergebnis ist ein Hinweis, keine Garantie).

### 5.2 Background Sync — ehrliche Einordnung

| Plattform | Background Sync API (`SyncManager`) | Periodic Background Sync |
|---|---|---|
| Chrome / Edge (Desktop, Android) | unterstützt | nur für installierte PWAs, heuristisch |
| Safari macOS / **iOS / iPadOS** (auch als Home-Screen-PWA) | **nicht unterstützt** | nicht unterstützt |
| Firefox | nicht unterstützt | nicht unterstützt |

(Stand der Recherche bei Erstellung; vor Umsetzung gegen aktuelle Kompatibilitätstabellen prüfen.)

Für den Haupt-Use-Case (Haushaltsmitglieder mit iPhone im Supermarkt) bringt Background Sync
also **nichts**. Hinzu kommt ein technischer Blocker: Der Access-Token lebt nur im Speicher
der Seite, der Refresh-Token ist ein HttpOnly-Cookie (seit H-01). Ein Service Worker könnte
`/api/auth/refresh` zwar mit `credentials: 'include'` und dem CSRF-Header aufrufen, bräuchte
dafür aber eine zweite Refresh-Logik (inkl. Grace-Window-Verhalten gegenüber offenen Tabs).

**Entscheidung (Empfehlung):** Kein Background Sync in Phase 2. Sync läuft ausschliesslich im
App-Kontext über die Trigger aus 4.5. Konsequenz für den User: Änderungen werden übertragen,
sobald die App nach dem Einkauf wieder geöffnet oder in den Vordergrund geholt wird. Das muss
im UI ehrlich kommuniziert werden („wird beim nächsten Öffnen mit Netz synchronisiert“).

Background Sync für Chromium kann später als reines Plus ergänzt werden (Meilenstein M7), wenn
Tokens ohnehin in IndexedDB wandern.

### 5.3 iOS-spezifische Grenzen

- iOS beendet Hintergrund-PWAs aggressiv → Szenario S2 (Kaltstart offline) ist der Normalfall,
  nicht die Ausnahme. Precache + IndexedDB-Cache sind deshalb Pflicht, nicht Kür.
- Safari löscht Script-beschreibbaren Speicher von Websites, die 7 Tage nicht besucht wurden
  (ITP). Zum Home-Bildschirm hinzugefügte Web-Apps sind laut WebKit davon ausgenommen. Für
  Nutzer im normalen Safari-Tab ist Datenverlust nach längerer Inaktivität also möglich — betrifft
  nur noch nicht gesendete Ops, wenn jemand 7 Tage lang die App nicht öffnet.
- Kein zuverlässiges `online`-Event beim Zurückkehren aus dem Hintergrund → `visibilitychange`
  ist der wichtigere Trigger.

---

## 6. UX

### 6.1 Zustände

| Zustand | Anzeige |
|---|---|
| Online, nichts ausstehend | wie heute (Sync-Dot `connected`) |
| Offline, nichts ausstehend | Banner (neuer Text, s. u.), App voll bedienbar für Offline-Module |
| Offline, N ausstehend | Banner + Zähler „N Änderungen warten auf Verbindung“ |
| Online, synchronisiert gerade | Sync-Dot animiert, „Synchronisiere…“ |
| Fehler / Konflikte vorhanden | Dauerhafter, antippbarer Hinweis „N Änderungen konnten nicht gespeichert werden“ → öffnet Sheet |

Der heutige Bannertext „Änderungen können aktuell nicht gespeichert werden“ wird für
offline-fähige Module falsch und muss ersetzt werden.

### 6.2 Pro Item

- Kleines Icon (z. B. Phosphor `PhCloudArrowUp`) an Items mit ausstehender Op, Tooltip/`aria-label`
  „Wird synchronisiert, sobald du online bist“.
- Items mit `failed`/`conflict`: Warn-Icon (`PhWarningCircle`, bereits importiert in `App.vue`),
  Tippen öffnet Detail mit „Erneut versuchen“ / „Verwerfen“.
- Status wird aus der Outbox abgeleitet (`pendingByEntityId: Map<string, OutboxStatus>` im
  Sync-Store), nicht als Feld am Entity gespeichert.

### 6.3 Online-only-Aktionen offline

Buttons deaktivieren (`:disabled="!isOnline"`) mit Hinweis „Nur online verfügbar“. Kein
stilles Einreihen von Aktionen, die nicht offline-fähig sind.

### 6.4 Fehler- und Konfliktanzeige

- **Kein Toast pro Op** beim Sync (bei 20 Ops wäre das Spam). Ein zusammenfassender Toast nach
  Abschluss: „3 Änderungen synchronisiert“ nur, wenn vorher offline; Fehler als ein Toast mit
  Aktion „Anzeigen“.
- Sheet „Nicht gespeicherte Änderungen“: Liste mit Entitätsname, Aktion, Grund (übersetzter
  Fehlercode), Buttons „Erneut versuchen“ / „Verwerfen“ / bei Liste-gelöscht „In Liste … verschieben“.
- „Remote gelöscht“-Fälle (404 auf Update) als einmaliger Info-Toast, nicht als Fehler im Sheet.
- Undo nach Löschen: Ist der Delete noch `pending`, entfernt Undo die Op aus der Outbox (Item
  behält seine ID) statt wie heute ein neues Item anzulegen.

### 6.5 i18n-Keys (Vorschlag)

Neue bzw. geänderte Keys, jeweils in `de.json` **und** `en.json`; `npm run check:locales` läuft
bereits im `build`-Script und bricht bei Abweichung ab.

| Key | DE | EN |
|---|---|---|
| `offline.banner` (geändert) | Kein Netz – Änderungen werden gespeichert und später synchronisiert. | No connection – changes are saved and will sync later. |
| `offline.pendingCount` | {n} Änderung wartet auf Verbindung \| {n} Änderungen warten auf Verbindung | {n} change waiting for connection \| {n} changes waiting for connection |
| `offline.onlineOnly` | Nur online verfügbar | Only available online |
| `offline.itemPending` | Wird synchronisiert, sobald du online bist | Will sync when you're back online |
| `offline.syncOnOpen` | Wird beim nächsten Öffnen mit Netz übertragen | Will be sent the next time you open the app with a connection |
| `sync.syncing` | Synchronisiere… | Syncing… |
| `sync.synced` | {n} Änderung synchronisiert \| {n} Änderungen synchronisiert | {n} change synced \| {n} changes synced |
| `sync.failedCount` | {n} Änderung konnte nicht gespeichert werden \| {n} Änderungen konnten nicht gespeichert werden | {n} change could not be saved \| {n} changes could not be saved |
| `sync.show` | Anzeigen | Show |
| `sync.retry` | Erneut versuchen | Retry |
| `sync.discard` | Verwerfen | Discard |
| `sync.moveToList` | In Liste verschieben | Move to list |
| `sync.sheetTitle` | Nicht gespeicherte Änderungen | Unsaved changes |
| `sync.deletedRemotely` | „{name}“ wurde inzwischen gelöscht | "{name}" was deleted in the meantime |
| `sync.listDeleted` | Die Liste wurde inzwischen gelöscht | The list was deleted in the meantime |
| `sync.reason.validation` | Ungültige Daten | Invalid data |
| `sync.reason.forbidden` | Kein Zugriff mehr auf diesen Haushalt | No longer a member of this household |
| `sync.reason.conflict` | Wurde gleichzeitig geändert | Was changed at the same time |
| `sync.logoutPending.title` | Nicht synchronisierte Änderungen | Unsynced changes |
| `sync.logoutPending.body` | Es gibt {n} Änderungen, die noch nicht gespeichert sind. | There are {n} changes that have not been saved yet. |
| `sync.logoutPending.syncNow` | Jetzt synchronisieren | Sync now |
| `sync.logoutPending.discard` | Verwerfen und abmelden | Discard and log out |
| `sync.reloadRequired` | Die App wurde in einem anderen Tab aktualisiert. Bitte neu laden. | The app was updated in another tab. Please reload. |

Pluralformen mit `|` entsprechen der vue-i18n-Syntax.

---

## 7. Teststrategie und Rollout

### 7.1 Frontend-Unit-Tests (Vitest)

`vitest.config.ts` nutzt `environment: 'node'`. IndexedDB gibt es dort nicht → Dev-Dependency
**`fake-indexeddb`** (`import 'fake-indexeddb/auto'` im Test-Setup). Kein jsdom nötig, solange
die Offline-Schicht keine DOM-APIs nutzt.

| Testgruppe | Inhalt |
|---|---|
| `rebase()` | Reine Funktion: Create/Update/Delete/Action über Snapshot, Reihenfolge, Update auf fehlende Entität, Delete-gewinnt |
| Coalescing | alle Zeilen der Tabelle in 4.3, inkl. „inflight wird nicht angefasst“ |
| Fehlerklassifikation | Mapping Status → Verhalten (4.3), 404 bei Delete = Erfolg |
| Backoff | `vi.useFakeTimers()`, Jitter-Grenzen, Reset bei Trigger |
| Outbox-Persistenz | Enqueue → DB schliessen → neu öffnen → Ops vorhanden (gegen `fake-indexeddb`) |
| DB-Migration | DB mit Version n−1 anlegen, Upgrade auf n, Outbox-Inhalt bleibt erhalten |
| Sync-Engine | mit Mock-Online-Repository: Offline (Netzwerkfehler) → Ops bleiben; Online → in Reihenfolge gesendet; Abbruch mitten in der Queue |
| Socket-Merge | Event mit niedrigerer `version` wird ignoriert; Event bei pending Update behält lokale Felder |
| Isolation | zwei User-DBs, Haushaltswechsel, Logout löscht nur eigene DB |

Die Repository-Factories (Phase 1) erlauben, `createOfflineFirst…Repository(online, …)` mit
einem In-Memory-Fake für `online` zu testen. „Offline“ wird im Unit-Test durch ein
Online-Repository simuliert, das `AxiosError` ohne `response` (Netzwerkfehler) wirft.

### 7.2 Backend-Tests (pytest, SQLite in-memory wie bestehend)

- Create mit Client-`id` zweimal → genau eine Zeile, zweite Antwort 200 mit identischem Body,
  nur ein Socket-Emit (`emit_to_household_sync` ist in `conftest.py`-Fixtures bereits patchbar)
- Create mit `id`, die in anderem Haushalt existiert → 409, kein Leak
- Create ohne `id` → unverändertes Verhalten (Regression)
- PATCH zweimal mit gleichem Body → gleicher Zustand, `version` steigt (oder bleibt bei No-op —
  festlegen und testen)
- DELETE zweimal → 204, dann 404 (dokumentiert das Verhalten, auf das der Client baut)
- `complete`/`uncomplete` doppelt → 200, Zustand stabil (bestehendes Verhalten absichern)
- Migration: `alembic upgrade head` gegen PostgreSQL im Docker-Compose-Setup (manuell/CI),
  da die Unit-Tests `create_all` auf SQLite verwenden und Migrationen nicht abdecken

Bestehende Scoping-Tests (`test_shopping_scoping.py`, `test_todo_scoping.py`,
`test_chore_scoping.py`) um die neuen ID-Pfade ergänzen.

### 7.3 Offline simulieren

| Ebene | Werkzeug |
|---|---|
| Unit | Mock-Repository wirft Netzwerkfehler; `navigator.onLine` per `vi.stubGlobal` |
| E2E (optional, neu) | Playwright `browserContext.setOffline(true)` — Chromium ist in der Dev-/CI-Umgebung vorhanden. Szenarien S1–S4 als Smoke-Tests. Aktuell gibt es kein E2E-Setup im Repo |
| Manuell Desktop | Chrome DevTools → Network „Offline“ / „Slow 3G“; Application → Service Workers „Offline“; IndexedDB-Inspektor |
| Manuell iOS | Flugmodus, App aus App-Switcher beenden, neu öffnen (S2); zwei Geräte für S5 |

### 7.4 Meilensteine

Jeder Meilenstein ist einzeln auslieferbar und lässt das System in einem konsistenten Zustand.
Schätzung in Personentagen (PT) inkl. Tests, für eine Person, die die Codebasis kennt.

| # | Meilenstein | Inhalt | Nutzen ohne Folgemeilensteine | Schätzung |
|---|---|---|---|---|
| M0 ✅ | Backend-Grundlagen | B1 (Client-IDs), B2/B3 (`updated_at`, `version`, Migration), Tests. Frontend schickt ab jetzt `id` bei Create mit (Temp-ID = endgültige ID) | Entfernt den Temp-ID-Swap, behebt Duplikat-Risiko bei Retry, korrigiert Socket-Race in `handleTodoCreated` | 1,5–2 PT |
| M1 | Lese-Cache | `idb`, DB-Layout, `me`-Snapshot, Snapshot-Persistenz für Shopping/Todos/Chores, Offline-Kaltstart, Logout löscht DB | App zeigt im Keller den letzten Stand statt leerer Liste (S2) | 2–3 PT |
| M2 | Outbox + Shopping-Items offline | Outbox, Coalescing, Sync-Engine, Trigger, `rebase`, Socket-Handler-Umstellung Shopping, Pending-Icon, neue Banner-Texte, i18n | Kern-Use-Case S1/S3/S4 erfüllt | 3–4 PT |
| M3 | Todos offline | Repository/Store/Handler analog, `TodosView`-Refetch entfernen | S1 für Todos | 1,5–2 PT |
| M4 | Putzplan offline | `complete`/`uncomplete` über Outbox | S7 | 0,5–1 PT |
| M5 | Fehler/Konflikte & Härtung | Sheet „Nicht gespeicherte Änderungen“, Logout-Dialog, Web Locks / Multi-Tab, `storage.persist()`, Timeouts | Robustheit, Supportfähigkeit | 2 PT |
| M6 | Online-only-Kennzeichnung | Deaktivieren/Hinweise in allen anderen Modulen | Konsistente UX | 1 PT |
| M7 | Optional | Delta-Sync mit Change-Cursor + Tombstones; Background Sync für Chromium; Offline-Anlegen von Shopping-Listen | Performance, Android-Komfort | 3–5 PT |

**Summe M0–M6: ca. 11,5–15 PT.**

#### Umsetzungsstand M0 (2026-10-06)

- `SyncVersionMixin` in `backend/app/models.py` auf `ShoppingList`, `ShoppingItem`, `Todo`,
  `ChoreAssignment`: `updated_at` (mit `onupdate`) und `version`. Ein `before_update`-Hook erhöht
  `version` als SQL-Ausdruck (`version + 1`, atomar bei parallelen Updates) — **nur bei
  Netto-Änderung**: ein PATCH ohne effektive Änderung und ein wiederholtes `complete` lassen die
  Version unverändert. Core-`update()`-Statements (aktuell nur Todo-Claim) erhöhen `version`
  selbst.
- Migration `w1x2y3z4a5b6_add_sync_version_fields` (befüllt `updated_at` aus `created_at`),
  Up/Down/Up gegen PostgreSQL 16 geprüft.
- Optionales `id` in `ShoppingItemCreate`, `ShoppingListCreate`, `TodoCreate`
  (`backend/app/services/client_ids.py`): Wiederholung → `200` mit dem **bestehenden** Objekt
  (ein abweichender Payload wird ignoriert), kein zweites Socket-Event; ID eines anderen Haushalts
  → `409 ENTITY_ID_CONFLICT`; paralleler Insert mit gleicher ID (PK-Kollision) → bestehendes Objekt.
- Response-Schemas und damit Socket-Payloads enthalten `updated_at` und `version`.
- Frontend: Shopping-Items, Shopping-Listen und Todos werden mit Client-ID angelegt; Temp-ID-Swap
  und `pendingTempIds` entfallen. Socket-Handler und REST-Antworten für Shopping, Todos und
  Chore-Assignments laufen über `upsertVersioned()` (`frontend/src/utils/syncVersion.ts`) und
  verwerfen veraltete Stände. Behebt nebenbei, dass `handleTodoCreated` Todos anderer User
  verwarf, solange ein eigener Create lief.
- Bekannte Grenze: Ein Create-Retry, nachdem ein anderes Mitglied das Objekt bereits gelöscht hat,
  legt es neu an (ohne Tombstones nicht unterscheidbar). Für M2 akzeptiert.

Empfehlung: M2–M4 hinter ein Feature-Flag (z. B. `VITE_OFFLINE_WRITES`) stellen, damit die
Outbox im eigenen Haushalt getestet werden kann, bevor sie für alle aktiv ist (→ E7).

### 7.5 Abnahmekriterien Phase 2 (M0–M6)

- [ ] Kaltstart im Flugmodus zeigt Einkaufsliste, Todos und Putzplan mit letztem Stand
- [ ] Shopping-Items offline hinzufügen/abhaken/bearbeiten/löschen, App beenden, mit Netz öffnen → Server hat alle Änderungen, keine Duplikate
- [ ] Gleiches für Todos und Assignment-Erledigungen
- [ ] Zwei Geräte ändern offline verschiedene Felder desselben Items → beide Änderungen erhalten
- [ ] Remote gelöschtes Item, lokal bearbeitet → verschwindet nach Sync mit Hinweis, Queue läuft weiter
- [ ] Online-only-Aktionen sind offline erkennbar deaktiviert
- [ ] Logout mit ausstehenden Änderungen fragt nach; Logout löscht lokale Daten
- [ ] `npm run check:locales`, `npm run typecheck`, `npm test`, `pytest` grün
- [ ] Bestehende Online-Funktionalität unverändert (Regression)

---

## 8. Risiken

| # | Risiko | Auswirkung | Gegenmassnahme |
|---|---|---|---|
| R1 | iOS: kein Background Sync, App wird im Hintergrund beendet | Änderungen kommen erst beim nächsten Öffnen an; Partner sieht sie verspätet | Ehrliche UX („beim nächsten Öffnen“), `visibilitychange`-Trigger |
| R2 | Safari-Speicherräumung (7-Tage-Regel im Browser-Tab, Speicherdruck) | Verlust nicht gesendeter Ops | Installation als PWA empfehlen, `storage.persist()`, Ops möglichst schnell senden |
| R3 | Full-Snapshot wächst: abgehakte Shopping-Items werden nie gelöscht und alle mit `include_checked: true` geladen | Längere Sync-Zeit, mehr Datenvolumen im schwachen Netz | Messen; Abhilfe ohne Delta-Sync: abgehakte Items älter als X Tage nicht mehr laden oder „Abgehakte löschen“-Funktion (→ E8); sonst M7 |
| R4 | LWW überschreibt still eine Änderung des Partners am selben Feld | Gelegentlich „verlorene“ Bearbeitung | Feldweise statt objektweise; selten bei flachen Entitäten; optional Hinweis via `version` |
| R5 | Server-Zeitstempel = Sync-Zeit | „Abgehakt um 18:40“ obwohl um 17:10 im Laden | B7 / Entscheidung E4 |
| R6 | Komplexität Socket-Handler + Rebase | Subtile UI-Fehler (aufblitzende alte Werte) | `rebase` als reine, getestete Funktion; Handler nur noch „Snapshot updaten + rebase“ |
| R7 | Mehrere Tabs / App-Update mit Outbox-Formatänderung | Doppelte Sends, verwaiste Ops | Web Locks, Idempotenz, `formatVersion`, Migrations-Tests |
| R8 | Geteiltes Gerät, unverschlüsselte lokale Daten | Datenschutz | DB pro User, Logout löscht, gleiche Schutzklasse wie heutige Tokens |
| R9 | Refresh-Token läuft während langer Offline-Phase ab | Sync scheitert mit 401, User muss sich neu anmelden | Ops bleiben erhalten (3.4), nach Re-Login desselben Users weiter senden |
| R10 | `navigator.onLine` meldet „online“ im Funkloch | Fehlversuche, Batterie | Erfolg des Requests ist massgeblich, Backoff, Timeout |

---

## Offene Entscheidungen

**Entschieden am 2026-10-06:** Der Product Owner hat für E1–E12 jeweils die fett markierte
Empfehlung übernommen. Bei E8 (b oder c) ist die konkrete Variante vor M2 noch festzulegen.

| # | Frage | Optionen | Empfehlung |
|---|---|---|---|
| **E1** | Welche Module bekommen Offline-Schreiben, in welcher Reihenfolge? | a) nur Shopping-Items · b) Shopping-Items + Todos + Putzplan-Erledigungen · c) zusätzlich Shopping-Listen anlegen/umbenennen | **b**, Reihenfolge Shopping → Todos → Putzplan |
| **E2** | Konfliktstrategie | a) feldweises Last-Write-Wins · b) Writes mit veralteter Version ablehnen (409) und User entscheiden lassen | **a** für Phase 2; `version` wird trotzdem eingeführt |
| **E3** | Bearbeiten vs. Löschen gleichzeitig | a) Löschen gewinnt (mit Hinweis) · b) Bearbeiten „belebt“ das Item wieder | **a** |
| **E4** | Welcher Zeitpunkt zählt für `checked_at` / `done_at` / `completed_at` bei Offline-Aktionen? | a) Server-Zeit beim Sync (heute) · b) Client-Zeit mit Plausibilitätsgrenzen | **b**, falls diese Zeitstempel irgendwo angezeigt/ausgewertet werden sollen; sonst a |
| **E5** | Logout mit nicht synchronisierten Änderungen | a) Dialog (synchronisieren / verwerfen / abbrechen) · b) immer verwerfen · c) Logout offline sperren | **a** |
| **E6** | Zwei Personen legen offline denselben Artikel an | a) beide behalten · b) automatisch zusammenführen (gleicher Name + Liste, nicht abgehakt) | **a** (vorhersehbar), b ggf. später |
| **E7** | Rollout | a) direkt für alle · b) Feature-Flag, zuerst eigener Haushalt | **b** |
| **E8** | Wachstum abgehakter Einkaufsartikel (betrifft Sync-Volumen) | a) nichts tun · b) Server liefert abgehakte Items nur der letzten N Tage · c) Funktion „Abgehakte löschen“ | **b oder c**, vor M2 klären |
| **E9** | Background Sync für Android/Chromium | a) nie · b) später als Plus (M7) | **b** |
| **E10** | Online-only-Module offline: nur Lese-Cache oder gar nichts? | a) nichts (Hinweis „offline nicht verfügbar“) · b) Lese-Cache für Kalender/Notizen | **a** in Phase 2 |
| **E11** | Wie lange dürfen lokale Daten und nicht gesendete Ops eines abgemeldeten/abgelaufenen Users auf dem Gerät bleiben? | z. B. 7 / 30 Tage | **30 Tage**, danach automatisch löschen |
| **E12** | Soll Todo-Claim („Ich übernehme das“) offline möglich sein? | a) nein, online-only · b) ja, mit 409-Konfliktanzeige beim Sync | **a** |
