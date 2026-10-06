#!/usr/bin/env pwsh
# =============================================================================
# Restore-Skript für haushalt-app
# Stellt einen PostgreSQL-Dump via Docker Compose wieder her — und, falls
# vorhanden, das zugehörige Uploads-Archiv (casa-uploads-<Zeitstempel>.tar.gz).
# =============================================================================

param(
    [Parameter(Mandatory = $true, Position = 0, HelpMessage = "Pfad zur .dump-Datei")]
    [string]$DumpFile,

    [Parameter(HelpMessage = "Uploads-Archiv (default: casa-uploads-<Zeitstempel>.tar.gz neben dem Dump)")]
    [string]$UploadsFile,

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
$DbUser      = "haushalt"
$DbName      = "haushalt"
$ServiceName = "postgres"
$UploadsService = "backend"
# Container-Pfade (Linux) — bewusst als Strings, Split-Path würde unter Windows "\" erzeugen
$UploadsParent = "/app/data"
$UploadsDir    = "/app/data/uploads"

# --- 1. Prüfe ob Dump-Datei existiert ---
if (-not (Test-Path $DumpFile)) {
    Write-Error "Die Dump-Datei '$DumpFile' wurde nicht gefunden."
    exit 1
}

$fileInfo = Get-Item $DumpFile
if ($fileInfo.Length -eq 0) {
    Write-Error "Die Dump-Datei '$DumpFile' ist leer (0 Bytes)."
    exit 1
}

# Magic-Byte-Check
$magicBytes = [System.IO.File]::ReadAllBytes($DumpFile)[0..4]
$magic = [System.Text.Encoding]::ASCII.GetString($magicBytes)
if ($magic -ne "PGDMP") {
    Write-Error "Die Datei '$DumpFile' ist kein gültiger PostgreSQL Custom-Format-Dump (Magic Bytes: '$magic' statt 'PGDMP')."
    exit 1
}

Write-Host "Dump-Datei: $($fileInfo.FullName) ($([math]::Round($fileInfo.Length / 1KB, 1)) KB)" -ForegroundColor Cyan

# Zugehöriges Uploads-Archiv (gleicher Zeitstempel wie der Dump)
if (-not $UploadsFile) {
    $candidate = Join-Path $fileInfo.DirectoryName ($fileInfo.Name -replace '^casa-backup-', 'casa-uploads-' -replace '\.dump$', '.tar.gz')
    if ($candidate -ne $fileInfo.FullName -and (Test-Path $candidate)) { $UploadsFile = $candidate }
}
if ($UploadsFile) {
    if (-not (Test-Path $UploadsFile)) {
        Write-Error "Das Uploads-Archiv '$UploadsFile' wurde nicht gefunden."
        exit 1
    }
    Write-Host "Uploads-Archiv: $((Get-Item $UploadsFile).FullName)" -ForegroundColor Cyan
}
else {
    Write-Host "⚠️  Kein Uploads-Archiv gefunden — hochgeladene Dateien bleiben unverändert." -ForegroundColor Yellow
    Write-Host "   Dokumente/Fotos aus dem Dump können danach auf fehlende Dateien zeigen." -ForegroundColor Yellow
}

# --- 2. Prüfe ob Postgres-Container läuft ---
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

if ($UploadsFile -and $runningServices -notcontains $UploadsService) {
    Write-Error "Der Backend-Container '$UploadsService' läuft nicht. Er wird für das Wiederherstellen der Uploads benötigt."
    exit 1
}

# --- 3. Sicherheitsabfrage ---
Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════════════╗" -ForegroundColor Red
Write-Host "║  ⚠️  WARNUNG: Dies überschreibt die aktuelle Datenbank      ║" -ForegroundColor Red
Write-Host "║     '$DbName' vollständig!                                  ║" -ForegroundColor Red
if ($UploadsFile) {
Write-Host "║     Alle hochgeladenen Dateien werden ebenfalls ersetzt!    ║" -ForegroundColor Red
}
Write-Host "╚══════════════════════════════════════════════════════════════╝" -ForegroundColor Red
Write-Host ""

$antwort = Read-Host "Fortfahren? (j/n)"
if ($antwort -ne "j") {
    Write-Host "Abgebrochen. Keine Änderungen vorgenommen." -ForegroundColor Yellow
    exit 0
}

# --- 4. Dump in Container kopieren und pg_restore ausführen ---
Write-Host ""
Write-Host "Stelle Datenbank wieder her..." -ForegroundColor Cyan

try {
    # Dump byte-sicher in den Container kopieren
    docker compose @composeArgs cp $DumpFile "${ServiceName}:/tmp/casa-restore.dump"
    if ($LASTEXITCODE -ne 0) {
        Write-Error "docker compose cp fehlgeschlagen."
        exit 1
    }

    # Restore aus Datei im Container (kein stdin-Piping)
    docker compose @composeArgs exec -T $ServiceName pg_restore --clean --if-exists -U $DbUser -d $DbName /tmp/casa-restore.dump
    $restoreExitCode = $LASTEXITCODE
}
catch {
    # Aufräumen bei Fehler
    docker compose @composeArgs exec -T $ServiceName rm -f /tmp/casa-restore.dump 2>$null
    Write-Error "Fehler beim Restore: $_"
    exit 1
}
finally {
    # Temp-Datei im Container immer aufräumen
    docker compose @composeArgs exec -T $ServiceName rm -f /tmp/casa-restore.dump 2>$null
}

# --- 5. Ergebnis prüfen ---
Write-Host ""
if ($restoreExitCode -ne 0) {
    # pg_restore gibt manchmal Warnungen mit Exit-Code != 0 aus,
    # z.B. wenn Objekte nicht existieren die gelöscht werden sollen.
    # --clean --if-exists minimiert das, aber es kann trotzdem vorkommen.
    Write-Host "⚠️  pg_restore beendet mit Exit-Code $restoreExitCode." -ForegroundColor Yellow
    Write-Host "   Dies kann durch Warnungen verursacht werden (z.B. nicht existierende Objekte)." -ForegroundColor Yellow
    Write-Host "   Prüfe die Ausgabe oben auf tatsächliche Fehler." -ForegroundColor Yellow
}
else {
    Write-Host "═══════════════════════════════════════════" -ForegroundColor Green
    Write-Host "  ✅ Datenbank erfolgreich wiederhergestellt!" -ForegroundColor Green
    Write-Host "═══════════════════════════════════════════" -ForegroundColor Green
}

# --- 6. Uploads wiederherstellen ---
if ($UploadsFile) {
    Write-Host ""
    Write-Host "Stelle Uploads wieder her..." -ForegroundColor Cyan
    docker compose @composeArgs cp $UploadsFile "${UploadsService}:/tmp/casa-uploads.tar.gz"
    if ($LASTEXITCODE -ne 0) {
        Write-Error "docker compose cp des Uploads-Archivs fehlgeschlagen."
        exit 1
    }
    # Bestehende Dateien ersetzen, damit keine Dateien ohne DB-Eintrag zurückbleiben
    docker compose @composeArgs exec -T $UploadsService sh -c "find '$UploadsDir' -mindepth 1 -delete && tar -xzf /tmp/casa-uploads.tar.gz -C '$UploadsParent'"
    $uploadsExitCode = $LASTEXITCODE
    docker compose @composeArgs exec -T $UploadsService rm -f /tmp/casa-uploads.tar.gz 2>$null
    if ($uploadsExitCode -ne 0) {
        Write-Error "Wiederherstellen der Uploads ist mit Exit-Code $uploadsExitCode fehlgeschlagen."
        exit 1
    }
    Write-Host "  ✓ Uploads wiederhergestellt." -ForegroundColor Green
}

# --- 7. Empfehlung: Backend neu starten ---
$restartCmd = "docker compose"
$restartCmd += " -f $ComposeFile"
if ($EnvFile)     { $restartCmd += " --env-file $EnvFile" }
if ($ProjectName) { $restartCmd += " --project-name $ProjectName" }
$restartCmd += " restart backend"

Write-Host ""
Write-Host "📌 Empfehlung: Backend neu starten mit:" -ForegroundColor Cyan
Write-Host "   $restartCmd" -ForegroundColor White
Write-Host ""
