# Epic 12 — Token Persistence & Auth Lifecycle: Business Logic Review

**Datum:** 2026-08-25
**Reviewer:** Business Logic Reviewer (Automated)
**Status:** Review abgeschlossen — 2 × ⚠️ WARN, 1 × ❌ FAIL, 4 × ✅ PASS

---

## Zusammenfassung

| # | Szenario | Bewertung |
|---|----------|-----------|
| 1 | F5-Reload auf Household-Route | ✅ PASS |
| 2 | Browser schließen + öffnen | ✅ PASS |
| 3 | Access-Token abgelaufen, Aktion ausführen | ✅ PASS |
| 4 | Refresh-Token abgelaufen, Reload | ⚠️ WARN |
| 5 | Logout in Tab A, Tab B nächster Request | ⚠️ WARN |
| 6 | Foreign Household → 403, kein Logout | ✅ PASS |
| 7 | Socket Reconnect nach Token-Refresh | ❌ FAIL |

---

## Szenario 1: F5-Reload auf Household-Route

### ✅ PASS

**Erwartung:** User ist auf `/shopping`, drückt F5 → bleibt eingeloggt, bleibt auf `/shopping`, kein Flash.

**Code-Trace:**

1. [`main.ts`](frontend/src/main.ts:17-19) — Pinia wird installiert, dann `authStore.initialize()` **fire-and-forget** aufgerufen:
   ```ts
   const authStore = useAuthStore()
   authStore.initialize()  // ← NICHT awaited
   ```

2. [`auth.ts:37-77`](frontend/src/stores/auth.ts:37) — `initialize()`:
   - [`tokenStorage.get()`](frontend/src/services/tokenStorage.ts:23-35) liest aus `localStorage` → Tokens vorhanden
   - [`token.value = saved.accessToken`](frontend/src/stores/auth.ts:49) → `isAuthenticated` wird sofort `true`
   - [`fetchMe()`](frontend/src/stores/auth.ts:59) → API-Call zu `/api/auth/me` → User + Households geladen
   - [`_authReadyResolve()`](frontend/src/stores/auth.ts:76) → `authReady` Promise resolved

3. [`router/index.ts:96-114`](frontend/src/router/index.ts:96) — Navigation Guard:
   - [`await authStore.authReady`](frontend/src/router/index.ts:102) → **blockiert** bis `initialize()` fertig
   - [`authStore.isAuthenticated`](frontend/src/router/index.ts:104) → `true`
   - [`authStore.households.length > 0`](frontend/src/router/index.ts:110) → `true`
   - → **Durchlassen** zu `/shopping`

**Warum kein Flash:** Die initiale Navigation wird vom Guard **blockiert** bis `authReady` resolved. Da [`app.use(router)`](frontend/src/main.ts:21) nach `initialize()` aufgerufen wird und der Guard `await authReady` macht, wird keine Route gerendert bevor der Auth-Status bekannt ist.

**Bewertung:** Korrekt implementiert. Boot-Order (`Pinia → initialize() → Router → Mount`) ist sauber.

---

## Szenario 2: Browser schließen + öffnen

### ✅ PASS

**Erwartung:** User schließt Browser, öffnet App → noch eingeloggt.

**Code-Trace:**

Identisch mit Szenario 1, plus:

1. [`tokenStorage.ts:39`](frontend/src/services/tokenStorage.ts:39) — Tokens werden in `localStorage` gespeichert → **überlebt Browser-Close**
2. [`tokenStorage.get()`](frontend/src/services/tokenStorage.ts:23-35) — Beim nächsten Laden werden sie gelesen und validiert (Zeile 29: `parsed.accessToken && parsed.refreshToken && parsed.accessExpiresAt`)

**Sonderfall: Access-Token in der Zwischenzeit abgelaufen (>15 Min geschlossen):**
1. [`fetchMe()`](frontend/src/stores/auth.ts:59) → `api.get('/api/auth/me')` → 401
2. **Response-Interceptor** ([`client.ts:27-41`](frontend/src/api/client.ts:27)) fängt den 401 ab
3. [`authStore.refresh()`](frontend/src/api/client.ts:37) → Single-Flight → [`_doRefresh()`](frontend/src/stores/auth.ts:95) → neues Token-Paar
4. Retry von `/api/auth/me` → Erfolg
5. `initialize()` bekommt das erfolgreiche Ergebnis → Session aktiv ✅

