#!/usr/bin/env bash
# =============================================================================
# Restore-Skript für haushalt-app (Bash-Pendant zu restore-db.ps1, CASA-07 / PD-D2)
#
# Ablauf (Docker-Compose-Modus):
#   1. Dump prüfen (PGDMP-Magic), Sicherheitsabfrage
#   2. Backend stoppen — keine Schreibzugriffe während des Restores
#   3. Dump in eine FRISCHE Datenbank <db>_restore einspielen:
#        pg_restore --single-transaction --exit-on-error --no-owner
#      Jeder Fehler bricht ab; die Produktions-DB ist bis hier unverändert.
#   4. Tausch: <db> → <db>_before_restore_<Zeitstempel>, <db>_restore → <db>
#   5. Uploads-Archiv (gleicher Zeitstempel) einspielen — per Hilfscontainer
#   6. Backend starten (führt `alembic upgrade head` aus) und auf /api/health warten
#
# Nach einem Fehler wird das Backend wieder gestartet; Exit-Code != 0.
#
# Direkter Modus (--database-url, ohne Docker): Schritte 1, 3 und 4 gegen eine beliebige
# PostgreSQL-URL mit lokalem psql/pg_restore. Für Restore-Drills und CI
# (scripts/restore-drill.sh). Backend stoppen/Uploads sind dann Sache des Aufrufers.
#
# Migrationen sind forward-only (PD-D2): Ein Restore ist Disaster-Recovery. Ein älterer
# Dump gehört zum Code-Stand, mit dem er erstellt wurde — siehe docs/deployment.md §4.
# =============================================================================

set -Eeuo pipefail

usage() {
    cat <<'EOF'
Verwendung: scripts/restore-db.sh [Optionen] <dump-datei>

Optionen (Docker-Compose-Modus):
  -f, --compose-file DATEI   Compose-Datei (default: docker-compose.yml)
      --env-file DATEI       Env-Datei für Docker Compose
  -p, --project-name NAME    Compose-Projektname
      --uploads DATEI        Uploads-Archiv (default: casa-uploads-<Zeitstempel>.tar.gz neben dem Dump)
      --no-uploads           Uploads nicht anfassen

Direkter Modus:
      --database-url URL     Ziel-DB (postgresql://user:pw@host:port/db); ohne Docker

Allgemein:
  -y, --yes                  Keine Sicherheitsabfrage
      --drop-old             Vorherige DB nach erfolgreichem Tausch löschen (statt umbenannt behalten)
  -h, --help                 Diese Hilfe
EOF
}

COMPOSE_FILE="docker-compose.yml"
ENV_FILE=""
PROJECT_NAME=""
UPLOADS_FILE=""
NO_UPLOADS=0
DATABASE_URL_ARG=""
ASSUME_YES=0
DROP_OLD=0
DUMP_FILE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        -f|--compose-file) COMPOSE_FILE="$2"; shift 2 ;;
        --env-file) ENV_FILE="$2"; shift 2 ;;
        -p|--project-name) PROJECT_NAME="$2"; shift 2 ;;
        --uploads) UPLOADS_FILE="$2"; shift 2 ;;
        --no-uploads) NO_UPLOADS=1; shift ;;
        --database-url) DATABASE_URL_ARG="$2"; shift 2 ;;
        -y|--yes) ASSUME_YES=1; shift ;;
        --drop-old) DROP_OLD=1; shift ;;
        -h|--help) usage; exit 0 ;;
        -*) echo "Unbekannte Option: $1" >&2; usage >&2; exit 2 ;;
        *) DUMP_FILE="$1"; shift ;;
    esac
done

die() { echo "❌ $*" >&2; exit 1; }
info() { echo "→ $*"; }

[[ -n "$DUMP_FILE" ]] || { usage >&2; exit 2; }
[[ -f "$DUMP_FILE" ]] || die "Dump-Datei '$DUMP_FILE' nicht gefunden."
[[ -s "$DUMP_FILE" ]] || die "Dump-Datei '$DUMP_FILE' ist leer."
[[ "$(head -c 5 "$DUMP_FILE")" == "PGDMP" ]] || die "'$DUMP_FILE' ist kein PostgreSQL Custom-Format-Dump (Magic Bytes != PGDMP)."

STAMP="$(date +%Y%m%d_%H%M%S)"

