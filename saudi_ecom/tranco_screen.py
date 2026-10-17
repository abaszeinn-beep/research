"""Screen a Tranco rank slice for Saudi physical-goods storefronts, then fully verify the hits.

Stage 1 (cheap screen, per domain): homepage; DNS-only probes of Saudi subdomains (sa./ksa./saudi.) and
.sa / .com.sa siblings; Saudi locale paths (/en-sa, /ar-sa, /sa-en, /sa-ar, /sa, /ksa) and hreflang SA
alternates only when the homepage looks like a shop. A page is a hit when it looks like a shop and carries
Saudi content signals (SAR prices/currency, +966, VAT, Salla/Zid, .sa host, Saudi locale that survives redirects).
Stage 2: hits go through `verify.verify_one` (HTTP), JS/thin pages through `verify_browser.BrowserFetcher`,
and bot-walled ones through `secondary.check` (>=2 independent evidence types).

  python3 -m saudi_ecom.tranco_screen --shard 4 --start 150001 --end 200000
"""
from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import csv
import json
import os
import random
import re
import socket
import sqlite3
import time
import warnings
from collections import Counter
from urllib.parse import urljoin, urlsplit

import httpx

from . import signals as S
from .common import DEFAULT_HEADERS, MARKETPLACE_ROOTS, NON_STORE_ROOTS, identity, registrable_domain, _TLD
from .verify import CHALLENGE, SA_GEO, Fetcher, analyze, verify_one

OUT_DIR = "data/tranco_shards"
SA_PATHS = ["/en-sa/", "/ar-sa/", "/sa-en/", "/sa-ar/", "/sa/", "/ksa/"]
SA_SUBS = ["sa", "ksa", "saudi"]
COMMERCE_PLATFORMS = {"salla", "zid", "shopify", "woocommerce", "magento", "salesforce-commerce", "sap-hybris", "opencart",
                      "prestashop", "bigcommerce", "expandcart", "youcan", "matjrah", "wuilt", "ecwid", "vtex", "nopcommerce"}
NON_RETAIL_HOST = re.compile(r"(?:^|[.-])(?:cdn|cdns|analytics|tracking|tracker|telemetry|adserver|adsrv|doubleclick|pixel|metrics|"
                             r"dns|ntp|ocsp|crl|pki|akamai|edgekey|edgesuite|cloudfront|fastly|azureedge|amazonaws|googleusercontent)(?:[.-]|\d|$)", re.I)
NON_RETAIL_SUFFIX = re.compile(r"(?:^|\.)(?:gov|gob|gouv|mil|edu|ac|int|govt|nic)(?:\.[a-z]{2})?$", re.I)
HREFLANG_SA = re.compile(r"<link[^>]+hreflang=[\"'](?:ar|en)[-_]sa[\"'][^>]*href=[\"']([^\"']+)|<link[^>]+href=[\"']([^\"']+)[\"'][^>]*hreflang=[\"'](?:ar|en)[-_]sa[\"']", re.I)
SA_LINK = re.compile(r"href=[\"']((?:https?:)?//[^\"'\s<>]{3,120}?/(?:en|ar)[-_]sa/?|(?:https?:)?//(?:sa|ksa|saudi)\.[^\"'\s<>/]{3,80}/?|/(?:en|ar)[-_]sa/?|/sa[-_](?:en|ar)/?)[\"']", re.I)
SECONDARY_REASONS = re.compile(r"^(?:blocked_or_challenge|robots_disallowed|rate_limited)", re.I)
BROWSER_REASONS = re.compile(r"^(?:js_rendered|partial_ecommerce_evidence_js|weak_ecommerce_evidence|insufficient_ecommerce_evidence|fetch_failed:http_error|fetch_failed:timeout|verification_timeout)", re.I)
RECHECK_REASONS = re.compile(r"fetch_failed|timeout|rate_limited|http_5\d\d|RemoteProtocolError", re.I)


class ScreenFetcher(Fetcher):
    """Same politeness/robots logic as the verifier, with short timeouts and a smaller read cap."""

    def __init__(self, concurrency, per_host):
        super().__init__(concurrency, per_host)
        limits = httpx.Limits(max_connections=concurrency * 2, max_keepalive_connections=64)
        self.client = httpx.AsyncClient(headers=DEFAULT_HEADERS, follow_redirects=True, limits=limits,
                                        timeout=httpx.Timeout(10.0, connect=6.0), verify=False, http2=False)

    async def _raw_get(self, url, headers=None, read_limit=700_000):
        return await super()._raw_get(url, headers, min(read_limit, 700_000))

    async def quick(self, url, cap=28):
        try:
            return await asyncio.wait_for(self.get(url, tries=1), cap)
        except asyncio.TimeoutError:
            return None, url, "", {}, "timeout"


