"""Fast homepage screen of a ranked domain list (Tranco top-1M) for storefront signals.

One robots.txt check + one homepage GET per domain. Store-like or bot-walled domains are queued as
candidates (priority by rank) for the full verifier; everything else is recorded in `screen` with a reason.
Resumable: screened domains are skipped. Shard with --shard i --shards n to run several processes.

  python3 -m mktecom.screen --start 1 --end 200000 --concurrency 200 --shard 0 --shards 2
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import os
import re
import time
import urllib.robotparser
from collections import Counter
from urllib.parse import urlsplit

import httpx

from . import db
from . import signals as S
from .common import DEFAULT_HEADERS, NON_STORE_ROOTS, MARKETPLACE_ROOTS, identity, registrable_domain
from .market import M

TRANCO = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "top-1m.csv")
CHALLENGE = re.compile(r"just a moment\.\.\.|cf-chl|challenge-platform/h/|attention required! \| cloudflare|access denied|"
                       r"request could not be satisfied|pardon our interruption|captcha|are you a robot|incapsula|perimeterx|px-captcha|"
                       r"distil|ddos-guard|sucuri website firewall|_Incapsula_Resource|akamai|reference #\d", re.I)
COMMERCE = {"shopify", "woocommerce", "magento", "salesforce-commerce", "sap-hybris", "bigcommerce", "opencart", "prestashop",
            "volusion", "shift4shop", "miva", "zen-cart", "bigcartel", "ecwid", "lightspeed", "vtex", "oracle-commerce", "commercetools"}
SKIP_FOREIGN = re.compile(r"\.(?:ru|cn|jp|de|fr|it|es|nl|pl|br|in|ir|kr|tw|vn|id|tr|cz|ua|hu|ro|gr|sk|pt|se|no|dk|fi|be|ch|at|ar|cl|co|mx|pe|za|"
                          r"by|kz|th|my|ph|hk|sg|il|eg|sa|ae|pk|bd|lk|ng|ke|rs|hr|si|bg|lt|lv|ee|su|uz|az|ge|am|md|ba|mk|al|is|lu)$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS screen (
  domain TEXT PRIMARY KEY, rank INTEGER, status TEXT, reason TEXT, platform TEXT, final_url TEXT,
  signals TEXT, ts TEXT
);
CREATE INDEX IF NOT EXISTS idx_screen_status ON screen(status);
"""


def priority_for(rank: int) -> int:
    if rank <= 10_000:
        return 9
    if rank <= 50_000:
        return 8
    if rank <= 200_000:
        return 6
    if rank <= 500_000:
        return 4
    return 3


def classify(html: str, final: str):
    a_text = S.visible_text(html, 300000)
    plat = S.detect_platform(html, final)
    types, ld_cur = S.jsonld_types(html)
    n_links = len(set(m.group(0) for m in S.PRODUCT_LINK.finditer(html[:1_000_000])))
    atc = len(S.ADD_TO_CART.findall(html[:1_000_000]))
    cart = len(S.CART_CHECKOUT.findall(html[:1_000_000]))
    prices = len(S.PRICE_ANY.findall(a_text))
    usd = bool(S.LOCAL_CURRENCY_CODE.search(html[:800000])) or M.currency in ld_cur
    sig = f"plat={plat} links={n_links} atc={atc} cart={cart} prices={prices} usd={int(usd)}"
    store = ((plat in COMMERCE and (plat == "shopify" or atc >= 1 or prices >= 2 or n_links >= 3 or cart >= 2))
             or "Product" in types or "Offer" in types or (atc >= 1 and (n_links >= 2 or prices >= 2))
             or (cart >= 2 and prices >= 3) or (n_links >= 5 and (cart >= 1 or prices >= 2 or atc >= 1))
             or (plat in ("wix", "squarespace", "square") and (prices >= 2 or cart >= 1)))
    thin = len(a_text) < 1200 and html.count("<script") >= 3
    return store, thin, plat, sig, usd


