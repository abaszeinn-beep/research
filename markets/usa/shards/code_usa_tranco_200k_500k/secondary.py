"""Secondary-evidence pass for domains whose homepage blocked the HTTP client (403 / bot wall) during screening.

Channel: a normal, headed Chromium (Playwright on the VM's X display) loading pages the way a visitor would.
No CAPTCHA or interactive challenge is solved and nothing is spoofed beyond a standard desktop browser; if a page
still shows a challenge after a normal wait it stays unverified ("bot wall persists in normal browser").
robots.txt (read through the browser) is honored for every non-homepage URL.

The same verification logic as the live pass (pipeline.verify_store) runs on browser-rendered pages: homepage,
platform endpoints (Shopify meta.json / products.json, WooCommerce Store API), a product page, sitemap,
shipping/contact page. A store needs two independent current proofs to become `verified_secondary_evidence`:
the browser-rendered storefront AND a product-level proof (platform product endpoint, a product page with price /
add-to-cart, or a sitemap listing product URLs) plus the usual US relevance rule (USD + a US location signal).

  DISPLAY=:1 python3 secondary.py --concurrency 8 [--limit N]
"""
from __future__ import annotations

import argparse
import asyncio
import glob
import json
import re
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[3]))
import pipeline as P  # noqa: E402

GENERIC_TLDS = {"com", "net", "org", "us", "shop", "store", "co", "io", "biz", "info", "online", "site", "xyz", "club", "life",
                "style", "boutique", "clothing", "fashion", "beauty", "jewelry", "shoes", "pet", "pets", "toys", "games", "golf",
                "bike", "fish", "coffee", "wine", "vip", "top", "app", "ai", "me", "tv", "cc", "us.com", "supply", "supplies",
                "tools", "parts", "auto", "health", "care", "farm", "garden", "kitchen", "furniture", "watch", "bar", "art",
                "gallery", "market", "deals", "sale", "direct", "world", "global", "plus", "inc", "llc", "company", "co.us"}
RETAIL_NAME = re.compile(r"shop|store|boutique|outlet|supply|supplies|wear|apparel|cloth|fashion|jewel|beauty|cosmetic|gear|"
                         r"mart|market|depot|goods|direct|warehouse|parts|tools|toys|home|decor|furniture|kitchen|pet|vape|"
                         r"coffee|tea|wine|candle|soap|skin|hair|shoe|boots|bag|watch|bike|golf|fish|hunt|outdoor|garden", re.I)


def tld_of(dom):
    parts = dom.split(".")
    return ".".join(parts[-2:]) if ".".join(parts[-2:]) in GENERIC_TLDS else parts[-1]


def targets(limit, include_429=False):
    out = []
    for p in sorted(glob.glob(str(P.STATE / "w*.sqlite"))):
        con = sqlite3.connect(p, timeout=60)
        for dom, rank, hint in con.execute("SELECT domain, rank, hint FROM results WHERE status='blocked'"):
            h = json.loads(hint or "{}")
            if h.get("http") == 429 and not include_429:
                continue
            if tld_of(dom) not in GENERIC_TLDS:
                continue
            score = 0.0
            if any(re.search("product", m, re.I) for m in h.get("sitemaps") or []):
                score += 3
            if h.get("platform") in P.COMMERCE_PLATFORMS:
                score += 3
            if RETAIL_NAME.search(dom.split(".")[0]):
                score += 1
            if dom.endswith((".com", ".us", ".shop", ".store")):
                score += 0.5
            out.append((score, rank, dom, h))
        con.close()
    out.sort(key=lambda x: (-x[0], x[1]))
    return out[:limit] if limit else out


class BrowserFetcher:
    """Same interface as pipeline.Fetcher.get, backed by one browser page (shared cookies within the domain's context)."""

    def __init__(self, page, stats):
        self.page = page
        self.stats = stats
        self.shopify_sem = asyncio.Semaphore(1)

    async def get(self, url, limit=P.HOME_BYTES, total=25, tries=1, headers=None):
        try:
            resp = await self.page.goto(url, timeout=min(total, 25) * 1000, wait_until="domcontentloaded")
        except Exception as e:
            msg = str(e)
            if "ERR_NAME_NOT_RESOLVED" in msg:
                return None, url, "", {}, "dns_not_resolved"
            if "Timeout" in msg:
                return None, url, "", {}, "timeout"
            return None, url, "", {}, f"browser_error:{msg[:60]}"
        self.stats["browser_requests"] += 1
        if resp is None:
            return None, url, "", {}, "no_response"
        hdrs = await resp.all_headers()
        ctype = hdrs.get("content-type", "")
        if "html" in ctype or not ctype:
            await self.page.wait_for_timeout(2500)
            try:
                text = await self.page.content()
            except Exception:
                await self.page.wait_for_timeout(2000)
                text = await self.page.content()
            if P.CHALLENGE.search(text[:8000]):
                await self.page.wait_for_timeout(7000)
                text = await self.page.content()
                self.stats["challenge_wait"] += 1
            status = resp.status
            if status in (403, 503) and not P.CHALLENGE.search(text[:8000]) and len(text) > 30000:
                status = 200
        else:
            try:
                text = (await resp.body())[:limit].decode("utf-8", "replace")
            except Exception:
                text = ""
            status = resp.status
        return status, self.page.url, text[:limit], hdrs, None


