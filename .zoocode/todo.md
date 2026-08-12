# Epic 15 + Epic 16 + 16b: Implementierungsplan

## Status: ✅ ABGESCHLOSSEN (2026-08-12)

---

## Epic 15: Nginx Upload Body-Limit ✅
- **Datei:** [`frontend/nginx.conf:4`](frontend/nginx.conf:4)
- **Änderung:** `client_max_body_size 12m;`
- ⚠️ Wirkt erst nach `docker compose up -d --build`

## Epic 16: Kalender-Monatsansicht ✅

### Geänderte/Neue Dateien

| Datei | Aktion | Beschreibung |
|-------|--------|-------------|
| [`frontend/src/stores/calendar.ts`](frontend/src/stores/calendar.ts:178) | Geändert | `fetchEvents(fromDate?, toDate?)` parametrisiert |
| [`frontend/src/locales/de.json`](frontend/src/locales/de.json) | Geändert | +6 Keys (viewWeek, viewMonth, noEventsMonth, moreEvents, nextMonth, prevMonth) |
| [`frontend/src/locales/en.json`](frontend/src/locales/en.json) | Geändert | +6 Keys (EN-Pendants) |
| [`frontend/src/components/CalendarMonthGrid.vue`](frontend/src/components/CalendarMonthGrid.vue) | **NEU** | 7×5/6 Grid, Dots, Detail, Avatare, Navigation |
| [`frontend/src/views/CalendarView.vue`](frontend/src/views/CalendarView.vue) | Geändert | 3 Tabs, localStorage-Persistierung, Monatsstatus |
| [`frontend/src/components/ui/BasePillTabs.vue`](frontend/src/components/ui/BasePillTabs.vue) | Geändert | Token-Fixes (font-weight, transition) |
| [`docs/review-epic16-month-view.md`](docs/review-epic16-month-view.md) | **NEU** | UI-Polish-Review-Dokument |

### Umgesetzte Review-Fixes

| ID | Fix | Status |
|----|-----|--------|
| K1 | Today-Markierung `--ink` (konsistent mit Wochenansicht) | ✅ |
| K2 | Dots 4×4px in beiden Ansichten | ✅ |
| K3 | Avatar-Stack im Monats-Detail | ✅ |
| M1 | Pre-computed dotsMap (Performance) | ✅ |
| M2 | Detail-Panel max-height 50vh + scroll | ✅ |
| M3 | BasePillTabs Token-Fixes | ✅ |
| M4 | Day-Number 28px | ✅ |
| M5 | margin-bottom am Month-Grid | ✅ |
| G1 | aria-label i18n (prevMonth, nextMonth) | ✅ |
| G2 | dot-extra font-size 10px | ✅ |
| G3 | Firefox scrollbar-width: none | ✅ |

### Bewusst nicht umgesetzt
| ID | Grund |
|----|-------|
| G4 | Span-Badge-Padding — konsistent, kein passender Token |
| G5 | Mitternachts-Refresh — Aufwand/Nutzen ungünstig |

### Build-Status
- `npm run build` ✅
- `npm run check:locales` ✅ (599 Keys synchron)
