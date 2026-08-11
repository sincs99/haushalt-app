# Epic 10 — Kritische Bugfixes (Backup, StoredFile-Leichen, Pfadprüfung)

## Status: ✅ Abgeschlossen

---

## 10.1 KRITISCH: Backup-Skripte erzeugen korrupte Dumps unter Windows PowerShell

### Problem
- `scripts/backup-db.ps1` Zeile 51: `> $dumpFile` leitet Binärdaten durch PowerShell-Pipeline → Encoding-Zerstörung
- `scripts/restore-db.ps1` Zeile 73: `Get-Content -AsByteStream` existiert erst ab PS 6, bricht auf Windows PS 5.1 ab

### Fix
**backup-db.ps1** — Umstellen auf `docker compose cp`:
1. `docker compose exec -T $ServiceName pg_dump -U $DbUser -d $DbName -F c -f /tmp/casa-backup.dump`
2. `docker compose cp "${ServiceName}:/tmp/casa-backup.dump" $dumpFile`
3. `docker compose exec -T $ServiceName rm -f /tmp/casa-backup.dump`
4. Plausibilitätsprüfung: Datei existiert und > 1 KB, sonst Fehler + Datei löschen
5. Magic-Byte-Check: erste 5 Bytes müssen `PGDMP` sein, sonst Abbruch
6. Rotationslogik unverändert lassen

**restore-db.ps1** — Umstellen auf `docker compose cp`:
1. Vor Kopieren: Datei muss existieren und mit `PGDMP` beginnen, sonst Abbruch
2. `docker compose cp $DumpFile "${ServiceName}:/tmp/casa-restore.dump"`
3. `docker compose exec -T $ServiceName pg_restore --clean --if-exists -U $DbUser -d $DbName /tmp/casa-restore.dump`
4. `docker compose exec -T $ServiceName rm -f /tmp/casa-restore.dump`
5. Sicherheitsabfrage beibehalten

**README.md** Abschnitt „Datensicherung":
- Satz ergänzen: „Nach der Ersteinrichtung einmal den kompletten Zyklus testen: Backup erstellen → Restore ausführen → App prüfen."

### Dateien
- `scripts/backup-db.ps1`
- `scripts/restore-db.ps1`
- `README.md`

---

## 10.2 Verwaister StoredFile-Datensatz beim Pet-Löschen

### Problem
- `backend/app/routers/pets.py` Zeile 497–508: Beim Pet-Löschen wird nur die physische Datei entfernt, der `StoredFile`-DB-Datensatz bleibt als Leiche
- `backend/app/routers/files.py` Zeile 291–296: Löscht erst Datei, dann DB — bei Commit-Fehler bleibt Datensatz-Leiche

### Fix
**pets.py** `delete_pet()`:
1. `db.delete(stored_file)` vor dem Commit hinzufügen
2. Reihenfolge: erst Pet + StoredFile-Zeile löschen & committen, danach Best-effort physische Datei entfernen

**files.py** `delete_file()`:
1. Reihenfolge umdrehen: erst DB-Commit, dann physisches Löschen
2. Physisches Löschen als Best-effort (try/except)

### Dateien
- `backend/app/routers/pets.py`
- `backend/app/routers/files.py`

---

## 10.3 Pfadprüfung härten

### Problem
- `backend/app/services/storage.py` Zeile 24: `str.startswith` lässt Geschwister-Verzeichnisse wie `data/uploads-x` durch

### Fix
- Ersetze `if not str(abs_path).startswith(str(upload_root)):` durch `if not abs_path.is_relative_to(upload_root):`
- Kein weiterer Umbau

### Dateien
- `backend/app/services/storage.py`

---

## Abnahme-Kriterien
- [x] pytest grün — **317 passed, 0 failed** (bestehende Mocks kompatibel)
- [ ] Manuell auf Windows: `.\scripts\backup-db.ps1` → Dump beginnt mit PGDMP
- [ ] `.\scripts\restore-db.ps1` mit Dump → App läuft, Daten vorhanden
