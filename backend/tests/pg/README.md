# PostgreSQL-Testlane (`tests/pg/`, Marker `pg`)

Der normale Testlauf (`pytest -q`) nutzt SQLite in-memory mit **einer geteilten Session**
und `create_all` — Races, Row-Locks, Constraint-Verletzungen unter Last und Migrationen
sind dort unsichtbar (CASA-25). Diese Lane schliesst die Lücke.

## Ausführen

```bash
cd backend
export TEST_PG_URL=postgresql://audit:audit@localhost:5432/postgres   # Admin-URL, darf CREATE DATABASE
pytest -m pg -q            # nur die PG-Lane
pytest -q                  # alles (SQLite-Lane + PG-Lane, wenn TEST_PG_URL gesetzt)
```

Ohne `TEST_PG_URL` werden alle Tests in diesem Verzeichnis **übersprungen** — der
SQLite-Lauf bleibt unverändert. `TEST_PG_KEEP_DB=1` lässt die Test-DB nach dem Lauf stehen
(Debugging; Name steht in `pg_url`).

## Was die Fixtures (conftest.py) liefern

| Fixture | Inhalt |
|---|---|
| `pg_url` (package) | Frische DB `casa_test_<hex>`, migriert mit dem **echten** `alembic upgrade head` (Subprozess). `app.database.SessionLocal` ist für die Dauer der Lane an diese DB gebunden und wird danach zurückgesetzt. |
| `client` | `TestClient(app)` **ohne** `get_db`-Override → jede Anfrage hat ihre eigene Session, wie in Produktion. Lifespan (Push-Scheduler/Cleanup) läuft nicht. |
| `db` | Eigene echte Session (für Setup/Assertions; überschreibt die SQLite-`db`-Fixture). Nach Requests ggf. `db.expire_all()` aufrufen. |
| `emits` (autouse) | `EmitRecorder`: alle `emit_to_household_sync`-Aufrufe aus `app.routers.*`/`app.services.*` → `emits.calls`, `emits.events("todo_updated")`, `emits.names()`. |
| `make_household` / `household` | `make_household(["Anna", "Ben", "Carla"])` → `PgHousehold` mit `id`, `user_ids`, `tokens`, `headers(i)`, `url("/budget")`. Index 0 ist Admin, `joined_at` gestaffelt. |
| `pg_admin_url` | Admin-URL für Tests, die eigene Wegwerf-DBs brauchen (Migrationstests). |

Rate-Limiting ist abgeschaltet. Alle Tests teilen sich die DB eines Laufs — jeder Test legt
deshalb seine **eigenen** Haushalte an und verlässt sich nicht auf globale Zählungen.

## Helfer (`tests/pg/harness.py`)

- `run_parallel(fn, n)` — `fn(0..n-1)` in `n` Threads, per `threading.Barrier` gleichzeitig
  gestartet; Ergebnisse in Index-Reihenfolge, Exceptions werden als Wert zurückgegeben.
  `status_codes(results)` macht daraus eine Liste von Statuscodes.
- `add_member(hh, "Dora")`, `auth_headers(token)`.
- `fresh_database(admin_url, upgrade_to="<rev>")` — Context-Manager für eine eigene DB auf
  einem beliebigen Revisionsstand; `run_alembic(url, "upgrade", "head")` /
  `run_alembic(url, "downgrade", "-1")`.

## Beispiel: Race-Regressionstest

```python
from tests.pg.harness import run_parallel, status_codes

def test_parallel_first_budget_never_500(client, household):
    def put(i):
        return client.put(household.url("/budget"),
                          json={"month": "2026-03-01", "amount_rappen": 1000 + i},
                          headers=household.headers(i % 2))
    codes = status_codes(run_parallel(put, 6))
    assert 500 not in codes
```

Konventionen: Concurrency-Regressionstests gehören hierher (`test_<bereich>_*.py`), fachliche
Tests ohne Parallelität weiterhin in die SQLite-Lane.

## Sperren und Konflikte (F0-2)

- `app.services.locking.lock_household(db, household_id)` — `SELECT … FOR UPDATE` auf die
  `households`-Zeile; serialisiert haushaltsweite Check-then-Act-Abläufe (Mitgliedschaft,
  Kalender, Quota …). Immer zuerst sperren, danach weitere Zeilen.
- `lock_row(db, Model, id)` — Sperre auf eine einzelne Zeile. Beide lesen die Zeile unter der
  Sperre neu (`populate_existing`) und sind auf SQLite ein normales SELECT.
- Globaler Handler (`app/core/db_errors.py`): `IntegrityError`, `StaleDataError` und
  PostgreSQL-Deadlock/Serialisierung/Lock-Timeout (`40P01`, `40001`, `55P03`) →
  `409 {"detail": {"code": "CONFLICT_RETRY"}}`; `get_db` rollt die Session dabei zurück.
  Das ist ein Netz — bekannte Races gezielt sperren und fachlich beantworten.
- Sperr-Timeout im Test erzwingen: `db.execute(text("SET LOCAL lock_timeout = '200ms'"))`.

## CI

Job `backend-postgres` in `.github/workflows/ci.yml`: `postgres:16`-Service,
`alembic upgrade head`, `pytest -m pg`, danach `alembic downgrade -1 && alembic upgrade head`.
