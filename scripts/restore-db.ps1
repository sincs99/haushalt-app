#!/usr/bin/env pwsh
# =============================================================================
# Restore-Skript für haushalt-app (Disaster-Recovery, CASA-07 / PD-D2)
#
# Ablauf:
#   1. Dump prüfen (PGDMP-Magic), Sicherheitsabfrage
#   2. Backend stoppen — keine Schreibzugriffe während des Restores
#   3. Dump in eine FRISCHE Datenbank haushalt_restore einspielen:
#        pg_restore --single-transaction --exit-on-error --no-owner
#      Jeder Fehler bricht ab; die Produktions-DB ist bis hier unverändert.
#   4. Tausch: haushalt → haushalt_before_restore_<Zeitstempel>, haushalt_restore → haushalt
#   5. Uploads-Archiv (gleicher Zeitstempel) per Hilfscontainer einspielen
#   6. Backend starten (führt `alembic upgrade head` aus) und auf /api/health warten
#
# Nach einem Fehler vor dem DB-Tausch kann das bisher laufende Backend starten;
# nach dem Tausch bleibt es bei Fehlern zur sicheren Wiederaufnahme angehalten.
# Bash-Pendant: scripts/restore-db.sh (in CI per
# scripts/restore-drill.sh getestet).
#
# Migrationen sind forward-only: Ein älterer Dump gehört zum Code-Stand, mit dem er
# erstellt wurde (docs/deployment.md §4).
# =============================================================================

param(
    [Parameter(Mandatory = $true, Position = 0, HelpMessage = "Pfad zur .dump-Datei")]
    [string]$DumpFile,

    [Parameter(HelpMessage = "Uploads-Archiv (default: casa-uploads-<Zeitstempel>.tar.gz neben dem Dump)")]
    [string]$UploadsFile,

    [Parameter(HelpMessage = "Uploads nicht anfassen")]
    [switch]$NoUploads,

    [Parameter(HelpMessage = "Docker-Compose-Datei (default: docker-compose.yml)")]
    [string]$ComposeFile = "docker-compose.yml",

    [Parameter(HelpMessage = "Env-Datei für Docker Compose (optional)")]
    [string]$EnvFile,

    [Parameter(HelpMessage = "Docker-Compose-Projektname (optional)")]
    [string]$ProjectName,

    [Parameter(HelpMessage = "Keine Sicherheitsabfrage")]
    [switch]$Yes,

    [Parameter(HelpMessage = "Vorherige DB nach erfolgreichem Tausch löschen (statt umbenannt behalten)")]
    [switch]$DropOld
)

$ErrorActionPreference = "Stop"

# --- Compose-Befehlsbasis zusammenbauen ---
$composeArgs = @("-f", $ComposeFile)
if ($EnvFile)     { $composeArgs += @("--env-file", $EnvFile) }
if ($ProjectName) { $composeArgs += @("--project-name", $ProjectName) }

# --- Konfiguration ---
$DbUser         = "haushalt"
$DbName         = "haushalt"
$ServiceName    = "postgres"
$UploadsService = "backend"
$stageId        = [Guid]::NewGuid().ToString("N")
$RestoreDb      = "${DbName}_restore_${stageId}"
$OldDb          = "${DbName}_before_${stageId}"
$RemoteDump     = "/tmp/casa-restore-${stageId}.dump"
$Helper         = "casa-restore-helper-${stageId}"

function Invoke-Sql([string]$Database, [string]$Sql) {
    # -At: nur Werte, ON_ERROR_STOP: jeder SQL-Fehler → Exit-Code != 0
    $out = docker compose @composeArgs exec -T $ServiceName psql -U $DbUser -d $Database -X -q -v ON_ERROR_STOP=1 -At -c $Sql
    if ($LASTEXITCODE -ne 0) { throw "SQL fehlgeschlagen ($Database): $Sql" }
    return $out
}

