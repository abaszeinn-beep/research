"""Consistent DB snapshot (SQLite backup API) -> data/saudi_ecom.sqlite.gz for committing."""
import gzip, os, shutil, sqlite3
from . import db

def main():
    src = sqlite3.connect(db.DB_PATH, timeout=120)
    tmp = os.path.join(os.path.dirname(db.DB_PATH), "snapshot.sqlite")
    dst = sqlite3.connect(tmp)
    src.backup(dst)
    dst.execute("VACUUM")
    dst.close(); src.close()
    with open(tmp, "rb") as fi, gzip.open(tmp.replace("snapshot.sqlite", "saudi_ecom.sqlite.gz"), "wb", compresslevel=9) as fo:
        shutil.copyfileobj(fi, fo)
    os.remove(tmp)
    print("snapshot written", os.path.getsize(tmp.replace("snapshot.sqlite", "saudi_ecom.sqlite.gz")))

if __name__ == "__main__":
    main()