**Hinweis:** Die Refresh-Logik in [`initialize()` Zeile 62-66`](frontend/src/stores/auth.ts:62) ist **redundant** mit dem Interceptor. Der Interceptor fängt den 401 schon ab und refresht. Die doppelte Absicherung schadet nicht, macht den Code aber etwas verwirrend. Kein Bug, nur Code-Smell.

---

## Szenario 3: Access-Token abgelaufen, Aktion ausführen

### ✅ PASS

**Erwartung:** Transparenter Refresh, Aktion klappt, nur 1 Refresh-Request.

**Code-Trace:**

1. User klickt Aktion → API-Call über [`api`](frontend/src/api/client.ts:3) Client
2. **Request-Interceptor** ([`client.ts:11-18`](frontend/src/api/client.ts:11)) → setzt `Authorization: Bearer <expired-token>`
3. Backend → [`deps.py:22-24`](backend/app/core/deps.py:22) → `decode_access_token()` → JWT expired → `JWTError` → 401
4. **Response-Interceptor** ([`client.ts:27-41`](frontend/src/api/client.ts:27)):
   - `error.response?.status === 401` → ✅
   - URL nicht in [`AUTH_URLS`](frontend/src/api/client.ts:8) → ✅
   - `!originalRequest._retried` → ✅
   - [`authStore.refresh()`](frontend/src/api/client.ts:37) aufgerufen

5. **Single-Flight Pattern** ([`auth.ts:81-93`](frontend/src/stores/auth.ts:81)):
   ```ts
   if (_refreshPromise) return _refreshPromise  // Concurrent Requests teilen sich
   _refreshPromise = _doRefresh()
   ```
   - [`_doRefresh()`](frontend/src/stores/auth.ts:95) → **Direkter `axios.post`** (NICHT über `api` Client → kein Interceptor-Loop!)
   - Backend [`auth.py:156-205`](backend/app/routers/auth.py:156): Token-Rotation → alten Token revoken → neues Paar
   - `token.value` und `refreshToken.value` aktualisiert
   - [`tokenStorage.set()`](frontend/src/stores/auth.ts:108) → localStorage aktualisiert

6. Retry ([`client.ts:40-41`](frontend/src/api/client.ts:40)):
   ```ts
   originalRequest.headers.Authorization = `Bearer ${authStore.token}`
   return api(originalRequest)
   ```

7. **Concurrent Requests:** Alle 401-Responses teilen dasselbe `_refreshPromise` → exakt 1 Refresh-Request → alle retrien mit dem neuen Token ✅

**Backend Token-Rotation** ist korrekt:
- [`auth.py:170-179`](backend/app/routers/auth.py:170): **Reuse-Detection** — wenn ein revoked Token nochmal verwendet wird, werden ALLE Tokens des Users revoked (Security-Feature)
- [`auth.py:192-203`](backend/app/routers/auth.py:192): Alter Token wird revoked, `replaced_by_id` gesetzt → vollständige Audit-Chain

---

## Szenario 4: Refresh-Token abgelaufen, Reload

### ⚠️ WARN — Redirect-URL geht für Nicht-Default-Routen verloren

**Erwartung:** User landet auf `/login`, nach Login Redirect zurück zur Original-Route.

**Code-Trace:**

1. [`initialize()`](frontend/src/stores/auth.ts:37) → Tokens geladen → [`fetchMe()`](frontend/src/stores/auth.ts:59)
2. Access-Token ist ebenfalls expired → API-Call → 401
3. **Interceptor** fängt 401 → [`authStore.refresh()`](frontend/src/api/client.ts:37)
4. [`_doRefresh()`](frontend/src/stores/auth.ts:95) → `POST /api/auth/refresh` mit expired Refresh-Token
5. Backend [`auth.py:181-189`](backend/app/routers/auth.py:181): Token expired → 401 `REFRESH_TOKEN_EXPIRED`
6. Interceptor catch ([`client.ts:42-47`](frontend/src/api/client.ts:42)):
   ```ts
   catch {
     await authStore.logout()  // ← HIER ist das Problem
   }
   ```
7. [`logout()`](frontend/src/stores/auth.ts:199-216):
   - `_clearState()` → alle Tokens null
   - **`router.push('/login')`** ← **OHNE redirect-Query!**

8. Gleichzeitig: `initialize()` catch-Block → [`_clearState()`](frontend/src/stores/auth.ts:68) nochmal
9. [`_authReadyResolve()`](frontend/src/stores/auth.ts:76) → Guard wird freigegeben
10. **Guard** ([`router/index.ts:104-106`](frontend/src/router/index.ts:104)):
    ```ts
    if (!authStore.isAuthenticated) {
      return { path: '/login', query: { redirect: to.fullPath } }  // ← /login?redirect=/shopping
    }
    ```

**Race Condition:** Schritt 7 (`logout()` → `router.push('/login')`) und Schritt 10 (Guard → `/login?redirect=/shopping`) erzeugen **konkurrierende Navigationen**. In Vue Router 4 überschreibt eine neue Navigation eine pending Navigation. Da `logout()` zuerst `router.push('/login')` auslöst und der Guard erst danach die redirect-Navigation auslöst, ist die Reihenfolge undeterministisch.

**Konkretes Risiko:**
- Für `/shopping` fällt es nicht auf, weil [`LoginView.vue:28`](frontend/src/views/LoginView.vue:28) den Default `'/shopping'` verwendet:
  ```ts
  router.push(redirect || '/shopping')
  ```
- Für **andere Routen** (z.B. `/todos`, `/expenses`, `/calendar`) **geht die Redirect-URL verloren** — User landet nach Login immer auf `/shopping` statt auf der gewünschten Seite.

**Empfohlene Lösung:** In [`logout()`](frontend/src/stores/auth.ts:199) **NICHT** direkt navigieren. Stattdessen nur State clearen und die Navigation dem Guard überlassen. Oder: `logout()` einen optionalen `redirectTo`-Parameter geben.

---

## Szenario 5: Logout in Tab A, Tab B nächster Request

### ⚠️ WARN — Kein Cross-Tab-Sync, bis zu 15 Min Verzögerung

**Erwartung:** Tab B bekommt 401 → Logout → `/login`.

**Code-Trace:**

1. **Tab A:** [`authStore.logout()`](frontend/src/stores/auth.ts:199):
   - `POST /api/auth/logout` → Refresh-Token wird in DB revoked ([`auth.py:211-215`](backend/app/routers/auth.py:211))
   - `_clearState()` → [`tokenStorage.clear()`](frontend/src/services/tokenStorage.ts:42) → `localStorage.removeItem('haushalt_tokens')`

2. **Tab B:** Hat eigene JavaScript-Runtime mit eigenem Pinia Store
   - `token.value` ist noch gesetzt (Pinia ist nicht cross-tab)
   - **localStorage wurde geleert**, aber Tab B liest es nur bei [`initialize()`](frontend/src/stores/auth.ts:41) (einmalig beim Boot)

3. **Tab B nächster API-Call:**
   - **Access-Token noch gültig (< 15 Min)?** → [`deps.py:22`](backend/app/core/deps.py:22) → JWT ist stateless → **Request geht durch!** 🔴
   - **Access-Token expired?** → 401 → Interceptor → `refresh()` → Backend: Token revoked → 401 `REFRESH_TOKEN_INVALID` → `logout()` → `/login` ✅

**Konkrete Lücke:**
- Access-Tokens sind **stateless JWTs** — das Backend hat keine Revocation-List für Access-Tokens
- Tab B kann noch bis zu **15 Minuten** (`access_token_expire_minutes = 15`, [`config.py:8`](backend/app/core/config.py:8)) weiterarbeiten
- Es gibt keinen `window.addEventListener('storage', ...)` der Cross-Tab-Änderungen erkennt

**Risikobewertung:** Für eine Haushalt-App ist das **akzeptabel** (kein Sicherheits-Hochrisiko). Für Compliance-kritische Apps wäre es ein Problem.

**Empfohlene Verbesserung (optional):**
```ts
// In auth.ts oder main.ts:
window.addEventListener('storage', (event) => {
  if (event.key === 'haushalt_tokens' && event.newValue === null) {
    _clearState()
    router.push('/login')
  }
})
```

---

## Szenario 6: Foreign Household → 403, kein Logout

### ✅ PASS

**Erwartung:** 403 Fehler, User bleibt eingeloggt.

**Code-Trace:**

1. API-Call mit falscher Household-ID → Backend [`verify_household_access()`](backend/app/core/deps.py:32-46):
   ```python
   raise HTTPException(status_code=403, detail=error_detail(ErrorCode.NOT_HOUSEHOLD_MEMBER, ...))
   ```

2. **Response-Interceptor** ([`client.ts:27-28`](frontend/src/api/client.ts:27)):
   ```ts
   if (error.response?.status === 401 && ...)  // ← 403 ≠ 401 → Block wird übersprungen
   ```

3. Zeile 51: `return Promise.reject(error)` → Error wird an die View propagiert
4. Kommentar [`client.ts:50`](frontend/src/api/client.ts:50) bestätigt explizit:
   ```ts
   // 403 wird NICHT als Auth-Fehler behandelt — durchreichen!
   ```

**Bewertung:** Sauber implementiert. 403 wird korrekt von 401 unterschieden.

---

## Szenario 7: Socket Reconnect nach Token-Refresh

### ❌ FAIL — Socket wird NICHT mit neuem Token reconnected

**Erwartung:** Nach Token-Refresh verbindet der Socket mit dem neuen JWT.

**Code-Trace:**

1. Token wird refreshed → [`auth.ts:105`](frontend/src/stores/auth.ts:105): `token.value = data.access_token`
2. **Watch in App.vue** ([`App.vue:49-50`](frontend/src/App.vue:49)) feuert:
   ```ts
   watch(
     () => [authStore.token, authStore.currentHouseholdId] as const,
     ...
   ```
3. `token` ist truthy → **kein disconnect** (Zeile 119)
4. [`connect(token)`](frontend/src/App.vue:124) wird aufgerufen

5. **PROBLEM** in [`useSocket.ts:11-14`](frontend/src/composables/useSocket.ts:11):
   ```ts
   function connect(token: string) {
     if (socket?.connected) {
       return  // ← Socket ist noch connected → SOFORT RETURN!
     }
     // Neuer Socket wird NIE erstellt
   }
   ```

6. Die Funktion [`reconnectWithToken()`](frontend/src/composables/useSocket.ts:65-74) existiert und würde korrekt arbeiten:
   ```ts
   function reconnectWithToken(newToken: string) {
     if (socket) {
       socket.disconnect()
       socket = null
       // ...
     }
     connect(newToken)
   }
   ```
   **Aber sie wird nirgends aufgerufen!**

**Konsequenzen:**
- Der Socket behält den **alten (expired) Token** in `auth`
- Backend [`socket_manager.py:57-87`](backend/app/socket_manager.py:57) validiert den Token nur beim **Connect**, nicht bei laufender Verbindung → laufende Session funktioniert weiter
- **Aber:** Wenn die Verbindung unterbrochen wird (Netzwerk-Schwankung), versucht Socket.IO automatisch zu reconnecten mit dem **alten Token**. Ist dieser inzwischen expired → [`decode_access_token()`](backend/app/socket_manager.py:69) schlägt fehl → **Reconnect wird rejected** → Socket bleibt dauerhaft offline

**Empfohlene Lösung:** In [`App.vue`](frontend/src/App.vue:124) den Watch ändern:

```ts
// STATT:
connect(token)

// VERWENDE:
// Prüfen ob sich der Token geändert hat (nicht nur Household)
if (token !== oldValue?.[0]) {
  reconnectWithToken(token)
} else {
  connect(token)
}
```

---

## Übergreifende Findings

### Finding A: Doppelte Refresh-Logik (Code-Smell)

[`initialize()` Zeile 62-66`](frontend/src/stores/auth.ts:62) hat eine eigene Refresh-Logik, die redundant zum Response-Interceptor in [`client.ts:34-41`](frontend/src/api/client.ts:34) ist. Beide fangen 401 ab und rufen `refresh()` auf. Durch das Single-Flight-Pattern entsteht kein doppelter Refresh-Request, aber die Logik ist verwirrend.

**Empfehlung:** Den try/catch in `initialize()` vereinfachen — der Interceptor erledigt den Refresh bereits.

### Finding B: `logout()` navigiert direkt → Guard-Konflikt

[`logout()`](frontend/src/stores/auth.ts:214-215) navigiert mit `router.push('/login')`. Wenn `logout()` aus dem Interceptor heraus aufgerufen wird (während eine Navigation pending ist), entsteht eine Race Condition mit dem Guard. Der Guard würde die redirect-Query setzen, aber `logout()` navigiert ohne.

**Empfehlung:** `logout()` sollte nur State clearen. Die Navigation sollte dem Guard überlassen werden, oder `logout()` bekommt einen optionalen `redirect`-Parameter.

### Finding C: Kein Cleanup alter Refresh-Tokens im Backend

[`_create_token_pair()`](backend/app/routers/auth.py:77-97) erstellt bei jedem Login ein neues Token-Paar. Bei häufigem Login/Refresh sammeln sich alte Tokens in der DB an. Es gibt keinen Cleanup-Job für expired/revoked Tokens.

**Empfehlung:** Periodischen Cleanup-Job einrichten:
```sql
DELETE FROM refresh_tokens
WHERE revoked_at IS NOT NULL AND revoked_at < NOW() - INTERVAL '30 days'
   OR expires_at < NOW()
```

---

## Testfälle / Akzeptanzkriterien

| # | Testfall | Akzeptanzkriterium | Prio |
|---|----------|--------------------|------|
| T1 | F5 auf `/shopping` | User bleibt eingeloggt, kein Flash | ✅ Erfüllt |
| T2 | Browser zu + auf nach 5 Min | Session aktiv, transparenter Refresh | ✅ Erfüllt |
| T3 | 3 parallele API-Calls mit expired Token | Genau 1 Refresh-Request im Network-Tab | ✅ Erfüllt |
| T4 | Refresh-Token expired, Reload auf `/todos` | Nach Login Redirect zu `/todos` | ❌ Redirect geht verloren |
| T5 | Tab A Logout, Tab B wartet 16 Min, klickt | Tab B wird auf `/login` geleitet | ✅ Erfüllt (mit Verzögerung) |
| T5b | Tab A Logout, Tab B sofort klicken | Tab B sollte sofort ausgeloggt werden | ❌ Tab B arbeitet weiter |
| T6 | API-Call gibt 403 zurück | Kein Logout, Fehler wird angezeigt | ✅ Erfüllt |
| T7 | Token refreshed, Netzwerk kurz unterbrochen | Socket reconnected mit neuem Token | ❌ Socket nutzt alten Token |

---

## Priorisierte Empfehlungen

1. **🔴 Hoch — Socket Reconnect fixen:** In `App.vue` [`reconnectWithToken()`](frontend/src/composables/useSocket.ts:65) statt [`connect()`](frontend/src/composables/useSocket.ts:11) aufrufen, wenn sich der Token ändert.

2. **🟡 Mittel — Redirect-Verlust bei Logout fixen:** [`logout()`](frontend/src/stores/auth.ts:199) sollte nicht direkt navigieren, sondern die Navigation dem Router Guard überlassen.

3. **🟢 Niedrig — Cross-Tab-Sync:** `storage`-Event-Listener hinzufügen für sofortigen Logout in allen Tabs.

4. **🟢 Niedrig — DB-Cleanup-Job:** Periodischen Cleanup für expired/revoked Refresh-Tokens einrichten.

5. **🟢 Niedrig — Redundante Refresh-Logik:** Den manuellen Refresh in [`initialize()`](frontend/src/stores/auth.ts:62) entfernen — der Interceptor erledigt das bereits.