DOH = ["https://cloudflare-dns.com/dns-query", "https://dns.google/resolve"]
DOH_HOSTS = {"cloudflare-dns.com", "dns.google"}


def install_public_dns(loop, concurrency=150):
    """Resolve A records for this process via DNS-over-HTTPS.

    The VPC resolver rate-limits (~40 lookups/s) and plain UDP DNS gets throttled at the VM's egress under
    sustained load; DoH multiplexes over a couple of HTTP/2 connections. Raises the same gaierror codes as
    libc so NXDOMAIN stays distinguishable from temporary failures."""
    import ipaddress
    client = httpx.AsyncClient(http2=True, timeout=httpx.Timeout(8.0, connect=6.0), headers={"accept": "application/dns-json"},
                               limits=httpx.Limits(max_connections=8, max_keepalive_connections=8))
    cache: dict[str, object] = {}
    sem = asyncio.Semaphore(concurrency)
    orig = loop.getaddrinfo
    temp = socket.gaierror(socket.EAI_AGAIN, "Temporary failure in name resolution")

    async def lookup(host):
        if host in cache:
            return cache[host]
        res, servfail = temp, 0
        async with sem:
            for attempt in range(4):
                try:
                    r = await client.get(DOH[attempt % 2], params={"name": host, "type": "A"})
                    j = r.json() if r.status_code == 200 else None
                except (httpx.HTTPError, ValueError):
                    j = None
                if j is None:
                    await asyncio.sleep(0.5 + attempt)
                    continue
                stt = j.get("Status")
                if stt == 3:
                    res = socket.gaierror(socket.EAI_NONAME, "Name or service not known")
                    break
                if stt == 2:
                    servfail += 1
                    if servfail >= 2:
                        res = socket.gaierror(socket.EAI_NONAME, "Name or service not known (SERVFAIL)")
                        break
                    continue
                if stt == 0:
                    ips = [x["data"] for x in j.get("Answer") or [] if x.get("type") == 1]
                    res = ips or socket.gaierror(-5, "No address associated with hostname")
                    break
        if res is not temp:
            cache[host] = res
        return res

    async def getaddrinfo(host, port, *, family=0, type=0, proto=0, flags=0):
        h = (host.decode() if isinstance(host, bytes) else host or "").lower().rstrip(".")
        try:
            ipaddress.ip_address(h)
            return await orig(host, port, family=family, type=type, proto=proto, flags=flags)
        except ValueError:
            pass
        if not h or "." not in h or h in DOH_HOSTS:
            return await orig(host, port, family=family, type=type, proto=proto, flags=flags)
        res = await lookup(h)
        if isinstance(res, socket.gaierror):
            raise res
        p = int(port) if port not in (None, "") else 0
        return [(socket.AF_INET, type or socket.SOCK_STREAM, proto or 6, "", (ip, p)) for ip in res]

    loop.getaddrinfo = getaddrinfo
    return lookup


async def resolves(host):
    """True / False (NXDOMAIN or no A record) / None (temporary DNS failure)."""
    try:
        await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM), 20)
        return True
    except socket.gaierror as e:
        return None if e.errno == socket.EAI_AGAIN else False
    except Exception:
        return None


async def tcp_port(host, timeout=7):
    """First of 443/80 that accepts a TCP connection, else None (avoids stacking robots/www/http timeouts on dead hosts)."""
    for port in (443, 80):
        try:
            _, w = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
            w.close()
            return port
        except Exception:
            continue
    return None


def commerce_ish(a):
    return (a["platform"] in COMMERCE_PLATFORMS or a["add_to_cart"] >= 1 or a["cart"] >= 2 or a["n_product_links"] >= 3
            or bool(a["ld_types"] & {"Product", "Offer", "AggregateOffer"}))


