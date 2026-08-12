# UI-Polish-Review: Kalender-Monatsansicht (Epic 16)

**Reviewer:** Frontend UI Polish Reviewer  
**Datum:** 2026-08-12  
**Scope:** `CalendarMonthGrid.vue`, `CalendarView.vue` (Integration), `BasePillTabs.vue`  
**Status:** Review abgeschlossen — 3 kritisch, 5 mittel, 5 gering

---

## Zusammenfassung

Die Monatsansicht ist solide aufgebaut: sauberes BEM-Naming, konsequente Token-Nutzung, gutes Grid-Layout und klare Trennung zwischen Raster und Tages-Detail. Die Integration in `CalendarView.vue` (3-Tab-Layout) funktioniert korrekt.

Es gibt jedoch **drei konsistenz-relevante Probleme** zwischen Monats- und Wochenansicht, die die visuelle Einheitlichkeit brechen, sowie einige Token-Lücken und einen Performance-Stolperstein.

---

## ✅ Positiv

| Aspekt | Bewertung |
|--------|-----------|
| BEM-Naming (`month-grid__*`, `month-event-card__*`) | Konsistent, lesbar |
| Design-Token-Nutzung (Spacing, Farben, Radien, Typo) | ~90 % tokenisiert |
| Scoped CSS | ✓ Korrekt |
| Grid-Layout `repeat(7, 1fr)` | Responsive, kein Overflow |
| Randtage (`opacity: 0.35`) | Subtil, nicht aufdringlich |
| Event-Card-Struktur (Bar + Body + Content) | Spiegelt Wochenansicht |
| Transitions via `--transition-fast` | ✓ |
| Monats-Navigation (Pfeile + klickbarer Titel → heute) | Gute UX |
| Dark-Mode: Alle Farben via CSS-Variablen | ✓ Vollständig |

---

## 🔴 Kritisch (3)

### K1 — Today-Markierung: Inkonsistente Farbe zwischen Ansichten

| | Monatsansicht | Wochenansicht |
|---|---|---|
| **Datei** | [`CalendarMonthGrid.vue`](frontend/src/components/CalendarMonthGrid.vue:467) | [`CalendarView.vue`](frontend/src/views/CalendarView.vue:1337) |
| **Farbe** | `background: var(--acc)` (Gold/Braun) | `background: var(--ink)` (Dunkel) |
| **Wirkung** | Warmer Akzent-Kreis | Neutraler dunkler Kreis |

**Problem:** Der Benutzer lernt in der Wochenansicht, dass "heute" ein dunkler Kreis ist. In der Monatsansicht wechselt die Farbe ohne ersichtlichen Grund. Das bricht die visuelle Sprache.

**Fix-Vorschlag — Option A (Monatsansicht an Wochenansicht angleichen):**
```css
/* CalendarMonthGrid.vue :467 */
.month-grid__num--today {
  background: var(--ink);     /* war: var(--acc) */
  color: var(--card);
  font-weight: var(--font-weight-semibold);
}
```

**Fix-Vorschlag — Option B (Wochenansicht an Monatsansicht angleichen):**
```css
/* CalendarView.vue :1337 */
.week-strip__day--today .week-strip__num {
  background: var(--acc);     /* war: var(--ink) */
  color: var(--card);
  ...
}
```

> **Empfehlung:** Option A (bestehende Wochenansicht als Referenz behalten), da `--ink` neutraler ist und in beiden Themes besser funktioniert.

---

### K2 — Dot-Grösse: 6px vs. 4px zwischen Ansichten

| | Monatsansicht | Wochenansicht |
|---|---|---|
| **Datei** | [`CalendarMonthGrid.vue`](frontend/src/components/CalendarMonthGrid.vue:481) | [`CalendarView.vue`](frontend/src/views/CalendarView.vue:1371) |
| **Grösse** | `6px × 6px` | `4px × 4px` |

