"""Wayback Machine CDX host enumeration for the market ccTLD (hosts with captures since --since).

The public CDX API refuses paged domain queries, so each stream walks its slice of the SURT keyspace with
crafted resume keys: one request returns up to --batch distinct URLs, every registrable domain in the batch
becomes a candidate, and the next request starts after the last domain's whole subtree ("<surt>,~").
Streams are split by the first character of the second-level label; progress per stream is kept in jobs
(kind wayback_hosts), so a restart continues where it stopped.

  ECOM_MARKET=qatar python3 -m market_ecom.discover_wayback [--streams 4] [--since 2025]
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import random
import string
import zlib

import httpx

from . import db
from .common import registrable_domain
from .market import M

CDX = "https://web.archive.org/cdx/search/cdx"
CHARS = string.digits + string.ascii_lowercase


def rkey(surt: str) -> str:
    return base64.urlsafe_b64encode(zlib.compress(f"{surt} 99999999999999".encode())).decode().rstrip("=")


def slices():
    """(name, start_surt, stop_prefix) covering qa,<x>... ; the com.<tld> branch gets its own per-character slices."""
    t = M.tld
    out = []
    for ch in CHARS:
        out.append((f"{t},{ch}", f"{t},{ch}", f"{t},{ch}"))
    for ch in CHARS:
        out.append((f"{t},com,{ch}", f"{t},com,{ch}", f"{t},com,{ch}"))
    return out


def surt_host(urlkey: str) -> str:
    return urlkey.split(")", 1)[0]


def host_of(surt: str) -> str:
    return ".".join(reversed(surt.split(",")))


async def walk(client, con, name, start, stop, since, batch, gap, stats):
    row = con.execute("SELECT status, info FROM jobs WHERE kind='wayback_hosts' AND job=?", (name,)).fetchone()
    if row and row[0] == "done":
        return
    cur = row[1] if row and row[1] else start
    com_branch = f"{M.tld},com,"
    total = new_total = 0
    while True:
        params = {"url": f"zzzzzzzz.{M.tld}", "matchType": "domain", "fl": "urlkey", "collapse": "urlkey", "limit": str(batch),
                  "from": since, "filter": "statuscode:200", "resumeKey": rkey(cur)}
        text = None
        for attempt in range(6):
            try:
                r = await client.get(CDX, params=params, timeout=120)
                if r.status_code == 200 and "Temporarily Offline" not in r.text[:2000]:
                    text = r.text
                    break
                stats["http_" + str(r.status_code)] += 1
            except httpx.HTTPError as e:
                stats[type(e).__name__] += 1
            await asyncio.sleep(min(120, 8 * 2 ** attempt) + random.random() * 3)
        if text is None:
            db.mark_job(con, "wayback_hosts", name, "partial", total, new_total, cur)
            con.commit()
            print(f"[wayback] {name} giving up for now at {cur}", flush=True)
            return
        keys = [l.split(" ")[0] for l in text.splitlines() if l and not l.startswith("eJ")]
        hosts, last_reg = [], None
        finished = not keys
        for k in keys:
            s = surt_host(k)
            if not s.startswith(stop):
                finished = True
                break
            if name == f"{M.tld},c" and s.startswith(com_branch):
                continue
            h = host_of(s).split(":")[0]
            reg = registrable_domain(h)
            if reg:
                hosts.append(reg)
                last_reg = reg
        uniq = sorted(set(hosts))
        n = db.add_candidates(con, [(f"https://{h}/", 2) for h in uniq], "wayback:cdx", f"{M.tld} hosts since {since}") if uniq else 0
        total += len(set(hosts))
        new_total += n
        stats["requests"] += 1
        stats["hosts"] += len(set(hosts))
        stats["new"] += n
        if finished:
            db.mark_job(con, "wayback_hosts", name, "done", total, new_total, cur)
            con.commit()
            print(f"[wayback] {name} done hosts={total} new={new_total} {dict(stats)}", flush=True)
            return
        if name == f"{M.tld},c" and keys and surt_host(keys[-1]).startswith(com_branch):
            nxt = f"{M.tld},com-"
        elif last_reg:
            nxt = ",".join(reversed(last_reg.split("."))) + ",~"
        else:
            nxt = surt_host(keys[-1]) + ",~"
        if nxt <= cur:
            nxt = cur + "~"
        cur = nxt
        db.mark_job(con, "wayback_hosts", name, "partial", total, new_total, cur)
        con.commit()
        if stats["requests"] % 20 == 0:
            print(f"[wayback] {name} at {cur} {dict(stats)}", flush=True)
        await asyncio.sleep(gap + random.random())


async def main(streams, since, batch, gap):
    con = db.connect()
    db.register_source(con, "wayback:cdx", "index", f"Wayback Machine CDX host walk over *.{M.tld} (captures since {since})")
    db.heartbeat(con, "discover_wayback", "code-worker(asyncio)", streams, {"since": since})
    stats = __import__("collections").Counter()
    sem = asyncio.Semaphore(streams)
    async with httpx.AsyncClient(headers=M.ua_research, follow_redirects=True) as client:
        async def one(sl):
            async with sem:
                await walk(client, con, *sl, since, batch, gap, stats)
        await asyncio.gather(*(one(s) for s in slices()))
    print("[wayback] finished", dict(stats), flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--streams", type=int, default=4)
    ap.add_argument("--since", default="2025")
    ap.add_argument("--batch", type=int, default=1500)
    ap.add_argument("--gap", type=float, default=4.0)
    a = ap.parse_args()
    asyncio.run(main(a.streams, a.since, a.batch, a.gap))
