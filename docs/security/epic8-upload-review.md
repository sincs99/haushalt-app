# 🔒 Security Review — Epic 8: Upload-Infrastruktur + Katzenfotos

**Datum:** 2026-08-10  
**Reviewer:** Security-Review Agent  
**Status:** ⚠️ Bedingt freigegeben — 1 Hoch, 3 Mittel, beheben vor Go-Live  
**Scope:** File-Upload/Download/Delete, Pet-Photo-Integration, Frontend-Bildlademuster

---

## Geprüfte Dateien

| Datei | Bereich |
|---|---|
| `backend/app/routers/files.py` | Upload/Download/Delete Endpoints |
| `backend/app/services/storage.py` | LocalStorageService (Filesystem) |
| `backend/app/models.py` → `StoredFile` | Datenmodell |
| `backend/app/routers/pets.py` → PATCH | Pet-Foto-Verknüpfung |
| `backend/app/core/deps.py` | `verify_household_access` |
| `backend/app/main.py` | CORS, Router-Registrierung |
| `frontend/src/repositories/filesRepository.ts` | API-Client |
| `frontend/src/composables/useProtectedImage.ts` | Bildlade-Composable |
| `frontend/src/components/PetPhotoAvatar.vue` | Avatar-Komponente |
| `frontend/nginx.conf` | Reverse Proxy Config |
| `docker-compose.yml` | Volume-Konfiguration |
| `backend/tests/test_files_scoping.py` | Scoping-Tests |

---

## Findings

### 🔴 F-01 — Datei wird komplett in RAM geladen vor Größenprüfung (Hoch)

**Datei:** [`files.py`](../../backend/app/routers/files.py:124)  
**Zeilen:** 124–127

```python
raw_data = await file.read()          # ← Liest ALLES in RAM
if len(raw_data) > MAX_FILE_SIZE:     # ← Prüfung erst DANACH
```

**Risiko:** Ein Angreifer kann eine 1-GB-Datei senden. Der gesamte Body wird in den Speicher gelesen, bevor die 10-MB-Prüfung greift. Bei mehreren gleichzeitigen Anfragen → **Memory-Exhaustion / DoS**.

**Verstärkender Faktor:** Weder Uvicorn noch nginx begrenzen die Request-Body-Größe:
- [`nginx.conf`](../../frontend/nginx.conf) setzt kein `client_max_body_size` (Default: 1 MB — blockiert ironischerweise auch legitime Uploads > 1 MB)
- Uvicorn hat kein `--limit-request-body` konfiguriert

**Empfehlung:**
1. **nginx:** `client_max_body_size 11m;` im `location /api/` Block setzen
2. **Backend:** Chunk-basiertes Lesen mit Abbruch:
```python
chunks = []
total = 0
async for chunk in file:              # async streaming
    total += len(chunk)
    if total > MAX_FILE_SIZE:
        raise HTTPException(422, ...)  # Abbruch BEVOR alles gelesen
    chunks.append(chunk)
raw_data = b"".join(chunks)
```

---

### 🟡 F-02 — Keine Pillow Decompression-Bomb-Protection (Mittel)

**Datei:** [`files.py`](../../backend/app/routers/files.py:70)  
**Funktion:** `_process_image()`

```python
img = Image.open(io.BytesIO(data))
img.load()  # Decomprimiert vollständig in RAM
```

`Image.MAX_IMAGE_PIXELS` wird nirgendwo explizit gesetzt. Default ist ~89 Mio. Pixel = **~268 MB RAM** bei RGB. Ein speziell konstruiertes PNG (wenige KB komprimiert, Millionen Pixel unkomprimiert) kann:
- RAM-Verbrauch explodieren lassen
- CPU-Zeit für Decompression verbrauchen

**Empfehlung:**
```python
from PIL import Image
Image.MAX_IMAGE_PIXELS = 5_000_000  # ~5 Megapixel = ~15 MB RAM (ausreichend für 1600px max)
```
Am Anfang von `files.py` oder als App-weite Konfiguration setzen.

---

### 🟡 F-03 — PDF-Inhalt wird nicht validiert (Mittel)

**Datei:** [`files.py`](../../backend/app/routers/files.py:150-165)

