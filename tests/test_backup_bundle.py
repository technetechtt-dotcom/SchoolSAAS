"""Backup restoration keeps learner records, evidence and approved letters intact."""
import os,sqlite3,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def test_backup_bundle_restore(tmp_path):
    db=tmp_path/"school.db"
    with sqlite3.connect(db) as connection:
        connection.execute("CREATE TABLE schools(id INTEGER PRIMARY KEY,name TEXT)")
        connection.execute("INSERT INTO schools VALUES(1,'Fictional Demo School')")
    evidence=tmp_path/"source_evidence"/"1"
    letters=tmp_path/"source_letters"/"1"
    evidence.mkdir(parents=True);letters.mkdir(parents=True)
    (evidence/"sample.bin").write_bytes(b"example private evidence")
    (letters/"approved.pdf").write_bytes(b"%PDF-1.4\nTest")
    output=tmp_path/"backups"
    env=os.environ.copy()
    env.update(DATABASE_URL="sqlite:///"+str(db),BACKUP_DIR=str(output),
        EVIDENCE_UPLOAD_DIR=str(evidence.parent),LETTER_UPLOAD_DIR=str(letters.parent))
    result=subprocess.run([sys.executable,"scripts/backup_bundle.py"],cwd=ROOT,env=env,
                          capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    bundle=next(output.glob("*.tar.gz"))
    destination=tmp_path/"restored"
    result=subprocess.run([sys.executable,"scripts/verify_backup_bundle.py",str(bundle),str(destination)],
                          cwd=ROOT,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    with sqlite3.connect(destination/"database.sqlite") as restored:
        assert restored.execute("SELECT name FROM schools WHERE id=1").fetchone()[0]=="Fictional Demo School"
    assert (destination/"evidence"/"1"/"sample.bin").read_bytes()==b"example private evidence"
    assert (destination/"letters"/"1"/"approved.pdf").read_bytes().startswith(b"%PDF")
    # Restores must never overwrite existing data.
    second=subprocess.run([sys.executable,"scripts/verify_backup_bundle.py",str(bundle),str(destination)],
                          cwd=ROOT,capture_output=True,text=True,timeout=30)
    assert second.returncode!=0