def screen_page(html, final, variant):
    """Return (is_hit, evidence dict, analysis) for one fetched page."""
    a = analyze(html, final)
    score, sev = S.saudi_signals(html, a["text"], final, final, a["platform"], a["ld_currency"])
    host = (urlsplit(final).hostname or "").lower()
    shop = commerce_ish(a)
    sa_path = bool(SA_GEO.search(final)) and (variant != "home" or "/sa" in final.lower())
    hit = shop and (
        sev.get("currency_SAR_code") or (sev.get("sar_prices") or 0) >= 2 or sev.get("saudi_platform")
        or "sa_tld" in sev or "vat_number" in sev
        or ("saudi_phone" in sev and score >= 4)
        or (sa_path and score >= 2.5 and variant != "home")
    )
    if variant == "sibling" and host.endswith(".sa") and (shop or thin(html, a)):
        hit = True
    ev = {k: v for k, v in sev.items() if k != "saudi_places"} | {"score": round(score, 1), "platform": a["platform"], "shop": shop}
    return bool(hit), ev, a


def thin(html, a):
    return len(a["text"]) < 1200 and html.count("<script") >= 3


async def screen_domain(f: ScreenFetcher, rank, domain, connect_timeout=7):
    """Return dict(domain, rank, home_status, hits=[{url, kind, ev}], err)."""
    out = {"domain": domain, "rank": rank, "hits": [], "home": None, "err": None, "class": ""}
    root = registrable_domain(domain)
    ext = _TLD(root)
    if root in NON_STORE_ROOTS or root in MARKETPLACE_ROOTS or NON_RETAIL_SUFFIX.search(ext.suffix or "") or NON_RETAIL_HOST.search(domain):
        out["class"] = "non_retail_skip"
        return out
    is_sa = root.endswith(".sa")

    home_html, home_final, home_a = "", None, None
    hosts = [h for h in (domain, "www." + domain) if not domain.startswith("www.") or h == domain]
    dres = await asyncio.gather(*(resolves(h) for h in hosts))
    live = [h for h, ok in zip(hosts, dres) if ok]
    st, final, html, err = None, None, "", ("dns_error" if None in dres else "dns_not_resolved")
    if live:
        port, host = None, None
        for h in live:
            port = await tcp_port(h, timeout=connect_timeout)
            if port:
                host = h
                break
        if not port:
            err = "connect_error"
        else:
            st, final, html, _, err = await f.quick(f"{'https' if port == 443 else 'http'}://{host}/")
            if st is None and err in ("connect_error", "timeout") and port == 443:
                st, final, html, _, err = await f.quick(f"http://{host}/")
    out["home"] = st if st is not None else err
    if st is None:
        out["err"] = err
    elif st == 200 and html:
        home_html, home_final = html, final
        hit, ev, home_a = screen_page(html, final, "home")
        if is_sa and (home_a and (commerce_ish(home_a) or thin(html, home_a))):
            hit = True
        if hit:
            out["hits"].append({"url": final, "kind": "home", "ev": ev})
        out["class"] = "shop" if commerce_ish(home_a) else "non_commerce"
    elif st in (401, 403, 429, 503) or CHALLENGE.search((html or "")[:5000]):
        out["class"] = "blocked"
        if is_sa:
            out["hits"].append({"url": final or f"https://{domain}/", "kind": "home_blocked_sa", "ev": {"http": st}})
    else:
        out["class"] = f"http_{st}"

    if is_sa:
        return out

    probes = []
    fid = identity(home_final) if home_final else None
    final_root = fid["root_domain"] if fid else root
    if final_root != root and final_root.endswith(".sa"):
        return out
    label = ext.domain
    sib = [f"{label}.sa", f"{label}.com.sa"] if label and len(label) >= 3 else []
    subs = [f"{s}.{root}" for s in SA_SUBS]
    dns = await asyncio.gather(*(resolves(h) for h in subs + sib + [f"zq{random.randint(10**6, 10**7)}x.{root}"]))
    wildcard = dns[-1]
    if None in dns[:-1]:
        out["probe_dns_errors"] = dns[:-1].count(None)
    for h, ok in zip(subs, dns[:len(subs)]):
        if ok and not wildcard:
            probes.append(("subdomain", f"https://{h}/"))
    for h, ok in zip(sib, dns[len(subs):len(subs) + len(sib)]):
        if ok:
            probes.append(("sibling", f"https://{h}/"))

    if home_a is not None and (commerce_ish(home_a) or HREFLANG_SA.search(home_html[:300000])):
        seen = set()
        for m in HREFLANG_SA.finditer(home_html[:300000]):
            u = urljoin(home_final, (m.group(1) or m.group(2)).strip())
            if u not in seen:
                seen.add(u)
                probes.append(("hreflang", u))
        for m in SA_LINK.finditer(home_html[:400000]):
            u = urljoin(home_final, m.group(1))
            r = registrable_domain(urlsplit(u).hostname or "")
            if r == final_root and u not in seen and len(seen) < 4:
                seen.add(u)
                probes.append(("sa_link", u))
        base = f"{urlsplit(home_final).scheme}://{urlsplit(home_final).netloc}"
        for p in SA_PATHS:
            probes.append(("path", base + p))

    got_path_hit = False
    tried = set()
    for kind, u in probes:
        if u in tried:
            continue
        tried.add(u)
        is_pathlike = kind in ("hreflang", "sa_link", "path") and registrable_domain(urlsplit(u).hostname or "") == final_root and not re.match(r"https?://(?:sa|ksa|saudi)\.", u)
        if is_pathlike and got_path_hit:
            continue
        st2, fin2, h2, _, err2 = await f.quick(u, cap=25)
        if st2 is None:
            continue
        if st2 in (401, 403, 429, 503) or (st2 >= 400 and CHALLENGE.search((h2 or "")[:5000])):
            if kind in ("subdomain", "hreflang") or (kind == "sibling"):
                out["hits"].append({"url": fin2 or u, "kind": kind + "_blocked", "ev": {"http": st2}})
            continue
        if st2 != 200 or not h2:
            continue
        r2 = registrable_domain(urlsplit(fin2).hostname or "")
        if kind == "path":
            if not SA_GEO.search(fin2) or r2 != final_root:
                continue
            if home_html and len(h2) > 1000 and abs(len(h2) - len(home_html)) < 0.01 * len(home_html) and S.title_of(h2) == S.title_of(home_html):
                continue
        if kind == "sibling" and r2 not in (f"{label}.sa", f"{label}.com.sa") and not r2.endswith(".sa") and r2 != root:
            continue
        hit, ev, _ = screen_page(h2, fin2, kind)
        if hit:
            out["hits"].append({"url": fin2, "kind": kind, "ev": ev})
            if is_pathlike:
                got_path_hit = True
    return out


