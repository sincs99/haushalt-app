#!/usr/bin/env bash
# Transactional database restore; uploads are validated/staged before DB mutation.
# A failed pre-swap restore resumes only an originally running backend. A failed
# post-swap restore leaves it stopped, preserving the old DB for recovery.
# --database-url preserves the direct PostgreSQL mode used by restore-drill.sh;
# its caller is responsible for stopping applications and restoring uploads.
set -Eeuo pipefail

usage() {
    cat <<'EOF'
Usage: scripts/restore-db.sh [options] <custom-format.dump>
  -f, --compose-file FILE   Compose file (default docker-compose.yml)
      --env-file FILE       Compose environment file
  -p, --project-name NAME   Compose project
      --uploads FILE        Matching uploads archive (auto-detected if omitted)
      --no-uploads          Preserve uploads
      --database-url URL    Direct PostgreSQL mode, no Docker or upload restore
  -y, --yes                 Skip confirmation
      --drop-old            Drop previous DB only after the entire restore succeeds
  -h, --help                Show this help
EOF
}
die() { echo "Restore error: $*" >&2; exit 1; }
info() { echo "-> $*"; }
require_value() { [[ $# -ge 2 && -n "$2" ]] || die "Missing value for $1"; }

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
        -f|--compose-file) require_value "$@"; COMPOSE_FILE="$2"; shift 2 ;;
        --env-file) require_value "$@"; ENV_FILE="$2"; shift 2 ;;
        -p|--project-name) require_value "$@"; PROJECT_NAME="$2"; shift 2 ;;
        --uploads) require_value "$@"; UPLOADS_FILE="$2"; shift 2 ;;
        --no-uploads) NO_UPLOADS=1; shift ;;
        --database-url) require_value "$@"; DATABASE_URL_ARG="$2"; shift 2 ;;
        -y|--yes) ASSUME_YES=1; shift ;;
        --drop-old) DROP_OLD=1; shift ;;
        -h|--help) usage; exit 0 ;;
        -*) die "Unknown option: $1" ;;
        *) [[ -z "$DUMP_FILE" ]] || die "Only one dump is accepted"; DUMP_FILE="$1"; shift ;;
    esac
done
[[ -n "$DUMP_FILE" ]] || { usage >&2; exit 2; }
[[ -f "$DUMP_FILE" && -s "$DUMP_FILE" ]] || die "Dump is missing or empty: $DUMP_FILE"
[[ "$(head -c 5 -- "$DUMP_FILE")" == "PGDMP" ]] || die "Dump is not PostgreSQL custom format (PGDMP)"
# Normalize operator-selected paths so tools never interpret a leading dash.
DUMP_FILE="$(cd -- "$(dirname -- "$DUMP_FILE")" && pwd)/$(basename -- "$DUMP_FILE")"

RUN_ID="$(od -vAn -N16 -tx1 /dev/urandom | tr -d '[:space:]')"
[[ "$RUN_ID" =~ ^[0-9a-f]{32}$ ]] || die "Could not generate a unique restore ID"
# Independent of DB_NAME: PostgreSQL must never truncate a generated identifier.
RESTORE_DB="casa_restore_${RUN_ID}"
OLD_DB="casa_before_${RUN_ID}"
HELPER="casa-restore-helper-${RUN_ID}"
REMOTE_DUMP="/tmp/casa-restore-${RUN_ID}.dump"
HELPER_STARTED=0
STAGE_READY=0
TEMP_CREATED=0
OLD_RENAMED=0
SWAPPED=0
HAD_OLD=0
BACKEND_WAS_RUNNING=0
BACKEND_STOPPED=0

