"""Re-evaluate stored secondary evidence: re-run the (tightened) SEC EDGAR check where it was positive and re-apply the verdict rule.

  python3 -m mktecom.recompute_secondary
"""
import asyncio
import json
import warnings

import httpx

from . import db, secondary as S
from .reference import connect


def verdict_of(evs):
    ok = {e["type"] for e in evs if e.get("ok")}
    return "verified_secondary_evidence" if len(ok) >= 2 and (ok & S.STOREFRONT_TYPES or "sec_edgar" in ok or {"app_store", "google_play"} <= ok) else "insufficient_secondary_evidence"


async def main():
    warnings.filterwarnings("ignore")
    con = connect()
    rows = con.execute("SELECT s.key, s.prefix, s.verdict, s.evidence, r.name, r.root_domain FROM secondary_evidence s LEFT JOIN reference_stores r USING(key)").fetchall()
    changed = 0
    async with httpx.AsyncClient(follow_redirects=True) as live:
        for key, prefix, old, ev, name, root in rows:
            evs = json.loads(ev)
            if any(e["type"] == "sec_edgar" and e.get("ok") for e in evs):
                new_e = await S.sec_edgar(live, name or key, root or key.split("|")[0])
                evs = [new_e if e["type"] == "sec_edgar" else e for e in evs]
            v = verdict_of(evs)
            if v == old and not any(e["type"] == "sec_edgar" for e in evs):
                continue
            item = {"key": key, "name": name or key, "root": root}
            if v == "verified_secondary_evidence":
                S.save(con, item, {"key": key, "prefix": prefix, "verdict": v, "evidence": evs})
            else:
                con.execute("INSERT OR REPLACE INTO secondary_evidence VALUES(?,?,?,?,?)", (key, prefix, v, json.dumps(evs), db.now()))
                if old == "verified_secondary_evidence":
                    con.execute("UPDATE verifications SET status='unverified', reason='secondary_evidence_insufficient_after_recheck', method=NULL WHERE key=? AND status='verified_secondary_evidence'", (key,))
                    con.execute("UPDATE candidates SET status='unverified' WHERE key=?", (key,))
            if v != old:
                changed += 1
                print(key, old, "->", v, flush=True)
    print("changed", changed)


if __name__ == "__main__":
    asyncio.run(main())
