# haushalt-app

## Datensicherung

### Backup erstellen

```powershell
.\scripts\backup-db.ps1
```

Erstellt einen komprimierten Datenbank-Dump unter `backups/casa-backup-YYYY-MM-DD_HH-mm.dump`.  
Es werden automatisch maximal **14 Backups** vorgehalten; ältere werden gelöscht.

### Backup wiederherstellen

```powershell
.\scripts\restore-db.ps1 -DumpFile .\backups\casa-backup-2025-01-15_14-30.dump
```

Das Skript fragt vor dem Überschreiben der Datenbank nach einer Bestätigung.  
Nach dem Restore empfiehlt es sich, das Backend neu zu starten:

```powershell
docker compose restart backend
```

### ⚠️ Wichtige Warnungen

**`docker compose down -v` und `docker volume rm` LÖSCHEN ALLE DATEN unwiderruflich!**  
**Verwende NIEMALS `-v` bei `docker compose down`, es sei denn, du hast ein aktuelles Backup.**

### Empfohlene Backup-Regeln

1. **Vor jedem `alembic upgrade`** ein Backup erstellen
2. **Wöchentlich** manuell ein Backup erstellen
3. Backup-Datei zusätzlich in einen **Cloud-Speicher** (z.B. OneDrive, Google Drive) kopieren
4. **Nach der Ersteinrichtung** einmal den kompletten Zyklus testen: Backup erstellen → Restore ausführen → App prüfen