**Problem:** Die Farbpunkte unter den Tagen haben unterschiedliche Grössen. In einem 360px-Viewport mit 7 Spalten (~48px pro Zelle) sind 6px-Dots proportional stärker als gewollt. Ausserdem bricht es die visuelle Konsistenz.

**Fix-Vorschlag (einheitlich 5px als Kompromiss):**
```css
/* CalendarMonthGrid.vue */
.month-grid__dot {
  width: 5px;
  height: 5px;
}

/* CalendarView.vue */
.week-strip__dot {
  width: 5px;
  height: 5px;
}
```

> Alternativ: 4px in beiden Ansichten, da die Dots dekorativ sind und nicht zu dominant wirken sollen.

---

### K3 — Fehlende Avatare im Monats-Detail vs. Wochenansicht

| | Monats-Detail-Card | Wochen-Event-Card |
|---|---|---|
| **Datei** | [`CalendarMonthGrid.vue`](frontend/src/components/CalendarMonthGrid.vue:330) | [`CalendarView.vue`](frontend/src/views/CalendarView.vue:861) |
| **Teilnehmer** | Nur Text (`getParticipantNames`) | `BaseAvatar`-Stack + "Alle"-Chip |

**Problem:** Die Monats-Detail-Karten zeigen Teilnehmer nur als Text-Meta (z.B. "Max, Anna +1"), während die Wochenansicht Avatar-Kreise zeigt. Das ist ein signifikanter visueller Bruch — die Karten wirken "ärmer".

**Fix-Vorschlag:** Avatar-Stack in `month-event-card__body` hinzufügen (analog zur Wochenansicht):
```html
<!-- CalendarMonthGrid.vue, nach month-event-card__content -->
<div class="month-event-card__avatars">
  <template v-if="event.participant_ids.length === 0">
    <span class="month-event-card__everyone-chip">
      {{ t('calendar.everyone') }}
    </span>
  </template>
  <template v-else>
    <BaseAvatar
      v-for="pid in event.participant_ids.slice(0, 3)"
      :key="pid"
      :name="getMemberName(pid)"
      :user-id="pid"
      size="sm"
    />
    <span v-if="event.participant_ids.length > 3" class="month-event-card__extra">
      +{{ event.participant_ids.length - 3 }}
    </span>
  </template>
</div>
```

---

## 🟡 Mittel (5)

### M1 — `dotsForDay()` wird 3× pro Zelle aufgerufen (Performance)

**Datei:** [`CalendarMonthGrid.vue`](frontend/src/components/CalendarMonthGrid.vue:289)

Im Template wird `dotsForDay(day.date)` auf Zeile 289, 295 und 298 **dreimal** pro Grid-Zelle aufgerufen. Bei 42 Zellen = **126 Funktionsaufrufe** statt 42.

**Fix:**
```html
<button v-for="day in gridDays" :key="day.date" ...>
  <span class="month-grid__num" ...>{{ day.num }}</span>
  <!-- Einmal berechnen via Destructuring -->
  <span class="month-grid__dots" v-bind="{ ...(dots = dotsForDay(day.date)) && {} }">
```

**Besserer Fix — Pre-computed Map:**
```typescript
const dotsMap = computed(() => {
  const map = new Map<string, { colors: string[]; extra: number }>()
  for (const day of gridDays.value) {
    map.set(day.date, dotsForDay(day.date))
  }
  return map
})
```
```html
<span v-for="(color, idx) in dotsMap.get(day.date)?.colors" ...>
```

---

### M2 — Detail-Panel nicht scroll-begrenzt

**Datei:** [`CalendarMonthGrid.vue`](frontend/src/components/CalendarMonthGrid.vue:494)

Das `.month-grid__detail` hat kein `max-height`. Bei einem Tag mit 8+ Events wächst das Panel unbegrenzt, der "+ Termin"-Button wandert weit nach unten, und das Gesamtlayout wird unverhältnismässig lang.

**Fix:**
```css
.month-grid__detail-cards {
  max-height: 50vh;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
}
```

---

### M3 — Hardcoded Values in `BasePillTabs.vue`