if [[ -n "$DATABASE_URL_ARG" ]]; then
    MODE="direct"
    NO_UPLOADS=1
    [[ ! "$DATABASE_URL_ARG" =~ [[:cntrl:]] ]] || die "Control characters are not allowed in a PostgreSQL URL"
    url_no_query="${DATABASE_URL_ARG%%\?*}"
    URL_QUERY=""
    if [[ "$DATABASE_URL_ARG" == *\?* ]]; then
        URL_QUERY="?${DATABASE_URL_ARG#*\?}"
        # libpq query parameters must not override the database selected by url_for.
        # Restrict to transport/client settings; encoded or duplicate unknown keys fail.
        IFS='&' read -r -a url_parameters <<<"${URL_QUERY#?}"
        for parameter in "${url_parameters[@]}"; do
            key="${parameter%%=*}"
            [[ "$parameter" == *=* ]] || die "Invalid PostgreSQL URL query"
            case "$key" in
                sslmode|sslrootcert|sslcert|sslkey|sslpassword|connect_timeout|application_name|target_session_attrs) ;;
                *) die "Unsupported PostgreSQL URL parameter: $key" ;;
            esac
        done
    fi
    URL_BASE="${url_no_query%/*}"
    DB_NAME="${url_no_query##*/}"
    [[ "$URL_BASE" =~ ^postgres(ql)?://[^/]+$ ]] || die "Expected postgresql://authority/database"
    # ASCII allowlist covers BOTH quoted identifiers and string literals below.
    # Reject percent-encoding/quotes/metacharacters rather than normalize SQL input.
    [[ "$DB_NAME" =~ ^[a-zA-Z_][a-zA-Z0-9_]{0,62}$ ]] || die "Database name must be an ASCII identifier of 1-63 characters"
    [[ "$DB_NAME" != "postgres" && "$DB_NAME" != "template0" && "$DB_NAME" != "template1" ]] || die "Refusing to replace a PostgreSQL maintenance database"
    url_for() { printf '%s/%s%s\n' "$URL_BASE" "$1" "$URL_QUERY"; }
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
        "${compose[@]}" cp "$DUMP_FILE" "${PG_SERVICE}:${REMOTE_DUMP}"
        local rc=0
        "${compose[@]}" exec -T "$PG_SERVICE" pg_restore --single-transaction --exit-on-error --no-owner \
            -U "$DB_USER" -d "$1" "$REMOTE_DUMP" || rc=$?
        "${compose[@]}" exec -T "$PG_SERVICE" rm -f "$REMOTE_DUMP" || true
        return "$rc"
    }
    running="$("${compose[@]}" ps --status running --format '{{.Service}}')" || die "Cannot inspect Compose services"
    grep -qx "$PG_SERVICE" <<<"$running" || die "PostgreSQL service is not running"
    if grep -qx "$BACKEND_SERVICE" <<<"$running"; then BACKEND_WAS_RUNNING=1; fi
    if [[ $NO_UPLOADS -eq 0 && -z "$UPLOADS_FILE" ]]; then
        candidate="$(dirname -- "$DUMP_FILE")/$(basename -- "$DUMP_FILE" | sed -e 's/^casa-backup-/casa-uploads-/' -e 's/\.dump$/.tar.gz/')"
        [[ "$candidate" != "$DUMP_FILE" && -f "$candidate" ]] && UPLOADS_FILE="$candidate"
    fi
    if [[ $NO_UPLOADS -eq 0 && -n "$UPLOADS_FILE" ]]; then
        [[ -f "$UPLOADS_FILE" ]] || die "Upload archive missing: $UPLOADS_FILE"
        UPLOADS_FILE="$(cd -- "$(dirname -- "$UPLOADS_FILE")" && pwd)/$(basename -- "$UPLOADS_FILE")"
    fi
fi

echo "Dump: $DUMP_FILE"
echo "Database: $DB_NAME ($MODE)"
echo "Recovery database: $OLD_DB"
if [[ "$MODE" == "compose" && $NO_UPLOADS -eq 0 && -n "$UPLOADS_FILE" ]]; then
    echo "Uploads will be replaced from: $UPLOADS_FILE"
elif [[ "$MODE" == "compose" ]]; then
    echo "Uploads remain unchanged; restored documents/photos may refer to missing files."
fi
if [[ $ASSUME_YES -ne 1 ]]; then
    read -r -p "Replace database '$DB_NAME'? (j/n) " answer
    [[ "$answer" == "j" ]] || { echo "Cancelled without changes"; exit 0; }
fi

cleanup() {
    local rc=$?
    trap - EXIT
    set +e
    if [[ $rc -ne 0 ]]; then
        if [[ $SWAPPED -eq 0 && $OLD_RENAMED -eq 1 ]]; then
            # Compensate a failure between the two renames before resuming writes.
            if run_sql postgres "ALTER DATABASE \"$OLD_DB\" RENAME TO \"$DB_NAME\""; then
                OLD_RENAMED=0
            else
                echo "Database rename rollback failed; keep backend stopped. Old DB: $OLD_DB" >&2
            fi
        fi
        if [[ $SWAPPED -eq 0 && $TEMP_CREATED -eq 1 ]]; then
            run_sql postgres "DROP DATABASE IF EXISTS \"$RESTORE_DB\"" >/dev/null 2>&1 || true
        fi
        if [[ "$MODE" == "compose" ]]; then
            if [[ $SWAPPED -eq 1 || $OLD_RENAMED -eq 1 ]]; then
                # Includes a failure after starting the backend (health check/drop-old).
                "${compose[@]}" stop "$BACKEND_SERVICE" >&2 || true
                echo "Post-swap failure: backend remains stopped. Recovery DB: $OLD_DB; stage: $RUN_ID" >&2
            elif [[ $BACKEND_STOPPED -eq 1 && $BACKEND_WAS_RUNNING -eq 1 ]]; then
                "${compose[@]}" start "$BACKEND_SERVICE" >&2 || true
            fi
        fi
        echo "Restore failed (exit $rc). Recovery DB: $OLD_DB" >&2
    fi
    if [[ "$MODE" == "compose" ]]; then
        if [[ $HELPER_STARTED -eq 1 ]]; then
            if [[ $STAGE_READY -eq 1 && $SWAPPED -eq 0 && $OLD_RENAMED -eq 0 ]]; then
                docker exec "$HELPER" python /app/scripts/restore_uploads.py discard "$RUN_ID" >&2 || true
            fi
            docker rm -f "$HELPER" >/dev/null 2>&1 || true
        fi
        "${compose[@]}" exec -T "$PG_SERVICE" rm -f "$REMOTE_DUMP" >/dev/null 2>&1 || true
    fi
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Stage uses the backend image and upload volume, but never invokes its startup
# command/migrations. Invalid archives fail before either DB is touched.
if [[ "$MODE" == "compose" && $NO_UPLOADS -eq 0 && -n "$UPLOADS_FILE" ]]; then
    info "Validate and stage upload archive ..."
    "${compose[@]}" run -d --rm --no-deps --name "$HELPER" --entrypoint sleep "$BACKEND_SERVICE" infinity >/dev/null
    HELPER_STARTED=1
    docker cp "$UPLOADS_FILE" "${HELPER}:/tmp/casa-uploads.tar.gz"
    docker exec "$HELPER" python /app/scripts/restore_uploads.py stage "$RUN_ID" --archive /tmp/casa-uploads.tar.gz
    STAGE_READY=1
fi
if [[ "$MODE" == "compose" ]]; then
    BACKEND_STOPPED=1
    "${compose[@]}" stop "$BACKEND_SERVICE"
fi

info "Create isolated restore database $RESTORE_DB ..."
run_sql postgres "CREATE DATABASE \"$RESTORE_DB\" TEMPLATE template0"
TEMP_CREATED=1
run_restore "$RESTORE_DB"
revision="$(run_sql "$RESTORE_DB" "SELECT version_num FROM alembic_version")"
[[ -n "$revision" ]] || die "Restored database has no Alembic revision"

info "Swap databases ..."
run_sql postgres "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN ('$DB_NAME', '$RESTORE_DB') AND pid <> pg_backend_pid()" >/dev/null
existing_database="$(run_sql postgres "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'")"
if [[ -n "$existing_database" ]]; then
    HAD_OLD=1
    # Mark the attempt before sending SQL: a connection error can hide a
    # successful rename. Cleanup then fails closed if recovery is ambiguous.
    OLD_RENAMED=1
    run_sql postgres "ALTER DATABASE \"$DB_NAME\" RENAME TO \"$OLD_DB\""
fi
run_sql postgres "ALTER DATABASE \"$RESTORE_DB\" RENAME TO \"$DB_NAME\""
SWAPPED=1
TEMP_CREATED=0

if [[ "$MODE" == "compose" && $STAGE_READY -eq 1 ]]; then
    info "Apply validated upload stage ..."
    docker exec "$HELPER" python /app/scripts/restore_uploads.py apply "$RUN_ID"
    STAGE_READY=0
fi
if [[ "$MODE" == "compose" && $BACKEND_WAS_RUNNING -eq 1 ]]; then
    "${compose[@]}" start "$BACKEND_SERVICE"
    BACKEND_STOPPED=0
    healthy=0
    for (( attempt=0; attempt<60; attempt++ )); do
        if "${compose[@]}" exec -T "$BACKEND_SERVICE" python -c \
            "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/health', timeout=3).status==200 else 1)" >/dev/null 2>&1; then
            healthy=1
            break
        fi
        sleep 2
    done
    [[ $healthy -eq 1 ]] || die "Backend health check failed; inspect logs before restarting"
fi
# Never destroy the recovery DB before upload application and backend checks.
if [[ $HAD_OLD -eq 1 && $DROP_OLD -eq 1 ]]; then
    run_sql postgres "DROP DATABASE \"$OLD_DB\""
fi
info "Restore complete (Alembic $revision)"
if [[ $HAD_OLD -eq 1 && $DROP_OLD -eq 0 ]]; then
    echo "Previous database retained: $OLD_DB"
fi
