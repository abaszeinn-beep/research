"""Async live verifier for Shopify storefront candidates (US market).

Per candidate (evidence URL + UTC timestamp recorded):
  1. robots.txt respected for every host; GET /meta.json on the discovered host (myshopify or custom domain)
     -> platform confirmation, primary custom domain (identity), myshopify_domain (dedup), base currency,
        merchant country, ships_to_countries, published product count.
  2. Quick rejects: non-USD base currency, does not ship to US, non-US merchant without US-specific signal,
     zero published products, store unavailable / frozen (HTTP 402 / unavailable pages), DNS failure.
  3. Primary storefront homepage: live 200, not a password / coming-soon page, not a bot wall (bot walls ->
     unverified, never bypassed); US contact/shipping signals from visible text.
  4. /products.json: physical products (variants requires_shipping=true, not gift cards), availability.
  5. One product page: 200 + add-to-cart form (/cart/add) = purchase path; JSON-LD priceCurrency.
     /cart.js is not requested: Shopify's default robots.txt disallows /cart*, so the product-page
     add-to-cart form is the purchase-path proof.
Bounded global concurrency (adaptive on HTTP 429), per-host semaphore + minimum gap, short timeouts,
bounded exponential backoff, per-candidate time cap so one slow host never blocks the rest.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import sys
import time
import urllib.robotparser
from collections import Counter, defaultdict, deque
from urllib.parse import urlsplit

from curl_cffi.requests import AsyncSession
from curl_cffi.requests.errors import RequestsError as CurlError

sys.path.insert(0, os.path.dirname(__file__))
from common import HEADERS, connect, registrable, utcnow, set_meta, get_meta  # noqa: E402
import signals as S  # noqa: E402

MAX_BYTES = 2_500_000
GIFT = re.compile(r"gift ?card|e-?gift|digital|download|ebook|e-book|pdf|template|preset|course|membership|"
                  r"service|consultation|appointment|booking|ticket|donation|warranty|"
                  r"shipping protection|route package|insurance|\btip\b", re.I)
RETRYABLE = ("unreachable", "bot_wall_or_rate_limited (meta.json HTTP 429", "candidate_time_cap", "storefront_unreachable",
             "verifier_exception", "storefront_http_429", "bot_wall_on_storefront (HTTP 429")


class Limiter:
    """Global in-flight request limit that adapts to HTTP 429 pressure (AIMD)."""

    def __init__(self, start, lo, hi):
        self.limit, self.lo, self.hi = start, lo, hi
        self.inflight = 0
        self.cond = asyncio.Condition()
        self.window = deque(maxlen=400)
        self.last_adjust = time.monotonic()
        self.peak = start

    async def __aenter__(self):
        async with self.cond:
            while self.inflight >= self.limit:
                await self.cond.wait()
            self.inflight += 1

    async def __aexit__(self, *a):
        async with self.cond:
            self.inflight -= 1
            self.cond.notify_all()

    def record(self, is_429):
        self.window.append(1 if is_429 else 0)
        now = time.monotonic()
        if now - self.last_adjust < 10 or len(self.window) < 100:
            return
        rate = sum(self.window) / len(self.window)
        if rate > 0.03:
            self.limit = max(self.lo, int(self.limit * 0.7))
            self.window.clear()
        elif rate < 0.005:
            self.limit = min(self.hi, self.limit + 4)
            self.peak = max(self.peak, self.limit)
        self.last_adjust = now


class Rate:
    """Request-start rate limiter (req/s) with multiplicative decrease on HTTP 429, slow recovery."""

    def __init__(self, rps, lo=2.0, hi=None):
        self.rps, self.lo, self.hi = rps, lo, hi or rps * 1.5
        self.next_t = time.monotonic()
        self.lock = asyncio.Lock()
        self.last_cut = 0.0
        self.last_up = time.monotonic()

    async def wait(self):
        async with self.lock:
            now = time.monotonic()
            if now - self.last_up > 30:
                self.rps = min(self.hi, self.rps * 1.03)
                self.last_up = now
            t = max(now, self.next_t)
            self.next_t = t + 1.0 / self.rps
        if t > now:
            await asyncio.sleep(t - now)

    def hit_429(self):
        now = time.monotonic()
        if now - self.last_cut > 5:
            self.rps = max(self.lo, self.rps * 0.8)
            self.last_cut = now
            self.last_up = now


class Fetcher:
    def __init__(self, concurrency, per_host=2, gap=0.35, rps=18.0, rps_max=None):
        self.rate = Rate(rps, hi=rps_max or rps)
        self.client = AsyncSession(headers=HEADERS, timeout=20, max_clients=concurrency * 3, verify=False,
                                   allow_redirects=True, max_redirects=8)
        self.lim = Limiter(concurrency, 8, concurrency * 2)
        self.per_host, self.gap = per_host, gap
        self.host_sem = {}
        self.host_last = defaultdict(float)
        self.host_gap = defaultdict(lambda: gap)
        self.robots = {}
        self.robots_lock = defaultdict(asyncio.Lock)
        self.stats = Counter()

    def _sem(self, h):
        if h not in self.host_sem:
            self.host_sem[h] = asyncio.Semaphore(self.per_host)
        return self.host_sem[h]

    async def _raw(self, url):
        r = await self.client.get(url)
        body = r.content[:MAX_BYTES]
        try:
            text = body.decode(r.encoding or "utf-8", errors="replace")
        except LookupError:
            text = body.decode("utf-8", errors="replace")
        return r.status_code, str(r.url), text, r.headers

    async def allowed(self, url):
        sp = urlsplit(url)
        base = f"{sp.scheme}://{sp.netloc}"
        async with self.robots_lock[base]:
            if base not in self.robots:
                rp = None
                st, _, txt, _, err = await self.get(base + "/robots.txt", check_robots=False, tries=2)
                if st == 200 and "<html" not in txt[:300].lower():
                    rp = urllib.robotparser.RobotFileParser()
                    rp.parse(txt.splitlines())
                self.robots[base] = rp if rp else ("dns" if err == "dns_not_resolved" else None)
                if len(self.robots) > 200_000:
                    self.robots.clear()
        rp = self.robots.get(base)
        if rp is None or rp == "dns":
            return True
        try:
            return rp.can_fetch(HEADERS["User-Agent"], url)
        except Exception:
            return True

    async def get(self, url, tries=3, check_robots=True):
        """-> (status, final_url, text, headers, error)"""
        if check_robots and not await self.allowed(url):
            self.stats["robots_disallowed"] += 1
            return None, url, "", {}, "robots_disallowed"
        host = (urlsplit(url).hostname or "").lower()
        if self.robots.get(f"https://{host}") == "dns":
            return None, url, "", {}, "dns_not_resolved"
        delay = 2.0
        err = None
        for attempt in range(tries):
            async with self._sem(host):
                wait = self.host_gap[host] - (time.monotonic() - self.host_last[host])
                if wait > 0:
                    await asyncio.sleep(wait)
                self.host_last[host] = time.monotonic()
                async with self.lim:
                    await self.rate.wait()
                    try:
                        st, final, text, hdrs = await asyncio.wait_for(self._raw(url), 25)
                        self.stats["requests"] += 1
                        self.lim.record(st == 429)
                        if st == 429:
                            self.stats["http_429"] += 1
                            self.rate.hit_429()
                            self.host_gap[host] = min(self.host_gap[host] * 2 + 0.5, 8)
                        if st in (429, 502, 503, 504) and attempt < tries - 1 and not S.CHALLENGE.search(text[:4000]):
                            err = f"http_{st}"
                            ra = hdrs.get("retry-after", "")
                            if st == 429:
                                delay = max(delay, min(float(ra), 30) if ra.isdigit() else 8)
                        else:
                            return st, final, text, hdrs, None
                    except asyncio.TimeoutError:
                        err = "timeout"
                        if attempt >= 1:
                            break
                    except (CurlError, UnicodeError, ValueError, OSError) as e:
                        m = str(e)
                        if "Could not resolve host" in m:
                            return None, url, "", {}, "dns_not_resolved"
                        if "Maximum" in m and "redirect" in m:
                            return None, url, "", {}, "too_many_redirects"
                        if "timed out" in m or "Timeout" in m:
                            err = "timeout"
                            if attempt >= 1:
                                break
                        elif "SSL" in m or "certificate" in m:
                            err = "ssl_error"
                        elif "Failed to connect" in m or "Connection refused" in m or "Couldn't connect" in m:
                            err = "connect_error"
                        else:
                            err = f"http_error:{m[:60]}"
            await asyncio.sleep(delay + random.random())
            delay = min(delay * 2, 20)
        self.stats["failed_fetch"] += 1
        return None, url, "", {}, err


def jload(txt):
    t = (txt or "").lstrip()
    if not t.startswith("{") and not t.startswith("["):
        return None
    try:
        return json.loads(t)
    except ValueError:
        return None


class Verifier:
    def __init__(self, con, fetcher):
        self.con = con
        self.f = fetcher
        self.msd_owner = {}
        for key, msd in con.execute("SELECT key, myshopify_domain FROM results WHERE myshopify_domain IS NOT NULL "
                                    "AND myshopify_domain!='' AND status NOT IN ('duplicate','error') "
                                    "AND reason NOT LIKE 'unreachable%' AND reason NOT LIKE 'candidate_time_cap%'"):
            self.msd_owner.setdefault(msd, key)
        self.stats = Counter()

    def save(self, key, r):
        cols = ["status", "reason", "store_name", "canonical_url", "root_domain", "myshopify_domain", "platform",
                "category", "us_evidence", "verification_url", "verification_utc", "currency", "country", "extra"]
        vals = [r.get(c) for c in cols]
        for _ in range(30):
            try:
                self.con.execute(f"INSERT OR REPLACE INTO results(key, {', '.join(cols)}) VALUES (?{', ?' * len(cols)})", [key] + vals)
                self.con.execute("UPDATE candidates SET state='done' WHERE key=?", (key,))
                break
            except Exception:
                time.sleep(1)
        self.stats[r["status"]] += 1

    async def verify(self, key, kind, fetch_host, hint):
        out = {"platform": "shopify", "verification_utc": utcnow()}

        def done(status, reason, **kw):
            out.update(kw)
            out["status"], out["reason"] = status, reason
            out["verification_utc"] = utcnow()
            return out

        if kind == "myshopify" and key in self.msd_owner and self.msd_owner[key] != key:
            return done("duplicate", f"duplicate_of {self.msd_owner[key]}", myshopify_domain=key)

        base = f"https://{fetch_host}"
        murl = base + "/meta.json"
        st, final, txt, hdrs, err = await self.f.get(murl)
        out["verification_url"] = murl
        if err == "dns_not_resolved":
            return done("rejected", "dns_not_resolved")
        if err == "robots_disallowed":
            return done("unverified", "meta.json disallowed by robots.txt")
        if err:
            return done("unverified", f"unreachable ({err})")
        mj = jload(txt) if st == 200 else None
        if not isinstance(mj, dict) or "myshopify_domain" not in mj:
            low = txt[:20000]
            if st == 402:
                return done("rejected", "shopify_store_unavailable (HTTP 402 frozen/unpaid)")
            if st in (403, 429, 503) or S.CHALLENGE.search(low):
                return done("unverified", f"bot_wall_or_rate_limited (meta.json HTTP {st}); not bypassed")
            if S.UNAVAILABLE.search(low):
                return done("rejected", f"shopify_store_unavailable (HTTP {st})")
            if kind == "myshopify":
                return done("rejected", f"myshopify_host_not_serving_store (HTTP {st})")
            if st == 200 and ("cdn.shopify.com" in low or "Shopify.shop" in low):
                return done("unverified", "shopify storefront but meta.json unavailable (headless/custom)")
            return done("rejected", f"not_a_shopify_storefront (meta.json HTTP {st}; out of shard scope)")

        msd = (mj.get("myshopify_domain") or "").lower()
        dom = (mj.get("domain") or fetch_host).lower()
        cur = mj.get("currency") or ""
        country = mj.get("country") or ""
        ships = mj.get("ships_to_countries") or []
        name = (mj.get("name") or "").strip()
        nprod = mj.get("published_products_count")
        out.update(myshopify_domain=msd, currency=cur, country=country, store_name=name,
                   canonical_url=f"https://{dom}/",
                   root_domain=dom if dom.endswith(".myshopify.com") else registrable(dom))
        ev = {"meta_country": country, "meta_currency": cur,
              "ships_to": ",".join(ships[:12]) + ("..." if len(ships) > 12 else ""),
              "ships_to_n": len(ships), "published_products": nprod, "province": mj.get("province")}
        out["extra"] = json.dumps({"meta": {k: mj.get(k) for k in ("city", "province", "country", "currency", "domain",
                                  "myshopify_domain", "published_products_count", "money_format")}, "hint": hint}, ensure_ascii=False)
        if msd:
            owner = self.msd_owner.get(msd)
            if owner and owner != key:
                return done("duplicate", f"duplicate_of {owner}")
            self.msd_owner[msd] = key

        def evs():
            return "; ".join(f"{k}={v}" for k, v in ev.items() if v not in (None, "", 0, []))

        if cur != "USD":
            return done("rejected", f"non_usd_base_currency ({cur}, country={country})", us_evidence=evs())
        if ships and "US" not in ships:
            return done("rejected", f"does_not_ship_to_US (ships_to={','.join(ships[:6])})", us_evidence=evs())
        if nprod == 0:
            return done("rejected", "no_published_products (meta.json)", us_evidence=evs())

        rb = self.f.robots.get(f"https://{fetch_host}")
        if rb is not None and rb != "dns":
            self.f.robots.setdefault(f"https://{dom}", rb)
        if dom != fetch_host.lower() and not await self.f.allowed(f"https://{dom}/"):
            return done("unverified", "storefront disallowed by robots.txt", us_evidence=evs())
        hurl = f"https://{dom}/"
        st, final, html, hdrs, err = await self.f.get(hurl)
        if err == "dns_not_resolved":
            return done("rejected", f"primary_domain_dns_not_resolved ({dom})", us_evidence=evs())
        if err:
            return done("unverified", f"storefront_unreachable ({err})", us_evidence=evs())
        fpath = urlsplit(final).path
        if fpath.startswith("/password") or S.PASSWORD_PAGE.search(html[:60000]):
            return done("rejected", "password_protected_or_coming_soon_storefront", verification_url=final, us_evidence=evs())
        if st == 402 or (S.UNAVAILABLE.search(html[:20000]) and st != 200):
            return done("rejected", f"shopify_store_unavailable (HTTP {st})", verification_url=final, us_evidence=evs())
        if st in (403, 429, 503) or (S.CHALLENGE.search(html[:6000]) and st != 200):
            return done("unverified", f"bot_wall_on_storefront (HTTP {st}); not bypassed", verification_url=final, us_evidence=evs())
        if st != 200:
            return done("rejected" if st in (404, 410) else "unverified", f"storefront_http_{st}", verification_url=final, us_evidence=evs())
        final_host = (urlsplit(final).hostname or dom).lower()
        if registrable(final_host) != registrable(dom) and not final_host.endswith("myshopify.com"):
            out["canonical_url"] = f"https://{final_host}/"
            out["root_domain"] = registrable(final_host)
            ev["redirects_to"] = final_host
        contact = S.us_contact_signals(html if len(html) < 500_000 else html[:250_000] + html[-250_000:])
        ev.update(contact)
        m = S.ACTIVE_CUR.search(html)
        if m:
            ev["storefront_currency"] = m.group(1)
        if not name:
            out["store_name"] = S.store_name_from_html(html) or dom

        ships_us_only = ships == ["US"] or (0 < len(ships) <= 3 and "US" in ships)
        us_specific = any(k in contact for k in ("us_address", "us_phone", "us_shipping_text"))
        if country == "US":
            us_basis = "meta.json merchant country=US + base currency USD" + (" + ships to US" if "US" in ships else "")
        elif country == "CA" and not (ships == ["US"] or "us_address" in contact):
            return done("rejected", "canadian_merchant (meta.json country=CA)", verification_url=final, us_evidence=evs())
        elif ships_us_only and us_specific:
            us_basis = f"USD + ships only to {','.join(ships)} + US contact/shipping text (merchant country={country})"
        elif "US" in ships and "us_address" in contact:
            us_basis = f"USD + ships to US + US street address (merchant country={country})"
        else:
            return done("rejected", f"non_us_merchant (country={country or '?'}, ships_to_n={len(ships)}, no US-specific signal)",
                        verification_url=final, us_evidence=evs())

        purl = f"https://{dom}/products.json?limit=250"
        st, pfinal, ptxt, _, err = await self.f.get(purl)
        pj = jload(ptxt) if st == 200 else None
        prods = pj.get("products") if isinstance(pj, dict) else None
        if prods is None:
            handles = list(dict.fromkeys(re.findall(r"href=[\"'](?:https?://[^/\"']+)?/(?:[a-z]{2}(?:-[a-z]{2})?/)?(?:collections/[^/\"']+/)?products/([a-z0-9%_.-]+)", html, re.I)))
            if not handles:
                return done("unverified", f"products.json unavailable ({err or st}) and no product links on homepage",
                            verification_url=final, us_evidence=evs())
            prods = []
            for h in handles[:3]:
                st2, _, jt, _, _ = await self.f.get(f"https://{dom}/products/{h}.js", tries=2)
                pjs = jload(jt) if st2 == 200 else None
                if isinstance(pjs, dict):
                    pjs["variants"] = [{"requires_shipping": v.get("requires_shipping"), "available": v.get("available"),
                                        "price": v.get("price")} for v in pjs.get("variants") or []]
                    pjs["product_type"] = pjs.get("type", "")
                    prods.append(pjs)
            if not prods:
                return done("unverified", "products.json and product .js unavailable", verification_url=final, us_evidence=evs())
        if not prods:
            return done("rejected", "no_products_listed (products.json empty)", verification_url=pfinal, us_evidence=evs())
        phys = []
        for p in prods:
            vs = p.get("variants") or []
            if any(v.get("requires_shipping") for v in vs) and not GIFT.search(f"{p.get('product_type') or ''} {p.get('title') or ''}"):
                phys.append(p)
        if not phys:
            return done("rejected", f"no_physical_products (0/{len(prods)} products require shipping)",
                        verification_url=pfinal, us_evidence=evs())
        avail = [p for p in phys if any(v.get("available", True) for v in p.get("variants") or [])]
        types = [p.get("product_type") or "" for p in prods]
        titles = [p.get("title") or "" for p in prods][:120]
        tags = []
        for p in prods[:120]:
            t = p.get("tags")
            tags.extend(t if isinstance(t, list) else str(t or "").split(",")[:8])
        out["category"] = S.categorize(types, titles, tags[:400], out.get("store_name") or "", mj.get("description") or "")
        ev["physical_products_sampled"] = f"{len(phys)}/{len(prods)}"
        x = json.loads(out["extra"])
        x["top_types"] = [t for t, _ in Counter(t for t in types if t).most_common(6)]
        x["sample_titles"] = titles[:8]
        out["extra"] = json.dumps(x, ensure_ascii=False)
        if not avail:
            return done("unverified", "all sampled physical products sold out / unavailable", verification_url=pfinal, us_evidence=evs())

        verified_url = None
        for p in avail[:3]:
            h = p.get("handle")
            if not h:
                continue
            u = f"https://{dom}/products/{h}"
            st, pfu, ph, _, err = await self.f.get(u, tries=2)
            if st == 200 and S.ADD_TO_CART.search(ph):
                verified_url = pfu
                m = S.PRICE_CUR.search(ph) or S.ACTIVE_CUR.search(ph)
                if m:
                    ev["product_price_currency"] = m.group(1)
                break
            if st in (403, 429, 503):
                break
        if not verified_url:
            return done("unverified", "no product page with add-to-cart found (catalog-only / blocked)",
                        verification_url=final, us_evidence=evs())
        if ev.get("product_price_currency") and ev["product_price_currency"] != "USD" and country != "US":
            return done("rejected", f"product priced in {ev['product_price_currency']}", verification_url=verified_url, us_evidence=evs())
        ev["basis"] = us_basis
        return done("verified", "live storefront; physical products; add-to-cart on product page; " + us_basis,
                    verification_url=verified_url, us_evidence=evs())

    async def run_one(self, key, kind, fh, hint):
        try:
            r = await asyncio.wait_for(self.verify(key, kind, fh, hint), 150)
        except asyncio.TimeoutError:
            r = {"status": "unverified", "reason": "candidate_time_cap_exceeded", "platform": "shopify",
                 "verification_utc": utcnow(), "verification_url": f"https://{fh}/meta.json"}
        except Exception as e:
            r = {"status": "error", "reason": f"verifier_exception {type(e).__name__}: {str(e)[:120]}", "platform": "shopify",
                 "verification_utc": utcnow(), "verification_url": f"https://{fh}/meta.json"}
        self.save(key, r)


async def main(concurrency, stores_in_flight, max_n, min_priority, idle_exit, retry, shard=0, nshards=1, rps=18.0, rps_max=None):
    con = connect()
    con.execute("UPDATE candidates SET state='pending' WHERE state='claimed' AND rowid % ? = ?", (nshards, shard))
    if retry:
        keys = [k for (k, r) in con.execute("SELECT key, reason FROM results WHERE status IN ('unverified','error')")
                if any((r or "").startswith(x) for x in RETRYABLE)]
        con.executemany("UPDATE candidates SET state='pending' WHERE key=?", [(k,) for k in keys])
        con.executemany("DELETE FROM results WHERE key=?", [(k,) for k in keys])
        print(f"[verify] re-queued {len(keys)} retryable candidates", flush=True)
    f = Fetcher(concurrency, rps=rps, rps_max=rps_max)
    v = Verifier(con, f)
    t0 = time.time()
    processed = 0
    queue = asyncio.Queue(maxsize=stores_in_flight * 4)
    stop = False

    async def producer():
        idle_since = None
        while not stop:
            rows = con.execute("SELECT key, kind, fetch_host, hint FROM candidates WHERE state='pending' AND priority>=? "
                               "AND rowid % ? = ? ORDER BY priority DESC, rowid LIMIT 500", (min_priority, nshards, shard)).fetchall()
            if not rows:
                idle_since = idle_since or time.time()
                if time.time() - idle_since > idle_exit:
                    break
                await asyncio.sleep(30)
                continue
            idle_since = None
            con.executemany("UPDATE candidates SET state='claimed' WHERE key=?", [(r[0],) for r in rows])
            for r in rows:
                await queue.put(r)
        for _ in range(stores_in_flight):
            await queue.put(None)

    async def worker():
        nonlocal processed
        while True:
            item = await queue.get()
            if item is None:
                return
            await v.run_one(*item)
            processed += 1
            if max_n and processed >= max_n:
                return

    async def reporter():
        while True:
            await asyncio.sleep(60)
            el = time.time() - t0
            print(f"[verify] {processed} done in {el/60:.1f}m ({processed/el:.1f}/s) limit={f.lim.limit} "
                  f"inflight={f.lim.inflight} rps={f.rate.rps:.1f} {dict(v.stats)} {dict(f.stats)}", flush=True)
            set_meta(con, f"verify_stats_last_{shard}", {"processed": processed, "elapsed_s": el, "limit": f.lim.limit,
                                                "stores_in_flight": stores_in_flight, **v.stats,
                                                **{"f_" + k: n for k, n in f.stats.items()}})
            set_meta(con, "concurrency_peak", max(get_meta(con, "concurrency_peak", 0) or 0, f.lim.peak))

    rep = asyncio.create_task(reporter())
    prod = asyncio.create_task(producer())
    await asyncio.gather(*[worker() for _ in range(stores_in_flight)])
    stop = True
    prod.cancel()
    rep.cancel()
    set_meta(con, f"verify_runtime_s_{shard}", (get_meta(con, f"verify_runtime_s_{shard}", 0) or 0) + time.time() - t0)
    print(f"[verify] finished {processed} {dict(v.stats)} {dict(f.stats)}", flush=True)
    await f.client.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--concurrency", type=int, default=48, help="global in-flight HTTP requests (adaptive, up to 2x)")
    ap.add_argument("--stores", type=int, default=120, help="candidates verified in parallel")
    ap.add_argument("--max", type=int, default=0)
    ap.add_argument("--min-priority", type=float, default=-99)
    ap.add_argument("--idle-exit", type=int, default=900)
    ap.add_argument("--retry", action="store_true", help="re-queue retryable unverified results first")
    ap.add_argument("--rps", type=float, default=18.0, help="max request starts per second (adaptive on 429)")
    ap.add_argument("--rps-max", type=float, default=None)
    ap.add_argument("--shard", default="0/1", help="i/n: this process takes candidates with rowid %% n == i")
    a = ap.parse_args()
    import warnings
    warnings.filterwarnings("ignore")
    si, sn = map(int, a.shard.split("/"))
    asyncio.run(main(a.concurrency, a.stores, a.max, a.min_priority, a.idle_exit, a.retry, si, sn, a.rps, a.rps_max))
