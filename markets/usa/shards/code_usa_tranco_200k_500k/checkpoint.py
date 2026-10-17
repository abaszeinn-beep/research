"""Checkpoint / restore the per-worker screening state so a VM restart resumes instead of starting over.

  python3 checkpoint.py save      # dump results (+ secondary) tables to markets/usa/shards/state_usa_tranco_200k_500k/*.jsonl.gz
  python3 checkpoint.py restore   # rebuild data/usa_tranco_200k_500k/*.sqlite from the dumps (only for missing DB files)
"""
from __future__ import annotations

import glob
import gzip
import json
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from pipeline import STATE, connect  # noqa: E402

CK = HERE.parent / "state_usa_tranco_200k_500k"
RCOLS = ["domain", "rank", "stage", "status", "reason", "row", "detail", "hint", "ts", "elapsed"]


def save():
    CK.mkdir(exist_ok=True)
    for p in sorted(glob.glob(str(STATE / "w*.sqlite"))):
        name = Path(p).stem
        con = sqlite3.connect(p, timeout=60)
        rows = con.execute(f"SELECT {','.join(RCOLS)} FROM results").fetchall()
        meta = dict(con.execute("SELECT k,v FROM meta").fetchall())
        con.close()
        tmp = CK / f"{name}.jsonl.gz.tmp"
        with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as fh:
            fh.write(json.dumps({"_meta": meta}) + "\n")
            for r in rows:
                fh.write(json.dumps(dict(zip(RCOLS, r)), ensure_ascii=False) + "\n")
        tmp.rename(CK / f"{name}.jsonl.gz")
        print(name, len(rows))
    sec = STATE / "secondary.sqlite"
    if sec.exists():
        con = sqlite3.connect(sec, timeout=60)
        rows = con.execute("SELECT domain,rank,score,row,detail,ts FROM secondary").fetchall()
        con.close()
        with gzip.open(CK / "secondary.jsonl.gz", "wt", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(dict(zip(["domain", "rank", "score", "row", "detail", "ts"], r)), ensure_ascii=False) + "\n")
        print("secondary", len(rows))


def restore():
    for p in sorted(glob.glob(str(CK / "w*.jsonl.gz"))):
        worker = int(Path(p).name.split(".")[0][1:])
        if (STATE / f"w{worker}.sqlite").exists():
            print(f"w{worker}: db exists, skipped")
            continue
        con = connect(worker)
        n = 0
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            for line in fh:
                d = json.loads(line)
                if "_meta" in d:
                    con.executemany("INSERT OR REPLACE INTO meta VALUES(?,?)", list(d["_meta"].items()))
                    continue
                con.execute(f"INSERT OR REPLACE INTO results VALUES({','.join('?' * len(RCOLS))})", [d[c] for c in RCOLS])
                n += 1
        con.commit()
        print(f"w{worker}: restored {n}")
    sp = CK / "secondary.jsonl.gz"
    if sp.exists() and not (STATE / "secondary.sqlite").exists():
        con = sqlite3.connect(STATE / "secondary.sqlite")
        con.execute("CREATE TABLE IF NOT EXISTS secondary(domain TEXT PRIMARY KEY, rank INT, score REAL, row TEXT, detail TEXT, ts TEXT)")
        with gzip.open(sp, "rt", encoding="utf-8") as fh:
            for line in fh:
                d = json.loads(line)
                con.execute("INSERT OR REPLACE INTO secondary VALUES(?,?,?,?,?,?)", [d[c] for c in ["domain", "rank", "score", "row", "detail", "ts"]])
        con.commit()


if __name__ == "__main__":
    {"save": save, "restore": restore}[sys.argv[1]]()
