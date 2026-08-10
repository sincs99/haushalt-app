# Business-Logic-Review: Epic 8 — Upload-Infrastruktur + Katzenfotos

**Datum:** 2026-08-10  
**Reviewer:** Business-Logic-Reviewer (KI-gestützt)  
**Status:** ⚠️ Bedingt freigegeben — 3 kritische Befunde, 6 mittlere, 4 kleinere Hinweise  
**Scope:** Upload/Download/Delete, Pet-Foto-Workflow, Household-Scoping, Frontend-Flow

---

## 1. Fachliches Ziel

Benutzer sollen Fotos für ihre Haustiere hochladen können. Die Dateien werden serverseitig validiert, verkleinert und im Filesystem gespeichert. Jedes Pet kann genau ein Foto referenzieren. Dateien sind an einen Haushalt gebunden und dürfen nicht haushaltübergreifend genutzt werden.

---

## 2. Geprüfte Regeln & Befunde

### 2.1 Upload-Logik (MIME, Grössen, Resize)

| Regel | Implementierung | Bewertung |
|---|---|---|
| MIME-Whitelist: jpeg, png, webp, pdf | [`ALLOWED_MIME_TYPES`](backend/app/routers/files.py:28) | ✅ Sinnvoll |
| Max 10 MB | [`MAX_FILE_SIZE`](backend/app/routers/files.py:30) | ✅ Angemessen |
| Resize auf 1600px längste Kante | [`MAX_IMAGE_DIMENSION`](backend/app/routers/files.py:31) | ✅ Guter Kompromiss |
| JPEG Qualität 85 | [`JPEG_QUALITY`](backend/app/routers/files.py:32) | ✅ Standard-Best-Practice |
| PNG mit Transparenz bleibt PNG | [`_process_image()`](backend/app/routers/files.py:94) | ✅ Korrekt |
| WebP wird zu JPEG konvertiert | [`_process_image()`](backend/app/routers/files.py:102) | ✅ Universell kompatibel |
| Pillow validiert Bildinhalt | [`img.load()`](backend/app/routers/files.py:78) | ✅ Verhindert Fake-Bilder |

**Befund BL-E8-01 — EXIF-Rotation fehlt (Mittel ⚠️)**

In [`_process_image()`](backend/app/routers/files.py:70) wird `Image.open()` verwendet, aber `ImageOps.exif_transpose()` fehlt. Smartphone-Fotos enthalten EXIF-Orientierungsdaten. Ohne diese Korrektur werden Hochformat-Fotos auf vielen Geräten um 90° gedreht angezeigt.

> **Empfehlung:** Nach `img.load()` einfügen:
> ```python
> from PIL import ImageOps
> img = ImageOps.exif_transpose(img)
> ```

**Befund BL-E8-02 — HEIC/HEIF nicht unterstützt (Klein ℹ️)**

iPhones fotografieren standardmässig in HEIC-Format. Obwohl die meisten Browser HEIC beim File-Upload in JPEG konvertieren, ist dies nicht garantiert (z.B. Desktop-Browser mit manueller Dateiauswahl). Nutzer erhalten dann einen unklaren Fehler.

> **Empfehlung:** Entweder `image/heic` und `image/heif` zur Whitelist hinzufügen (mit Pillow-Plugin `pillow-heif`) oder im Frontend einen klaren Hinweis zeigen.

**Befund BL-E8-03 — PDF wird nicht inhaltlich validiert (Klein ℹ️)**

PDFs werden unverändert gespeichert ([Zeile 162–165](backend/app/routers/files.py:162)). Es gibt keine Inhaltsprüfung (z.B. ob die Datei wirklich ein valides PDF ist). Da PDFs aber nicht als Pet-Fotos verwendet werden können (MIME-Type-Check im PATCH), ist das Risiko gering.

---

### 2.2 Pet-Foto-Workflow (Upload → PATCH → Delete)

Der Frontend-Flow in [`handlePhotoUpload()`](frontend/src/views/PetDetailView.vue:53):

```
1. Upload Datei         → filesRepo.uploadFile() → erhält stored.id
2. PATCH Pet            → petsStore.updatePet({ photo_file_id: stored.id })
3. Altes Foto löschen   → filesRepo.deleteFile() (best-effort, catch ignoriert)
```

