"""Exercise restore orchestration with fake Docker/PostgreSQL binaries only.

Run: python scripts/tests/test_restore_db_sh.py
No real Docker daemon, PostgreSQL server, archive extraction or application code.
"""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "restore-db.sh"
BASH = shutil.which("bash") or str(Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe")

FAKE = r'''#!/usr/bin/env bash
set -eu
name="${0##*/}"
printf '%s' "$name" >> "$MOCK_LOG"
printf '\t%s' "$@" >> "$MOCK_LOG"
printf '\n' >> "$MOCK_LOG"
if [[ "$name" == "sleep" ]]; then exit 0; fi
if [[ "$name" == "docker" && " $* " == *" ps --status running "* ]]; then
    echo postgres
    if [[ "$MOCK_BACKEND_RUNNING" == "1" ]]; then echo backend; fi
    exit 0
fi
if [[ " $* " == *"restore_uploads.py stage "* && "$MOCK_FAIL" == "stage" ]]; then exit 21; fi
if [[ " $* " == *"restore_uploads.py apply "* && "$MOCK_FAIL" == "apply" ]]; then exit 22; fi
if [[ " $* " == *"/api/health"* && "$MOCK_FAIL" == "health" ]]; then exit 25; fi
if [[ "$name" == "pg_restore" || " $* " == *" pg_restore "* ]]; then
    if [[ "$MOCK_FAIL" == "restore" ]]; then exit 23; fi
    exit 0
fi
if [[ "$name" == "psql" || " $* " == *" psql "* ]]; then
    sql=""
    while [[ $# -gt 0 ]]; do
        if [[ "$1" == "-c" ]]; then sql="$2"; break; fi
        shift
    done
    if [[ "$sql" == 'SELECT version_num FROM alembic_version' ]]; then echo fixture_revision; fi
    if [[ "$sql" == 'SELECT 1 FROM pg_database'* ]]; then
        if [[ "$MOCK_FAIL" == "lookup" ]]; then exit 26; fi
        echo 1
    fi
    if [[ "$sql" == 'ALTER DATABASE "casa_restore_'* && "$MOCK_FAIL" == "rename" ]]; then exit 24; fi
    if [[ "$sql" == 'DROP DATABASE "casa_before_'* && "$MOCK_FAIL" == "drop" ]]; then exit 27; fi
fi
'''


@unittest.skipUnless(Path(BASH).exists(), "Bash is required for the mocked shell harness")
class RestoreOrchestrationTests(unittest.TestCase):
    def run_restore(self, *, failure="", running=True, direct_url=None, drop=False):
        with tempfile.TemporaryDirectory(prefix="casa-restore-mock-") as temporary:
            root = Path(temporary)
            commands = root / "bin"
            commands.mkdir()
            for name in ("docker", "psql", "pg_restore", "sleep"):
                stub = commands / name
                stub.write_text(FAKE, encoding="utf-8", newline="\n")
                stub.chmod(0o700)
            dump = root / "fixture.dump"
            dump.write_bytes(b"PGDMP-dummy-not-a-real-database")
            uploads = root / "uploads.tar.gz"
            uploads.write_bytes(b"dummy-input-never-extracted")
            log = root / "calls.log"
            log.touch()
            environment = {
                **os.environ,
                "PATH": str(commands) + os.pathsep + str(Path(BASH).parent) + os.pathsep + os.environ.get("PATH", ""),
                "MOCK_LOG": str(log),
                "MOCK_BIN": commands.as_posix(),
                "MOCK_FAIL": failure,
                "MOCK_BACKEND_RUNNING": "1" if running else "0",
            }
            # Git Bash prepends system binaries to inherited Windows PATH. Shell
            # functions guarantee these four commands always use our stubs.
            wrapper = r'''
docker() { "$MOCK_BIN/docker" "$@"; }
psql() { "$MOCK_BIN/psql" "$@"; }
pg_restore() { "$MOCK_BIN/pg_restore" "$@"; }
sleep() { "$MOCK_BIN/sleep" "$@"; }
source "$1" "${@:2}"
'''
            arguments = [BASH, "-c", wrapper, "restore-test", str(SCRIPT), "--yes"]
            if direct_url is not None:
                arguments += ["--database-url", direct_url]
            else:
                arguments += ["--uploads", str(uploads)]
            if drop:
                arguments += ["--drop-old"]
            arguments += [str(dump)]
            result = subprocess.run(arguments, env=environment, capture_output=True, text=True, timeout=90)
            calls = log.read_text(encoding="utf-8").splitlines()
            return result, calls

    def test_stage_failure_never_mutates_database_or_stops_backend(self):
        result, calls = self.run_restore(failure="stage")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertTrue(any("restore_uploads.py\tstage\t" in call for call in calls))
        self.assertFalse(any("CREATE DATABASE" in call or "\tstop\tbackend" in call or "\tstart\tbackend" in call for call in calls))

    def test_failed_restore_restarts_only_previously_running_backend(self):
        for running in (True, False):
            with self.subTest(running=running):
                result, calls = self.run_restore(failure="restore", running=running)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(any("\tstart\tbackend" in call for call in calls), running)
                self.assertTrue(any('DROP DATABASE IF EXISTS "casa_restore_' in call for call in calls))
                self.assertTrue(any("restore_uploads.py\tdiscard\t" in call for call in calls))
                self.assertFalse(any('DROP DATABASE "casa_before_' in call for call in calls))

    def test_rename_failure_restores_original_name_before_backend_resume(self):
        result, calls = self.run_restore(failure="rename", drop=True)
        self.assertNotEqual(result.returncode, 0)
        rollback = next(i for i, call in enumerate(calls) if 'ALTER DATABASE "casa_before_' in call)
        resume = next(i for i, call in enumerate(calls) if "\tstart\tbackend" in call)
        self.assertLess(rollback, resume)
        self.assertFalse(any('DROP DATABASE "casa_before_' in call for call in calls))

    def test_upload_failure_preserves_old_database_and_stops_backend(self):
        result, calls = self.run_restore(failure="apply", drop=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any("\tstart\tbackend" in call for call in calls))
        self.assertGreaterEqual(sum("\tstop\tbackend" in call for call in calls), 2)
        self.assertFalse(any('DROP DATABASE "casa_before_' in call for call in calls))
        self.assertFalse(any("restore_uploads.py\tdiscard\t" in call for call in calls))

    def test_health_failure_stops_restarted_backend_and_keeps_old_database(self):
        result, calls = self.run_restore(failure="health", drop=True)
        self.assertNotEqual(result.returncode, 0)
        start = next(i for i, call in enumerate(calls) if "\tstart\tbackend" in call)
        self.assertTrue(any("\tstop\tbackend" in call for call in calls[start + 1:]))
        self.assertFalse(any('DROP DATABASE "casa_before_' in call for call in calls))

    def test_success_drops_old_database_only_after_apply_and_health(self):
        result, calls = self.run_restore(drop=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        stage = next(i for i, call in enumerate(calls) if "restore_uploads.py\tstage\t" in call)
        create = next(i for i, call in enumerate(calls) if "CREATE DATABASE" in call)
        apply = next(i for i, call in enumerate(calls) if "restore_uploads.py\tapply\t" in call)
        health = next(i for i, call in enumerate(calls) if "/api/health" in call)
        drop = next(i for i, call in enumerate(calls) if 'DROP DATABASE "casa_before_' in call)
        self.assertLess(stage, create)
        self.assertLess(apply, health)
        self.assertLess(health, drop)

    def test_success_does_not_start_previously_stopped_backend(self):
        result, calls = self.run_restore(running=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any("\tstart\tbackend" in call for call in calls))

    def test_direct_mode_accepts_long_valid_database_name_without_truncation(self):
        target = "d" * 63
        result, calls = self.run_restore(direct_url=f"postgresql://fixture:dummy@localhost/{target}?sslmode=disable", drop=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(call.startswith("docker") for call in calls))
        create = next(call for call in calls if "CREATE DATABASE" in call)
        temporary_name = create.split('CREATE DATABASE "')[1].split('"')[0]
        self.assertLessEqual(len(temporary_name), 63)
        self.assertNotEqual(temporary_name, target)

    def test_direct_mode_rejects_sql_identifiers_and_url_database_overrides(self):
        invalid = [
            "postgresql://fixture@localhost/db';DROP DATABASE postgres;--",
            "postgresql://fixture@localhost/" + "d" * 64,
            "postgresql://fixture@localhost/db?dbname=other",
            "postgresql://fixture@localhost/db?%64bname=other",
            "postgresql://fixture@localhost/db?sslmode=disable\n&dbname=other",
            "postgresql://fixture@localhost/postgres",
        ]
        for url in invalid:
            with self.subTest(url=url):
                result, calls = self.run_restore(direct_url=url)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