def load_known(dbpath):
    con = sqlite3.connect(dbpath)
    roots, keys, recheck = set(), set(), {}
    for k, rd, st, reason in con.execute("SELECT c.key, c.root_domain, c.status, v.reason FROM candidates c LEFT JOIN verifications v USING(key)"):
        keys.add(k)
        if rd:
            if st == "unverified" and RECHECK_REASONS.search(reason or ""):
                recheck.setdefault(rd, []).append(k)
            else:
                roots.add(rd)
    # a root counts as known when any of its candidates was decided for a non-network reason
    return roots, keys, recheck


def read_all(pattern):
    import glob
    out = []
    for p in sorted(glob.glob(pattern)):
        out += read_jsonl(p)
    return out


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path) as fh:
        for line in fh:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


async def run(shard, start, end, tranco, dbpath, conc, vconc, retry_errors=False, connect_timeout=7, part=0, parts=1):
    warnings.filterwarnings("ignore")
    loop = asyncio.get_running_loop()
    loop.set_default_executor(concurrent.futures.ThreadPoolExecutor(64))
    install_public_dns(loop)
    os.makedirs(f"{OUT_DIR}/work", exist_ok=True)
    screen_log = f"{OUT_DIR}/work/shard_{shard}_screen.p{part}.jsonl"
    verify_log = f"{OUT_DIR}/work/shard_{shard}_verify.p{part}.jsonl"
    start_path = f"{OUT_DIR}/work/shard_{shard}_started"
    if not os.path.exists(start_path):
        open(start_path, "w").write(str(time.time()))
    t0 = time.time()

    rows = []
    with open(tranco) as fh:
        for r, d in csv.reader(fh):
            if start <= int(r) <= end:
                rows.append((int(r), d.strip().lower()))
    known_roots, known_keys, recheck = load_known(dbpath)
    last = {x["domain"]: x for x in read_jsonl(screen_log)}
    retryable = ("connect_error", "timeout", "domain_timeout", "http_error:ConnectError", "dns_error")
    done_dom = {d for d, x in last.items() if not (retry_errors and (x.get("err") or "").startswith(retryable) and not x.get("retried"))}
    done_keys = {x["key"] for x in read_all(f"{OUT_DIR}/work/shard_{shard}_verify.p*.jsonl")}
    skipped, todo, rechecks = [], [], []
    for r, d in rows:
        rd = registrable_domain(d)
        if rd in known_roots:
            skipped.append(d)
        elif rd in recheck:
            rechecks.append((r, d, recheck[rd]))
        else:
            todo.append((r, d))
    print(f"[shard{shard}] slice={len(rows)} known_skip={len(skipped)} recheck={len(rechecks)} todo={len(todo)} already_screened={len(done_dom)}", flush=True)

    f = ScreenFetcher(conc, 2)
    vf = Fetcher(vconc, 2)
    vqueue: asyncio.Queue = asyncio.Queue()
    queued = set(done_keys)
    stats = Counter()
    sfh = open(screen_log, "a")
    vfh = open(verify_log, "a")

    def enqueue(rank, origin, hit):
        ident = identity(hit["url"])
        if not ident:
            return
        k = ident["key"]
        if k in queued:
            return
        if k in known_keys or (ident["root_domain"] in known_roots and ident["root_domain"] != registrable_domain(origin)):
            stats["hit_known_variant"] += 1
            return
        queued.add(k)
        vqueue.put_nowait({"rank": rank, "origin": origin, "kind": hit["kind"], "screen_ev": hit.get("ev"), "ident": ident, "url": hit["url"]})

    todo = [t for i, t in enumerate(todo) if i % parts == part]
    if part != 0:
        rechecks = []
    for r, d, ks in rechecks:
        for k in ks:
            if k not in queued:
                queued.add(k)
                vqueue.put_nowait({"rank": r, "origin": d, "kind": "recheck_network_unverified", "screen_ev": {},
                                   "ident": {"key": k, "url": "https://" + (k.split("|")[0]) + "/", "root_domain": registrable_domain(d), "platform_hint": None}, "url": "https://" + k.split("|")[0] + "/"})
    for x in read_jsonl(screen_log):
        for h in x.get("hits", []):
            enqueue(x["rank"], x["domain"], h)

    sem = asyncio.Semaphore(conc)
    screen_done = asyncio.Event()

    async def screen_one(r, d):
        async with sem:
            try:
                res = await asyncio.wait_for(screen_domain(f, r, d, connect_timeout), 150)
                if retry_errors:
                    res["retried"] = True
            except asyncio.TimeoutError:
                res = {"domain": d, "rank": r, "hits": [], "home": "timeout", "err": "domain_timeout", "class": ""}
            except Exception as e:
                res = {"domain": d, "rank": r, "hits": [], "home": None, "err": f"screen_error:{type(e).__name__}", "class": ""}
        sfh.write(json.dumps(res, ensure_ascii=False) + "\n")
        stats["screened"] += 1
        stats["class:" + (res.get("class") or "none")] += 1
        if res.get("err"):
            stats["err"] += 1
        for h in res["hits"]:
            stats["hits"] += 1
            enqueue(r, d, h)

    async def screener():
        pending = [(r, d) for r, d in todo if d not in done_dom]
        tasks = set()
        for r, d in pending:
            tasks.add(asyncio.create_task(screen_one(r, d)))
            if len(tasks) >= conc * 3:
                _, tasks = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        if tasks:
            await asyncio.wait(tasks)
        sfh.flush()
        screen_done.set()

    async def verifier(i):
        while True:
            try:
                item = await asyncio.wait_for(vqueue.get(), 5)
            except asyncio.TimeoutError:
                if screen_done.is_set() and vqueue.empty():
                    return
                continue
            ident = item["ident"]
            try:
                res = await asyncio.wait_for(verify_one(vf, dict(ident)), 240)
            except asyncio.TimeoutError:
                res = {"status": "unverified", "reason": "verification_timeout", "final_url": ident["url"], "evidence_url": ident["url"]}
            except Exception as e:
                res = {"status": "unverified", "reason": f"verifier_error:{type(e).__name__}:{str(e)[:80]}", "final_url": ident["url"], "evidence_url": ident["url"]}
            rec = {k: v for k, v in res.items() if k not in ("cat_text",)}
            rec.update({"key": ident["key"], "root_domain": ident["root_domain"], "rank": item["rank"], "origin": item["origin"],
                        "kind": item["kind"], "screen_ev": item["screen_ev"], "screen_url": item["url"], "pass": "http"})
            vfh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            vfh.flush()
            stats["v:" + rec["status"]] += 1

    async def reporter():
        while True:
            await asyncio.sleep(60)
            el = time.time() - t0
            print(f"[shard{shard}] {round(el)}s screened={stats['screened']}/{len(todo) - len(done_dom)} hits={stats['hits']} vq={vqueue.qsize()} "
                  f"{dict((k, v) for k, v in stats.items() if k.startswith(('v:', 'class:', 'err', 'hit_known')))} req={f.stats['requests']}", flush=True)
            sfh.flush()
            if part == 0:
                write_outputs(shard, start, end, len(rows), len(skipped), final=False)

    rep = asyncio.create_task(reporter())
    await asyncio.gather(screener(), *[verifier(i) for i in range(vconc)])
    rep.cancel()
    sfh.close()
    vfh.close()
    write_outputs(shard, start, end, len(rows), len(skipped), final=False)
    print(f"[shard{shard}] stage1+http verify done {dict(stats)}", flush=True)