Die Backend-Validierung in [`update_pet()`](backend/app/routers/pets.py:444):
- Prüft ob `StoredFile` existiert ✅
- Prüft ob `household_id` übereinstimmt ✅
- Prüft ob MIME-Type `image/*` ist ✅

**Befund BL-E8-04 — Verwaiste Datei bei PATCH-Fehler (Kritisch 🔴)**

Wenn der Upload in Schritt 1 erfolgreich ist, aber der PATCH in Schritt 2 fehlschlägt (z.B. Netzwerkfehler, Validierungsfehler), bleibt die hochgeladene Datei als **verwaiste Datei** in der DB und auf dem Filesystem. Es gibt keinen Cleanup-Mechanismus.

Bei wiederholten fehlgeschlagenen Versuchen sammeln sich Waisen an.

> **Empfehlung:** 
> 1. **Kurzfristig:** Im Frontend-`catch`-Block die gerade hochgeladene Datei per `deleteFile()` aufräumen:
>    ```typescript
>    try {
>      const stored = await filesRepo.uploadFile(householdId.value, file)
>      try {
>        await petsStore.updatePet(petId.value, { photo_file_id: stored.id })
>        // ... altes Foto löschen
>      } catch {
>        // PATCH fehlgeschlagen → Upload rückgängig machen
>        await filesRepo.deleteFile(householdId.value, stored.id).catch(() => {})
>        throw new Error('PATCH failed')
>      }
>    } catch { ... }
>    ```
> 2. **Mittelfristig:** Background-Job der Dateien ohne Referenz nach X Stunden löscht.

**Befund BL-E8-05 — Verwaiste Datei bei Pet-Löschung (Kritisch 🔴)**

Wenn ein Pet gelöscht wird ([`delete_pet()`](backend/app/routers/pets.py:487)), wird `db.delete(pet)` aufgerufen. Der FK `photo_file_id` hat `ondelete="SET NULL"` ([Modell Zeile 694](backend/app/models.py:694)), aber da das Pet gelöscht wird, passiert nichts mit der referenzierten `StoredFile`. Die Datei bleibt **verwaist** in der DB und auf dem Filesystem.

> **Empfehlung:** In `delete_pet()` vor dem `db.delete()` das Foto aufräumen:
> ```python
> old_file_id = pet.photo_file_id
> db.delete(pet)
> db.commit()
> if old_file_id:
>     old_file = db.get(StoredFile, old_file_id)
>     if old_file and not db.query(Pet).filter(Pet.photo_file_id == old_file_id).first():
>         _storage.delete(old_file.storage_path)
>         db.delete(old_file)
>         db.commit()
> ```

**Befund BL-E8-06 — Kein "Foto entfernen"-Button im Frontend (Mittel ⚠️)**

In [`PetDetailView.vue`](frontend/src/views/PetDetailView.vue:592) gibt es nur einen Kamera-Button zum Hochladen eines neuen Fotos. Es fehlt eine Möglichkeit, ein Foto komplett zu entfernen (auf `null` zu setzen). Das Backend unterstützt dies (`photo_file_id: null` im PATCH), aber das Frontend bietet es nicht an.

> **Empfehlung:** Einen "✕"-Button oder Long-Press-Option am Foto hinzufügen, der `photo_file_id: null` sendet und anschliessend die alte Datei löscht.

**Befund BL-E8-07 — Foto-Sharing zwischen Pets möglich (Klein ℹ️)**

Es gibt kein `UNIQUE`-Constraint auf `Pet.photo_file_id`. Mehrere Pets können dasselbe Foto referenzieren (z.B. durch manuellen API-Aufruf). Das ist fachlich ungewöhnlich, aber der `FILE_IN_USE`-Schutz im Frontend verhindert korrekterweise das Löschen des geteilten Fotos. **Akzeptabel**, solange kein Unique-Constraint gewünscht ist.

---

### 2.3 FILE_IN_USE Schutz

Die Implementierung in [`delete_file()`](backend/app/routers/files.py:250):

```python
pet_ref = db.query(Pet).filter(Pet.photo_file_id == file_id).first()
if pet_ref is not None:
    raise HTTPException(422, FILE_IN_USE)
```

| Aspekt | Bewertung |
|---|---|
| Prüft Pet-Referenzen vor Löschung | ✅ Korrekt |
| Frontend ignoriert FILE_IN_USE beim alten Foto | ✅ Best-effort Pattern |
| Cross-Household-Sicherheit | ✅ Nicht nötig (DELETE prüft ohnehin household_id) |