async def check(browser, dom, rank, hint, stats):
    ctx = await browser.new_context(locale="en-US", viewport={"width": 1366, "height": 900})
    await ctx.route(re.compile(r"\.(?:png|jpe?g|gif|webp|avif|svg|woff2?|ttf|mp4|webm)(?:\?|$)", re.I), lambda r: r.abort())
    page = await ctx.new_page()
    f = BrowserFetcher(page, stats)
    try:
        url = hint.get("final") or f"https://{dom}/"
        base = re.match(r"^(https?://[^/]+)", url).group(1)
        site = P.Site(f, base)
        st, final, html, hdrs, err = await f.get(base + "/")
        if st is None:
            return None, {"status": "error", "reason": f"browser:{err}"}
        if P.CHALLENGE.search(html[:8000]) or st in (401, 403, 429, 503):
            row = P.mk_row(dom, rank, canonical_storefront_url=base + "/", status="unverified", platform=hint.get("platform") or "",
                           verification_url=final, discovery_source=f"tranco_top1m:{P.TRANCO_ID}; normal_browser",
                           reason=f"bot wall persists in normal browser (HTTP {st}; interactive challenge not attempted); HTTP client: HTTP {hint.get('http')} {hint.get('server') or ''}".strip())
            store_like = hint.get("platform") in P.COMMERCE_PLATFORMS or any(re.search("product", m, re.I) for m in hint.get("sitemaps") or [])
            return (row if store_like else None), {"status": "still_blocked", "reason": row["reason"]}
        st_r, _, rtxt, _, _ = await f.get(base + "/robots.txt", total=15)
        if st_r == 200 and "<html" not in rtxt[:500].lower():
            import urllib.robotparser
            rp = urllib.robotparser.RobotFileParser()
            rp.parse(re.sub(r"<[^>]+>", "", rtxt).splitlines())
            site.rp = rp
            site.sitemaps = list(rp.site_maps() or [])
        st, final, html, hdrs, err = await f.get(base + "/")
        if st is None or st >= 400:
            return None, {"status": "error", "reason": f"browser_home_http_{st}:{err}"}
        c = P.cheap_signals(html, final, hdrs)
        if not P.is_hit(c):
            return None, {"status": "non_store", "reason": f"platform={c['platform']},atc={c['add_to_cart']},links={c['product_links']}"}
        row = await P.verify_store(site, dom, rank, final, html, hdrs, c)
        detail = row.pop("detail", {})
        row["discovery_source"] = f"tranco_top1m:{P.TRANCO_ID}; normal_browser"
        prefix = f"normal-browser evidence (HTTP client got {hint.get('http')} {hint.get('server') or ''}".rstrip() + ")"
        if row["status"] == "verified":
            proofs = ["browser-rendered storefront " + final]
            if detail.get("probe", {}).get("n"):
                proofs.append(f"{P.urljoin(base, '/products.json') if row['platform'] == 'shopify' else 'platform product API'}")
            if detail.get("product_page"):
                proofs.append("product page " + detail["product_page"]["url"])
            if detail.get("sitemap"):
                proofs.append("sitemap " + detail["sitemap"]["sitemap"])
            if len(proofs) >= 2:
                row["status"] = "verified_secondary_evidence"
                row["reason"] = f"{prefix}; proofs: {' | '.join(proofs[:3])}; {row['reason']}"
            else:
                row["status"] = "unverified"
                row["reason"] = f"{prefix}; only one proof (storefront) — {row['reason']}"
        else:
            row["reason"] = f"{prefix}; {row['reason']}"
        return row, {"status": row["status"], "detail": detail}
    finally:
        await ctx.close()


async def main(limit, concurrency, include_429):
    from playwright.async_api import async_playwright
    con = sqlite3.connect(P.STATE / "secondary.sqlite", timeout=60)
    con.execute("CREATE TABLE IF NOT EXISTS secondary(domain TEXT PRIMARY KEY, rank INT, score REAL, row TEXT, detail TEXT, ts TEXT)")
    done = {r[0] for r in con.execute("SELECT domain FROM secondary")}
    todo = [t for t in targets(limit, include_429) if t[2] not in done]
    print(f"[secondary] targets={len(todo)} done={len(done)}", flush=True)
    q: asyncio.Queue = asyncio.Queue()
    for t in todo:
        q.put_nowait(t)
    stats = Counter()
    t0 = time.time()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--disable-dev-shm-usage", "--no-first-run"])

        async def worker():
            nonlocal browser
            while True:
                try:
                    score, rank, dom, hint = q.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    row, det = await asyncio.wait_for(check(browser, dom, rank, hint, stats), 240)
                except Exception as e:
                    row, det = None, {"status": "error", "reason": f"{type(e).__name__}:{str(e)[:100]}"}
                    if not browser.is_connected():
                        browser = await p.chromium.launch(headless=False, args=["--disable-dev-shm-usage", "--no-first-run"])
                con.execute("INSERT OR REPLACE INTO secondary VALUES(?,?,?,?,?,?)",
                            (dom, rank, score, json.dumps(row, ensure_ascii=False) if row else None,
                             json.dumps(det, default=str, ensure_ascii=False)[:5000], P.now()))
                con.commit()
                stats["n"] += 1
                stats[det.get("status", "?")] += 1
                if stats["n"] % 50 == 0:
                    el = time.time() - t0
                    print(f"[secondary] {el/60:.1f}min rate={stats['n']/el*60:.0f}/min {dict(stats)}", flush=True)

        await asyncio.gather(*[worker() for _ in range(concurrency)])
        await browser.close()
    print(f"[secondary] finished {dict(stats)}", flush=True)


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--include-429", action="store_true")
    a = ap.parse_args()
    asyncio.run(main(a.limit, a.concurrency, a.include_429))
