# Epic 17b: Foto-Styling reparieren + Gewicht in kg

## Status: ✅ Abgeschlossen

---

## Übersicht
Zwei kritische Frontend-Bugs vor Deployment:
1. Tailwind-Utility-Klassen ohne Tailwind → Styling kaputt
2. Gewichtseingabe erwartet Gramm, Nutzer denken in kg

## Subtask 1: Tailwind → Scoped CSS (Foto-Bereich)

### Betroffene Dateien
- `frontend/src/views/PetDetailView.vue` (Zeilen 618–648, Template)
- `frontend/src/components/PetPhotoAvatar.vue` (komplett)

### Problem
Beide Dateien verwenden Tailwind-Klassen (w-24, h-24, rounded-full, hidden,
bg-primary, absolute, flex, items-center, object-cover, text-xs, etc.).
Dieses Projekt hat KEIN Tailwind installiert → keine der Klassen greift.

### Lösung: PetDetailView.vue (Foto-Bereich, Zeilen 618–648)
Ersetze alle Tailwind-Klassen durch BEM-Klassen mit scoped CSS:

**Template-Änderungen:**
```html
<!-- ALT (Zeile 618-648) -->
<div class="flex flex-col items-center mb-4">
  <div class="relative">
    <div class="w-24 h-24 rounded-full overflow-hidden bg-surface-variant ...">
    ...
    <button class="absolute bottom-0 right-0 w-8 h-8 rounded-full bg-primary ...">
  ...
<input ... class="hidden" ...>

<!-- NEU -->
<div class="pet-photo-section">
  <div class="pet-photo-wrapper">
    <div class="pet-photo" / "pet-photo pet-photo--placeholder">
    ...
    <button class="pet-photo__camera-btn">
  ...
<input ... class="pet-photo__input" ...>
```

**CSS-Regeln (scoped):**
```css
.pet-photo-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-bottom: var(--space-4);
}

.pet-photo-wrapper {
  position: relative;
}

.pet-photo {
  width: 112px;
  height: 112px;
  border-radius: 50%;
  overflow: hidden;
  border: 2px solid var(--line);
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--chip);
}

.pet-photo img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.pet-photo__camera-btn {
  position: absolute;
  bottom: 0;
  right: 0;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--color-primary);
  color: #fff;
  border: 2px solid var(--surface);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  box-shadow: var(--shadow-card);
}

.pet-photo__input {
  display: none;
}

.pet-photo__upload-status {
  font-size: var(--text-xs);
  color: var(--sub);
  margin-top: var(--space-1);
}
```

### Lösung: PetPhotoAvatar.vue (komplett)
Ersetze computed `sizeClasses` (Tailwind) durch scoped CSS mit BEM:

```css
.pet-avatar {
  border-radius: 50%;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  background: var(--chip);
}

.pet-avatar--sm { width: 40px; height: 40px; }
.pet-avatar--md { width: 48px; height: 48px; }
.pet-avatar--lg { width: 96px; height: 96px; }

.pet-avatar__img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.pet-avatar__loading {
  width: 100%;
  height: 100%;
  background: var(--chip);
  animation: pulse 1.5s ease-in-out infinite;
}

.pet-avatar__icon {
  color: var(--sub);
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
```

---

## Subtask 2: Gewichtseingabe in kg

### Betroffene Dateien
- `frontend/src/utils/money.ts`
- `frontend/src/views/PetsView.vue`
- `frontend/src/views/PetDetailView.vue`
- `frontend/src/locales/de.json`
- `frontend/src/locales/en.json`

### Problem
Eingabefeld erwartet Gramm (parseWeightGrams), Nutzer geben kg ein.
"4,5" wird als 5 Gramm interpretiert statt 4500g.

### Lösung

#### money.ts
- **Entferne** `parseWeightGrams`
- **Erstelle** `parseWeightKgToGrams(input: string): number | null | undefined`
  - Leer → `undefined`
  - Komma→Punkt, parseFloat
  - Bereich: 0.1–50 kg (Haustier-tauglich)
  - ×1000, Math.round → ganze Gramm
  - Ungültig → `null`

#### PetsView.vue
- Import: `parseWeightKgToGrams` statt `parseWeightGrams` (Zeile 9)
- `handleCreatePet()`: `parseWeightKgToGrams(formWeightGrams.value)` (Zeile 209)
- Placeholder: `$t('pets.weightPlaceholder')` statt `$t('pets.weight')` (Zeile 411)

#### PetDetailView.vue
- Import: `parseWeightKgToGrams` statt `parseWeightGrams` (Zeile 9)
- `openEditPetDialog()`: Vorbefüllung als kg-String (Zeile 416):
  ```ts
  editFormWeightGrams.value = pet.value.weight_grams
    ? (pet.value.weight_grams / 1000).toFixed(1).replace('.', ',')
    : ''
  ```
- `handleUpdatePet()`: `parseWeightKgToGrams(editFormWeightGrams.value)` (Zeile 446)
- Placeholder: `$t('pets.weightPlaceholder')` (Zeile 1113)

#### Locales
- `de.json`: `"weight": "Gewicht (kg)"`, `"weightPlaceholder": "z.B. 4,5"`
- `en.json`: `"weight": "Weight (kg)"`, `"weightPlaceholder": "e.g. 4.5"`

### NICHT ändern
- DB/Backend/API: `weight_grams` bleibt Gramm
- `formatWeight()` bleibt wie sie ist (rechnet schon g→kg)

---

## Subtask 3: Grep-Prüfung
Nach Abschluss: `Select-String` im Projekt auf Tailwind-Muster in .vue-Dateien.
Erwartung: 0 Treffer für `w-\d+`, `h-\d+`, `rounded-full`, `bg-primary`,
`text-on-`, `hidden` (als alleinige Klasse), `flex`, `items-center` etc.

## Subtask 4: Build-Prüfung
- `npm run build` (im frontend-Verzeichnis)
- `npm run check:locales` (falls vorhanden)

---

## Abnahmekriterien
- [ ] Foto als runder 112px Avatar mit 2px Border
- [ ] Kein "Choose File" sichtbar
- [ ] Kamera-Badge als 36px Kreis, unten-rechts am Avatar
- [ ] Upload-Status als Text unterhalb, kein Layoutsprung
- [ ] PetPhotoAvatar.vue (Listenseite) ebenfalls korrektes Styling
- [ ] Gewicht "4,5" eingeben → Karte zeigt "4.5 kg"
- [ ] Bestehendes Gewicht (z.B. 4500g) erscheint als "4,5" im Edit-Formular
- [ ] npm run build grün
- [ ] npm run check:locales grün
- [ ] Keine Tailwind-Klassen in .vue-Dateien
