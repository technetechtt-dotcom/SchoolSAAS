"""Initial Alembic baseline must never silently upgrade populated school data."""
import os,sys,subprocess
from pathlib import Path
from sqlalchemy import create_engine,text

def test_baseline_refuses_existing_database(tmp_path):
    filename=tmp_path/"legacy_school.db"
    url="sqlite:///"+str(filename)
    engine=create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE schools (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"))
        conn.execute(text("INSERT INTO schools(id,name) VALUES (1,'Existing school')"))
    engine.dispose()
    env=os.environ.copy()
    env.update(DATABASE_URL=url,SCHEMA_AUTO_CREATE="false",
               JWT_SECRET="migration-test-secret-not-for-deployment")
    result=subprocess.run([sys.executable,"-m","alembic","upgrade","head"],
        cwd=str(Path(__file__).resolve().parents[1]),env=env,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=45)
    assert result.returncode!=0
    assert "Baseline migration requires an empty database" in result.stderr
    with create_engine(url).connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM schools")).scalar_one()==1
