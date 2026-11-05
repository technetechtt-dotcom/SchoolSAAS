"""Generate a verified bundle of database, evidence and approved-letter files.

Uses SQLite's online backup API, or pg_dump -Fc for PostgreSQL.
Bundle encryption and off-site retention are deployment responsibilities.
"""
import hashlib,json,os,shutil,sqlite3,subprocess,tarfile,tempfile
from pathlib import Path
from datetime import datetime,timezone
from urllib.parse import urlparse,unquote

def digest(path):
    h=hashlib.sha256()
    with open(path,"rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):h.update(block)
    return h.hexdigest()

def backup():
    url=os.environ.get("DATABASE_URL","sqlite:///./schoolcare_demo.db")
    out=Path(os.environ.get("BACKUP_DIR","./backups")).resolve()
    out.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive=out/f"schoolsaas-{stamp}.tar.gz"
    with tempfile.TemporaryDirectory() as working:
        stage=Path(working)
        if url.startswith("sqlite:///"):
            source=Path(url.removeprefix("sqlite:///")).resolve()
            if not source.is_file():raise RuntimeError("Source SQLite database is missing")
            with sqlite3.connect(str(source)) as current,sqlite3.connect(str(stage/"database.sqlite")) as target:
                current.backup(target)
                if target.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
                    raise RuntimeError("SQLite backup failed integrity check")
            database_type="sqlite"
        elif url.startswith("postgresql"):
            parsed=urlparse(url.replace("postgresql+psycopg://","postgresql://",1))
            env=os.environ.copy()
            if parsed.password:env["PGPASSWORD"]=unquote(parsed.password)
            subprocess.run(["pg_dump","-Fc","--no-owner","-h",parsed.hostname or "localhost",
                "-p",str(parsed.port or 5432),"-U",unquote(parsed.username or "postgres"),
                "-d",parsed.path.lstrip("/"),"-f",str(stage/"database.dump")],env=env,check=True)
            database_type="postgresql"
        else:raise ValueError("Unsupported DATABASE_URL scheme")
        for name,key,default in (("evidence","EVIDENCE_UPLOAD_DIR","./uploads"),
                                ("letters","LETTER_UPLOAD_DIR","./uploads/letters")):
            location=Path(os.environ.get(key,default)).resolve()
            target=stage/name
            if location.is_dir():
                shutil.copytree(location,target,symlinks=False)
            else:target.mkdir()
        files={}
        for file in stage.rglob("*"):
            if file.is_file():
                files[file.relative_to(stage).as_posix()]=digest(file)
        (stage/"manifest.json").write_text(json.dumps(
            {"format":1,"database_type":database_type,"created_at":stamp,"files":files},
            sort_keys=True,indent=2))
        with tarfile.open(archive,"w:gz") as bundle:
            for file in stage.rglob("*"):
                if file.is_file():bundle.add(file,arcname=file.relative_to(stage).as_posix(),
                                             recursive=False)
    print(archive)
    return archive

if __name__=="__main__":backup()