# --- 1. Dump prüfen ---
if (-not (Test-Path -LiteralPath $DumpFile -PathType Leaf)) {
    Write-Error "Die Dump-Datei '$DumpFile' wurde nicht gefunden."
    exit 1
}
$fileInfo = Get-Item -LiteralPath $DumpFile
if ($fileInfo.Length -lt 5) {
    Write-Error "Die Dump-Datei '$DumpFile' ist leer (0 Bytes)."
    exit 1
}
$stream = [System.IO.File]::OpenRead($fileInfo.FullName)
try {
    $magicBytes = New-Object byte[] 5
    if ($stream.Read($magicBytes, 0, 5) -ne 5) { throw "Dump header is incomplete" }
} finally { $stream.Dispose() }
$magic = [System.Text.Encoding]::ASCII.GetString($magicBytes)
if ($magic -ne "PGDMP") {
    Write-Error "Die Datei '$DumpFile' ist kein gültiger PostgreSQL Custom-Format-Dump (Magic Bytes: '$magic' statt 'PGDMP')."
    exit 1
}
Write-Host "Dump-Datei: $($fileInfo.FullName) ($([math]::Round($fileInfo.Length / 1KB, 1)) KB)" -ForegroundColor Cyan

# Zugehöriges Uploads-Archiv (gleicher Zeitstempel wie der Dump)
if (-not $NoUploads -and -not $UploadsFile) {
    $candidate = Join-Path $fileInfo.DirectoryName ($fileInfo.Name -replace '^casa-backup-', 'casa-uploads-' -replace '\.dump$', '.tar.gz')
    if ($candidate -ne $fileInfo.FullName -and (Test-Path -LiteralPath $candidate -PathType Leaf)) { $UploadsFile = $candidate }
}
if ($NoUploads) { $UploadsFile = $null }
if ($UploadsFile) {
    if (-not (Test-Path -LiteralPath $UploadsFile -PathType Leaf)) {
        Write-Error "Das Uploads-Archiv '$UploadsFile' wurde nicht gefunden."
        exit 1
    }
    $UploadsFile = (Get-Item -LiteralPath $UploadsFile).FullName
    Write-Host "Uploads-Archiv: $UploadsFile" -ForegroundColor Cyan
}
else {
    Write-Host "⚠️  Kein Uploads-Archiv — hochgeladene Dateien bleiben unverändert." -ForegroundColor Yellow
    Write-Host "   Dokumente/Fotos aus dem Dump können danach auf fehlende Dateien zeigen." -ForegroundColor Yellow
}

# --- 2. Prüfe ob Postgres-Container läuft ---
# @(...) erzwingt ein Array; exakter Vergleich mit -notcontains (siehe backup-db.ps1)
$runningServices = @(docker compose @composeArgs ps --status running --format "{{.Service}}" 2>&1 | ForEach-Object { "$_".Trim() })
if ($LASTEXITCODE -ne 0) {
    Write-Error "Fehler beim Abfragen des Container-Status. Läuft Docker?"
    exit 1
}
if ($runningServices -notcontains $ServiceName) {
    Write-Error "Der Postgres-Container '$ServiceName' läuft nicht. Starte ihn zuerst mit: docker compose $($composeArgs -join ' ') up -d $ServiceName"
    exit 1
}
Write-Host "  ✓ Postgres-Container läuft." -ForegroundColor Green

# --- 3. Sicherheitsabfrage ---
if (-not $Yes) {
    Write-Host ""
    Write-Host "⚠️  Die Datenbank '$DbName' wird durch den Dump ersetzt." -ForegroundColor Red
    Write-Host "   Die bisherige bleibt als '$OldDb' erhalten (ausser mit -DropOld)." -ForegroundColor Red
    if ($UploadsFile) { Write-Host "   Alle hochgeladenen Dateien werden ebenfalls ersetzt!" -ForegroundColor Red }
    Write-Host "   Das Backend ist während des Restores gestoppt." -ForegroundColor Red
    $antwort = Read-Host "Fortfahren? (j/n)"
    if ($antwort -ne "j") {
        Write-Host "Abgebrochen. Keine Änderungen vorgenommen." -ForegroundColor Yellow
        exit 0
    }
}

