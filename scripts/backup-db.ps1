#!/usr/bin/env pwsh
# =============================================================================
# Datenbank-Backup-Skript für haushalt-app
# Erstellt einen komprimierten PostgreSQL-Dump via Docker Compose.
# =============================================================================

$ErrorActionPreference = "Stop"

# --- Konfiguration ---
$DbUser       = "haushalt"
$DbName       = "haushalt"
$ServiceName  = "postgres"
$BackupDir    = Join-Path $PSScriptRoot ".." "backups"
$MaxBackups   = 14

# --- 1. Prüfe ob Postgres-Container läuft ---
Write-Host "Prüfe ob Postgres-Container läuft..." -ForegroundColor Cyan

try {
    $containerStatus = docker compose ps --status running --format "{{.Service}}" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Fehler beim Abfragen des Container-Status. Läuft Docker?"
        exit 1
    }
    if ($containerStatus -notmatch $ServiceName) {
        Write-Error "Der Postgres-Container '$ServiceName' läuft nicht. Starte ihn zuerst mit: docker compose up -d $ServiceName"
        exit 1
    }
}
catch {
    Write-Error "Fehler beim Prüfen des Containers: $_"
    exit 1
}

Write-Host "  ✓ Postgres-Container läuft." -ForegroundColor Green

# --- 2. Backup-Verzeichnis erstellen falls nötig ---
if (-not (Test-Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
    Write-Host "  ✓ Verzeichnis '$BackupDir' erstellt." -ForegroundColor Green
}

# --- 3. Dateiname generieren ---
$timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm"
$dumpFile  = Join-Path $BackupDir "casa-backup-${timestamp}.dump"

# --- 4. pg_dump ausführen (byte-sicher via docker compose cp) ---
Write-Host "Erstelle Backup: $dumpFile ..." -ForegroundColor Cyan

# Dump IM Container erstellen:
docker compose exec -T $ServiceName pg_dump -U $DbUser -d $DbName -F c -f /tmp/casa-backup.dump
if ($LASTEXITCODE -ne 0) {
    # Temp-Datei im Container aufräumen
    docker compose exec -T $ServiceName rm -f /tmp/casa-backup.dump
    Write-Error "pg_dump ist mit Exit-Code $LASTEXITCODE fehlgeschlagen."
    exit 1
}

# Byte-sicher aus dem Container kopieren:
docker compose cp "${ServiceName}:/tmp/casa-backup.dump" $dumpFile
if ($LASTEXITCODE -ne 0) {
    docker compose exec -T $ServiceName rm -f /tmp/casa-backup.dump
    if (Test-Path $dumpFile) { Remove-Item $dumpFile -Force }
    Write-Error "docker compose cp fehlgeschlagen."
    exit 1
}

# Temp-Datei im Container entfernen:
docker compose exec -T $ServiceName rm -f /tmp/casa-backup.dump

# --- 5. Plausibilitätsprüfung ---
if (-not (Test-Path $dumpFile)) {
    Write-Error "Dump-Datei wurde nicht erstellt."
    exit 1
}

$fileSize = (Get-Item $dumpFile).Length
if ($fileSize -lt 1024) {
    Remove-Item $dumpFile -Force
    Write-Error "Dump-Datei ist zu klein ($fileSize Bytes). Backup fehlgeschlagen."
    exit 1
}

# Magic-Byte-Check: Custom-Format beginnt mit PGDMP
$magicBytes = [System.IO.File]::ReadAllBytes($dumpFile)[0..4]
$magic = [System.Text.Encoding]::ASCII.GetString($magicBytes)
if ($magic -ne "PGDMP") {
    Remove-Item $dumpFile -Force
    Write-Error "Dump-Datei hat ungültige Magic Bytes ('$magic' statt 'PGDMP'). Dump ist korrupt."
    exit 1
}

# --- 6. Rotation: Nur die neuesten N Backups behalten ---
$allDumps = Get-ChildItem -Path $BackupDir -Filter "*.dump" | Sort-Object LastWriteTime -Descending
if ($allDumps.Count -gt $MaxBackups) {
    $toDelete = $allDumps | Select-Object -Skip $MaxBackups
    foreach ($old in $toDelete) {
        Remove-Item $old.FullName -Force
        Write-Host "  🗑 Altes Backup gelöscht: $($old.Name)" -ForegroundColor DarkYellow
    }
}

# --- 7. Erfolgsmeldung ---
$sizeKB = [math]::Round($fileSize / 1024, 1)
$sizeMB = [math]::Round($fileSize / 1MB, 2)
$sizeDisplay = if ($sizeMB -ge 1) { "${sizeMB} MB" } else { "${sizeKB} KB" }

Write-Host ""
Write-Host "═══════════════════════════════════════════" -ForegroundColor Green
Write-Host "  ✅ Backup erfolgreich erstellt!" -ForegroundColor Green
Write-Host "  📁 Datei:  $dumpFile" -ForegroundColor Green
Write-Host "  📦 Größe:  $sizeDisplay" -ForegroundColor Green
Write-Host "  🔢 Backups vorhanden: $([math]::Min($allDumps.Count, $MaxBackups)) / $MaxBackups" -ForegroundColor Green
Write-Host "═══════════════════════════════════════════" -ForegroundColor Green
