"""Screen a Tranco rank slice for Saudi storefronts selling physical products, then verify the hits.

Stage 1 (cheap screen, per domain): homepage + Saudi variants (locale paths, sa./ksa./saudi. subdomains,
<label>.sa / <label>.com.sa siblings). A page is a hit when it shows Saudi storefront signals.
Stage 2: every hit goes through `verify.verify_one`; bot-walled / JS-only hits additionally go through
`secondary.check` (>=2 independent current proofs -> verified_secondary_evidence).

Working state (resumable) lives in data/cache/tranco_shard_<N>/; outputs in data/tranco_shards/.

  python3 -m saudi_ecom.tranco_screen --shard 1 --start 1 --end 50000 --tranco data/raw/top-1m.csv
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import multiprocessing
import os
import random
import re
import sqlite3
import time
import warnings
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from urllib.parse import urljoin, urlsplit

import aiodns
import httpx

from . import db
from . import signals as S
from . import verify as V
from .common import DEFAULT_HEADERS, MARKETPLACE_ROOTS, NON_STORE_ROOTS, _TLD, identity, registrable_domain

ROOT = os.path.join(os.path.dirname(__file__), "..")
OUT_DIR = os.path.join(ROOT, "data", "tranco_shards")

NETWORK_REASONS = ("fetch_failed", "verification_timeout", "rate_limited", "http_500", "http_502", "http_504",
                   "http_520", "http_521", "http_522", "http_523", "http_524", "http_525", "http_526", "http_530", "verifier_error")
SECONDARY_REASONS = ("blocked_or_challenge", "robots_disallowed", "js_rendered_or_thin_page", "partial_ecommerce_evidence_js_page")
LOCALE_PATHS = ["/en-sa/", "/ar-sa/", "/sa-en/", "/sa-ar/", "/sa/", "/ksa/"]
SUB_LABELS = ["sa", "ksa", "saudi"]
COMMERCE_PLATFORMS = {"salla", "zid", "shopify", "woocommerce", "magento", "salesforce-commerce", "opencart", "prestashop",
                      "bigcommerce", "expandcart", "youcan", "matjrah", "sap-hybris", "vtex", "ecwid", "wuilt"}

NON_RETAIL_SUFFIX = re.compile(r"(?:^|\.)(?:gov|edu|mil|int|ac|gouv|gob|govt|nic|arpa|sch)(?:\.[a-z]{2})?$")
NON_RETAIL_LABEL = re.compile(
    r"(?:^|[-\d])(?:cdn|apis?|analytics|metrics|telemetry|tracking|tracker|adserver|adsrv|adnxs|pixel|dns|ntp|smtp|"
    r"edge|cloudfront|akamai\w*|fastly\w*|googleapis|gstatic|doubleclick|googlesyndication|googleusercontent|"
    r"azureedge|msedge|trafficmanager|amazonaws|cloudflare\w*|jsdelivr|unpkg|recaptcha|gravatar|wp|wordpress|"
    r"github\w*|gitlab|npmjs|pypi|docker|kubernetes|statuspage|zendesk|hubspot|salesforce|mailchimp|sendgrid|"
    r"onetrust|cookielaw|hotjar|segment|mixpanel|newrelic|datadog\w*|sentry|bugsnag|optimizely)(?:$|[-\d])")

SAUDI_HREF = re.compile(
    r"<link[^>]+hreflang=[\"'](?:ar|en)[-_]sa[\"'][^>]*>|"
    r"href=[\"']((?:https?:)?//[^\"'\s<>]+)?(/(?:en|ar)[-_]sa/?|/sa[-_](?:en|ar)/?|/ksa/?|/saudi(?:-arabia)?/?)(?=[\"'?#])", re.I)
INTL_966 = re.compile(r"(?:\+|00)\s?966[\s\-]?\(?[1-9]|wa\.me/966|phone=966")
HREF_IN = re.compile(r"href=[\"']([^\"']+)[\"']", re.I)
SAUDI_HOST_HREF = re.compile(r"href=[\"'](https?://(?:sa|ksa|saudi|en-sa|ar-sa)\.[a-z0-9.-]+|https?://[a-z0-9.-]+\.(?:com\.)?sa)/?[\"'/?#]", re.I)


def non_retail(dom: str) -> str | None:
    if dom in NON_STORE_ROOTS or dom in MARKETPLACE_ROOTS:
        return "known_non_store_or_marketplace"
    if NON_RETAIL_SUFFIX.search(dom):
        return "government_or_education_tld"
    if NON_RETAIL_LABEL.search(_TLD(dom).domain or ""):
        return "infrastructure_domain_name"
    return None


def page_features(html: str, url: str, final: str) -> dict:
    """CPU-heavy part (runs in a process pool)."""
    html = html[:700_000]
    a = V.analyze(html, final)
    score, sev = S.saudi_signals(html, a["text"], url, final, a["platform"], set(a["ld_currency"]))
    links = []
    root = registrable_domain(urlsplit(final).hostname or "")
    label = _TLD(root).domain
    for m in SAUDI_HREF.finditer(html[:400_000]):
        tag = m.group(0)
        if tag.lower().startswith("<link"):
            h = HREF_IN.search(tag)
            href = h.group(1) if h else None
        else:
            href = (m.group(1) or "") + m.group(2)
        if href:
            links.append(urljoin(final, href))
    for m in SAUDI_HOST_HREF.finditer(html[:400_000]):
        h = (urlsplit(m.group(1)).hostname or "").lower()
        r = registrable_domain(h)
        if r == root or (label and _TLD(r).domain == label):
            links.append(m.group(1) + "/")
    keep = []
    for u in links:
        h = (urlsplit(u).hostname or "").lower()
        r = registrable_domain(h)
        if (r == root or (label and _TLD(r).domain == label)) and u not in keep:
            keep.append(u)
    return {
        "platform": a["platform"], "title": a["title"][:120], "text_len": len(a["text"]), "scripts": html.count("<script"),
        "add_to_cart": a["add_to_cart"], "cart": a["cart"], "n_product_links": a["n_product_links"],
        "sar_prices": a["sar_prices"], "any_prices": a["any_prices"], "score": score, "sev": sev,
        "saudi_links": keep[:4], "challenge": bool(V.CHALLENGE.search(html[:5000])),
        "sa_locale_html": bool(S.SA_LOCALE.search(html[:300_000])),
        "intl_966": bool(INTL_966.search(html[:600_000])),
    }


def commerce(f) -> bool:
    return (f["add_to_cart"] > 0 or f["n_product_links"] >= 3 or f["platform"] in COMMERCE_PLATFORMS
            or (f["cart"] >= 2 and f["sar_prices"] + f["any_prices"] >= 3))


def hit_reason(f, saudi_specific: bool) -> str | None:
    """saudi_specific: the URL itself is Saudi (.sa domain, sa./ksa. subdomain, Saudi locale path)."""
    sev = f["sev"]
    n_sar = sev.get("sar_prices", 0)
    if "currency_SAR_code" in sev or n_sar >= 3 or (n_sar and commerce(f)):
        return "SAR prices/currency" + (f" ({n_sar} price strings)" if n_sar else " (store currency code)")
    if f["platform"] in ("salla", "zid"):
        return f"{f['platform']} storefront assets"
    if not commerce(f):
        return None
    content = [k for k in ("vat_number",) if k in sev]
    if f["sa_locale_html"]:
        content.append("ar/en-SA locale markup")
    if f["intl_966"]:
        content.append("+966 phone")
    if len(sev.get("saudi_places") or []) >= 2:
        content.append("Saudi place names")
    if saudi_specific and content:
        return "commerce page on Saudi-specific URL with " + ", ".join(content)
    # generic global homepage: hreflang alone is handled by following the Saudi link; needs a Saudi contact plus more
    if f["intl_966"] and ("vat_number" in sev or len(sev.get("saudi_places") or []) >= 2):
        return "commerce homepage with " + ", ".join(content)
    return None


class ScreenFetcher(V.Fetcher):
    """verify.Fetcher (robots.txt, per-host semaphores and gaps) with short timeouts and a small read cap."""

    def __init__(self, concurrency: int, per_host: int = 1):
        super().__init__(concurrency, per_host)
        limits = httpx.Limits(max_connections=concurrency * 2, max_keepalive_connections=concurrency // 2)
        self.client = httpx.AsyncClient(headers=DEFAULT_HEADERS, follow_redirects=True, limits=limits,
                                        timeout=httpx.Timeout(10.0, connect=10.0), verify=False, max_redirects=8)

    async def get(self, url, headers=None, tries=2, check_robots=True, read_limit=700_000):
        if check_robots:
            try:
                ok = await asyncio.wait_for(self.allowed(url), 20)
            except asyncio.TimeoutError:
                ok = True
            if not ok:
                self.stats["robots_disallowed"] += 1
                return None, url, "", {}, "robots_disallowed"
        host = V.bucket(urlsplit(url).hostname or "")
        last_err = None
        for attempt in range(tries):
            async with self.global_sem, self._sem(host):
                gap = time.monotonic() - self.host_last[host]
                if gap < self.host_gap[host]:
                    await asyncio.sleep(self.host_gap[host] - gap)
                self.host_last[host] = time.monotonic()
                try:
                    st, final, text, hdrs = await asyncio.wait_for(self._raw_get(url, headers, read_limit), 20)
                    self.stats["requests"] += 1
                    if st in (429, 502, 503, 504) and attempt < tries - 1 and not V.CHALLENGE.search(text[:5000]):
                        last_err = f"http_{st}"
                        if st == 429:
                            self.host_gap[host] = min(self.host_gap[host] * 2, 5.0)
                    else:
                        return st, final, text, hdrs, None
                except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                    msg = str(e)
                    if any(s in msg for s in ("Name or service not known", "No address associated", "nodename nor servname", "getaddrinfo failed")):
                        return None, url, "", {}, "dns_not_resolved"
                    last_err = "connect_error"
                except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout, asyncio.TimeoutError):
                    return None, url, "", {}, "timeout"
                except httpx.TooManyRedirects:
                    return None, url, "", {}, "too_many_redirects"
                except (httpx.HTTPError, UnicodeError, ValueError, OSError) as e:
                    last_err = f"http_error:{type(e).__name__}"
            await asyncio.sleep(2 + random.random())
        return None, url, "", {}, last_err


def install_dns_cache(loop, threads=96):
    """Cache getaddrinfo per host and give it a large thread pool: the default 8-thread executor queues
    hundreds of concurrent lookups until httpx's connect timeout fires, which looks like dead hosts."""
    from concurrent.futures import ThreadPoolExecutor
    import socket
    pool = ThreadPoolExecutor(threads)
    cache: dict = {}
    inflight: dict = {}
    permanent = (socket.EAI_NONAME, getattr(socket, "EAI_NODATA", -5))

    async def resolve(host, port, family, type, proto, flags):
        last = None
        for attempt in range(2):
            try:
                return await loop.run_in_executor(pool, socket.getaddrinfo, host, port, family, type, proto, flags)
            except socket.gaierror as e:
                last = e
                if e.errno in permanent:
                    break
                await asyncio.sleep(1)
        raise last

    async def getaddrinfo(host, port, *, family=0, type=0, proto=0, flags=0):
        key = (host, port, family, type, proto, flags)
        if key in cache:
            r = cache[key]
            if isinstance(r, Exception):
                raise r
            return r
        if key not in inflight:
            inflight[key] = asyncio.ensure_future(resolve(*key))
        fut = inflight[key]
        try:
            r = await asyncio.shield(fut)
            cache[key] = r
            return r
        except socket.gaierror as e:
            if e.errno in permanent:
                cache[key] = e
            raise
        finally:
            if fut.done():
                inflight.pop(key, None)

    loop.getaddrinfo = getaddrinfo
    loop.set_default_executor(pool)