**Datei:** [`BasePillTabs.vue`](frontend/src/components/ui/BasePillTabs.vue:36)

| Zeile | Ist | Soll |
|-------|-----|------|
| 36 | `padding: 6px 16px` | `padding: var(--space-1) var(--space-4)` (4px 16px → nah genug) |
| 39 | `font-weight: 600` | `font-weight: var(--font-weight-semibold)` |
| 42 | `transition: all 150ms` | `transition: background var(--transition-fast), color var(--transition-fast)` |

`transition: all` ist ein Performance-Anti-Pattern (animiert ungewollt auch `padding`, `font-size` etc.).

---

### M4 — Day-Number Grösse: 26px vs. 28px

**Dateien:**
- [`CalendarMonthGrid.vue`](frontend/src/components/CalendarMonthGrid.vue:460): `width: 26px; height: 26px`
- [`CalendarView.vue`](frontend/src/views/CalendarView.vue:1340): `width: 28px; height: 28px`

Die Tages-Zahlen-Kreise sind im Monatsraster 2px kleiner als im Wochen-Strip. Optisch subtil, aber bei Today-Markierung wird der Unterschied sichtbar.

**Fix:** Beide auf 28px angleichen, oder einen Token `--day-num-size: 28px` einführen.

---

### M5 — Fehlender Bottom-Margin am Month-Grid

**Datei:** [`CalendarMonthGrid.vue`](frontend/src/components/CalendarMonthGrid.vue:358)

`.month-grid` hat kein `margin-bottom`. Wenn unterhalb Polls oder andere Sektionen folgen, kleben sie direkt am Grid oder am Detail-Panel.

**Fix:**
```css
.month-grid {
  padding: 0 var(--space-4);
  margin-bottom: var(--space-4);
}
```

---

## 🟢 Gering (5)

### G1 — Aria-Label Hardcoded (Englisch)

**Datei:** [`CalendarMonthGrid.vue`](frontend/src/components/CalendarMonthGrid.vue:259)

```html
<!-- Zeile 253: korrekt -->
<button ... :aria-label="t('common.back')">

<!-- Zeile 259: hardcoded English -->
<button ... aria-label="Next month">
```

**Fix:** `:aria-label="t('common.forward')"` oder `t('calendar.nextMonth')`.

---

### G2 — `font-size: 8px` ohne Token

**Datei:** [`CalendarMonthGrid.vue`](frontend/src/components/CalendarMonthGrid.vue:489)

`.month-grid__dot-extra` nutzt `font-size: 8px`, das kleiner ist als das kleinste Token `--text-xs` (12px). Bei 8px besteht Lesbarkeitsgefahr auf hochauflösenden Displays.

**Vorschlag:** Auf `10px` erhöhen oder `--text-xs` mit `transform: scale(0.8)` nutzen.

---

### G3 — Firefox Scrollbar bei Filter-Chips

**Datei:** [`CalendarView.vue`](frontend/src/views/CalendarView.vue:1248)

`.calendar-filter-chips::-webkit-scrollbar { display: none }` versteckt die Scrollbar nur in WebKit-Browsern. Firefox zeigt weiterhin eine Scrollbar.

**Fix:**
```css
.calendar-filter-chips {
  scrollbar-width: none; /* Firefox */
}
```

---

### G4 — Span-Badge Padding nicht tokenisiert

**Dateien:** [`CalendarMonthGrid.vue`](frontend/src/components/CalendarMonthGrid.vue:584), [`CalendarView.vue`](frontend/src/views/CalendarView.vue:1815)

`padding: 1px 6px` ist in beiden Dateien identisch (konsistent ✓), aber nicht tokenisiert. Akzeptabel, da kein passender Spacing-Token existiert.

---

### G5 — `todayStr` als `computed` ohne Date-Refresh

**Datei:** [`CalendarMonthGrid.vue`](frontend/src/components/CalendarMonthGrid.vue:73)

`todayStr` wird einmalig beim Mount berechnet. Wenn die App über Mitternacht offen bleibt, bleibt der alte Tag als "heute" markiert. Sehr geringes Risiko, aber erwähnenswert.

