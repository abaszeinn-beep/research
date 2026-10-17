"""Harvest merchant domains from public platform showcase / customer-story pages (robots.txt respected)."""
from __future__ import annotations

import asyncio
import re
import urllib.robotparser
from urllib.parse import urljoin, urlsplit

import httpx

from . import db
from .common_us import NON_STORE_ROOTS, identity

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
SEEDS = {
    "bigcommerce-showcase": ("https://www.bigcommerce.com/showcase/", r"https://www\.bigcommerce\.com/showcase/[a-z0-9-]+/"),
    "bigcommerce-case-studies": ("https://www.bigcommerce.com/case-study/case-study.xml", r"https://www\.bigcommerce\.com/case-study/[a-z0-9-]+/"),
    "salesforce-customer-stories": ("https://www.salesforce.com/customer-stories/", r"https://www\.salesforce\.com/customer-stories/[a-z0-9-]+/"),
    "woocommerce-showcase": ("https://woocommerce.com/showcase/?country=US", r"https://woocommerce\.com/showcase/[a-z0-9-]+/"),
}
DOMAIN = re.compile(r"(?<![@\w.-])((?:www\.)?[a-z0-9][a-z0-9-]{1,40}\.(?:com|us|net|co|shop|store))(?![\w-])", re.I)
SKIP = re.compile(r"bigcommerce|salesforce|woocommerce|commerce\.com|ctfassets|googleapis|gstatic|makeswift|feedonomics|wistia|"
                  r"youtube|linkedin|instagram|facebook|twitter|pinterest|tiktok|cloudfront|akamai|adobe|wordpress|jetpack|"
                  r"automattic|wp\.com|gravatar|typekit|hubspot|marketo|optimizely|segment|newrelic|onetrust|cookielaw|sentry|"
                  r"tableau|slack|mulesoft|heroku|demandware|force\.com|my\.site|trailhead|g2\.com|capterra|example\.com|schema", re.I)


async def main():
    con = db.connect()
    async with httpx.AsyncClient(headers={"User-Agent": UA}, follow_redirects=True, timeout=30) as c:
        robots = {}

        async def ok(u):
            base = "{0.scheme}://{0.netloc}".format(urlsplit(u))
            if base not in robots:
                rp = urllib.robotparser.RobotFileParser()
                try:
                    r = await c.get(base + "/robots.txt")
                    rp.parse(r.text.splitlines() if r.status_code == 200 else [])
                except httpx.HTTPError:
                    rp.parse([])
                robots[base] = rp
            return robots[base].can_fetch("*", u)

        for src, (seed, detail_rx) in SEEDS.items():
            if db.job_done(con, "showcase", src):
                continue
            pages, found = [seed], {}
            try:
                r = await c.get(seed)
                txt = r.text
            except httpx.HTTPError:
                continue
            pages += sorted(set(re.findall(detail_rx, txt)))[:400]
            sem = asyncio.Semaphore(4)

            async def grab(u):
                if not await ok(u):
                    return ""
                async with sem:
                    await asyncio.sleep(0.5)
                    try:
                        rr = await c.get(u)
                        return rr.text if rr.status_code == 200 else ""
                    except httpx.HTTPError:
                        return ""

            texts = await asyncio.gather(*[grab(u) for u in pages])
            for u, t in zip(pages, texts):
                for m in set(DOMAIN.findall(t)):
                    d = m.lower()
                    if SKIP.search(d):
                        continue
                    ident = identity("https://" + d)
                    if not ident or ident["root_domain"] in NON_STORE_ROOTS:
                        continue
                    found.setdefault(ident["key"], {**ident, "priority": 6, "hits": 1, "sample_url": u})
            new = db.add_candidates(con, found.values(), source="platform-showcase", detail=src)
            db.mark_job(con, "showcase", src, "done", len(found), new, f"{len(pages)} pages")
            print(f"[showcase] {src}: pages={len(pages)} domains={len(found)} new={new}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
