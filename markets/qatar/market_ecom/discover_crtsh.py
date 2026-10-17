"""Certificate-transparency discovery via crt.sh JSON (hosts under the market ccTLD). Resumable per query."""
from __future__ import annotations

import argparse
import json
import time

import httpx

from . import db
from .market import M


def main(queries):
    con = db.connect()
    db.register_source(con, "crtsh", "index", f"crt.sh certificate transparency search for *.{M.tld} hosts")
    with httpx.Client(headers=M.ua_research, timeout=300) as c:
        for q in queries:
            if db.job_done(con, "crtsh", q):
                continue
            data = None
            for attempt in range(4):
                try:
                    r = c.get("https://crt.sh/", params={"q": q, "output": "json", "exclude": "expired"})
                    if r.status_code == 200:
                        data = json.loads(r.text)
                        break
                    print(f"[crtsh] {q} http {r.status_code}", flush=True)
                except (httpx.HTTPError, ValueError) as e:
                    print(f"[crtsh] {q} error {type(e).__name__}", flush=True)
                time.sleep(4 * 2 ** attempt)
            if data is None:
                db.mark_job(con, "crtsh", q, "failed")
                continue
            hosts = set()
            for row in data:
                for h in (row.get("name_value") or "").split("\n"):
                    h = h.strip().lstrip("*.").lower()
                    if h and M.is_cctld_host(h):
                        hosts.add(h)
            n = db.add_candidates(con, [(f"https://{h}/", 2) for h in hosts], "crtsh", q)
            db.mark_job(con, "crtsh", q, "done", len(hosts), n)
            print(f"[crtsh] {q}: hosts={len(hosts)} new={n}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", default=f"%.com.{M.tld},%.net.{M.tld},%.{M.tld}")
    main(ap.parse_args().queries.split(","))
