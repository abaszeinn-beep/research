"""Secondary evidence for bot-walled / robots-blocked storefronts (no bypassing of the live site).

Evidence 1 (Common Crawl): a capture from the three most recent crawls of a product page on the store's host,
read from the public WARC file with a byte-range request: needs a USD/$ price plus add-to-cart / cart markers.
Evidence 2 (Wayback Machine): a capture within the last 180 days of the homepage (or a product page) with
cart/product markers and no parked/closed text.
US relevance is judged on the archived HTML with the same combined-signal rules as live verification.
Both evidence types + US verdict "verified" -> verified_secondary_evidence; otherwise the row stays unverified.
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import random
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import httpx

from . import db
from . import usignals as S
from .verify_us import PRODUCT_URL, NON_PRODUCT_URL

UA = {"User-Agent": "usa-ecom-directory-research/1.0 (secondary evidence; polite)"}
CRAWLS = ["CC-MAIN-2026-39", "CC-MAIN-2026-34", "CC-MAIN-2026-30"]
BLOCKED = ("blocked_or_challenge", "robots_disallowed", "rate_limited", "fetch_failed:timeout")


async def get(c, url, tries=4, **kw):
    delay = 3
    for _ in range(tries):
        try:
            r = await c.get(url, timeout=90, **kw)
            if r.status_code in (200, 206, 404):
                return r
        except httpx.HTTPError:
            pass
        await asyncio.sleep(delay + random.random() * 2)
        delay = min(delay * 2, 40)
    return None


def warc_html(raw: bytes) -> str:
    try:
        data = gzip.decompress(raw)
    except OSError:
        return ""
    parts = data.split(b"\r\n\r\n", 2)
    if len(parts) < 3:
        return ""
    return parts[2].decode("utf-8", errors="replace")


async def cc_evidence(c, cc_sem, host):
    for crawl in CRAWLS:
        async with cc_sem:
            r = await get(c, f"https://index.commoncrawl.org/{crawl}-index",
                          params={"url": f"{host}/*", "output": "json", "filter": ["status:200", "mime:text/html"], "limit": "300"})
        if r is None or r.status_code != 200:
            continue
        recs = [json.loads(l) for l in r.text.splitlines() if l.startswith("{")]
        prods = [x for x in recs if PRODUCT_URL.search(x["url"]) and not NON_PRODUCT_URL.search(x["url"])]
        home = [x for x in recs if urlsplit(x["url"]).path in ("", "/")]
        for rec in (prods[:2] + home[:1]):
            off, ln = int(rec["offset"]), int(rec["length"])
            rr = await get(c, "https://data.commoncrawl.org/" + rec["filename"], headers={"Range": f"bytes={off}-{off + ln - 1}"})
            if rr is None or rr.status_code not in (200, 206):
                continue
            html = warc_html(rr.content)
            if not html:
                continue
            text = S.visible_text(html)
            price = len(S.PRICE_DOLLAR.findall(text)) + len(S.PRICE_USD.findall(text))
            atc = len(S.ADD_TO_CART.findall(html)) + len(S.CART_CHECKOUT.findall(html))
            if price and atc:
                return {"type": "commoncrawl_capture", "url": rec["url"], "timestamp": rec["timestamp"], "crawl": crawl,
                        "prices": price, "cart_markers": atc, "html": html, "text": text}
    return None


async def wayback_evidence(c, wb_sem, url, max_age_days=180):
    since = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).strftime("%Y%m%d")
    async with wb_sem:
        r = await get(c, "https://web.archive.org/cdx/search/cdx",
                      params={"url": url, "output": "json", "filter": "statuscode:200", "from": since, "limit": "-3", "fl": "timestamp,original"}, tries=3)
    if r is None or r.status_code != 200:
        return None
    try:
        rows = json.loads(r.text)[1:]
    except ValueError:
        return None
    for ts, orig in reversed(rows):
        async with wb_sem:
            rr = await get(c, f"https://web.archive.org/web/{ts}id_/{orig}", tries=2, follow_redirects=True)
        if rr is None or rr.status_code != 200:
            continue
        html = rr.text
        text = S.visible_text(html)
        if S.PARKED.search(text[:4000]) and len(text) < 3500 or S.CLOSED.search(text[:6000]) and len(text) < 8000:
            return None
        markers = len(S.ADD_TO_CART.findall(html)) + len(S.CART_CHECKOUT.findall(html))
        links = len(S.PRODUCT_LINK.findall(html))
        if markers and (links or S.PRICE_DOLLAR.search(text)):
            return {"type": "wayback_capture", "url": f"https://web.archive.org/web/{ts}/{orig}", "timestamp": ts,
                    "cart_markers": markers, "product_links": links, "html": html, "text": text}
    return None


async def one(c, cc_sem, wb_sem, key, final_url, http_status, old_reason):
    host = urlsplit(final_url or "https://" + key).hostname or key
    cc = await cc_evidence(c, cc_sem, host)
    wb = await wayback_evidence(c, wb_sem, f"https://{host}/") if cc else None
    ev_list = [e for e in (cc, wb) if e]
    if not ev_list:
        return None
    html = " ".join(e["html"][:600000] for e in ev_list)
    text = " ".join(e["text"][:200000] for e in ev_list)
    score, ev = S.us_signals(html, text, final_url or f"https://{host}/", {})
    ust, ureason = S.us_verdict(score, ev)
    proofs = [{k: v for k, v in e.items() if k not in ("html", "text")} for e in ev_list]
    platform = S.detect_platform(html, final_url or host)
    cat = S.classify([S.title_of(cc["html"]) if cc else "", S.meta(html, "description") or "", text[:6000]], [6, 4, 1])
    name = S.clean(S.store_name(ev_list[0]["html"], key, host))[:120]
    if cc and wb and ust == "verified":
        status = "verified_secondary_evidence"
        reason = (f"live site {old_reason.split(' ')[0]}; secondary: Common Crawl product capture {cc['timestamp'][:8]} "
                  f"({cc['prices']} prices, cart markers) + Wayback capture {wb['timestamp'][:8]}; {ureason}")
    else:
        status = "unverified"
        reason = f"{old_reason.split(' ')[0]}; secondary evidence insufficient ({len(ev_list)} archive proof(s); us={ust}: {ureason})"
    return {"status": status, "reason": reason[:400], "us_evidence": json.dumps({**ev, "secondary_proofs": proofs}, ensure_ascii=False)[:3000],
            "evidence_url": (wb or cc)["url"], "product_evidence": cc["url"] if cc else "", "platform": platform, "category": cat, "store_name": name,
            "us_score": round(score, 2)}


async def main(limit, concurrency):
    con = db.connect()
    like = " OR ".join(f"v.reason LIKE '{b}%'" for b in BLOCKED)
    rows = con.execute(f"SELECT v.key, v.final_url, v.http_status, v.reason FROM verifications v JOIN candidates c USING(key) "
                       f"WHERE v.status='unverified' AND ({like}) AND coalesce(v.method,'')!='secondary' ORDER BY c.priority DESC, c.hits DESC LIMIT ?", (limit,)).fetchall()
    print(f"[secondary] {len(rows)} targets", flush=True)
    cc_sem, wb_sem, sem = asyncio.Semaphore(3), asyncio.Semaphore(4), asyncio.Semaphore(concurrency)
    stats = {"verified_secondary_evidence": 0, "unverified": 0, "none": 0}
    async with httpx.AsyncClient(headers=UA, follow_redirects=True) as c:
        async def run(row):
            async with sem:
                try:
                    res = await asyncio.wait_for(one(c, cc_sem, wb_sem, *row), 600)
                except Exception as e:
                    res = None
                    print(f"[secondary] {row[0]} error {e!r}"[:200], flush=True)
            key = row[0]
            if res is None:
                stats["none"] += 1
                db.retry(con, lambda: con.execute("UPDATE verifications SET method='secondary', reason=reason||' ; no archive evidence found (CC/Wayback)' WHERE key=?", (key,)))
                return
            stats[res["status"]] += 1
            ts = db.now()
            db.retry(con, lambda: (
                con.execute("UPDATE verifications SET status=?, reason=?, us_evidence=?, evidence_url=?, product_evidence=?, platform=coalesce(nullif(?, 'custom/unknown'), platform), "
                            "category=?, store_name=coalesce(nullif(store_name,''), ?), us_score=?, verified_at=?, method='secondary' WHERE key=?",
                            (res["status"], res["reason"], res["us_evidence"], res["evidence_url"], res["product_evidence"], res["platform"],
                             res["category"], res["store_name"], res["us_score"], ts, key)),
                con.execute("UPDATE candidates SET status=? WHERE key=?", (res["status"], key))))
            print(f"[secondary] {key}: {res['status']} {res['reason'][:120]}", flush=True)
        await asyncio.gather(*[run(r) for r in rows])
    print("[secondary] done", stats, flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--concurrency", type=int, default=6)
    a = ap.parse_args()
    asyncio.run(main(a.limit, a.concurrency))