class Screener:
    def __init__(self, shard, known_roots, known_keys, concurrency):
        self.shard = shard
        self.known_roots = known_roots
        self.known_keys = known_keys
        self.f = ScreenFetcher(concurrency, 1)
        self.dns = aiodns.DNSResolver(timeout=3, tries=2)
        self.pool = ProcessPoolExecutor(max_workers=3, mp_context=multiprocessing.get_context("forkserver"))
        self.stats = Counter()

    async def resolves(self, host) -> bool:
        try:
            await asyncio.wait_for(self.dns.query_dns(host, "A"), 8)
            return True
        except Exception:
            return False

    async def features(self, html, url, final):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.pool, page_features, html, url, final)

    async def fetch(self, url):
        st, final, html, hdrs, err = await self.f.get(url)
        if st is None and err == "connect_error" and url.startswith("https://"):
            st, final, html, hdrs, err = await self.f.get("http://" + url[8:], tries=1)
        ctype = (hdrs or {}).get("content-type", "")
        return st, final, html, ctype, err

    async def page(self, url, saudi_specific, home_sig=None):
        """Fetch one page; return (hit dict | None, features | None, status/err)."""
        st, final, html, ctype, err = await self.fetch(url)
        if st is None:
            return None, None, err
        if st >= 400 or (ctype and "html" not in ctype.lower()) or not html:
            return None, None, f"http_{st}" if st >= 400 else "non_html"
        if saudi_specific:
            # a locale/subdomain probe that lands back on a generic or other-country page is not a Saudi storefront
            fid = identity(final)
            if not fid or not (V.SA_GEO.search(final) or "|sa" in fid["key"] or fid["root_domain"].endswith(".sa")):
                return None, None, "variant_redirected_away"
        feat = await self.features(html, url, final)
        feat["final"] = final
        if home_sig and saudi_specific and not ("sar_prices" in feat["sev"] or "currency_SAR_code" in feat["sev"]):
            t, n = home_sig
            if feat["title"] == t and abs(feat["text_len"] - n) <= max(200, 0.03 * n):
                return None, feat, "variant_same_as_homepage"
        why = hit_reason(feat, saudi_specific)
        if not why:
            return None, feat, "challenge_page" if feat["challenge"] else "no_saudi_storefront_signals"
        return {"url": url, "final": final, "why": why, "platform": feat["platform"], "sev": feat["sev"]}, feat, "hit"

    async def screen(self, rank, dom) -> dict:
        out = {"rank": rank, "domain": dom, "hits": [], "probes": {}}
        nr = non_retail(dom)
        if nr:
            out["skip"] = nr
            return out
        ext = _TLD(dom)
        is_sa = dom.endswith(".sa")
        home_url = f"https://{dom}/"
        hit, feat, why = await self.page(home_url, is_sa)
        if feat is None and why in ("connect_error", "dns_not_resolved", "timeout") or why and why.startswith("http_error"):
            h2, f2, w2 = await self.page(f"https://www.{dom}/", is_sa)
            if f2 is not None or h2 or w2 not in ("dns_not_resolved",):
                hit, feat, why = h2, f2, w2
        out["home"] = why
        if hit:
            out["hits"].append(hit | {"via": "homepage"})
        if is_sa:
            return out

        home_sig = (feat["title"], feat["text_len"]) if feat else None
        label = ext.domain or ""
        sub_hosts = [f"{s}.{dom}" for s in SUB_LABELS]
        siblings = [f"{label}.sa", f"{label}.com.sa"] if len(label) >= 3 else []
        names = sub_hosts + siblings + [f"zq{random.randint(10**6, 10**7)}x.{dom}"]
        res = await asyncio.gather(*(self.resolves(h) for h in names))
        wildcard = res[-1]
        live = {h for h, ok in zip(names[:-1], res[:-1]) if ok}
        out["dns_variants"] = sorted(live) + (["*wildcard*"] if wildcard else [])

        found_saudi = bool(hit and (V.SA_GEO.search(hit["final"]) or registrable_domain(urlsplit(hit["final"]).hostname or "").endswith(".sa")))
        probe_paths = feat is not None and not feat["challenge"] and (
            commerce(feat) or feat["saudi_links"] or (feat["text_len"] < 1500 and feat["scripts"] >= 3))
        urls = []
        if feat and feat["saudi_links"]:
            urls += [(u, "homepage Saudi link") for u in feat["saudi_links"]]
        if probe_paths and not found_saudi:
            base = re.match(r"https?://[^/]+", feat.get("final") or home_url).group(0)
            urls += [(base + p, "locale path") for p in LOCALE_PATHS]
        for h in sub_hosts:
            if h in live and (not wildcard or (feat and commerce(feat))):
                urls.append((f"https://{h}/", "Saudi subdomain"))
        blocked_home = bool(feat is None and (why or "").startswith(("http_403", "http_429", "http_503")) or (feat and feat["challenge"]))
        # a walled Saudi variant is only worth secondary evidence when the brand root looks like a retailer (or is walled itself)
        walled_ok = blocked_home or bool(feat and commerce(feat))
        walled = ("http_403", "http_429", "http_503", "challenge_page")
        seen = set()
        for u, kind in urls:
            if found_saudi and kind == "locale path":
                continue
            ident = identity(u)
            ikey = ident["key"] if ident else u
            if ikey in seen:
                continue
            if ident and ident["key"] in self.known_keys:
                out["probes"][u] = "known_in_db"
                continue
            h, fv, w = await self.page(u, True, home_sig)
            out["probes"][u] = w
            if h:
                hk = (identity(h["final"]) or {}).get("key", h["final"])
                if hk not in seen and hk not in self.known_keys:
                    out["hits"].append(h | {"via": kind})
                seen.update({ikey, hk})
                found_saudi = True
            elif walled_ok and kind == "Saudi subdomain" and w.startswith(walled) and not wildcard and not found_saudi:
                seen.add(ikey)
                found_saudi = True
                out["hits"].append({"url": u, "final": u, "why": f"bot-walled Saudi subdomain of a retail brand ({w})",
                                    "platform": "", "sev": {}, "via": kind, "blocked": True})
        for s in siblings:
            if s not in live:
                continue
            if s in self.known_roots:
                out["probes"][s] = "known_in_db"
                continue
            h, fv, w = await self.page(f"https://{s}/", True)
            if h is None and w in ("connect_error", "dns_not_resolved", "timeout"):
                h2, fv2, w2 = await self.page(f"https://www.{s}/", True)
                if h2 or fv2 is not None or w2.startswith("http_"):
                    h, fv, w = h2, fv2, w2
            out["probes"][s] = w
            if h:
                hk = (identity(h["final"]) or {}).get("key", h["final"])
                if hk not in seen and hk not in self.known_keys:
                    out["hits"].append(h | {"via": f"sibling .sa domain of {dom}"})
                seen.add(hk)
            elif walled_ok and w.startswith(walled) and not found_saudi:
                found_saudi = True
                out["hits"].append({"url": f"https://{s}/", "final": f"https://{s}/", "why": f"bot-walled .sa sibling of a retail brand ({w})",
                                    "platform": "", "sev": {}, "via": f"sibling .sa domain of {dom}", "blocked": True})
        # A global homepage flagged only by a phone number or hreflang is superseded by its Saudi-specific storefront.
        home_hits = [h for h in out["hits"] if h["via"] == "homepage"]
        if home_hits and len(out["hits"]) > 1 and not home_hits[0]["why"].startswith("SAR"):
            out["hits"] = [h for h in out["hits"] if h["via"] != "homepage"]
        return out


