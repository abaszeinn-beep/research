"""Write the pending (unverified-yet) queue, ordered by verification priority, as a gzip TSV; or reload it into a DB."""
from __future__ import annotations

import argparse
import gzip
import os

from . import db
from .common_us import MARKETPLACE_ROOTS  # noqa: F401
from .export import OUT_DIR, load_tranco

PATH = os.path.join(OUT_DIR, "usa_other_platforms_pending_queue.tsv.gz")


def dump():
    con = db.connect()
    tr = load_tranco()
    with gzip.open(PATH, "wt", encoding="utf-8", compresslevel=9) as fh:
        fh.write("key\turl\troot_domain\tplatform_hint\tpriority\thits\ttranco_rank\n")
        n = 0
        for key, url, root, plat, pr, hits in con.execute(
                "SELECT key,url,root_domain,platform_hint,priority,hits FROM candidates WHERE status IN ('pending','in_progress') "
                "ORDER BY priority DESC, hits DESC"):
            fh.write(f"{key}\t{url}\t{root}\t{plat or ''}\t{pr:.1f}\t{hits}\t{tr.get(root, '')}\n")
            n += 1
    print("pending rows", n, os.path.getsize(PATH))


def load():
    con = db.connect()
    with gzip.open(PATH, "rt", encoding="utf-8") as fh:
        next(fh)
        rows = [l.rstrip("\n").split("\t") for l in fh]
    con.execute("BEGIN")
    con.executemany("INSERT OR IGNORE INTO candidates(key,url,root_domain,platform_hint,priority,hits,status) VALUES(?,?,?,?,?,?,'pending')",
                    [(r[0], r[1], r[2], r[3] or None, float(r[4]), int(r[5])) for r in rows])
    con.execute("COMMIT")
    print("loaded", len(rows))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", action="store_true")
    load() if ap.parse_args().load else dump()
