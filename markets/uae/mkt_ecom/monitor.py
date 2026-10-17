"""Every N seconds: snapshot metrics into the DB and append a compact line to logs/progress_metrics.jsonl."""
import json, os, sys, time
from . import db
from .status import snapshot

def main(interval=600):
    path = os.path.join(os.path.dirname(__file__), "..", "logs", "progress_metrics.jsonl")
    while True:
        con = db.connect()
        d = snapshot(con)
        line = {"ts": d["ts"], "candidates": d["candidates_total"], "status": d["candidates_by_status"],
                "verified_by_platform": d["verified_by_platform"], "verifications_last_10min": d["verifications_last_10min"],
                "queries": d["queries_done"], "cc_jobs": d["cc_jobs"]}
        with open(path, "a") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
        print(json.dumps(line, ensure_ascii=False), flush=True)
        con.close()
        time.sleep(interval)

if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 600)
