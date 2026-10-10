# Audit evidence (2026-10-10)

These are the reproduction scripts and captured outputs behind `docs/qa/FULL_LOGIC_AUDIT.md`.
They are **not** part of the application and are not run in CI. None of them modifies application code or
production data. Every backend script creates its own throw-away PostgreSQL database named `audit_*`.

## Layout

| Path | Content |
|---|---|
| `pgharness.py` | PostgreSQL harness: creates a fresh DB, runs the real `alembic upgrade head`, mocks Socket.IO emits and push, returns a FastAPI `TestClient` that opens **one DB session per request** (unlike `backend/tests/conftest.py`, which shares one SQLite session) |
| `journeys/` | Lead-auditor end-to-end journeys (J1 finance + member departure, J3/V2 concurrent expense edits, J4 meal poll → shopping, V1 null-PATCH) |
| `finance/`, `households/`, `chores_tasks_time/`, `shopping_food_calendar/`, `pets_plants_documents/`, `tags_ai/`, `frontend_realtime_ux/`, `infra_data_tests/` | Module audits (scripts, `*.out` captured outputs, vitest scratch tests) |
| `module-reports/` | The per-module working reports the main documents were consolidated from |

## Running

Prerequisites: PostgreSQL 16 reachable as `postgresql://audit:audit@localhost:5432/` with a superuser `audit`
(adapt `PG` in `pgharness.py`), and the backend requirements plus `pytest hypothesis httpx` installed.

```bash
cd docs/qa/audit-evidence
export PYTHONPATH=$PWD:$PWD/../../../backend
python journeys/v2_shares.py            # concurrent participant edits -> sum(shares) != amount
python journeys/j1_finance_leave.py     # 3-person finance journey with departure
```

Scripts written by the module auditors use one of three import styles; with the `PYTHONPATH` above all of
them resolve `pgharness`. Scripts in `infra_data_tests/` expect the directory containing `pg/pgharness.py`
as first argument (create `pg/` as a symlink to this directory). `restore_rollback.sh` needs `pg_dump`/`pg_restore`.

The vitest scratch configs (`*.config.mts`/`*.config.ts`) contain absolute paths of the audit machine
(`<scratchpad>` placeholders); adjust `include`/`root` before running them from `frontend/`
with `npx vitest run --config <path>`.

Race scripts are probabilistic. Counts quoted in the audit are from the recorded runs (`*.out`).
