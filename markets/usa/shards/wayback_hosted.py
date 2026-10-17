"""Wayback CDX discovery of platform-hosted store subdomains (evenly sampled CDX pages, resumable)."""
from __future__ import annotations

import argparse
import asyncio
import random

import httpx

from . import db
from .common_us import identity

API = "https://web.archive.org/cdx/search/cdx"
DOMAINS = ["bigcartel.com", "mybigcommerce.com", "square.site", "company.site", "3dcartstores.com", "myvolusion.com", "ecwid.com"]


async def get(client, params, tries=5):
    delay = 5
    for _ in range(tries):
        try:
            r = await client.get(API, params=params, timeout=120)
            if r.status_code == 200:
                return r.text
        except httpx.HTTPError:
            pass
        await asyncio.sleep(delay + random.random() * 3)
        delay = min(delay * 2, 60)
    return None


async def main(samples, concurrency, since):
    con = db.connect()
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(headers={"User-Agent": "usa-ecom-directory-research/1.0 (polite CDX client)"}) as client:
        async def page(dom, p):
            job = f"{dom}|{since}|{p}"
            if db.job_done(con, "wayback", job):
                return
            async with sem:
                txt = await get(client, {"url": dom, "matchType": "domain", "fl": "original", "from": since, "page": str(p),
                                         "filter": "statuscode:200"})
            if txt is None:
                db.mark_job(con, "wayback", job, "failed")
                return
            found = {}
            for line in txt.splitlines():
                ident = identity(line.strip())
                if ident and ident["root_domain"] == dom:
                    found.setdefault(ident["key"], {**ident, "priority": 1.5, "hits": 1, "sample_url": line.strip()})
            new = db.add_candidates(con, found.values(), source="wayback-cdx", detail=dom)
            db.mark_job(con, "wayback", job, "done", len(found), new)
            print(f"[wayback] {job} hosts={len(found)} new={new}", flush=True)

        for dom in DOMAINS:
            async with sem:
                txt = await get(client, {"url": dom, "matchType": "domain", "showNumPages": "true", "from": since})
            try:
                n = int((txt or "").strip())
            except ValueError:
                print(f"[wayback] cannot size {dom}", flush=True)
                continue
            pages = sorted(set(int(i * n / samples) for i in range(samples))) if n > samples else list(range(n))
            print(f"[wayback] {dom}: {n} pages, sampling {len(pages)}", flush=True)
            await asyncio.gather(*[page(dom, p) for p in pages])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=150)
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--since", default="2025")
    a = ap.parse_args()
    asyncio.run(main(a.samples, a.concurrency, a.since))