def load_known(con):
    roots, keys, root_status = set(), set(), {}
    platform_roots = {"salla.sa", "zid.store", "myshopify.com", "salla.store", "expandcart.com", "matjrah.store", "youcan.shop",
                      "wuilt.com", "wixsite.com", "company.site", "ecwid.com"}
    rows = con.execute("""SELECT c.key, c.url, c.root_domain, c.status, c.platform_hint, v.reason, v.final_key
                          FROM candidates c LEFT JOIN verifications v ON v.key=c.key""").fetchall()
    for key, url, root, st, ph, reason, fkey in rows:
        keys.add(key)
        for r in {root, (registrable_domain(fkey.split("|")[0].split("/")[0]) if fkey else None)}:
            if not r or r in platform_roots:
                continue
            roots.add(r)
            netw = st == "unverified" and any((reason or "").startswith(p) for p in NETWORK_REASONS)
            root_status.setdefault(r, []).append((key, url, root, ph, "network" if netw else st))
    return roots, keys, root_status


def csv_row(res, rank, src):
    try:
        sev = json.loads(res.get("saudi_evidence") or "{}")
    except ValueError:
        sev = {}
    sev_txt = "; ".join(f"{k}={v}" for k, v in sev.items())
    screen = src.get("why", "")
    ev = f"screen: {screen} [via {src.get('via', '')}]" + (f" | verifier: {sev_txt}" if sev_txt else "")
    final = res.get("final_url") or src.get("url")
    key = res.get("key") or ""
    canon = final
    ident = identity(final or "") if final else None
    if res.get("status") in ("verified", "verified_secondary_evidence") and ident:
        if "|" in key and ident.get("key", "").split("|")[0] == key.split("|")[0]:
            canon = ident["url"]
        elif "|" not in key:
            canon = f"https://{urlsplit(final).hostname}/" if not ("|" in ident["key"]) else ident["url"]
    root = registrable_domain((urlsplit(canon or "").hostname or "")) if canon else ""
    reason = res.get("reason") or ""
    if res.get("product_evidence") and res.get("status") == "verified":
        reason += f" | product sample: {res['product_evidence']}"
    return {"store_name": res.get("store_name") or "", "canonical_storefront_url": canon or "", "root_domain": root,
            "tranco_rank": rank, "platform": res.get("platform") or src.get("platform") or "", "category": res.get("category") or "",
            "status": res.get("status") or "unverified", "saudi_evidence": ev[:1500],
            "verification_url": res.get("evidence_url") if res.get("method") == "secondary" else (final or ""),
            "verification_utc": res.get("verified_at") or "", "reason": reason[:1500]}


