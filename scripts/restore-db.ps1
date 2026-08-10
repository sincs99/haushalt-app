#!/usr/bin/env pwsh
# =============================================================================
# Datenbank-Restore-Skript für haushalt-app
# Stellt einen PostgreSQL-Dump via Docker Compose wieder her.
# =============================================================================

param(
    [Parameter(Mandatory = $true, HelpMessage = "Pfad zur .dump-Datei")]
    [string]$DumpFile
)

$ErrorActionPreference = "Stop"

# --- Konfiguration ---
$DbUser      = "haushalt"
$DbName      = "haushalt"
$ServiceName = "postgres"

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

Write-Host "Dump-Datei: $($fileInfo.FullName) ($([math]::Round($fileInfo.Length / 1KB, 1)) KB)" -ForegroundColor Cyan

# --- 2. Prüfe ob Postgres-Container läuft ---
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

# --- 3. Sicherheitsabfrage ---
Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════════════╗" -ForegroundColor Red
Write-Host "║  ⚠️  WARNUNG: Dies überschreibt die aktuelle Datenbank      ║" -ForegroundColor Red
Write-Host "║     '$DbName' vollständig!                                  ║" -ForegroundColor Red
Write-Host "╚══════════════════════════════════════════════════════════════╝" -ForegroundColor Red
Write-Host ""

$antwort = Read-Host "Fortfahren? (j/n)"
if ($antwort -ne "j") {
    Write-Host "Abgebrochen. Keine Änderungen vorgenommen." -ForegroundColor Yellow
    exit 0
}

# --- 4. pg_restore ausführen ---
Write-Host ""
Write-Host "Stelle Datenbank wieder her..." -ForegroundColor Cyan

try {
    Get-Content -Path $DumpFile -AsByteStream -ReadCount 0 | docker compose exec -T $ServiceName pg_restore --clean --if-exists -U $DbUser -d $DbName
    $restoreExitCode = $LASTEXITCODE
}
catch {
    Write-Error "Fehler beim Restore: $_"
    exit 1
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

# --- 6. Empfehlung: Backend neu starten ---
Write-Host ""
Write-Host "📌 Empfehlung: Backend neu starten mit:" -ForegroundColor Cyan
Write-Host "   docker compose restart backend" -ForegroundColor White
Write-Host ""