def latest_by_key(shard):
    recs = {}
    for x in read_all(f"{OUT_DIR}/work/shard_{shard}_verify.p*.jsonl"):
        recs[x["key"]] = x
    for x in read_jsonl(f"{OUT_DIR}/work/shard_{shard}_post.jsonl"):
        if x["key"] in recs:
            recs[x["key"]] = recs[x["key"]] | x
    return recs


CONTENT_SAUDI = ("currency_SAR_code", "vat_number", "sa_tld", "saudi_platform", "shopify_shop_country")


def content_saudi_ok(ev):
    """Saudi evidence that does not come from the URL locale alone."""
    if any(k in ev and ev[k] not in (None, False) for k in CONTENT_SAUDI if k != "shopify_shop_country") or ev.get("shopify_shop_country") == "SA":
        return True
    if (ev.get("sar_prices") or 0) >= 2:
        return True
    ph = str(ev.get("saudi_phone") or "")
    return bool(re.search(r"966|^05", ph))


async def postpass(shard, passes, conc):
    """Second-stage passes over the hits; every result is appended to work/shard_<n>_post.jsonl."""
    warnings.filterwarnings("ignore")
    loop = asyncio.get_running_loop()
    install_public_dns(loop)
    post_path = f"{OUT_DIR}/work/shard_{shard}_post.jsonl"
    fh = open(post_path, "a")

    def emit(rec, pass_name, res):
        out = {k: v for k, v in res.items() if k not in ("cat_text", "key")}
        out.update({"key": rec["key"], "pass": pass_name})
        fh.write(json.dumps(out, ensure_ascii=False) + "\n")
        fh.flush()

    def as_ident(r):
        url = r.get("screen_url") or r.get("final_url")
        ident = identity(url) or {}
        return {"key": r["key"], "url": ident.get("url") if ident.get("key") == r["key"] else url,
                "root_domain": r.get("root_domain"), "platform_hint": None}

    if "retry" in passes:
        recs = latest_by_key(shard)
        todo = [r for r in recs.values() if r.get("status") == "unverified" and RECHECK_REASONS.search(r.get("reason") or "") or
                re.search(r"blocked_or_challenge_http_(?:503|404)", (r.get("reason") or "")) and r.get("status") == "unverified"]
        print(f"[post:retry] {len(todo)}", flush=True)
        f = Fetcher(conc, 1)
        for b in BUCKET_SLOW:
            f.host_gap[b] = 3.0
        sem = asyncio.Semaphore(conc)

        async def one(r):
            async with sem:
                await asyncio.sleep(random.random() * 5)
                try:
                    res = await asyncio.wait_for(verify_one(f, as_ident(r)), 300)
                except Exception as e:
                    res = {"status": "unverified", "reason": f"retry_error:{type(e).__name__}"}
                res["method"] = "http_retry"
                emit(r, "retry", res)
        await asyncio.gather(*(one(r) for r in todo))

    if "browser" in passes:
        from playwright.async_api import async_playwright
        from .verify_browser import BrowserFetcher
        recs = latest_by_key(shard)
        todo = [r for r in recs.values() if r.get("status") == "unverified" and BROWSER_REASONS.search(r.get("reason") or "")
                and (r["key"].endswith(".sa") or "|" in r["key"] or re.match(r"(?:sa|ksa|saudi)\.", r["key"]) or (r.get("saudi_score") or 0) >= 2)]
        print(f"[post:browser] {len(todo)}", flush=True)
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            bf = BrowserFetcher(browser, conc)
            sem = asyncio.Semaphore(conc)

            async def one(r):
                async with sem:
                    try:
                        res = await asyncio.wait_for(verify_one(bf, as_ident(r)), 300)
                    except Exception as e:
                        res = {"status": "unverified", "reason": f"{r.get('reason')}; browser_error:{type(e).__name__}"}
                    res["method"] = "browser"
                    if res.get("status") == "unverified" and str(res.get("reason", "")).startswith("browser_error"):
                        res["reason"] = f"{r.get('reason')}; {res['reason']}"
                    emit(r, "browser", res)
            await asyncio.gather(*(one(r) for r in todo))
            await browser.close()

    if "secondary" in passes:
        from . import secondary as SEC
        recs = latest_by_key(shard)
        todo = [r for r in recs.values() if r.get("status") == "unverified" and SECONDARY_REASONS.search(r.get("reason") or "")]
        print(f"[post:secondary] {len(todo)}", flush=True)
        sem = asyncio.Semaphore(conc)
        async with httpx.AsyncClient(headers=SEC.UA_RESEARCH, follow_redirects=True) as arch, \
                httpx.AsyncClient(headers=SEC.UA_BROWSER, follow_redirects=True) as live:
            async def one(r):
                k = r["key"]
                url = r.get("final_url") or r.get("screen_url")
                name = r.get("store_name") or ""
                if not name or name == k:
                    name = _TLD(urlsplit(url).hostname or k).domain or k
                item = {"key": k, "url": url, "name": name, "domains": [r.get("root_domain") or registrable_domain(urlsplit(url).hostname or "")],
                        "global_root": "|" not in k and not k.endswith(".sa") and not re.match(r"(?:sa|ksa|saudi)\.", k)}
                async with sem:
                    try:
                        res = await asyncio.wait_for(SEC.check((arch, live, live), item), 600)
                    except Exception as e:
                        res = {"verdict": "secondary_error", "evidence": [], "error": type(e).__name__}
                evs = [e for e in res.get("evidence", []) if e.get("ok")]
                ev_text = " | ".join(f"{e['type']}: {e['detail']} ({e.get('url')}, {e.get('date')})" for e in evs)
                if res["verdict"] == "verified_secondary_evidence":
                    out = {"status": "verified_secondary_evidence", "reason": "verified_secondary_evidence: " + ev_text,
                           "evidence_url": evs[0].get("url"), "verified_at": now_utc(), "method": "secondary",
                           "store_name": r.get("store_name") or name}
                else:
                    out = {"reason": f"{r.get('reason')}; secondary evidence insufficient ({ev_text or 'none'})", "secondary_checked": now_utc()}
                out["secondary_evidence"] = res.get("evidence")
                emit(r, "secondary", out)
                print(f"[post:secondary] {k} -> {res['verdict']} {[e['type'] for e in evs]}", flush=True)
            await asyncio.gather(*(one(r) for r in todo))

    if "qa" in passes:
        recs = latest_by_key(shard)
        n = 0
        for r in recs.values():
            if r.get("status") != "verified":
                continue
            try:
                ev = json.loads(r.get("saudi_evidence") or "{}")
            except ValueError:
                ev = {}
            if not content_saudi_ok(ev):
                emit(r, "qa", {"status": "unverified", "reason": f"qa: Saudi relevance rests on the URL locale only ({r.get('reason')}; evidence {ev})"})
                n += 1
        print(f"[post:qa] downgraded {n}", flush=True)
    fh.close()


