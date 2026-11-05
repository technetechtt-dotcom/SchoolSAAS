"""Verify backup-bundle integrity and restore a SQLite backup to a staging folder.

Never overwrites a database or active evidence directory.
PostgreSQL bundles are verified with pg_restore --list, not restored automatically.
"""
import hashlib,json,sqlite3,subprocess,sys,tarfile,tempfile
from pathlib import Path,PurePosixPath

def digest(path):
    h=hashlib.sha256()
    with open(path,"rb") as stream:
        for block in iter(lambda:stream.read(1048576),b""):h.update(block)
    return h.hexdigest()

def verify(bundle_path,restore_dir=None):
    path=Path(bundle_path)
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp)
        with tarfile.open(path,"r:gz") as archive:
            for member in archive.getmembers():
                relative=PurePosixPath(member.name)
                if (relative.is_absolute() or ".." in relative.parts
                        or member.issym() or member.islnk() or not member.isfile()):
                    raise ValueError("Unsafe backup member: "+member.name)
            archive.extractall(root,filter="data")
        manifest=json.loads((root/"manifest.json").read_text())
        expected=manifest["files"]
        actual={f.relative_to(root).as_posix():digest(f)
                for f in root.rglob("*") if f.is_file() and f.name!="manifest.json"}
        if actual!=expected:raise RuntimeError("Bundle checksum verification failed")
        dbtype=manifest["database_type"]
        if dbtype=="sqlite":
            with sqlite3.connect(str(root/"database.sqlite")) as db:
                if db.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
                    raise RuntimeError("SQLite restore integrity check failed")
            if restore_dir:
                destination=Path(restore_dir)
                if destination.exists() and any(destination.iterdir()):
                    raise RuntimeError("Restore destination must be empty")
                destination.mkdir(parents=True,exist_ok=True)
                import shutil
                for entry in root.iterdir():
                    if entry.name=="manifest.json":continue
                    target=destination/entry.name
                    if entry.is_dir():shutil.copytree(entry,target)
                    else:shutil.copy2(entry,target)
        elif dbtype=="postgresql":
            subprocess.run(["pg_restore","--list",str(root/"database.dump")],
                           check=True,stdout=subprocess.DEVNULL)
            if restore_dir:
                raise RuntimeError("PostgreSQL restoration requires an isolated staging database and operator approval")
        else:raise RuntimeError("Unknown bundle type")
    print("Bundle verified:",path)
    return True

if __name__=="__main__":
    if len(sys.argv) not in (2,3):
        raise SystemExit("Usage: python scripts/verify_backup_bundle.py BUNDLE [EMPTY_STAGING_DIR_FOR_SQLITE]")
    verify(sys.argv[1],sys.argv[2] if len(sys.argv)==3 else None)