**Befund BL-E8-08 — Nur Pet-Referenzen geprüft, nicht erweiterbar (Mittel ⚠️)**

Die FILE_IN_USE-Prüfung sucht **nur** nach `Pet.photo_file_id`-Referenzen. Wenn zukünftig andere Entitäten `StoredFile` referenzieren (Rezeptfotos, Dokumentanhänge, Notiz-Bilder), muss die Prüfung manuell erweitert werden.

> **Empfehlung:** Kommentar als TODO im Code + bei zukünftigen Erweiterungen Pattern prüfen:
> ```python
> # TODO: Bei neuen FK-Referenzen auf StoredFile hier erweitern
> # Alternativ: Generische Reverse-FK-Suche implementieren
> ```

**Befund BL-E8-09 — Kein kaskadenartiges "Löschen mit Dereferenzierung" (Klein ℹ️)**

Aktuell ist es nicht möglich, ein Foto zu löschen und gleichzeitig die Pet-Referenz zu entfernen (Atomic Operation). Der Client muss zuerst das Pet patchen (neue/keine file_id), dann die Datei löschen. Das ist fachlich korrekt für den jetzigen Use-Case, könnte aber bei Admin-Funktionen (z.B. "alle Fotos eines Pets zurücksetzen") hinderlich sein.

---

### 2.4 Household-Scoping Logik

| Szenario | Schutz | Bewertung |
|---|---|---|
| Upload in fremden Haushalt | [`verify_household_access`](backend/app/routers/files.py:120) → 403 | ✅ |
| Download aus fremdem Haushalt | `household_id`-Check ([Zeile 206](backend/app/routers/files.py:206)) → 404 | ✅ |
| Delete in fremdem Haushalt | `household_id`-Check ([Zeile 242](backend/app/routers/files.py:242)) → 404 | ✅ |
| PATCH Pet mit Foto aus anderem Haushalt | `household_id`-Check ([Zeile 461](backend/app/routers/pets.py:461)) → 422 FILE_MISMATCH | ✅ |
| Test-Abdeckung | Cross-tenant Tests vorhanden | ✅ |

**Befund BL-E8-10 — Physische Dateien bei Haushalt-Löschung nicht aufgeräumt (Kritisch 🔴)**

Wenn der letzte User einen Haushalt verlässt ([`leave_household()`](backend/app/routers/households.py:148)), wird `db.delete(household)` aufgerufen. Durch `cascade="all, delete-orphan"` werden alle `StoredFile`-DB-Einträge gelöscht — aber die **physischen Dateien** unter `data/uploads/{household_id}/` bleiben bestehen!

Über Zeit sammeln sich verwaiste Ordner mit Dateien an, die nie aufgeräumt werden.

> **Empfehlung:** 
> 1. **Kurzfristig:** Vor `db.delete(household)` alle Dateien vom Filesystem löschen:
>    ```python
>    for sf in household.stored_files:
>        _storage.delete(sf.storage_path)
>    ```
> 2. **Mittelfristig:** SQLAlchemy `after_delete`-Event-Listener auf `StoredFile` oder einen periodischen Cleanup-Job.

**Befund BL-E8-11 — User verlässt Haushalt: Fotos korrekt behandelt (Klein ℹ️)**

`StoredFile.uploaded_by_user_id` hat `ondelete="SET NULL"` → Die Datei bleibt erhalten, nur der Uploader wird auf `null` gesetzt. Pet-Fotos bleiben unverändert. **Fachlich korrekt** — das Foto gehört dem Haushalt, nicht dem User.

---

### 2.5 Frontend-Flow

