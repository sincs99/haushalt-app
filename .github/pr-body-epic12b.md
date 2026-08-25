## Epic 12b — Auth Hardening

### Bug Fixes
- **A1**: Transport errors (network, 5xx, timeout) no longer clear tokens
- **A2**: Multi-tab refresh conflict resolved (frontend reads latest token from storage + backend grace window 30s)
- **A3**: Concurrent logout deduplicated, manual vs. expiry logout distinguished

### Hardening
- **C1**: Rate limiting on login (5/min) and register (3/hour) via slowapi 0.1.9
- **C2**: Lazy refresh-token cleanup after each rotation
- **C3**: JWT secret startup check (no placeholder, ≥32 chars)
- **B1**: TokenStorage interface now async (Capacitor-ready)

### Tests
- 345/345 backend tests (6 new: grace window, rate limit, JWT check, cleanup)
- `vue-tsc --noEmit` ✅
- `npm run check:locales` ✅
