# Epic 8: Upload-Infrastruktur + Katzenfotos ✅ ABGESCHLOSSEN

## Ziel
Wiederverwendbare Datei-Upload-Basis (lokale Ablage in Docker-Volume, Supabase-Storage-Adapter später) und als erster Nutzer: Fotos für die Tiere.

**Status**: ✅ Komplett — inkl. Security-Review-Fixes und Business-Logic-Fixes
**Datum**: 2026-08-10
**Backend-Tests**: 317/317 bestanden
**Frontend**: vue-tsc ✅, 588 i18n-Keys synchron

---

## Phase 1: Backend — Storage-Grundlage ✅

### 8.1a StoredFile Model + Pet.photo_file_id + Migration ✅
- `StoredFile` Model in `backend/app/models.py`
- `Pet.photo_file_id` FK ergänzt
- Migration `q1r2s3t4u5v6_add_stored_files_and_pet_photo.py`
- `Household.stored_files` Relationship

### 8.1b LocalStorageService ✅
- `backend/app/services/storage.py`
- `save()`, `open()`, `delete()` + `_safe_path()` Defense-in-Depth

### 8.1c Files Router + Error Codes ✅
- `backend/app/routers/files.py` — POST/GET/DELETE
- Error Codes: FILE_TOO_LARGE, FILE_TYPE_NOT_ALLOWED, FILE_NOT_FOUND, FILE_IN_USE, FILE_MISMATCH
- Chunk-basiertes Lesen (F-01 Fix)
- Pillow MAX_IMAGE_PIXELS = 25M (F-02 Fix)
- PDF Magic-Byte-Validierung (F-03 Fix)
- Content-Disposition Sanitisierung (F-04 Fix)
- EXIF-Rotation mit ImageOps.exif_transpose() (BL-01 Fix)

### 8.1d Docker — Upload-Volume ✅
- `uploaddata:/app/data/uploads` Volume
- `UPLOAD_DIR` Env-Var

### 8.1e Pillow ✅
- `Pillow==11.2.1` in requirements.txt

---

## Phase 2: Backend — Pet-Foto Integration ✅

### 8.2 Pet-Foto PATCH-Erweiterung ✅
- `PetResponse.photo_file_id` + `PetUpdate.photo_file_id`
- PATCH-Validierung: Household-Zugehörigkeit + Bild-MIME → FILE_MISMATCH
- Foto-Cleanup bei Pet-Löschung (BL-10 Fix)

---

## Phase 3: Frontend ✅

### 8.3a filesRepository.ts + StoredFile Type ✅
- `frontend/src/repositories/filesRepository.ts`
- `StoredFile` Interface in types/index.ts
- `Pet.photo_file_id` + `PetUpdatePayload.photo_file_id`

### 8.3b useProtectedImage Composable ✅
- `frontend/src/composables/useProtectedImage.ts`
- Blob-Download via JWT, ObjectURL, Cleanup

### 8.3c PetDetailView Foto-Bereich ✅
- Rundes Foto mit Kamera-Button
- Upload → PATCH → altes Foto löschen
- Orphaned-File-Cleanup bei PATCH-Fehler (BL-04 Fix)
- Client-seitige Grössenprüfung (Quick-Win)
- accept="image/jpeg,image/png,image/webp" (Quick-Win)

### 8.3d PetsView Foto-Thumbnails ✅
- `PetPhotoAvatar.vue` Component (sm/md/lg)
- Ersetzt PhCat-Icon wenn photo_file_id vorhanden

### 8.3e i18n Keys ✅
- 4 Photo-Keys unter `pets.*`
- 5 Error-Keys unter `files.*`
- DE + EN synchron (588 Keys)

---

## Phase 4: Tests ✅

### test_files_scoping.py ✅
- 14 Tests: Upload/Download/Delete + Cross-Tenant + Validation + Pet-Photo-PATCH

### conftest.py ✅
- StoredFile Import, files Router Patch, stored_file_a/stored_file_b Fixtures

---

## Phase 5: Reviews ✅

### Security-Review ✅
- Dokument: `docs/security/epic8-upload-review.md`
- 8 Findings identifiziert, alle relevanten (F-01 bis F-05) gefixt

### Business-Logic-Review ✅
- Dokument: `docs/review-epic8-upload.md`
- 13 Findings, Top-3 kritische gefixt (BL-01, BL-04, BL-10)

---

## Zusammenfassung der erstellten/geänderten Dateien

### Neue Dateien:
- `backend/app/services/storage.py`
- `backend/app/routers/files.py`
- `backend/migrations/versions/q1r2s3t4u5v6_add_stored_files_and_pet_photo.py`
- `backend/tests/test_files_scoping.py`
- `frontend/src/repositories/filesRepository.ts`
- `frontend/src/composables/useProtectedImage.ts`
- `frontend/src/components/PetPhotoAvatar.vue`
- `docs/security/epic8-upload-review.md`
- `docs/review-epic8-upload.md`

### Geänderte Dateien:
- `backend/app/models.py` (StoredFile + Pet.photo_file_id)
- `backend/app/core/error_codes.py` (5 neue Codes)
- `backend/app/main.py` (files Router)
- `backend/app/routers/pets.py` (photo_file_id PATCH + Cleanup)
- `backend/requirements.txt` (Pillow)
- `backend/tests/conftest.py` (Patches + Fixtures)
- `docker-compose.yml` (Upload-Volume)
- `frontend/src/types/index.ts` (StoredFile + Pet-Erweiterung)
- `frontend/src/views/PetDetailView.vue` (Foto-Upload)
- `frontend/src/views/PetsView.vue` (Foto-Thumbnails)
- `frontend/src/locales/de.json` (9 Keys)
- `frontend/src/locales/en.json` (9 Keys)