| Aspekt | Bewertung |
|---|---|
| Kamera-Button → File-Input → Upload → Update | ✅ Intuitiv |
| Loading-State (`photoUploading`) | ✅ Korrekt angezeigt |
| Kamera-Button disabled während Upload | ✅ |
| Input-Reset für erneute Auswahl | ✅ (`input.value = ''` [Zeile 59](frontend/src/views/PetDetailView.vue:59)) |
| ObjectURL cleanup bei Unmount | ✅ ([`onUnmounted(() => cleanup())`](frontend/src/composables/useProtectedImage.ts:42)) |
| ObjectURL cleanup bei fileId-Wechsel | ✅ ([`watch` mit `cleanup()`](frontend/src/composables/useProtectedImage.ts:40)) |
| Blob-Download statt direkter URL (JWT-Schutz) | ✅ ([`fetchFileAsObjectUrl`](frontend/src/repositories/filesRepository.ts:24)) |
| PetPhotoAvatar Fallback auf Icon | ✅ ([`PhCat`](frontend/src/components/PetPhotoAvatar.vue:48)) |
| PetsView Fallback auf Emoji | ✅ ([`speciesEmoji()`](frontend/src/views/PetsView.vue:353)) |

**Befund BL-E8-12 — Frontend accept-Attribut zu breit (Mittel ⚠️)**

Das File-Input hat [`accept="image/*"`](frontend/src/views/PetDetailView.vue:619), was alle Bildformate erlaubt (GIF, BMP, TIFF, SVG, etc.). Das Backend akzeptiert aber nur jpeg/png/webp. Nutzer können ein GIF auswählen und erhalten dann eine generische Fehlermeldung.

> **Empfehlung:** Einschränken auf:
> ```html
> accept="image/jpeg,image/png,image/webp"
> ```

**Befund BL-E8-13 — Keine Client-seitige Grössenprüfung (Mittel ⚠️)**

Die Dateigrösse wird erst nach dem Upload vom Backend geprüft. Ein 50 MB Bild wird komplett hochgeladen, bevor der Fehler kommt. Bei schlechter Mobilfunkverbindung ist das eine schlechte User-Experience.

> **Empfehlung:** Vor dem Upload prüfen:
> ```typescript
> if (file.size > 10 * 1024 * 1024) {
>   showToast(t('pets.fileTooLarge'))
>   return
> }
> ```

---

## 3. Risikobewertung

### Risiken für Benutzer

| # | Risiko | Schwere | Wahrscheinlichkeit |
|---|---|---|---|
| R1 | Foto wird gedreht angezeigt (EXIF) | Mittel | Hoch (Smartphone-Fotos) |
| R2 | Upload scheint zu klappen, aber Foto erscheint nicht (PATCH-Fehler) | Hoch | Niedrig |
| R3 | Kein Weg Foto zu entfernen | Niedrig | Mittel |
| R4 | Unklare Fehlermeldung bei falschem Format | Niedrig | Mittel |

### Risiken für Business/Betrieb

| # | Risiko | Schwere | Wahrscheinlichkeit |
|---|---|---|---|
| R5 | Filesystem füllt sich mit verwaisten Dateien | Hoch | Hoch (bei aktiver Nutzung) |
| R6 | FILE_IN_USE-Prüfung bei neuen Features vergessen | Mittel | Mittel |
| R7 | Storage-Kosten durch Waisen | Niedrig | Mittel |

---

## 4. Empfohlene Verbesserungen (Priorisiert)

### Prio 1 — Vor Go-Live

| # | Befund | Aufwand | Empfehlung |
|---|---|---|---|
| BL-E8-01 | EXIF-Rotation fehlt | 5 Min | `ImageOps.exif_transpose()` in `_process_image()` |
| BL-E8-04 | Verwaiste Datei bei PATCH-Fehler | 15 Min | Cleanup im Frontend-catch oder Backend-Transaction |
| BL-E8-10 | Physische Dateien bei Haushalt-Löschung | 30 Min | Filesystem-Cleanup vor CASCADE-Delete |

### Prio 2 — Nächster Sprint

| # | Befund | Aufwand | Empfehlung |
|---|---|---|---|
| BL-E8-05 | Verwaiste Datei bei Pet-Löschung | 20 Min | Foto-Cleanup in `delete_pet()` |
| BL-E8-06 | Kein "Foto entfernen"-Button | 30 Min | UI-Element + PATCH mit `null` |
| BL-E8-12 | accept-Attribut zu breit | 2 Min | `accept="image/jpeg,image/png,image/webp"` |
| BL-E8-13 | Keine Client-Grössenprüfung | 5 Min | `file.size`-Check vor Upload |

### Prio 3 — Mittelfristig