BUCKET_SLOW = ("salla.sa", "zid.store")


def now_utc():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def saudi_ev_text(r):
    try:
        ev = json.loads(r.get("saudi_evidence") or "{}")
    except (ValueError, TypeError):
        ev = {}
    parts = [f"{k}={v}" if v is not True else k for k, v in ev.items()]
    if not parts and r.get("screen_ev"):
        parts = ["screen:" + ",".join(f"{k}={v}" if v is not True else k for k, v in r["screen_ev"].items() if k not in ("shop",))]
    return "; ".join(str(p) for p in parts)[:500]


def canonical(r):
    u = r.get("final_url") or r.get("screen_url") or ""
    k = r["key"]
    if "|" in k:
        m = SA_GEO.search(u)
        sp = urlsplit(u)
        segs = [s for s in sp.path.split("/") if s]
        keep = []
        for s in segs[:2]:
            keep.append(s)
            if SA_GEO.search("/" + "/".join(keep) + "/"):
                return f"{sp.scheme}://{sp.netloc}/" + "/".join(keep) + "/"
        return u if m else u
    sp = urlsplit(u)
    return f"{sp.scheme or 'https'}://{sp.netloc}/" if sp.netloc else u


COLS = ["store_name", "canonical_storefront_url", "root_domain", "tranco_rank", "platform", "category", "status", "saudi_evidence",
        "verification_url", "verification_utc", "reason"]