```python
if content_type in IMAGE_MIME_TYPES:
    # Pillow-Validierung ✓
    ...
else:
    # PDF unverändert speichern ← KEINE Inhaltsvalidierung
    processed_data = raw_data
```

Die MIME-Prüfung basiert **ausschließlich auf dem Client-gesendeten `Content-Type`-Header**, der trivial fälschbar ist. Ein Angreifer könnte:
1. Eine HTML-Datei mit `Content-Type: application/pdf` hochladen
2. Beim Download wird `media_type="application/pdf"` gesetzt + `Content-Disposition: inline`
3. Manche Browser (ältere Versionen) könnten Content-Sniffing betreiben → **potenzielle Stored XSS**

**Empfehlung:**
1. Magic-Byte-Prüfung für PDFs: `data[:5] == b'%PDF-'`
2. `Content-Disposition: attachment` statt `inline` für PDFs (sicherer Default)
3. Response-Header `X-Content-Type-Options: nosniff` setzen

---

### 🟡 F-04 — Content-Disposition Header Injection via Dateiname (Mittel)

**Datei:** [`files.py`](../../backend/app/routers/files.py:227-229)

```python
headers={
    "Content-Disposition": f'inline; filename="{stored_file.original_name}"'
}
```

`original_name` stammt aus `file.filename` (Client-kontrolliert, Zeile 147). Ein Dateiname wie `photo"; filename="evil.exe` oder mit Newlines (`\r\n`) könnte:
- HTTP Response Header Injection auslösen
- Irreführende Dateinamen beim Download erzwingen

**Empfehlung:**
```python
import re
safe_name = re.sub(r'[^\w.\-]', '_', stored_file.original_name)
# Oder RFC 6266 konforme Enkodierung:
headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(stored_file.original_name)}"}
```

---

### 🟢 F-05 — Path-Traversal-Schutz fehlt als Defense-in-Depth (Gering)

**Datei:** [`storage.py`](../../backend/app/services/storage.py:37-46)

```python
def open(self, storage_path: str) -> BinaryIO:
    abs_path = self.upload_dir / storage_path  # Kein resolve()+Prefix-Check
    return abs_path.open("rb")

def delete(self, storage_path: str) -> None:
    abs_path = self.upload_dir / storage_path  # Kein resolve()+Prefix-Check
    if abs_path.exists():
        abs_path.unlink()
```

Der `storage_path` wird von `save()` sicher generiert (`{uuid}/{uuid}{ext}`), **nie** vom Benutzer kontrolliert. Trotzdem fehlt eine Validierung in `open()` und `delete()`, dass der aufgelöste Pfad innerhalb von `upload_dir` liegt.

**Aktuelles Risiko:** Gering (Pfad ist nicht user-kontrolliert). Bei einem DB-Compromise oder zukünftiger Code-Änderung wäre Path Traversal jedoch möglich.

**Empfehlung:**
```python
def _safe_path(self, storage_path: str) -> Path:
    abs_path = (self.upload_dir / storage_path).resolve()
    if not abs_path.is_relative_to(self.upload_dir.resolve()):
        raise ValueError("Path traversal detected")
    return abs_path
```

---

### 🟢 F-06 — Kein Rate-Limiting auf Upload-Endpoint (Gering)

**Datei:** [`files.py`](../../backend/app/routers/files.py:116)

Kein Rate-Limiting auf `POST /api/households/{id}/files/`. Ein authentifizierter Angreifer könnte massenhaft Dateien hochladen und den Speicher füllen.

**Risiko:** Gering (erfordert gültigen JWT + Household-Mitgliedschaft).

**Empfehlung:**
- Rate-Limit (z.B. 20 Uploads/Minute pro User)
- Oder Quota pro Household (z.B. 100 MB gesamt)

---

### ℹ️ F-07 — Kein Index auf `StoredFile.household_id` (Info)

**Datei:** [`models.py`](../../backend/app/models.py:925-926)

```python
household_id: Mapped[uuid.UUID] = mapped_column(
    ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    # Kein index=True
)
```

Kein expliziter Index auf `household_id`. Bei wachsender Datenmenge werden Queries langsamer. Kein Sicherheitsrisiko, aber Performance-Empfehlung.

---

### ℹ️ F-08 — `UPLOAD_DIR` Default ist relativer Pfad (Info)

**Datei:** [`storage.py`](../../backend/app/services/storage.py:18)

