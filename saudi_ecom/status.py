"""Print pipeline progress metrics and store a snapshot in the metrics table."""
import json
from . import db

def snapshot(con):
    q = lambda s: con.execute(s).fetchall()
    d = {
        "ts": db.now(),
        "candidates_by_status": dict(q("SELECT status,count(*) FROM candidates GROUP BY 1")),
        "candidates_total": q("SELECT count(*) FROM candidates")[0][0],
        "by_platform_hint": dict(q("SELECT coalesce(platform_hint,'independent'),count(*) FROM candidates GROUP BY 1")),
        "verified_by_platform": dict(q("SELECT platform,count(*) FROM verifications WHERE status='verified' GROUP BY 1 ORDER BY 2 DESC")),
        "first_source_yield": [list(r) for r in q("SELECT c.first_source, count(*), sum(c.status='verified') FROM candidates c GROUP BY 1 ORDER BY 3 DESC")],
        "queries_done": dict(q("SELECT engine||':'||status,count(*) FROM queries GROUP BY 1")),
        "cc_jobs": dict(q("SELECT status,count(*) FROM jobs WHERE kind='cc' GROUP BY 1")),
        "top_reasons": [list(r) for r in q("SELECT status, substr(reason,1,50) r, count(*) FROM verifications WHERE status!='verified' GROUP BY 1,2 ORDER BY 3 DESC LIMIT 15")],
        "verifications_last_10min": q("SELECT count(*) FROM verifications WHERE verified_at > strftime('%Y-%m-%dT%H:%M:%SZ','now','-10 minutes')")[0][0],
        "workers": [list(r) for r in q("SELECT name,kind,concurrency,heartbeat FROM workers")],
    }
    con.execute("INSERT INTO metrics VALUES (?,?)", (d["ts"], json.dumps(d, ensure_ascii=False)))
    return d

if __name__ == "__main__":
    print(json.dumps(snapshot(db.connect()), ensure_ascii=False, indent=1))
