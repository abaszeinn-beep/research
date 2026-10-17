#!/usr/bin/env python3
"""Secondary evidence for bot-walled ("challenged") domains, without bypassing anything.

Funnel per domain:
 1. robots.txt (served by most bot walls; fetched normally). Commerce paths (cart/checkout/
    basket/add-to-cart/product) mark the site as a probable store; otherwise it is dropped
    (counted, no row) because a bot wall alone says nothing about retail.
 2. Sitemaps listed in robots.txt (robots-allowed) -> product URLs. Proof A (live, current).
 3. Wayback Machine availability API for up to 3 product URLs + homepage -> raw archived
    capture (id_) within MAX_AGE_DAYS showing a product with price + ordering control.
    Proof B (archived storefront page, capture date stored).
 4. US relevance from archived pages (USD + US phone/address/shipping/shop country).
 Both proofs + US => verified_secondary_evidence; otherwise unverified with reason.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import us_signals as U  # noqa: E402
from worker import ATC_LOW, WORK, Net, canonical, iter_results, now_utc, registrable_domain, tier  # noqa: E402

MAX_AGE_DAYS = 365
ROBOTS_COMMERCE = re.compile(r"^\s*(?:dis)?allow:\s*\S*(?:/cart|/checkout|/basket|add-to-cart|add_to_cart|/my-account|/customer/account|"
                             r"/catalog/product|/products?/|/collections/|route=checkout|/orders)", re.I | re.M)
ROBOTS_PLATFORM = [("shopify", re.compile(r"we use shopify|/checkouts/|/\d+/checkouts", re.I)),
                   ("woocommerce", re.compile(r"add-to-cart|wp-admin", re.I)),
                   ("magento", re.compile(r"/catalog/product|/customer/account|/checkout/cart", re.I)),
                   ("bigcommerce", re.compile(r"/cart\.php|/checkout\.php|/finishorder\.php", re.I)),
                   ("salesforce-commerce", re.compile(r"demandware|/on/demandware", re.I))]
PRODUCT_LOC = re.compile(r"<loc>\s*(https?://[^<\s]{0,300}?(?:/products?/[^<\s]+|/p/[^<\s]+|/item/[^<\s]+|/pd/[^<\s]+|-p\d{3,}[^<\s]*|\.html))\s*</loc>", re.I)


class Wayback:
    def __init__(self, net: Net, conc: int, gap: float):
        self.net, self.sem, self.gap, self.last = net, asyncio.Semaphore(conc), gap, 0.0
        self.lock = asyncio.Lock()

    async def _pace(self):
        async with self.lock:
            wait = self.last + self.gap - time.monotonic()
            self.last = max(time.monotonic(), self.last + self.gap)
        if wait > 0:
            await asyncio.sleep(wait)

    async def closest(self, url: str):
        """Newest 200 capture of exactly this URL via the CDX API (fast for exact URLs)."""
        since = datetime.fromtimestamp(time.time() - MAX_AGE_DAYS * 86400, timezone.utc).strftime("%Y%m%d")
        async with self.sem:
            await self._pace()
            r = await self.net.get("https://web.archive.org/cdx/search/cdx?url=" + quote(url, safe="") +
                                   f"&filter=statuscode:200&fl=timestamp,original&from={since}&limit=-1",
                                   robots=False, timeout=30, tries=2)
        if r.status != 200 or not r.text.strip():
            return None
        parts = r.text.strip().splitlines()[-1].split(" ", 1)
        if len(parts) != 2 or not parts[0].isdigit():
            return None
        ts, orig = parts
        age = (datetime.now(timezone.utc) - datetime.strptime(ts[:8], "%Y%m%d").replace(tzinfo=timezone.utc)).days
        return {"ts": ts, "age": age, "orig": orig, "url": f"https://web.archive.org/web/{ts}/{orig}"}

    async def raw(self, ts: str, url: str):
        async with self.sem:
            await self._pace()
            r = await self.net.get(f"https://web.archive.org/web/{ts}id_/{url}", robots=False, timeout=40, tries=2, max_bytes=2_000_000)
        return r.text if r.status == 200 else ""


async def sitemap_products(net: Net, origin: str, maps):
    for sm in maps[:3]:
        r = await net.get(sm, timeout=15, max_bytes=3_000_000)
        if r.status != 200 or "<loc>" not in r.text:
            continue
        prods = PRODUCT_LOC.findall(r.text)
        children = re.findall(r"<sitemap>\s*<loc>\s*([^<\s]+)\s*</loc>", r.text, re.I)
        if prods and not children:
            return sm, prods
        named = [c for c in children if re.search(r"product", c, re.I)]
        for ch in (named or children[:1])[:2]:
            r2 = await net.get(ch, timeout=15, max_bytes=3_000_000)
            if r2.status == 200:
                locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", r2.text) if named else PRODUCT_LOC.findall(r2.text)
                locs = [x for x in locs if not re.search(r"\.(?:jpe?g|png|webp|gif)(?:\?|$)", x, re.I)]
                if len(locs) >= 3:
                    return ch, locs
    return None, []


async def process(net: Net, wb: Wayback, domain: str, rank: int, home_url: str):
    rec = {"d": domain, "r": rank, "src": "secondary"}
    origin = re.match(r"^https?://[^/]+", home_url or f"https://{domain}").group(0)
    rb = await net.get(origin + "/robots.txt", robots=False, timeout=10, tries=1, max_bytes=300_000)
    if rb.status != 200 or "<html" in rb.text[:500].lower() or U.CHALLENGE.search(rb.text[:3000]):
        rec["s"] = "sec_no_robots"
        return rec
    robots = rb.text
    if not ROBOTS_COMMERCE.search(robots):
        rec["s"] = "sec_not_store"
        return rec
    plat = next((p for p, rx in ROBOTS_PLATFORM if rx.search(robots)), "custom/unknown")
    maps = re.findall(r"^\s*sitemap:\s*(\S+)", robots, re.I | re.M) or [origin + "/sitemap.xml"]
    await net.load_robots(origin)
    sm, prods = await sitemap_products(net, origin, maps)
    proof_a = f"robots-allowed sitemap {sm} lists {len(prods)} product URLs (fetched {now_utc()})" if prods else ""

    proof_a = "; ".join(x for x in (f"live robots.txt has commerce paths ({len(ROBOTS_COMMERCE.findall(robots))} cart/checkout/product rules)", proof_a) if x)
    proof_b, b_url, pages, texts, b_age = "", "", [], [], None
    home_html = ""
    snap = await wb.closest(origin + "/")
    if snap:
        home_html = await wb.raw(snap["ts"], snap["orig"])
        if home_html:
            pages.append(home_html)
            texts.append(U.visible_text(home_html))
            if plat == "custom/unknown":
                plat = U.detect_platform(home_html, origin)
    cands = list(prods[:: max(1, len(prods) // 3)][:2]) if prods else []
    if home_html:
        links = [m.group(1) for m in U.PRODUCT_LINK.finditer(home_html[:900_000])]
        links = [re.sub(r"^https?://web\.archive\.org/web/\d+(?:id_)?/", "", l) for l in links]
        links = [l if l.startswith("http") else origin + "/" + l.lstrip("/") for l in links]
        links = [l for l in links if registrable_domain(re.sub(r"^https?://", "", l).split("/")[0]) == registrable_domain(domain)]
        cands += sorted(set(links), key=lambda u: (0 if re.search(r"/products?/", u) else 1, len(u)))[:2]
    for pu in cands[:3]:
        snap = await wb.closest(pu)
        if not snap:
            continue
        html = await wb.raw(snap["ts"], snap["orig"])
        if not html:
            continue
        types, _ = U.jsonld(html)
        low = html[:900_000].lower()
        txt = U.visible_text(html)
        has_price = bool(U.PRICE_USD.search(txt) or U.PRICE_OTHER.search(txt) or "pricecurrency" in low)
        if (types & {"Product", "ProductGroup"} or re.search(r"og:type[\"'][^>]*content=[\"']product", low)) and has_price and \
                (ATC_LOW.search(low) or plat == "shopify"):
            proof_b = f"Wayback capture {snap['ts'][:8]} ({snap['age']} days old) of product page with price + ordering control"
            b_url, b_age = snap["url"], snap["age"]
            pages.append(html)
            texts.append(txt)
            if plat == "custom/unknown":
                plat = U.detect_platform(html, pu)
            break
    if not proof_a and not proof_b and not home_html:
        rec["s"] = "sec_no_evidence"
        return rec
    decision, ev, why = U.us_signals(pages, texts, origin, {}) if pages else ("weak", {}, "no archived pages")
    if decision == "weak" and home_html:
        pol = [re.sub(r"^https?://web\.archive\.org/web/\d+(?:id_)?/", "", x) for x in
               re.findall(r"href=[\"']([^\"'#<>\s]{0,200}?(?:shipping|contact)[^\"'#<>\s]{0,60})[\"']", home_html[:900_000], re.I)]
        pol = [x if x.startswith("http") else origin + "/" + x.lstrip("/") for x in pol]
        for x in list(dict.fromkeys(pol))[:1]:
            snap = await wb.closest(x)
            if snap:
                h = await wb.raw(snap["ts"], snap["orig"])
                if h:
                    pages.append(h)
                    texts.append(U.visible_text(h))
        decision, ev, why = U.us_signals(pages, texts, origin, {})
    base_html = home_html or (pages[0] if pages else "")
    title = U.title_of(base_html)
    desc = U.meta(base_html, "description") or ""
    names = [U.title_of(p) for p in pages[:1]]
    cat = U.classify_category([title, desc, " ".join(names), texts[-1][:20000] if texts else ""], [3, 2, 3, 1])
    name = U.store_name(base_html, re.sub(r"^https?://", "", origin)) if base_html else domain.split(".")[0]
    if decision in ("non_us", "canada"):
        status, reason = "rejected", "not US-targeted (archived pages): " + why
    elif proof_a and proof_b and decision == "us":
        status, reason = "verified_secondary_evidence", f"live site bot-walled (HTTP 403 challenge, not bypassed); proof A: {proof_a}; proof B: {proof_b}; {why}"
    elif not prods and not proof_b and (U.SERVICE_TITLE.search(title) or not home_html):
        rec["s"] = "sec_no_evidence"
        return rec
    else:
        missing = [x for x, ok in (("live sitemap product URLs", proof_a), ("recent archived product page", proof_b), ("US relevance", decision == "us")) if not ok]
        status, reason = "unverified", "bot-walled; secondary evidence incomplete (missing: " + ", ".join(missing) + f"); {why}"
        if proof_a:
            reason += "; " + proof_a
        if proof_b:
            reason += "; " + proof_b
    if U.ADULT.search(title + " " + desc):
        status, reason = "rejected", "adult (out of scope)"
    rec["s"] = "hit"
    rec["row"] = {
        "store_name": name, "canonical_storefront_url": canonical(origin + "/"), "root_domain": registrable_domain(re.sub(r"^https?://", "", origin)),
        "platform": plat, "category": cat, "status": status,
        "us_evidence": "; ".join(f"{k}={v if not isinstance(v, list) else '|'.join(map(str, v))}" for k, v in ev.items()),
        "verification_url": b_url or (sm or origin + "/robots.txt"), "verification_utc": now_utc(),
        "discovery_source": "tranco_top1m_500001_1000000 (secondary evidence: robots/sitemap + Wayback)",
        "tranco_rank": rank, "reason": reason,
    }
    if b_age is not None:
        rec["wb_age"] = b_age
    return rec


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--concurrency", type=int, default=40)
    ap.add_argument("--wayback-concurrency", type=int, default=4)
    ap.add_argument("--wayback-gap", type=float, default=0.7)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--domains", default="")
    args = ap.parse_args()
    net = Net(args.concurrency, 4)
    await net.start()
    wb = Wayback(net, args.wayback_concurrency, args.wayback_gap)
    if args.domains:
        for d in args.domains.split(","):
            print(json.dumps(await process(net, wb, d, 0, f"https://{d}/"), ensure_ascii=False))
        await net.close()
        return
    out_path = os.path.join(WORK, "results_secondary.jsonl")
    done = {r["d"] for r in iter_results("results_secondary")}
    latest = {}
    for r in iter_results("results_w"):
        latest[r["d"]] = r
    for r in iter_results("results_shopify"):
        latest[r["d"]] = r
    items = sorted(((tier(d), r["r"], d, r.get("u", "")) for d, r in latest.items() if r.get("s") == "challenged" and d not in done))
    if args.limit:
        items = items[: args.limit]
    print(f"secondary: {len(items)} challenged domains to process", flush=True)
    q: asyncio.Queue = asyncio.Queue()
    for it in items:
        q.put_nowait(it)
    out = open(out_path, "a", buffering=1)
    cnt = Counter()
    t0 = time.time()

    async def runner():
        while True:
            try:
                _, rank, d, u = q.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                rec = await asyncio.wait_for(process(net, wb, d, rank, u), 400)
            except asyncio.TimeoutError:
                rec = {"d": d, "r": rank, "s": "sec_timeout"}
            except Exception as e:  # noqa: BLE001
                rec = {"d": d, "r": rank, "s": "sec_error", "e": f"{type(e).__name__}: {str(e)[:100]}"}
            rec["t"] = int(time.time())
            out.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
            cnt[rec["s"]] += 1
            if rec["s"] == "hit":
                cnt["row_" + rec["row"]["status"]] += 1

    async def reporter():
        while True:
            await asyncio.sleep(60)
            n = sum(v for k, v in cnt.items() if not k.startswith("row_"))
            print(f"[{now_utc()}] secondary done={n} rate={n / (time.time() - t0):.2f}/s remaining={q.qsize()} {dict(cnt)}", flush=True)

    rep = asyncio.create_task(reporter())
    await asyncio.gather(*(runner() for _ in range(args.concurrency)))
    rep.cancel()
    out.close()
    await net.close()
    print("secondary finished", dict(cnt), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
