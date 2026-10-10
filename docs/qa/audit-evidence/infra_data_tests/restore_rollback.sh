#!/bin/bash
# Reproduces docs/deployment.md:210 rollback path: backup before update -> update (migration adds widget_tokens) -> restore old dump with pg_restore --clean --if-exists (as scripts/restore-db.ps1:139)
S=$1; W=$S/work/infra_data_tests; export PGPASSWORD=audit; B=postgresql://audit:audit@localhost:5432; DB=audit_infra_rb
export JWT_SECRET_KEY=audit-secret-key-only-for-tests-min32-xyz CORS_ORIGINS=http://x DATABASE_URL=$B/$DB
cd /home/user/haushalt-app/backend
psql $B/postgres -qc "drop database if exists $DB with (force)" -c "create database $DB" 2>/dev/null
$S/venv/bin/python -m alembic upgrade y1z2a3b4c5d6 >/dev/null 2>&1
psql $DATABASE_URL -qc "insert into users(id,email,password_hash,display_name,created_at) values ('11111111-1111-1111-1111-111111111111','old@x.ch','x','OldName',now());
insert into households(id,name,invite_code,created_at) values ('22222222-2222-2222-2222-222222222222','HH','ABCDEFGH',now());
insert into household_members(id,household_id,user_id,role,joined_at) values (gen_random_uuid(),'22222222-2222-2222-2222-222222222222','11111111-1111-1111-1111-111111111111','admin',now());"
pg_dump -Fc -d $DATABASE_URL -f $W/pre_update.dump
echo "== update to head, then app writes"
$S/venv/bin/python -m alembic upgrade head >/dev/null 2>&1
psql $DATABASE_URL -qc "update users set display_name='ChangedAfterBackup' where email='old@x.ch';
insert into users(id,email,password_hash,display_name,created_at) values ('33333333-3333-3333-3333-333333333333','new@x.ch','x','New',now());
insert into widget_tokens(id,user_id,household_id,token_hash,token_prefix,created_at) values (gen_random_uuid(),'33333333-3333-3333-3333-333333333333','22222222-2222-2222-2222-222222222222','h','casa_w',now());
update households set name='HH-changed';"
echo "== restore pre-update dump"
pg_restore --clean --if-exists -d $DATABASE_URL $W/pre_update.dump 2>&1 | grep -E "^pg_restore: (error|warning)" | cut -c1-160
echo "pg_restore exit=${PIPESTATUS[0]}"
psql $DATABASE_URL -Atc "select 'alembic', version_num from alembic_version; select 'users', email, display_name from users order by email; select 'households', name from households; select 'members', count(*) from household_members; select 'widget_tokens table', to_regclass('widget_tokens');"
echo "== backend container start: alembic upgrade head"
$S/venv/bin/python -m alembic upgrade head 2>&1 | grep -E "Running|DuplicateTable" | head -3