def write_outputs(shard, start, end, n_slice, n_known, final):
    sp = f"{OUT_DIR}/work/shard_{shard}_started"
    runtime = time.time() - float(open(sp).read()) if os.path.exists(sp) else 0
    recs = latest_by_key(shard)
    screen = list({x["domain"]: x for x in read_all(f"{OUT_DIR}/work/shard_{shard}_screen.p*.jsonl")}.values())
    out = []
    for r in recs.values():
        st = r.get("status") or "unverified"
        if st not in ("verified", "verified_secondary_evidence", "unverified", "rejected"):
            st = "unverified"
        reason = r.get("reason") or ""
        reason = f"{reason} [found via {r.get('kind')} of {r.get('origin')}]"
        out.append({"store_name": r.get("store_name") or r["key"], "canonical_storefront_url": canonical(r), "root_domain": r.get("root_domain"),
                    "tranco_rank": r.get("rank"), "platform": r.get("platform") or "", "category": r.get("category") or "", "status": st,
                    "saudi_evidence": saudi_ev_text(r), "verification_url": r.get("evidence_url") or r.get("final_url") or "",
                    "verification_utc": r.get("verified_at") or "", "reason": reason[:600]})
    order = {"verified": 0, "verified_secondary_evidence": 1, "unverified": 2, "rejected": 3}
    out.sort(key=lambda x: (order[x["status"]], x["tranco_rank"] or 0))
    tmp = f"{OUT_DIR}/shard_{shard}.csv.tmp"
    with open(tmp, "w", newline="") as fh:
        w = csv.DictWriter(fh, COLS)
        w.writeheader()
        w.writerows(out)
    os.replace(tmp, f"{OUT_DIR}/shard_{shard}.csv")
    c = Counter(x["status"] for x in out)
    errs = sum(1 for s in screen if s.get("err") and s.get("err") != "dns_not_resolved")
    dns = sum(1 for s in screen if s.get("err") == "dns_not_resolved")
    summary = {"shard": shard, "rank_start": start, "rank_end": end, "tranco_list_id": open("data/raw/tranco_id").read().strip() if os.path.exists("data/raw/tranco_id") else None,
               "domains_in_slice": n_slice, "skipped_as_known": n_known, "screened": len(screen),
               "non_retail_skipped_fast": sum(1 for s in screen if s.get("class") == "non_retail_skip"),
               "saudi_hits": len(recs), "verified": c["verified"], "verified_secondary_evidence": c["verified_secondary_evidence"],
               "unverified": c["unverified"], "rejected": c["rejected"],
               "errors": errs, "dns_not_resolved": dns, "runtime_seconds": round(runtime), "complete": final}
    json.dump(summary, open(f"{OUT_DIR}/shard_{shard}_summary.json", "w"), indent=2)
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, required=True)
    ap.add_argument("--start", type=int, required=True)
    ap.add_argument("--end", type=int, required=True)
    ap.add_argument("--tranco", default="data/raw/top-1m.csv")
    ap.add_argument("--db", default="data/saudi_ecom.sqlite")
    ap.add_argument("--concurrency", type=int, default=200)
    ap.add_argument("--verify-concurrency", type=int, default=24)
    ap.add_argument("--retry-errors", action="store_true", help="re-screen domains whose last attempt failed to connect")
    ap.add_argument("--connect-timeout", type=float, default=7)
    ap.add_argument("--part", type=int, default=0)
    ap.add_argument("--parts", type=int, default=1)
    ap.add_argument("--finalize", action="store_true", help="only rewrite the CSV + summary from the work files")
    ap.add_argument("--post", default="", help="comma list of post passes: retry,browser,secondary,qa")
    a = ap.parse_args()
    if a.post:
        asyncio.run(postpass(a.shard, a.post.split(","), a.concurrency))
    elif a.finalize:
        known_roots, _, recheck = load_known(a.db)
        with open(a.tranco) as fh:
            sl = [d for r, d in csv.reader(fh) if a.start <= int(r) <= a.end]
        n_known = sum(1 for d in sl if registrable_domain(d) in known_roots)
        print(json.dumps(write_outputs(a.shard, a.start, a.end, len(sl), n_known, final=True), indent=1))
    else:
        asyncio.run(run(a.shard, a.start, a.end, a.tranco, a.db, a.concurrency, a.verify_concurrency, a.retry_errors, a.connect_timeout, a.part, a.parts))
