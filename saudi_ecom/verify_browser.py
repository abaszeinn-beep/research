"""Second-pass verifier using headless Chromium (Playwright) for JS-rendered or bot-gated pages.

Takes candidates whose HTTP verification ended as unverified for JS/thin-page or
blocked/challenge reasons, renders HTML pages in a real browser (no CAPTCHA solving; if a
challenge persists the candidate stays unverified), and re-runs the same analysis.
"""
from __future__ import annotations

import argparse
import asyncio
import re
import time
import warnings
from urllib.parse import urlsplit

from playwright.async_api import async_playwright

from . import db
from .verify import Fetcher, verify_one, save, CHALLENGE

REASONS = ("js_rendered_or_thin_page%", "partial_ecommerce_evidence_js_page%", "fetch_failed:http_error%", "insufficient_ecommerce_evidence%", "fetch_failed:timeout%")


class BrowserFetcher(Fetcher):
    def __init__(self, browser, concurrency):
        super().__init__(concurrency * 4, 2)
        self.browser = browser
        self.page_sem = asyncio.Semaphore(concurrency)

    async def get(self, url, headers=None, tries=2, check_robots=True):
        if headers or re.search(r"\.(?:json|xml|txt)(?:\?|$)|/wp-json/|api\.", url):
            return await super().get(url, headers, tries, check_robots)
        if check_robots and not await self.allowed(url):
            return None, url, "", {}, "robots_disallowed"
        async with self.page_sem:
            ctx = await self.browser.new_context(locale="ar-SA", timezone_id="Asia/Riyadh",
                                                 user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                                                 viewport={"width": 1366, "height": 900})
            page = await ctx.new_page()
            try:
                resp = await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=12000)
                except Exception:
                    pass
                html = await page.content()
                if CHALLENGE.search(html[:6000]):
                    await page.wait_for_timeout(8000)
                    html = await page.content()
                st = resp.status if resp else 200
                if st in (403, 503) and not CHALLENGE.search(html[:6000]) and len(html) > 20000:
                    st = 200
                self.stats["browser_pages"] += 1
                return st, page.url, html, {}, None
            except Exception as e:
                return None, url, "", {}, f"browser_error:{type(e).__name__}"
            finally:
                await ctx.close()


async def main(concurrency, limit, keys):
    warnings.filterwarnings("ignore")
    con = db.connect()
    if keys:
        rows = [dict(zip(("key", "url", "root_domain", "platform_hint"), r)) for r in con.execute(
            f"SELECT key,url,root_domain,platform_hint FROM candidates WHERE key IN ({','.join('?' * len(keys))})", keys)]
    else:
        cond = " OR ".join("v.reason LIKE ?" for _ in REASONS)
        rows = [dict(zip(("key", "url", "root_domain", "platform_hint"), r)) for r in con.execute(
            f"SELECT c.key,c.url,c.root_domain,c.platform_hint FROM candidates c JOIN verifications v USING(key) "
            f"WHERE c.status='unverified' AND (v.method IS NULL OR v.method='http') AND ({cond}) ORDER BY c.priority DESC LIMIT ?",
            (*REASONS, limit))]
    print(f"[browser] {len(rows)} candidates", flush=True)
    db.heartbeat(con, "verify_browser", "code-worker(playwright)", concurrency, {"todo": len(rows)})
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        f = BrowserFetcher(browser, concurrency)
        sem = asyncio.Semaphore(concurrency)
        stats = {}

        async def one(c):
            async with sem:
                try:
                    res = await asyncio.wait_for(verify_one(f, c), 300)
                except Exception as e:
                    res = {"key": c["key"], "final_url": c["url"], "status": "unverified", "reason": f"browser_verifier_error:{type(e).__name__}", "verified_at": db.now(), "evidence_url": c["url"]}
                res["method"] = "browser"
                save(con, res)
                stats[res["status"]] = stats.get(res["status"], 0) + 1
                n = sum(stats.values())
                if n % 20 == 0:
                    print(f"[browser] {n}/{len(rows)} {stats}", flush=True)
                    db.heartbeat(con, "verify_browser", "code-worker(playwright)", concurrency, stats)

        await asyncio.gather(*[one(c) for c in rows])
        await browser.close()
    print("[browser] done", stats, flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--limit", type=int, default=5000)
    ap.add_argument("--keys", nargs="*")
    a = ap.parse_args()
    asyncio.run(main(a.concurrency, a.limit, a.keys))
