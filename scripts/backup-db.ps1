#!/usr/bin/env pwsh
# =============================================================================
# Backup-Skript für haushalt-app
# Erstellt einen komprimierten PostgreSQL-Dump und ein Archiv der hochgeladenen
# Dateien (Volume uploaddata) mit gleichem Zeitstempel via Docker Compose.
# =============================================================================

param(
    [Parameter(HelpMessage = "Docker-Compose-Datei (default: docker-compose.yml)")]
    [string]$ComposeFile = "docker-compose.yml",

    [Parameter(HelpMessage = "Env-Datei für Docker Compose (optional)")]
    [string]$EnvFile,

    [Parameter(HelpMessage = "Docker-Compose-Projektname (optional)")]
    [string]$ProjectName
)

$ErrorActionPreference = "Stop"

# --- Compose-Befehlsbasis zusammenbauen ---
$composeArgs = @("-f", $ComposeFile)
if ($EnvFile)     { $composeArgs += @("--env-file", $EnvFile) }
if ($ProjectName) { $composeArgs += @("--project-name", $ProjectName) }

# --- Konfiguration ---
$DbUser       = "haushalt"
$DbName       = "haushalt"
$ServiceName  = "postgres"
$UploadsService = "backend"
# Container-Pfade (Linux) — bewusst als Strings, Split-Path würde unter Windows "\" erzeugen
$UploadsParent = "/app/data"
$UploadsLeaf   = "uploads"
$BackupDir    = Join-Path $PSScriptRoot ".." "backups"
$MaxBackups   = 14

# --- 1. Prüfe ob Postgres-Container läuft ---
Write-Host "Prüfe ob Postgres-Container läuft..." -ForegroundColor Cyan

try {
    # @(...) erzwingt ein Array: bei mehreren laufenden Services liefert compose mehrere Zeilen.
    # -notmatch auf einem Array gibt die NICHT passenden Elemente zurück (z.B. "backend") und
    # wäre damit immer wahr — deshalb exakter Vergleich mit -notcontains.
    $runningServices = @(docker compose @composeArgs ps --status running --format "{{.Service}}" 2>&1 | ForEach-Object { "$_".Trim() })
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Fehler beim Abfragen des Container-Status. Läuft Docker?"
        exit 1
    }
    if ($runningServices -notcontains $ServiceName) {
        Write-Error "Der Postgres-Container '$ServiceName' läuft nicht. Starte ihn zuerst mit: docker compose @composeArgs up -d $ServiceName"
        exit 1
    }
}
catch {
    Write-Error "Fehler beim Prüfen des Containers: $_"
    exit 1
}

Write-Host "  ✓ Postgres-Container läuft." -ForegroundColor Green

# Uploads werden über den Backend-Container gesichert (dort ist das Volume gemountet)
if ($runningServices -notcontains $UploadsService) {
    Write-Error "Der Backend-Container '$UploadsService' läuft nicht. Ohne ihn können die Uploads nicht gesichert werden."
    exit 1
}
Write-Host "  ✓ Backend-Container läuft." -ForegroundColor Green

