#!/usr/bin/env bash
# =============================================================================
# Restore-Drill (CASA-07 / PD-D2): Backup → Update → Restore → Vergleich → Upgrade
#
#   1. Wegwerf-DB auf einer älteren Revision (OLD_REV) anlegen und befüllen
#   2. Zustand festhalten (pro Tabelle Zeilenzahl + md5 über alle Zeilen), pg_dump
#   3. alembic upgrade head + Schreibzugriffe "nach dem Backup" (auch in neuen Tabellen)
#   4. scripts/restore-db.sh --database-url … (gleiche Logik wie im Betrieb)
#   5. Zustand muss exakt dem Backup entsprechen; danach alembic upgrade head erfolgreich
#   6. Gegenprobe: ein kaputter Dump muss mit Exit-Code != 0 abbrechen und die DB unverändert lassen
#
# Verwendung:
#   PG_ADMIN_URL=postgresql://user:pw@localhost:5432/postgres scripts/restore-drill.sh
# Optional: OLD_REV (default y1z2a3b4c5d6 — vor widget_tokens/ai_user_usage, deren FKs auf
# users den alten "pg_restore --clean"-Restore zerlegt haben), PYTHON (default python3).
# Exit-Code 0 = Drill bestanden.
# =============================================================================

set -Eeuo pipefail

: "${PG_ADMIN_URL:?PG_ADMIN_URL setzen, z. B. postgresql://user:pw@localhost:5432/postgres}"
OLD_REV="${OLD_REV:-y1z2a3b4c5d6}"
PYTHON="${PYTHON:-python3}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
DB="casa_drill_$(date +%s)_$$"
BASE="${PG_ADMIN_URL%/*}"
DB_URL="${BASE}/${DB}"

export DATABASE_URL="$DB_URL"
export JWT_SECRET_KEY="${JWT_SECRET_KEY:-restore-drill-secret-key-only-for-tests-min32}"
export CORS_ORIGINS="${CORS_ORIGINS:-http://localhost:5173}"

cleanup() {
    psql "$PG_ADMIN_URL" -X -q -c "DROP DATABASE IF EXISTS \"$DB\" WITH (FORCE)" >/dev/null 2>&1 || true
    rm -rf "$WORK"
}
trap cleanup EXIT

fail() { echo "❌ DRILL FAILED: $*" >&2; exit 1; }
sql() { psql "$DB_URL" -X -q -v ON_ERROR_STOP=1 -At -c "$1"; }
alembic() { (cd "$ROOT/backend" && "$PYTHON" -m alembic "$@"); }

# Zeilenzahl + md5 aller Zeilen pro Tabelle (inkl. alembic_version)
snapshot() {
    local tables t
    tables="$(sql "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1")"
    for t in $tables; do
        sql "SELECT '$t', count(*), md5(coalesce(string_agg(x::text, '|' ORDER BY x::text), '')) FROM \"$t\" x"
    done
}

echo "== 1. Wegwerf-DB $DB auf Revision $OLD_REV"
psql "$PG_ADMIN_URL" -X -q -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$DB\""
alembic upgrade "$OLD_REV" >/dev/null 2>&1 || fail "alembic upgrade $OLD_REV"
sql "INSERT INTO users (id, email, password_hash, display_name, created_at) VALUES
       ('11111111-1111-1111-1111-111111111111', 'old@example.com', 'x', 'OldName', now()),
       ('44444444-4444-4444-4444-444444444444', 'ben@example.com', 'x', 'Ben', now());
     INSERT INTO households (id, name, invite_code, created_at)
       VALUES ('22222222-2222-2222-2222-222222222222', 'HH', 'ABCDEFGH', now());
     INSERT INTO household_members (id, household_id, user_id, role, joined_at) VALUES
       (gen_random_uuid(), '22222222-2222-2222-2222-222222222222', '11111111-1111-1111-1111-111111111111', 'admin', now()),
       (gen_random_uuid(), '22222222-2222-2222-2222-222222222222', '44444444-4444-4444-4444-444444444444', 'member', now());"

