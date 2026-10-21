#!/usr/bin/env pwsh
# =============================================================================
# Backup-Skript für haushalt-app
# Erstellt einen komprimierten PostgreSQL-Dump und ein Archiv der hochgeladenen
# Dateien (Volume uploaddata) mit gleichem Zeitstempel via Docker Compose.
#
# Konsistenz von Dump und Uploads (CASA-57):
#   - Standard (laufender Betrieb): erst der Dump (Snapshot), DANACH die Uploads.
#     Das Archiv enthält damit jede Datei, auf die der Dump zeigt — ausser sie wurde
#     zwischen Dump und Archiv gelöscht. Zusätzliche, neuere Dateien sind harmlos
#     (verwaiste Uploads räumt das Backend auf).
#   - -Consistent: Backend wird für die Dauer des Backups gestoppt (kurze Downtime,
#     z. B. nachts) — Dump und Uploads sind dann exakt ein Paar.
#
# Aufbewahrung: -Keep N (default 14) pro Typ. Off-Host-Kopie: -CopyTo <Pfad>
# (zweites Laufwerk, NAS-Freigabe, synchronisierter Cloud-Ordner).
# =============================================================================

param(
    [Parameter(HelpMessage = "Docker-Compose-Datei (default: docker-compose.yml)")]
    [string]$ComposeFile = "docker-compose.yml",

    [Parameter(HelpMessage = "Env-Datei für Docker Compose (optional)")]
    [string]$EnvFile,

    [Parameter(HelpMessage = "Docker-Compose-Projektname (optional)")]
    [string]$ProjectName,

    [Parameter(HelpMessage = "Backend während des Backups stoppen (exakt konsistentes Paar)")]
    [switch]$Consistent,

    [Parameter(HelpMessage = "Anzahl aufbewahrter Backups je Typ (default: 14)")]
    [ValidateRange(1, 1000)]
    [int]$Keep = 14,

    [Parameter(HelpMessage = "Zusätzlich hierhin kopieren (Off-Host: anderes Laufwerk, NAS, Cloud-Ordner)")]
    [string]$CopyTo
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
$Helper       = "casa-backup-helper-$(Get-Date -Format 'yyyyMMddHHmmss')"

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
if (-not $Consistent -and $runningServices -notcontains $UploadsService) {
    Write-Error "Der Backend-Container '$UploadsService' läuft nicht. Ohne ihn können die Uploads nicht gesichert werden (oder -Consistent verwenden)."
    exit 1
}

# --- 2. Backup-Verzeichnis erstellen falls nötig ---
if (-not (Test-Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
    Write-Host "  ✓ Verzeichnis '$BackupDir' erstellt." -ForegroundColor Green
}

# --- 3. Dateiname generieren ---
$timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm"
$dumpFile  = Join-Path $BackupDir "casa-backup-${timestamp}.dump"
$uploadsFile = Join-Path $BackupDir "casa-uploads-${timestamp}.tar.gz"

$backendStopped = $false
try {
    if ($Consistent) {
        Write-Host "Stoppe Backend für ein konsistentes Paar (Dump + Uploads) ..." -ForegroundColor Cyan
        docker compose @composeArgs stop $UploadsService
        if ($LASTEXITCODE -ne 0) { throw "Backend konnte nicht gestoppt werden." }
        $backendStopped = $true
    }

    # --- 4. pg_dump ausführen (byte-sicher via docker compose cp) ---
    Write-Host "Erstelle Backup: $dumpFile ..." -ForegroundColor Cyan

    docker compose @composeArgs exec -T $ServiceName pg_dump -U $DbUser -d $DbName -F c -f /tmp/casa-backup.dump
    if ($LASTEXITCODE -ne 0) {
        docker compose @composeArgs exec -T $ServiceName rm -f /tmp/casa-backup.dump
        throw "pg_dump ist mit Exit-Code $LASTEXITCODE fehlgeschlagen."
    }
    docker compose @composeArgs cp "${ServiceName}:/tmp/casa-backup.dump" $dumpFile
    $cpExitCode = $LASTEXITCODE
    docker compose @composeArgs exec -T $ServiceName rm -f /tmp/casa-backup.dump
    if ($cpExitCode -ne 0) {
        if (Test-Path $dumpFile) { Remove-Item $dumpFile -Force }
        throw "docker compose cp fehlgeschlagen."
    }

    # --- 5. Plausibilitätsprüfung ---
    if (-not (Test-Path $dumpFile)) { throw "Dump-Datei wurde nicht erstellt." }
    $fileSize = (Get-Item $dumpFile).Length
    if ($fileSize -lt 1024) {
        Remove-Item $dumpFile -Force
        throw "Dump-Datei ist zu klein ($fileSize Bytes). Backup fehlgeschlagen."
    }
    # Magic-Byte-Check: Custom-Format beginnt mit PGDMP
    $magic = [System.Text.Encoding]::ASCII.GetString([System.IO.File]::ReadAllBytes($dumpFile)[0..4])
    if ($magic -ne "PGDMP") {
        Remove-Item $dumpFile -Force
        throw "Dump-Datei hat ungültige Magic Bytes ('$magic' statt 'PGDMP'). Dump ist korrupt."
    }

    # --- 6. Uploads sichern (NACH dem Dump, siehe Kopf) ---
    Write-Host "Sichere Uploads: $uploadsFile ..." -ForegroundColor Cyan
    $cpExitCode = 1
    if ($Consistent) {
        # Backend ist gestoppt → Hilfscontainer mit demselben Upload-Volume
        docker compose @composeArgs run -d --rm --no-deps --name $Helper $UploadsService sleep 600 | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Hilfscontainer für die Uploads konnte nicht gestartet werden." }
        docker exec $Helper tar -czf /tmp/casa-uploads.tar.gz -C $UploadsParent $UploadsLeaf
        $tarExitCode = $LASTEXITCODE
        if ($tarExitCode -eq 0) {
            docker cp "${Helper}:/tmp/casa-uploads.tar.gz" $uploadsFile
            $cpExitCode = $LASTEXITCODE
        }
        docker rm -f $Helper | Out-Null
    }
    else {
        docker compose @composeArgs exec -T $UploadsService tar -czf /tmp/casa-uploads.tar.gz -C $UploadsParent $UploadsLeaf
        $tarExitCode = $LASTEXITCODE
        if ($tarExitCode -eq 0) {
            docker compose @composeArgs cp "${UploadsService}:/tmp/casa-uploads.tar.gz" $uploadsFile
            $cpExitCode = $LASTEXITCODE
        }
        docker compose @composeArgs exec -T $UploadsService rm -f /tmp/casa-uploads.tar.gz
    }
    if ($tarExitCode -ne 0) {
        throw "Archivieren der Uploads ist mit Exit-Code $tarExitCode fehlgeschlagen. Der DB-Dump liegt vor, ist aber ohne passende Uploads unvollständig."
    }
    if ($cpExitCode -ne 0 -or -not (Test-Path $uploadsFile)) {
        if (Test-Path $uploadsFile) { Remove-Item $uploadsFile -Force }
        throw "Kopieren des Uploads-Archivs fehlgeschlagen."
    }

    # Gzip-Magic-Bytes prüfen (1F 8B)
    $gzMagic = [System.IO.File]::ReadAllBytes($uploadsFile)[0..1]
    if ($gzMagic[0] -ne 0x1F -or $gzMagic[1] -ne 0x8B) {
        Remove-Item $uploadsFile -Force
        throw "Uploads-Archiv ist kein gültiges gzip-Archiv."
    }
    $uploadsSize = (Get-Item $uploadsFile).Length
}
catch {
    docker rm -f $Helper 2>$null | Out-Null
    if ($backendStopped) {
        docker compose @composeArgs start $UploadsService
    }
    Write-Error "Backup fehlgeschlagen: $_"
    exit 1
}

if ($backendStopped) {
    Write-Host "Starte Backend wieder ..." -ForegroundColor Cyan
    docker compose @composeArgs start $UploadsService
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Backup erstellt, aber das Backend konnte nicht gestartet werden: docker compose $($composeArgs -join ' ') start $UploadsService"
        exit 1
    }
}

# --- 7. Rotation: Nur die neuesten N Backups behalten (Dumps und Upload-Archive) ---
foreach ($filter in @("casa-backup-*.dump", "casa-uploads-*.tar.gz")) {
    $allFiles = @(Get-ChildItem -Path $BackupDir -Filter $filter | Sort-Object LastWriteTime -Descending)
    if ($allFiles.Count -gt $Keep) {
        foreach ($old in ($allFiles | Select-Object -Skip $Keep)) {
            Remove-Item $old.FullName -Force
            Write-Host "  🗑 Altes Backup gelöscht: $($old.Name)" -ForegroundColor DarkYellow
        }
    }
}
$dumpCount = @(Get-ChildItem -Path $BackupDir -Filter "casa-backup-*.dump").Count

# --- 8. Off-Host-Kopie (optional) ---
if ($CopyTo) {
    try {
        if (-not (Test-Path $CopyTo)) { New-Item -ItemType Directory -Path $CopyTo -Force | Out-Null }
        Copy-Item $dumpFile, $uploadsFile -Destination $CopyTo -Force
        # Gleiche Aufbewahrung am Ziel
        foreach ($filter in @("casa-backup-*.dump", "casa-uploads-*.tar.gz")) {
            @(Get-ChildItem -Path $CopyTo -Filter $filter | Sort-Object LastWriteTime -Descending) |
                Select-Object -Skip $Keep | ForEach-Object { Remove-Item $_.FullName -Force }
        }
        Write-Host "  ✓ Kopie abgelegt in: $CopyTo" -ForegroundColor Green
    }
    catch {
        Write-Error "Backup lokal erstellt, aber die Kopie nach '$CopyTo' ist fehlgeschlagen: $_"
        exit 1
    }
}

# --- 9. Erfolgsmeldung ---
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
Write-Host "  🔢 Backups vorhanden: $dumpCount / $Keep" -ForegroundColor Green
if (-not $CopyTo) {
    Write-Host "  ⚠️  Keine Off-Host-Kopie (-CopyTo) — ein Backup auf demselben Host schützt nicht vor Plattenausfall." -ForegroundColor Yellow
}
Write-Host "═══════════════════════════════════════════" -ForegroundColor Green