```python
self.upload_dir = Path(upload_dir or os.getenv("UPLOAD_DIR", "data/uploads"))
```

Default `data/uploads` ist relativ zum CWD. In Docker ist dies durch `UPLOAD_DIR: /app/data/uploads` und ein Named Volume korrekt gelöst. Lokal könnte der Pfad unerwartet sein.

---

## Positiv-Befunde ✅

| Prüfpunkt | Bewertung | Details |
|---|---|---|
| **Household-Scoping** | ✅ Korrekt | `verify_household_access` auf allen 3 Endpoints, zusätzlich `household_id`-Abgleich bei Download/Delete |
| **Pet-Photo Cross-Tenant** | ✅ Korrekt | PATCH prüft `stored_file.household_id != household_id` + MIME-Check (`image/*`) |
| **FILE_IN_USE Schutz** | ✅ Korrekt | Delete prüft Pet-Referenzen, gibt 422 zurück |
| **Bild-Validierung (Pillow)** | ✅ Korrekt | `Image.open()` + `img.load()` validiert echten Bildinhalt; ungültige Bilder → 422 |
| **UUID-basierte Dateinamen** | ✅ Korrekt | Dateien werden als `{uuid4}{ext}` gespeichert, Original-Name nur in DB |
| **Frontend Auth-Pattern** | ✅ Korrekt | Blob-Download via Axios mit JWT, `URL.createObjectURL()` statt `<img src="api-url">` |
| **ObjectURL Cleanup** | ✅ Korrekt | `onUnmounted()` ruft `revokeObjectURL()` auf, Cleanup auch bei Re-Render |
| **Multi-Tenant-Tests** | ✅ Vorhanden | Upload, Download, Delete Cross-Tenant + FILE_IN_USE + MIME + Size Tests |
| **Storage-Pfad nicht user-kontrolliert** | ✅ Korrekt | `save()` generiert Pfad aus UUID, `filename`-Parameter wird NICHT im Pfad verwendet |
| **Docker Volume** | ✅ Korrekt | Named Volume `uploaddata` unter `/app/data/uploads` |

---

## Zusammenfassung der Findings

| # | Schweregrad | Finding | Status |
|---|---|---|---|
| F-01 | 🔴 Hoch | RAM-Exhaustion: Datei wird komplett gelesen vor Größenprüfung | Offen |
| F-02 | 🟡 Mittel | Keine Pillow Decompression-Bomb-Protection | Offen |
| F-03 | 🟡 Mittel | PDF-Inhalt wird nicht validiert (nur Content-Type Header) | Offen |
| F-04 | 🟡 Mittel | Content-Disposition Header Injection via Dateiname | Offen |
| F-05 | 🟢 Gering | Path-Traversal Defense-in-Depth fehlt in storage.py | Offen |
| F-06 | 🟢 Gering | Kein Rate-Limiting auf Upload-Endpoint | Offen |
| F-07 | ℹ️ Info | Kein Index auf StoredFile.household_id | Offen |
| F-08 | ℹ️ Info | UPLOAD_DIR Default ist relativer Pfad | Akzeptiert |

---

## Gesamtbewertung

**Architektur und Grundstruktur sind solide.** Das Household-Scoping ist durchgängig korrekt implementiert, die Zugriffskontrolle auf allen Endpoints vorhanden, UUID-basierte Dateispeicherung verhindert Filename-Kollisionen und das Frontend-Pattern mit Blob-Download + ObjectURL ist vorbildlich.

**Vor Go-Live zu beheben:**
1. **F-01 (Hoch):** Streaming-Upload mit Chunk-basierter Größenprüfung + `client_max_body_size` in nginx
2. **F-02 (Mittel):** `Image.MAX_IMAGE_PIXELS` begrenzen
3. **F-03 (Mittel):** PDF Magic-Byte-Prüfung + `Content-Disposition: attachment` für PDFs
4. **F-04 (Mittel):** Dateiname sanitisieren im Content-Disposition Header

**Empfohlen (nicht blockierend):**
- F-05: Path-Traversal-Guard in `storage.py` als Defense-in-Depth
- F-06: Rate-Limiting / Storage-Quota
- F-07: DB-Index ergänzen

**Geschätzter Aufwand für kritische Fixes:** ~2–4 Stunden