echo "== 2. Zustand festhalten + pg_dump"
snapshot >"$WORK/before.txt"
pg_dump -Fc -d "$DB_URL" -f "$WORK/backup.dump"

echo "== 3. Update auf head + Schreibzugriffe nach dem Backup"
alembic upgrade head >/dev/null 2>&1 || fail "alembic upgrade head (Update)"
HEAD_REV="$(sql "SELECT version_num FROM alembic_version")"
sql "UPDATE users SET display_name = 'ChangedAfterBackup' WHERE email = 'old@example.com';
     INSERT INTO users (id, email, password_hash, display_name, created_at)
       VALUES ('33333333-3333-3333-3333-333333333333', 'new@example.com', 'x', 'New', now());
     UPDATE households SET name = 'HH-changed';"
# Neue Tabellen mit FK auf users/households (genau die haben den alten Restore zerlegt)
if [[ -n "$(sql "SELECT to_regclass('widget_tokens')")" ]]; then
    sql "INSERT INTO widget_tokens (id, user_id, household_id, token_hash, token_prefix, created_at)
         VALUES (gen_random_uuid(), '33333333-3333-3333-3333-333333333333',
                 '22222222-2222-2222-2222-222222222222', 'h', 'casa_w', now())"
fi
if [[ -n "$(sql "SELECT to_regclass('ai_user_usage')")" ]]; then
    sql "INSERT INTO ai_user_usage (id, user_id, day, calls)
         VALUES (gen_random_uuid(), '11111111-1111-1111-1111-111111111111', current_date, 3)"
fi
snapshot >"$WORK/after_update.txt"

echo "== 4. Gegenprobe: kaputter Dump bricht ab, DB bleibt unverändert"
head -c 4096 "$WORK/backup.dump" >"$WORK/broken.dump"
if "$ROOT/scripts/restore-db.sh" --database-url "$DB_URL" --yes --drop-old "$WORK/broken.dump" >"$WORK/broken.log" 2>&1; then
    fail "restore-db.sh meldete Erfolg für einen abgeschnittenen Dump"
fi
snapshot >"$WORK/after_broken.txt"
diff -u "$WORK/after_update.txt" "$WORK/after_broken.txt" || fail "DB nach fehlgeschlagenem Restore verändert"
[[ -z "$(psql "$PG_ADMIN_URL" -X -At -c "SELECT 1 FROM pg_database WHERE datname = '${DB}_restore'")" ]] \
    || fail "Temporäre ${DB}_restore nach Fehler nicht aufgeräumt"
echo "   ok (Exit-Code != 0, Daten unverändert)"

echo "== 5. Restore des Backups"
"$ROOT/scripts/restore-db.sh" --database-url "$DB_URL" --yes --drop-old "$WORK/backup.dump" \
    || fail "restore-db.sh Exit-Code != 0"
snapshot >"$WORK/after_restore.txt"
diff -u "$WORK/before.txt" "$WORK/after_restore.txt" || fail "Zustand nach Restore != Backup"
echo "   ok (alle Tabellen identisch mit dem Backup, Revision $(sql "SELECT version_num FROM alembic_version"))"

echo "== 6. Backend-Start: alembic upgrade head"
alembic upgrade head >"$WORK/upgrade.log" 2>&1 || { cat "$WORK/upgrade.log" >&2; fail "alembic upgrade head nach Restore"; }
[[ "$(sql "SELECT version_num FROM alembic_version")" == "$HEAD_REV" ]] || fail "nicht auf head ($HEAD_REV)"
[[ "$(sql "SELECT display_name FROM users WHERE email = 'old@example.com'")" == "OldName" ]] || fail "Daten nach Upgrade verändert"

echo
echo "✅ Restore-Drill bestanden ($OLD_REV → $HEAD_REV → Restore → $HEAD_REV)"