| # | Befund | Aufwand | Empfehlung |
|---|---|---|---|
| BL-E8-08 | FILE_IN_USE nicht erweiterbar | 5 Min | TODO-Kommentar im Code |
| BL-E8-02 | HEIC nicht unterstützt | 1–2 Std | `pillow-heif` Plugin oder Frontend-Hinweis |
| — | Orphan-Cleanup-Job | 2–4 Std | Background-Job für Dateien ohne Referenz |

---

## 5. Testfälle / Akzeptanzkriterien

### Upload-Logik

| # | Testfall | Erwartung | Status |
|---|---|---|---|
| T1 | PNG 100×100 hochladen | 201, JPEG zurück (kein Alpha) | ✅ getestet |
| T2 | PNG mit Transparenz hochladen | 201, bleibt PNG | ✅ getestet |
| T3 | Datei > 10 MB hochladen | 422 FILE_TOO_LARGE | ✅ getestet |
| T4 | Shell-Script hochladen (falscher MIME) | 422 FILE_TYPE_NOT_ALLOWED | ✅ getestet |
| T5 | Fake-PNG (Bytes sind kein Bild) hochladen | 422 FILE_TYPE_NOT_ALLOWED | ✅ (Pillow wirft Exception) |
| T6 | **Hochformat-Smartphone-Foto mit EXIF-Rotation** | **Korrekt rotiert gespeichert** | ❌ fehlt |

### Pet-Foto-Workflow

| # | Testfall | Erwartung | Status |
|---|---|---|---|
| T7 | PATCH Pet mit gültigem photo_file_id | 200, file_id gesetzt | ✅ getestet |
| T8 | PATCH Pet mit file_id aus anderem Haushalt | 422 FILE_MISMATCH | ✅ getestet |
| T9 | PATCH Pet mit nicht existierender file_id | 422 FILE_MISMATCH | ✅ getestet |
| T10 | **Upload erfolgreich → PATCH schlägt fehl → Datei aufräumen** | **Keine Waisen** | ❌ fehlt |
| T11 | **Pet löschen → Referenzierte Datei aufräumen** | **Keine Waisen** | ❌ fehlt |
| T12 | **PATCH Pet mit `photo_file_id: null`** | **200, Foto entfernt** | ❌ fehlt (Backend unterstützt es, kein Frontend-Test) |

### FILE_IN_USE

| # | Testfall | Erwartung | Status |
|---|---|---|---|
| T13 | Datei löschen die von Pet referenziert wird | 422 FILE_IN_USE | ✅ getestet |
| T14 | Datei löschen die von keinem Pet referenziert wird | 204 | ✅ getestet |

### Household-Scoping

| # | Testfall | Erwartung | Status |
|---|---|---|---|
| T15 | Upload in fremden Haushalt | 403 | ✅ getestet |
| T16 | Download aus fremdem Haushalt | 403 | ✅ getestet |
| T17 | Delete in fremdem Haushalt | 403 | ✅ getestet |
| T18 | **Haushalt löschen → Filesystem aufräumen** | **Keine verwaisten Dateien** | ❌ fehlt |

---

## 6. Zusammenfassung

### Was gut funktioniert ✅
- **Bildverarbeitung**: Pillow-Validierung, Resize, Qualitätskompromiss — alles fachlich sinnvoll
- **Household-Scoping**: Durchgängig korrekt implementiert mit guter Testabdeckung
- **FILE_IN_USE-Schutz**: Verhindert Datenverlust durch versehentliches Löschen
- **Frontend-Flow**: Intuitiver Upload mit korrektem Memory-Management
- **JWT-geschützter Bild-Download**: Blob-Download-Pattern statt direkter URL ist korrekt

### Was verbessert werden muss ⚠️
- **EXIF-Rotation**: Smartphone-Fotos werden potenziell falsch rotiert angezeigt
- **Verwaiste Dateien**: Drei Szenarien (PATCH-Fehler, Pet-Löschung, Haushalt-Löschung) erzeugen Filesystem-Waisen
- **Frontend-Validierung**: accept-Attribut zu breit, keine Grössenprüfung
- **Fehlende Foto-Entfernen-Option**: User können Foto nur ersetzen, nicht entfernen

### Gesamturteil
Die Kernfunktionalität ist **solide implementiert**. Die Hauptrisiken liegen bei **verwaisten Dateien** (Speicherwachstum über Zeit) und der **fehlenden EXIF-Rotation** (schlechte UX bei Smartphone-Fotos). Beide sind mit geringem Aufwand behebbar.
