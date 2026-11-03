"""Create a timestamped backup of the configured database.

SQLite: copies the database file.
Postgres: runs pg_dump when available.
Always verify restores separately before relying on a backup.
"""
from __future__ import annotations
import os, shutil, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

url = os.environ.get("DATABASE_URL", "sqlite:///./schoolcare_demo.db")
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
out_dir = Path(os.environ.get("BACKUP_DIR", "./backups"))
out_dir.mkdir(parents=True, exist_ok=True)

if url.startswith("sqlite:///"):
    src = Path(url.replace("sqlite:///", "", 1))
    if not src.exists():
        raise SystemExit(f"SQLite database not found: {src}")
    dest = out_dir / f"{src.stem}-{stamp}.db"
    shutil.copy2(src, dest)
    print(f"Wrote {dest}")
elif url.startswith("postgresql"):
    dest = out_dir / f"schoolcare-{stamp}.sql"
    parsed = urlparse(url)
    env = os.environ.copy()
    if parsed.password:
        env["PGPASSWORD"] = parsed.password
    cmd = ["pg_dump", "-h", parsed.hostname or "localhost", "-p", str(parsed.port or 5432),
           "-U", parsed.username or "postgres", "-d", parsed.path.lstrip("/"), "-f", str(dest)]
    subprocess.check_call(cmd, env=env)
    print(f"Wrote {dest}")
else:
    raise SystemExit(f"Unsupported DATABASE_URL scheme for backup script: {url}")
sys.exit(0)
