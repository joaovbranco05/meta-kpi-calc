"""Run integration tests against a new, Unix-socket-only PostgreSQL 17 cluster."""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--postgres-bin", required=True, type=Path)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C",
           "PYTHONDONTWRITEBYTECODE": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}

    def run(command, **kwargs):
        return subprocess.run([str(item) for item in command], env=env, check=True, **kwargs)

    version = subprocess.check_output([str(args.postgres_bin / "postgres"), "--version"], env=env, text=True)
    if "PostgreSQL) 17." not in version:
        raise ValueError("A PostgreSQL 17 server is required")
    with tempfile.TemporaryDirectory(prefix="meta-kpi-pg-", dir="/tmp") as temporary:
        root = Path(temporary)
        data, socket = root / "data", root / "socket"
        socket.mkdir(mode=0o700)
        started = False
        try:
            run([args.postgres_bin / "initdb", "-D", data, "-U", "mk_test", "-A", "trust",
                 "--encoding=UTF8", "--no-locale"], stdout=subprocess.DEVNULL)
            run([args.postgres_bin / "pg_ctl", "-D", data, "-l", root / "server.log", "-o",
                 f"-c listen_addresses= -k {socket} -p 55487", "-w", "start"], stdout=subprocess.DEVNULL)
            started = True
            server = subprocess.check_output([str(args.postgres_bin / "psql"), "-h", str(socket), "-p", "55487",
                "-U", "mk_test", "-d", "postgres", "-Atc", "SELECT version()"], env=env, text=True)
            print("Servidor de teste:", server.strip(), flush=True)
            copy = root / "project"
            copy.mkdir()
            for name in ("src", "tests", "alembic", "frontend"):
                shutil.copytree(project / name, copy / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            for name in ("pyproject.toml", "requirements.txt", "alembic.ini"):
                shutil.copy2(project / name, copy / name)
            env.update(META_KPI_TEST_PG_SOCKET=str(socket), META_KPI_TEST_PG_PORT="55487")
            return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                                   "tests/test_postgresql.py"], cwd=copy, env=env).returncode
        finally:
            if started:
                run([args.postgres_bin / "pg_ctl", "-D", data, "-m", "fast", "-w", "stop"], stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    raise SystemExit(main())