# ---------------------------------------------------------------------------
# Modus: Befehle für psql / pg_restore
# ---------------------------------------------------------------------------
if [[ -n "$DATABASE_URL_ARG" ]]; then
    MODE="direct"
    NO_UPLOADS=1
    url_no_query="${DATABASE_URL_ARG%%\?*}"
    url_query=""
    [[ "$DATABASE_URL_ARG" == *\?* ]] && url_query="?${DATABASE_URL_ARG#*\?}"
    URL_BASE="${url_no_query%/*}"
    DB_NAME="${url_no_query##*/}"
    [[ -n "$DB_NAME" && "$URL_BASE" == *://* ]] || die "Ungültige --database-url."

    url_for() { echo "${URL_BASE}/$1${url_query}"; }
    # psql gegen eine bestimmte DB (Admin-Befehle laufen über "postgres")
    run_sql() { psql "$(url_for "$1")" -X -q -v ON_ERROR_STOP=1 -At -c "$2"; }
    run_restore() { pg_restore --single-transaction --exit-on-error --no-owner -d "$(url_for "$1")" "$DUMP_FILE"; }
else
    MODE="compose"
    DB_NAME="haushalt"
    DB_USER="haushalt"
    PG_SERVICE="postgres"
    BACKEND_SERVICE="backend"
    compose=(docker compose -f "$COMPOSE_FILE")
    [[ -n "$ENV_FILE" ]] && compose+=(--env-file "$ENV_FILE")
    [[ -n "$PROJECT_NAME" ]] && compose+=(--project-name "$PROJECT_NAME")

    run_sql() { "${compose[@]}" exec -T "$PG_SERVICE" psql -U "$DB_USER" -d "$1" -X -q -v ON_ERROR_STOP=1 -At -c "$2"; }
    run_restore() {
        "${compose[@]}" cp "$DUMP_FILE" "${PG_SERVICE}:/tmp/casa-restore.dump"
        local rc=0
        "${compose[@]}" exec -T "$PG_SERVICE" pg_restore --single-transaction --exit-on-error --no-owner \
            -U "$DB_USER" -d "$1" /tmp/casa-restore.dump || rc=$?
        "${compose[@]}" exec -T "$PG_SERVICE" rm -f /tmp/casa-restore.dump || true
        return "$rc"
    }

    running="$("${compose[@]}" ps --status running --format '{{.Service}}')" || die "Container-Status nicht abfragbar. Läuft Docker?"
    grep -qx "$PG_SERVICE" <<<"$running" || die "Postgres-Container '$PG_SERVICE' läuft nicht (docker compose up -d $PG_SERVICE)."

    if [[ $NO_UPLOADS -eq 0 && -z "$UPLOADS_FILE" ]]; then
        candidate="$(dirname "$DUMP_FILE")/$(basename "$DUMP_FILE" | sed -e 's/^casa-backup-/casa-uploads-/' -e 's/\.dump$/.tar.gz/')"
        [[ "$candidate" != "$DUMP_FILE" && -f "$candidate" ]] && UPLOADS_FILE="$candidate"
    fi
    if [[ $NO_UPLOADS -eq 0 && -n "$UPLOADS_FILE" ]]; then
        [[ -f "$UPLOADS_FILE" ]] || die "Uploads-Archiv '$UPLOADS_FILE' nicht gefunden."
        [[ "$(head -c 2 "$UPLOADS_FILE" | od -An -tx1 | tr -d ' \n')" == "1f8b" ]] || die "'$UPLOADS_FILE' ist kein gzip-Archiv."
    fi
fi

RESTORE_DB="${DB_NAME}_restore"
OLD_DB="${DB_NAME}_before_restore_${STAMP}"

echo "Dump:      $DUMP_FILE"
echo "Ziel-DB:   $DB_NAME ($MODE)"
if [[ "$MODE" == "compose" ]]; then
    if [[ $NO_UPLOADS -eq 0 && -n "$UPLOADS_FILE" ]]; then
        echo "Uploads:   $UPLOADS_FILE (bestehende Dateien werden ersetzt)"
    else
        echo "Uploads:   ⚠️  kein Archiv — Dateien bleiben unverändert, Dokumente/Fotos können fehlen"
    fi
fi

if [[ $ASSUME_YES -ne 1 ]]; then
    echo
    echo "⚠️  Die Datenbank '$DB_NAME' wird durch den Dump ersetzt (die alte bleibt als '$OLD_DB' erhalten)."
    read -r -p "Fortfahren? (j/n) " answer
    [[ "$answer" == "j" ]] || { echo "Abgebrochen. Keine Änderungen vorgenommen."; exit 0; }
fi

# ---------------------------------------------------------------------------
# Backend stoppen; bei jedem Ausgang (auch Fehler) wieder starten
# ---------------------------------------------------------------------------
BACKEND_STOPPED=0
cleanup() {
    local rc=$?
    if [[ "$MODE" == "compose" ]]; then
        docker rm -f "casa-restore-helper-${STAMP}" >/dev/null 2>&1 || true
        if [[ $BACKEND_STOPPED -eq 1 && $rc -ne 0 ]]; then
            echo "→ Starte Backend nach Fehler wieder ..." >&2
            "${compose[@]}" start "$BACKEND_SERVICE" >&2 || true
        fi
    fi
    if [[ $rc -ne 0 ]]; then
        run_sql postgres "DROP DATABASE IF EXISTS \"$RESTORE_DB\"" >/dev/null 2>&1 || true
        echo "❌ Restore fehlgeschlagen (Exit-Code $rc). '$DB_NAME' ist unverändert, sofern der Tausch nicht erreicht wurde." >&2
    fi
}
trap cleanup EXIT

if [[ "$MODE" == "compose" ]]; then
    info "Stoppe Backend ..."
    "${compose[@]}" stop "$BACKEND_SERVICE"
    BACKEND_STOPPED=1
fi

# ---------------------------------------------------------------------------
# Restore in frische Datenbank
# ---------------------------------------------------------------------------
info "Lege frische Datenbank '$RESTORE_DB' an ..."
run_sql postgres "DROP DATABASE IF EXISTS \"$RESTORE_DB\""
run_sql postgres "CREATE DATABASE \"$RESTORE_DB\" TEMPLATE template0"

info "pg_restore --single-transaction --exit-on-error ..."
run_restore "$RESTORE_DB"

revision="$(run_sql "$RESTORE_DB" "SELECT version_num FROM alembic_version" 2>/dev/null || true)"
[[ -n "$revision" ]] || die "Wiederhergestellte DB hat keine alembic_version — ist das ein Casa-Dump?"
info "Wiederhergestellt: Alembic-Revision $revision"

# ---------------------------------------------------------------------------
# Tausch (Backend ist gestoppt; verbliebene Verbindungen trennen)
# ---------------------------------------------------------------------------
info "Tausche Datenbanken: $DB_NAME → $OLD_DB, $RESTORE_DB → $DB_NAME ..."
run_sql postgres "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN ('$DB_NAME', '$RESTORE_DB') AND pid <> pg_backend_pid()" >/dev/null
if [[ -n "$(run_sql postgres "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'")" ]]; then
    run_sql postgres "ALTER DATABASE \"$DB_NAME\" RENAME TO \"$OLD_DB\""
    HAD_OLD=1
else
    HAD_OLD=0
fi
run_sql postgres "ALTER DATABASE \"$RESTORE_DB\" RENAME TO \"$DB_NAME\""

if [[ $HAD_OLD -eq 1 && $DROP_OLD -eq 1 ]]; then
    run_sql postgres "DROP DATABASE \"$OLD_DB\""
    info "Vorherige Datenbank gelöscht."
fi

# ---------------------------------------------------------------------------
# Uploads (Hilfscontainer mit dem Upload-Volume — das Backend ist gestoppt)
# ---------------------------------------------------------------------------
if [[ "$MODE" == "compose" && $NO_UPLOADS -eq 0 && -n "$UPLOADS_FILE" ]]; then
    helper="casa-restore-helper-${STAMP}"
    info "Stelle Uploads wieder her ..."
    "${compose[@]}" run -d --rm --no-deps --name "$helper" "$BACKEND_SERVICE" sleep 600 >/dev/null
    docker cp "$UPLOADS_FILE" "${helper}:/tmp/casa-uploads.tar.gz"
    docker exec "$helper" sh -c "find /app/data/uploads -mindepth 1 -delete && tar -xzf /tmp/casa-uploads.tar.gz -C /app/data && rm -f /tmp/casa-uploads.tar.gz"
    docker rm -f "$helper" >/dev/null
    info "Uploads wiederhergestellt."
fi

# ---------------------------------------------------------------------------
# Backend starten (alembic upgrade head) und auf /api/health warten
# ---------------------------------------------------------------------------
if [[ "$MODE" == "compose" ]]; then
    info "Starte Backend (führt alembic upgrade head aus) ..."
    "${compose[@]}" start "$BACKEND_SERVICE"
    BACKEND_STOPPED=0
    healthy=0
    for _ in $(seq 1 60); do
        if "${compose[@]}" exec -T "$BACKEND_SERVICE" python -c \
            "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/health', timeout=3).status==200 else 1)" \
            >/dev/null 2>&1; then
            healthy=1
            break
        fi
        sleep 2
    done
    [[ $healthy -eq 1 ]] || die "Backend meldet nach 120 s nicht gesund — Logs: docker compose logs backend. Alte DB: $OLD_DB"
fi

echo
echo "═══════════════════════════════════════════"
echo "  ✅ Restore erfolgreich (Revision $revision)"
if [[ $HAD_OLD -eq 1 && $DROP_OLD -eq 0 ]]; then
    echo "  Vorherige DB als '$OLD_DB' behalten. Nach Prüfung löschen:"
    echo "    DROP DATABASE \"$OLD_DB\";"
fi
echo "═══════════════════════════════════════════"