FIELDS = ["store_name", "canonical_storefront_url", "root_domain", "tranco_rank", "platform", "category", "status",
          "saudi_evidence", "verification_url", "verification_utc", "reason"]


def write_outputs(shard, work, meta):
    results = {}
    for line in open(os.path.join(work, "results.jsonl"), encoding="utf-8") if os.path.exists(os.path.join(work, "results.jsonl")) else []:
        r = json.loads(line)
        results[r["key"]] = r
    rows = []
    for r in results.values():
        rows.append(csv_row(r["res"], r["rank"], r["src"]))
    # one row per storefront identity: verified beats unverified beats rejected, then best rank
    order = {"verified": 0, "verified_secondary_evidence": 1, "unverified": 2, "rejected": 3}
    best = {}
    for row in sorted(rows, key=lambda x: (order.get(x["status"], 9), x["tranco_rank"])):
        ident = identity(row["canonical_storefront_url"]) if row["canonical_storefront_url"] else None
        k = (ident or {}).get("key") or row["canonical_storefront_url"]
        if k not in best:
            best[k] = row
    rows = sorted(best.values(), key=lambda x: (order.get(x["status"], 9), x["tranco_rank"]))
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"shard_{shard}.csv")
    with open(path + ".tmp", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    os.replace(path + ".tmp", path)
    c = Counter(r["status"] for r in rows)
    summary = dict(meta) | {"saudi_hits": meta.get("saudi_hits", 0), "storefront_rows": len(rows), "verified": c["verified"],
                            "verified_secondary_evidence": c["verified_secondary_evidence"], "unverified": c["unverified"],
                            "rejected": c["rejected"]}
    with open(os.path.join(OUT_DIR, f"shard_{shard}_summary.json"), "w") as fh:
        json.dump(summary, fh, indent=2)
    return summary


async def main(a):
    warnings.filterwarnings("ignore")
    install_dns_cache(asyncio.get_running_loop())
    t0 = time.time()
    work = os.path.join(ROOT, "data", "cache", f"tranco_shard_{a.shard}")
    os.makedirs(work, exist_ok=True)
    rt_path = os.path.join(work, "runtime.json")
    prior = json.load(open(rt_path))["seconds"] if os.path.exists(rt_path) else 0.0

    def runtime():
        return round(prior + time.time() - t0)
    con = sqlite3.connect(os.path.join(ROOT, "data", "saudi_ecom.sqlite"))
    known_roots, known_keys, root_status = load_known(con)
    con.close()
    slice_rows = []
    with open(a.tranco) as fh:
        for line in fh:
            r, d = line.strip().split(",", 1)
            r = int(r)
            if a.start <= r <= a.end:
                slice_rows.append((r, d.strip().lower()))
    meta = {"shard": a.shard, "tranco_list": a.list_id, "rank_start": a.start, "rank_end": a.end, "domains_in_slice": len(slice_rows)}

    to_screen, rechecks, skipped_known = [], [], 0
    for r, d in slice_rows:
        root = registrable_domain(d)
        if root in root_status or root in known_roots:
            entries = root_status.get(root, [])
            if entries and all(e[4] == "network" for e in entries) and not non_retail(root) and not any(non_retail(e[2] or "") or identity(e[1]) is None for e in entries):
                rechecks += [(r, e) for e in entries]
            else:
                skipped_known += 1
            continue
        to_screen.append((r, root))
    meta |= {"skipped_known": skipped_known, "rechecked_known_network_errors": len({e[1][2] for e in rechecks})}

    screen_path = os.path.join(work, "screen.jsonl")
    res_path = os.path.join(work, "results.jsonl")
    done_domains, done_keys, pending_hits = set(), set(), []
    if os.path.exists(res_path):
        for line in open(res_path, encoding="utf-8"):
            done_keys.add(json.loads(line)["key"])
    if os.path.exists(screen_path):
        for line in open(screen_path, encoding="utf-8"):
            s = json.loads(line)
            done_domains.add(s["domain"])
            pending_hits += [(s["rank"], h) for h in s["hits"]]
    sc = Screener(a.shard, known_roots, known_keys, a.concurrency)
    vf = V.Fetcher(a.verify_concurrency, 2)
    vq: asyncio.Queue = asyncio.Queue()
    sq: asyncio.Queue = asyncio.Queue()
    queued = set(done_keys)
    stats = Counter()
    lock = asyncio.Lock()

    def enqueue(rank, h, cand=None):
        cand = cand or identity(h["final"]) or identity(h["url"])
        if not cand:
            return
        if cand["key"] in queued:
            return
        if not h.get("recheck") and cand["key"] in known_keys:
            stats["hit_known_in_db"] += 1
            return
        queued.add(cand["key"])
        vq.put_nowait((rank, h, cand))

    for r, e in rechecks:
        key, url, root, ph, _ = e
        enqueue(r, {"url": url, "final": url, "why": "re-check of DB candidate left unverified by a network/rate-limit error",
                    "via": "db_recheck", "recheck": True}, {"key": key, "url": url, "root_domain": root, "platform_hint": ph})
    for r, h in pending_hits:
        enqueue(r, h)

    def guard(cand, res):
        """A non-Saudi-specific global root needs SAR / Saudi VAT / Shopify country SA / Saudi platform to count as verified."""
        if res.get("status") != "verified":
            return res
        k = res.get("final_key") or cand["key"]
        if "|" in k or k.endswith(".sa") or k.split(".")[0] in ("sa", "ksa", "saudi") or k.startswith(("salla.sa/",)) or "zid.store" in k:
            return res
        try:
            sev = json.loads(res.get("saudi_evidence") or "{}")
        except ValueError:
            sev = {}
        if any(x in sev for x in ("currency_SAR_code", "sar_prices", "vat_number", "saudi_platform")) or sev.get("shopify_shop_country") == "SA":
            return res
        return dict(res) | {"status": "unverified", "reason": "global_root_without_SAR_or_Saudi_store_config (manual review; verifier said: " + res["reason"] + ")"}

    async def record(rank, h, cand, res):
        res = guard(cand, res)
        async with lock:
            with open(res_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"key": cand["key"], "rank": rank, "src": {k: v for k, v in h.items() if k != "sev"},
                                     "res": {k: v for k, v in res.items() if k not in ("cat_text", "ecom_evidence")} | {"ecom_evidence": (res.get("ecom_evidence") or "")[:1500]}},
                                    ensure_ascii=False) + "\n")
        stats["res_" + res["status"]] += 1

    from . import secondary as SEC

    async def verifier():
        while True:
            rank, h, cand = await vq.get()
            try:
                res = await asyncio.wait_for(V.verify_one(vf, cand), 240)
            except asyncio.TimeoutError:
                res = {"key": cand["key"], "final_url": cand["url"], "status": "unverified", "reason": "verification_timeout", "verified_at": db.now(), "evidence_url": cand["url"]}
            except Exception as e:
                res = {"key": cand["key"], "final_url": cand["url"], "status": "unverified", "reason": f"verifier_error:{type(e).__name__}:{str(e)[:80]}", "verified_at": db.now(), "evidence_url": cand["url"]}
            if res["status"] == "unverified" and (res.get("reason") or "").startswith(SECONDARY_REASONS):
                sq.put_nowait((rank, h, cand, res))
            else:
                await record(rank, h, cand, res)
            vq.task_done()

    async def secondary_worker(clients):
        while True:
            rank, h, cand, res = await sq.get()
            try:
                item = {"key": cand["key"], "url": res.get("final_url") or cand["url"], "name": res.get("store_name") or _TLD(cand["root_domain"]).domain,
                        "domains": [cand["root_domain"]], "global_root": False}
                sres = await asyncio.wait_for(SEC.check(clients, item), a.secondary_timeout)
                oks = [e for e in sres["evidence"] if e.get("ok")]
                if sres["verdict"] == "verified_secondary_evidence":
                    ev_text = " | ".join(f"{e['type']}: {e['detail']} ({e.get('url')}, {e.get('date')})" for e in oks)
                    res = dict(res) | {"status": "verified_secondary_evidence", "method": "secondary", "evidence_url": oks[0].get("url"),
                                       "reason": "verified_secondary_evidence (live: " + res["reason"] + "): " + ev_text, "verified_at": db.now()}
                else:
                    res = dict(res) | {"reason": res["reason"] + " | secondary evidence insufficient: " +
                                       ", ".join(f"{e['type']}={'ok' if e.get('ok') else e.get('detail', 'no')}" for e in sres["evidence"])[:600]}
            except Exception as e:
                res = dict(res) | {"reason": res["reason"] + f" | secondary check error {type(e).__name__}"}
            await record(rank, h, cand, res)
            sq.task_done()

    sem = asyncio.Semaphore(a.domains_in_flight)
    screen_fh = open(screen_path, "a", encoding="utf-8")

    async def screen_one(rank, dom):
        async with sem:
            try:
                out = await asyncio.wait_for(sc.screen(rank, dom), 150)
            except asyncio.TimeoutError:
                out = {"rank": rank, "domain": dom, "hits": [], "error": "screen_timeout"}
            except Exception as e:
                out = {"rank": rank, "domain": dom, "hits": [], "error": f"{type(e).__name__}:{str(e)[:100]}"}
            screen_fh.write(json.dumps(out, ensure_ascii=False) + "\n")
            screen_fh.flush()
            stats["screened"] += 1
            for h in out["hits"]:
                enqueue(rank, h)

    def screen_counts():
        c = Counter()
        hits = set()
        for line in open(screen_path, encoding="utf-8"):
            s = json.loads(line)
            if s.get("skip"):
                c["skipped_non_retail"] += 1
                continue
            c["screened"] += 1
            if s.get("error"):
                c["errors"] += 1
            elif s.get("home") in ("dns_not_resolved",):
                c["unreachable_dns"] += 1
            elif s.get("home") in ("timeout", "connect_error", "too_many_redirects") or (s.get("home") or "").startswith("http_error"):
                c["errors"] += 1
            elif s.get("home") == "robots_disallowed":
                c["robots_disallowed_homepage"] += 1
            if s["hits"]:
                c["domains_with_saudi_hits"] += 1
                for h in s["hits"]:
                    hits.add(h["final"])
        c["saudi_hits"] = len(hits)
        return c

    async def checkpoint():
        while True:
            await asyncio.sleep(a.checkpoint_every)
            m = meta | dict(screen_counts()) | {"runtime_seconds": runtime(), "in_progress": True,
                                                 "verify_queue": vq.qsize(), "secondary_queue": sq.qsize()}
            s = write_outputs(a.shard, work, m)
            json.dump({"seconds": runtime()}, open(rt_path, "w"))
            print(f"[shard{a.shard}] checkpoint {json.dumps(s)} {dict(stats)} req={sc.f.stats['requests']}", flush=True)

    todo = [(r, d) for r, d in to_screen if d not in done_domains]
    print(f"[shard{a.shard}] slice={len(slice_rows)} known={skipped_known} recheck_entries={len(rechecks)} to_screen={len(to_screen)} remaining={len(todo)} pending_verify={vq.qsize()}", flush=True)
    async with httpx.AsyncClient(headers=SEC.UA_RESEARCH, follow_redirects=True) as arch, \
            httpx.AsyncClient(headers=SEC.UA_BROWSER, follow_redirects=True) as live, \
            httpx.AsyncClient(headers=SEC.UA_BROWSER, follow_redirects=True) as brw:
        workers = [asyncio.create_task(verifier()) for _ in range(a.verify_workers)]
        workers += [asyncio.create_task(secondary_worker((arch, live, brw))) for _ in range(a.secondary_workers)]
        cp = asyncio.create_task(checkpoint())
        tasks = [asyncio.create_task(screen_one(r, d)) for r, d in todo]
        for i in range(0, len(tasks), 2000):
            await asyncio.gather(*tasks[i:i + 2000])
            print(f"[shard{a.shard}] screened {min(i + 2000, len(tasks))}/{len(tasks)} {dict(stats)} req={sc.f.stats['requests']}", flush=True)
        await vq.join()
        await sq.join()
        for w in workers:
            w.cancel()
        cp.cancel()
    screen_fh.close()
    m = meta | dict(screen_counts()) | {"runtime_seconds": runtime(), "in_progress": False}
    s = write_outputs(a.shard, work, m)
    json.dump({"seconds": runtime()}, open(rt_path, "w"))
    print(f"[shard{a.shard}] DONE {json.dumps(s)}", flush=True)
    sc.pool.shutdown()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, required=True)
    ap.add_argument("--start", type=int, required=True)
    ap.add_argument("--end", type=int, required=True)
    ap.add_argument("--tranco", default=os.path.join(ROOT, "data", "raw", "top-1m.csv"))
    ap.add_argument("--list-id", default="")
    ap.add_argument("--concurrency", type=int, default=200, help="concurrent HTTP requests while screening")
    ap.add_argument("--domains-in-flight", type=int, default=300)
    ap.add_argument("--verify-concurrency", type=int, default=32)
    ap.add_argument("--verify-workers", type=int, default=16)
    ap.add_argument("--secondary-workers", type=int, default=3)
    ap.add_argument("--secondary-timeout", type=int, default=420)
    ap.add_argument("--checkpoint-every", type=int, default=300)
    asyncio.run(main(ap.parse_args()))