---

## Checkliste (Abgleich mit Prüfkriterien)

### Mobile (360px Breite)
| Kriterium | Status | Anmerkung |
|-----------|--------|-----------|
| Raster-Zellen kompakt, min 40px Touch-Target | ✅ | `min-height: 40px` gesetzt |
| Dots 6px Durchmesser | ⚠️ | 6px korrekt, aber inkonsistent zu Week-Strip (4px) → K2 |
| Wochentag-Header ohne Overflow | ✅ | 2-Buchstaben-Labels ("Mo", "Di") passen in 7×1fr |
| Monats-Navigation proportioniert | ✅ | Pfeile 20px + padding 8px, Titel zentriert |
| Tages-Detail scrollbar | ❌ | Kein max-height/overflow → M2 |

### Layout & Spacing
| Kriterium | Status | Anmerkung |
|-----------|--------|-----------|
| Design-Tokens konsistent | ⚠️ | ~90 %, einige Hardcoded-Values → M3, G2 |
| Kein hardcodiertes px wo Tokens vorhanden | ⚠️ | `font-size: 8px`, `26px` day-num, `6px 16px` pills |
| Randtage visuell abgegrenzt | ✅ | `opacity: 0.35` — subtil und korrekt |
| Heute-Markierung sichtbar | ⚠️ | Sichtbar ja, aber Farbe inkonsistent → K1 |

### Konsistenz mit Wochenansicht
| Kriterium | Status | Anmerkung |
|-----------|--------|-----------|
| Event-Karten gleiche Darstellung | ❌ | Avatare fehlen → K3 |
| Farb-Dots gleiche Grösse | ❌ | 6px vs. 4px → K2 |
| Filter-Chips gleichwertig | ✅ | Identische Chips, gleiche Stelle im Layout |

### 3-Tab-Layout
| Kriterium | Status | Anmerkung |
|-----------|--------|-----------|
| BasePillTabs responsive | ✅ | `overflow-x: auto`, kurze Labels passen auf 360px |
| Aktiver Tab erkennbar | ✅ | `--ink` Background, `--card` Text |

### Dark Mode / Theme
| Kriterium | Status | Anmerkung |
|-----------|--------|-----------|
| Alle Farben via CSS-Variablen | ✅ | Keine hardcodierten Farben ausser Kalender-Palette |

### Interaktion
| Kriterium | Status | Anmerkung |
|-----------|--------|-----------|
| Tap auf Tag → Toggle-Detail | ✅ | `expandedDay` toggle korrekt |
| "+ Termin"-Button erreichbar | ⚠️ | Erreichbar, aber bei vielen Events weit unten → M2 |
| Monats-Navigation smooth | ✅ | Kein Layout-Shift, `expandedDay` wird zurückgesetzt |

---

## Prioritäts-Reihenfolge für Fixes

| Prio | ID | Aufwand | Beschreibung |
|------|----|---------|--------------|
| 1 | K1 | 2 min | Today-Farbe angleichen |
| 2 | K2 | 2 min | Dot-Grösse vereinheitlichen |
| 3 | M1 | 10 min | `dotsForDay` Computed-Map |
| 4 | K3 | 20 min | Avatare in Month-Detail hinzufügen |
| 5 | M2 | 2 min | Detail-Panel scroll-begrenzen |
| 6 | M5 | 1 min | Bottom-Margin hinzufügen |
| 7 | G1 | 1 min | Aria-Label i18n |
| 8 | M3 | 5 min | BasePillTabs Token-Cleanup |
| 9 | M4 | 2 min | Day-Number 28px angleichen |
| 10 | G2 | 1 min | 8px font-size erhöhen |
| 11 | G3 | 1 min | Firefox scrollbar-width |

---

*Gesamtbewertung: **7/10** — Solide Basis mit guter Token-Nutzung. Die drei Konsistenz-Brüche (K1–K3) zur Wochenansicht sind die wichtigsten Fixes vor Release.*