# --- 2. Backup-Verzeichnis erstellen falls nötig ---
if (-not (Test-Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
    Write-Host "  ✓ Verzeichnis '$BackupDir' erstellt." -ForegroundColor Green
}

# --- 3. Dateiname generieren ---
$timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm"
$dumpFile  = Join-Path $BackupDir "casa-backup-${timestamp}.dump"
$uploadsFile = Join-Path $BackupDir "casa-uploads-${timestamp}.tar.gz"

# --- 4. pg_dump ausführen (byte-sicher via docker compose cp) ---
Write-Host "Erstelle Backup: $dumpFile ..." -ForegroundColor Cyan

# Dump IM Container erstellen:
docker compose @composeArgs exec -T $ServiceName pg_dump -U $DbUser -d $DbName -F c -f /tmp/casa-backup.dump
if ($LASTEXITCODE -ne 0) {
    # Temp-Datei im Container aufräumen
    docker compose @composeArgs exec -T $ServiceName rm -f /tmp/casa-backup.dump
    Write-Error "pg_dump ist mit Exit-Code $LASTEXITCODE fehlgeschlagen."
    exit 1
}

# Byte-sicher aus dem Container kopieren:
docker compose @composeArgs cp "${ServiceName}:/tmp/casa-backup.dump" $dumpFile
if ($LASTEXITCODE -ne 0) {
    docker compose @composeArgs exec -T $ServiceName rm -f /tmp/casa-backup.dump
    if (Test-Path $dumpFile) { Remove-Item $dumpFile -Force }
    Write-Error "docker compose cp fehlgeschlagen."
    exit 1
}

# Temp-Datei im Container entfernen:
docker compose @composeArgs exec -T $ServiceName rm -f /tmp/casa-backup.dump

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

# --- 6. Uploads sichern (Ablage-Dokumente, Tierfotos) ---
Write-Host "Sichere Uploads: $uploadsFile ..." -ForegroundColor Cyan

docker compose @composeArgs exec -T $UploadsService tar -czf /tmp/casa-uploads.tar.gz -C $UploadsParent $UploadsLeaf
if ($LASTEXITCODE -ne 0) {
    docker compose @composeArgs exec -T $UploadsService rm -f /tmp/casa-uploads.tar.gz
    Write-Error "Archivieren der Uploads ist mit Exit-Code $LASTEXITCODE fehlgeschlagen. Der DB-Dump liegt vor, ist aber ohne passende Uploads unvollständig."
    exit 1
}

docker compose @composeArgs cp "${UploadsService}:/tmp/casa-uploads.tar.gz" $uploadsFile
$cpExitCode = $LASTEXITCODE
docker compose @composeArgs exec -T $UploadsService rm -f /tmp/casa-uploads.tar.gz
if ($cpExitCode -ne 0 -or -not (Test-Path $uploadsFile)) {
    if (Test-Path $uploadsFile) { Remove-Item $uploadsFile -Force }
    Write-Error "docker compose cp der Uploads fehlgeschlagen."
    exit 1
}

# Gzip-Magic-Bytes prüfen (1F 8B)
$gzMagic = [System.IO.File]::ReadAllBytes($uploadsFile)[0..1]
if ($gzMagic[0] -ne 0x1F -or $gzMagic[1] -ne 0x8B) {
    Remove-Item $uploadsFile -Force
    Write-Error "Uploads-Archiv ist kein gültiges gzip-Archiv."
    exit 1
}
$uploadsSize = (Get-Item $uploadsFile).Length

# --- 7. Rotation: Nur die neuesten N Backups behalten (Dumps und Upload-Archive) ---
$allDumps = Get-ChildItem -Path $BackupDir -Filter "*.dump" | Sort-Object LastWriteTime -Descending
foreach ($filter in @("*.dump", "casa-uploads-*.tar.gz")) {
    $allFiles = Get-ChildItem -Path $BackupDir -Filter $filter | Sort-Object LastWriteTime -Descending
    if ($allFiles.Count -gt $MaxBackups) {
        $toDelete = $allFiles | Select-Object -Skip $MaxBackups
        foreach ($old in $toDelete) {
            Remove-Item $old.FullName -Force
            Write-Host "  🗑 Altes Backup gelöscht: $($old.Name)" -ForegroundColor DarkYellow
        }
    }
}

# --- 8. Erfolgsmeldung ---
$sizeKB = [math]::Round($fileSize / 1024, 1)
$sizeMB = [math]::Round($fileSize / 1MB, 2)
$sizeDisplay = if ($sizeMB -ge 1) { "${sizeMB} MB" } else { "${sizeKB} KB" }
$uploadsSizeMB = [math]::Round($uploadsSize / 1MB, 2)

Write-Host ""
Write-Host "═══════════════════════════════════════════" -ForegroundColor Green
Write-Host "  ✅ Backup erfolgreich erstellt!" -ForegroundColor Green
Write-Host "  📁 Datei:  $dumpFile" -ForegroundColor Green
Write-Host "  📦 Größe:  $sizeDisplay" -ForegroundColor Green
Write-Host "  🖼 Uploads: $uploadsFile ($uploadsSizeMB MB)" -ForegroundColor Green
Write-Host "  🔢 Backups vorhanden: $([math]::Min($allDumps.Count, $MaxBackups)) / $MaxBackups" -ForegroundColor Green
Write-Host "═══════════════════════════════════════════" -ForegroundColor Green