$backendStopped = $false
$backendWasRunning = $runningServices -contains $UploadsService
$oldRenamed = $false
$swapped = $false
$stageReady = $false
try {
    # Validate and prepare all upload bytes before changing the database.
    if ($UploadsFile) {
        docker compose @composeArgs run -d --rm --no-deps --name $Helper --entrypoint sleep $UploadsService infinity | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Upload-Hilfscontainer konnte nicht starten." }
        docker cp $UploadsFile "${Helper}:/tmp/casa-uploads.tar.gz"
        if ($LASTEXITCODE -ne 0) { throw "Upload-Archiv konnte nicht kopiert werden." }
        docker exec $Helper python /app/scripts/restore_uploads.py stage $stageId --archive /tmp/casa-uploads.tar.gz
        if ($LASTEXITCODE -ne 0) { throw "Upload-Archivprüfung fehlgeschlagen; Datenbank und Dateien unverändert." }
        $stageReady = $true
    }
    # --- 4. Backend stoppen ---
    Write-Host "Stoppe Backend ..." -ForegroundColor Cyan
    docker compose @composeArgs stop $UploadsService
    if ($LASTEXITCODE -ne 0) { throw "Backend konnte nicht gestoppt werden." }
    $backendStopped = $true

    # --- 5. Restore in frische Datenbank ---
    Write-Host "Lege frische Datenbank '$RestoreDb' an ..." -ForegroundColor Cyan
    Invoke-Sql "postgres" "CREATE DATABASE `"$RestoreDb`" TEMPLATE template0" | Out-Null

    docker compose @composeArgs cp $fileInfo.FullName "${ServiceName}:$RemoteDump"
    if ($LASTEXITCODE -ne 0) { throw "docker compose cp des Dumps fehlgeschlagen." }

    Write-Host "pg_restore --single-transaction --exit-on-error ..." -ForegroundColor Cyan
    docker compose @composeArgs exec -T $ServiceName pg_restore --single-transaction --exit-on-error --no-owner -U $DbUser -d $RestoreDb $RemoteDump
    $restoreExitCode = $LASTEXITCODE
    docker compose @composeArgs exec -T $ServiceName rm -f $RemoteDump 2>$null
    # Jeder Exit-Code != 0 ist ein Fehler — die Transaktion wurde komplett zurückgerollt
    if ($restoreExitCode -ne 0) { throw "pg_restore ist mit Exit-Code $restoreExitCode fehlgeschlagen." }

    $revision = Invoke-Sql $RestoreDb "SELECT version_num FROM alembic_version"
    if (-not $revision) { throw "Wiederhergestellte DB hat keine alembic_version — ist das ein Casa-Dump?" }
    Write-Host "  ✓ Wiederhergestellt: Alembic-Revision $revision" -ForegroundColor Green

    # --- 6. Tausch ---
    Write-Host "Tausche Datenbanken ..." -ForegroundColor Cyan
    Invoke-Sql "postgres" "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN ('$DbName', '$RestoreDb') AND pid <> pg_backend_pid()" | Out-Null
    $oldRenamed = $true # Treat a lost SQL acknowledgement as a possible rename.
    Invoke-Sql "postgres" "ALTER DATABASE `"$DbName`" RENAME TO `"$OldDb`"" | Out-Null
    Invoke-Sql "postgres" "ALTER DATABASE `"$RestoreDb`" RENAME TO `"$DbName`"" | Out-Null
    $swapped = $true

    # --- 7. Uploads (Hilfscontainer mit dem Upload-Volume; das Backend ist gestoppt) ---
    if ($UploadsFile) {
        Write-Host "Stelle Uploads wieder her ..." -ForegroundColor Cyan
        docker exec $Helper python /app/scripts/restore_uploads.py apply $stageId
        if ($LASTEXITCODE -ne 0) { throw "Upload-Tausch fehlgeschlagen. Staging-ID: $stageId" }
        $stageReady = $false
        docker rm -f $Helper | Out-Null
        Write-Host "  ✓ Uploads wiederhergestellt." -ForegroundColor Green
    }

    # --- 8. Backend starten (alembic upgrade head) und auf /api/health warten ---
    if ($backendWasRunning) {
    Write-Host "Starte Backend (führt alembic upgrade head aus) ..." -ForegroundColor Cyan
    docker compose @composeArgs start $UploadsService
    if ($LASTEXITCODE -ne 0) { throw "Backend konnte nicht gestartet werden." }
    $backendStopped = $false

    $healthy = $false
    for ($i = 0; $i -lt 60; $i++) {
        docker compose @composeArgs exec -T $UploadsService python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/health', timeout=3).status==200 else 1)" 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { $healthy = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $healthy) {
        throw "Backend meldet nach 120 s nicht gesund. Logs: docker compose $($composeArgs -join ' ') logs backend"
    }
    }
    if ($DropOld) {
        Invoke-Sql "postgres" "DROP DATABASE `"$OldDb`"" | Out-Null
        Write-Host "  ✓ Vorherige Datenbank gelöscht." -ForegroundColor Green
    }
}
catch {
    Write-Host ""
    Write-Host "❌ Restore fehlgeschlagen: $_" -ForegroundColor Red
    if ($swapped) {
        docker compose @composeArgs stop $UploadsService | Out-Null
        Write-Host "   Backend bleibt zur Prüfung/Wiederaufnahme angehalten." -ForegroundColor Yellow
    }
    if (-not $swapped) {
        if ($oldRenamed) {
            try {
                Invoke-Sql "postgres" "ALTER DATABASE `"$OldDb`" RENAME TO `"$DbName`"" | Out-Null
                $oldRenamed = $false
            } catch { Write-Host "   Datenbank-Rückbenennung fehlgeschlagen; Backend bleibt gestoppt." -ForegroundColor Red }
        }
        try { Invoke-Sql "postgres" "DROP DATABASE IF EXISTS `"$RestoreDb`"" | Out-Null } catch { }
        if (-not $oldRenamed) { Write-Host "   Die bisherige Datenbank '$DbName' ist erhalten." -ForegroundColor Yellow }
    }
    else {
        Write-Host "   Die vorherige Datenbank liegt (falls nicht -DropOld) als '$OldDb' vor." -ForegroundColor Yellow
    }
    if ($stageReady -and -not $swapped -and -not $oldRenamed) {
        docker exec $Helper python /app/scripts/restore_uploads.py discard $stageId
        if ($LASTEXITCODE -eq 0) { $stageReady = $false }
    }
    if ($backendStopped -and $backendWasRunning -and -not $swapped -and -not $oldRenamed) {
        Write-Host "   Starte Backend wieder ..." -ForegroundColor Yellow
        docker compose @composeArgs start $UploadsService
    }
    if ($stageReady) { Write-Host "   Upload-Staging-ID zur Prüfung/Wiederaufnahme: $stageId" -ForegroundColor Yellow }
    exit 1
}
finally {
    try { docker compose @composeArgs exec -T $ServiceName rm -f $RemoteDump 2>$null | Out-Null } catch { }
    if ($UploadsFile) {
        try { docker rm -f $Helper 2>$null | Out-Null } catch { }
    }
}

Write-Host ""
Write-Host "═══════════════════════════════════════════" -ForegroundColor Green
Write-Host "  ✅ Restore erfolgreich (Revision $revision)" -ForegroundColor Green
if ($backendWasRunning) { Write-Host "  Backend gesund." -ForegroundColor Green }
if (-not $DropOld) {
    Write-Host "  Vorherige DB als '$OldDb' behalten. Nach Prüfung löschen:" -ForegroundColor Green
    Write-Host "    docker compose $($composeArgs -join ' ') exec -T postgres psql -U haushalt -d postgres -c 'DROP DATABASE `"$OldDb`"'" -ForegroundColor White
}
Write-Host "═══════════════════════════════════════════" -ForegroundColor Green
