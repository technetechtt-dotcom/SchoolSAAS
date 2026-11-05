"""Configure ephemeral PostgreSQL 16 CI database with RLS and normal app role.

Run only against the disposable GitHub Actions service database.
"""
import os
from pathlib import Path
import psycopg

dsn=os.environ["DATABASE_URL"].replace("postgresql+psycopg://","postgresql://")
with psycopg.connect(dsn,autocommit=True) as conn:
    sql="\n".join(line for line in Path("scripts/postgres_rls.sql").read_text().splitlines()
                    if not line.lstrip().startswith("--"))
    for statement in sql.split(";"):
        if statement.strip():
            conn.execute(statement)
    conn.execute("CREATE ROLE schoolcare_ci_app LOGIN PASSWORD 'ci-app-only-password'")
    conn.execute("GRANT CONNECT ON DATABASE schoolcare TO schoolcare_ci_app")
    conn.execute("GRANT USAGE ON SCHEMA public TO schoolcare_ci_app")
    conn.execute("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO schoolcare_ci_app")
    conn.execute("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO schoolcare_ci_app")
    conn.execute("REVOKE UPDATE,DELETE ON audit_events FROM schoolcare_ci_app")
print("RLS enabled and non-superuser CI role provisioned")
