"""Consistent DB snapshot (SQLite backup API) -> data/<market>_ecom.sqlite.gz for committing."""
import gzip, os, shutil, sqlite3
from . import db
from .market import M


def main():
    src = sqlite3.connect(db.DB_PATH, timeout=120)
    d = os.path.dirname(db.DB_PATH)
    tmp = os.path.join(d, "snapshot.sqlite")
    out = os.path.join(d, f"{M.code}_ecom.sqlite.gz")
    if os.path.exists(tmp):
        os.remove(tmp)
    dst = sqlite3.connect(tmp)
    src.backup(dst)
    # cat_text (page text kept for re-categorisation) dominates the size; the live DB keeps it.
    dst.execute("UPDATE verifications SET cat_text=NULL")
    dst.commit()
    dst.execute("VACUUM")
    dst.close(); src.close()
    with open(tmp, "rb") as fi, gzip.open(out + ".tmp", "wb", compresslevel=6) as fo:
        shutil.copyfileobj(fi, fo)
    os.replace(out + ".tmp", out)
    os.remove(tmp)
    print("snapshot written", out, os.path.getsize(out))


if __name__ == "__main__":
    main()
