"""One-time database upgrade from SchoolSAAS v0.2 to v0.3.

Run after taking a verified database backup, before starting the v0.3 application.
New installations can start normally. For production, replace with versioned Alembic
migrations and an environment-specific deployment plan.
"""
import os
from sqlalchemy import create_engine, inspect, text

url=os.environ.get("DATABASE_URL")
if not url:
    raise SystemExit("Set DATABASE_URL before running this migration")
engine=create_engine(url)
planned={
    "users":[("active","BOOLEAN NOT NULL DEFAULT TRUE")],
    "memberships":[("active","BOOLEAN NOT NULL DEFAULT TRUE"),
                   ("assigned_class","VARCHAR(30)")],
    "incidents":[("review_status","VARCHAR(30) NOT NULL DEFAULT 'pending'"),
                 ("review_notes","TEXT NOT NULL DEFAULT ''")]
}
with engine.begin() as conn:
    inspector=inspect(conn)
    for table,columns in planned.items():
        if not inspector.has_table(table):
            print(f"Skipping missing table {table}; fresh schema will be created on startup")
            continue
        present={c["name"] for c in inspector.get_columns(table)}
        for name,typ in columns:
            if name not in present:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {typ}"))
                print(f"Added {table}.{name}")
            else:
                print(f"Already present: {table}.{name}")

print("Column upgrade completed. New independent tables are created when the app starts.")