async def main(start, end, concurrency, shard, shards, wide_skip_foreign):
    from concurrent.futures import ThreadPoolExecutor
    asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max(64, concurrency)))
    con = db.connect()
    con.executescript(SCHEMA)
    db.register_source(con, "tranco", "ranking", "Tranco top-1M list (all TLDs), homepage screen for storefront signals")
    done = {r[0] for r in con.execute("SELECT domain FROM screen")}
    todo = []
    with open(TRANCO) as fh:
        for rank_s, dom in csv.reader(fh):
            rank = int(rank_s)
            if rank < start or rank > end or (rank % shards) != shard:
                continue
            dom = dom.strip().lower()
            if dom in done:
                continue
            todo.append((rank, dom))
    print(f"[screen{shard}] {len(todo)} domains to screen", flush=True)
    limits = httpx.Limits(max_connections=concurrency * 2, max_keepalive_connections=20)
    client = httpx.AsyncClient(headers=DEFAULT_HEADERS, follow_redirects=True, limits=limits, verify=False,
                               timeout=httpx.Timeout(15.0, connect=7.0))
    sem = asyncio.Semaphore(concurrency)
    stats = Counter()
    buf_screen, buf_cand = [], []
    t0 = time.time()

    async def get(url, cap=900_000):
        async with client.stream("GET", url) as r:
            chunks, size = [], 0
            async for ch in r.aiter_bytes():
                chunks.append(ch)
                size += len(ch)
                if size >= cap:
                    break
            body = b"".join(chunks)
            try:
                txt = body.decode(r.encoding or "utf-8", errors="replace")
            except LookupError:
                txt = body.decode("utf-8", errors="replace")
            return r.status_code, str(r.url), txt

    def flush():
        nonlocal buf_screen, buf_cand
        if buf_cand:
            for u, pr, det in buf_cand:
                db.add_candidates(con, [(u, pr)], source="tranco", detail=det)
        if buf_screen:
            for _ in range(10):
                try:
                    con.execute("BEGIN IMMEDIATE")
                    con.executemany("INSERT OR REPLACE INTO screen VALUES (?,?,?,?,?,?,?,?)", buf_screen)
                    con.execute("COMMIT")
                    break
                except Exception:
                    try:
                        con.execute("ROLLBACK")
                    except Exception:
                        pass
                    time.sleep(1)
        buf_screen, buf_cand = [], []

    async def one(rank, dom):
        ts = db.now()
        ident = identity(dom)
        root = registrable_domain(dom)
        if not ident or root in NON_STORE_ROOTS:
            buf_screen.append((dom, rank, "skipped", "non_store_or_infra_domain", None, None, None, ts))
            return
        if root in MARKETPLACE_ROOTS:
            buf_screen.append((dom, rank, "skipped", "marketplace: " + MARKETPLACE_ROOTS[root], None, None, None, ts))
            buf_cand.append((dom, priority_for(rank), f"rank {rank}"))
            return
        if wide_skip_foreign and rank > 200_000 and SKIP_FOREIGN.search(root):
            buf_screen.append((dom, rank, "skipped", "foreign_cctld_beyond_top200k", None, None, None, ts))
            return
        async with sem:
            base = f"https://{dom}"
            try:
                allowed = True
                try:
                    st, _, rtxt = await asyncio.wait_for(get(base + "/robots.txt", 200_000), 12)
                    if st == 200 and "<html" not in rtxt[:300].lower():
                        rp = urllib.robotparser.RobotFileParser()
                        rp.parse(rtxt.splitlines())
                        allowed = rp.can_fetch("*", base + "/") or rp.can_fetch(DEFAULT_HEADERS["User-Agent"], base + "/")
                except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                    if "Name or service not known" in str(e) or "No address" in str(e):
                        buf_screen.append((dom, rank, "dead", "dns_not_resolved", None, None, None, ts))
                        stats["dead"] += 1
                        return
                except Exception:
                    pass
                if not allowed:
                    buf_screen.append((dom, rank, "robots", "robots_disallows_homepage", None, None, None, ts))
                    stats["robots"] += 1
                    return
                try:
                    st, final, html = await asyncio.wait_for(get(base + "/"), 20)
                except (httpx.ConnectError, httpx.ConnectTimeout, asyncio.TimeoutError, httpx.ReadTimeout):
                    st, final, html = await asyncio.wait_for(get(f"https://www.{dom}/"), 20)
            except Exception as e:
                buf_screen.append((dom, rank, "dead", f"fetch_failed:{type(e).__name__}", None, None, None, ts))
                stats["dead"] += 1
                return
        fid = identity(final)
        if st in (401, 403, 429, 503) or (st >= 400 and CHALLENGE.search(html[:6000])) or (st == 200 and len(html) < 30000 and CHALLENGE.search(html[:6000]) and "<title" in html[:3000].lower()):
            buf_screen.append((dom, rank, "blocked", f"http_{st}", None, final, None, ts))
            stats["blocked"] += 1
            if False:
                buf_cand.append((final if fid else dom, max(priority_for(rank) - 2, 1), f"rank {rank} (blocked http_{st})"))
            return
        if st >= 400:
            buf_screen.append((dom, rank, "dead", f"http_{st}", None, final, None, ts))
            stats["dead"] += 1
            return
        store, thin, plat, sig, usd = classify(html, final)
        if store:
            pr = priority_for(rank) + (1 if usd else 0)
            buf_screen.append((dom, rank, "store_like", "", plat, final, sig, ts))
            buf_cand.append((final if fid else dom, pr, f"rank {rank}; {sig}"))
            stats["store_like"] += 1
        elif thin:
            buf_screen.append((dom, rank, "thin", "js_or_thin_homepage", plat, final, sig, ts))
            stats["thin"] += 1
            if False:
                buf_cand.append((final if fid else dom, max(priority_for(rank) - 3, 1), f"rank {rank} (thin homepage)"))
        else:
            buf_screen.append((dom, rank, "not_store", "no_storefront_signals_on_homepage", plat, final, sig, ts))
            stats["not_store"] += 1

    # interleave work in rank order across worker coroutines
    q: asyncio.Queue = asyncio.Queue()
    for it in todo:
        q.put_nowait(it)

    async def worker():
        while not q.empty():
            rank, dom = q.get_nowait()
            try:
                await asyncio.wait_for(one(rank, dom), 60)
            except Exception as e:
                buf_screen.append((dom, rank, "dead", f"screen_error:{type(e).__name__}", None, None, None, db.now()))
            stats["n"] += 1

    async def reporter():
        last = 0
        while True:
            await asyncio.sleep(30)
            flush()
            el = time.time() - t0
            info = dict(stats) | {"per_min": round(stats["n"] / (el / 60), 1), "left": q.qsize()}
            print(f"[screen{shard}] {info}", flush=True)
            db.heartbeat(con, f"screen:{shard}", "code-worker(asyncio)", concurrency, info)

    import warnings
    warnings.filterwarnings("ignore")
    rep = asyncio.create_task(reporter())
    await asyncio.gather(*[worker() for _ in range(concurrency)])
    rep.cancel()
    flush()
    print(f"[screen{shard}] finished {dict(stats)}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--end", type=int, default=200_000)
    ap.add_argument("--concurrency", type=int, default=200)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--no-skip-foreign", action="store_true")
    a = ap.parse_args()
    asyncio.run(main(a.start, a.end, a.concurrency, a.shard, a.shards, not a.no_skip_foreign))
