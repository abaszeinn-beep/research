"""Screen a Tranco rank slice for Saudi storefronts selling physical products.

Stages (all resumable; working files live in data/cache/tranco/shard_<N>/, outputs in data/tranco_shards/):
  screen  cheap pass over the slice (one process per --part): homepage, Saudi locale links / path variants,
          sa./ksa./saudi. subdomains and <label>.sa / <label>.com.sa siblings; a page is a hit when it shows
          ecommerce markers plus Saudi signals (any ecommerce-looking or blocked page on a .sa host).
  verify  every hit through verify.verify_one; bot-walled / JS-only hits through secondary.check.
          With --watch it keeps picking up hits while screen parts are still running.
  export  shard CSV + summary JSON.

  python3 -m saudi_ecom.tranco_screen screen --shard 2 --start 50001 --end 100000 --part 0 --parts 4
  python3 -m saudi_ecom.tranco_screen verify --shard 2 --start 50001 --end 100000 --watch
  python3 -m saudi_ecom.tranco_screen export --shard 2 --start 50001 --end 100000
"""
from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import csv
import glob
import json
import os
import random
import re
import socket
import sqlite3
import string
import time
import warnings
from urllib.parse import urljoin, urlsplit

import httpx

from . import signals as S
from .common import MARKETPLACE_ROOTS, NON_STORE_ROOTS, _TLD, identity, registrable_domain
from .verify import SA_GEO, Fetcher, analyze, verify_one

warnings.filterwarnings("ignore")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "data", "saudi_ecom.sqlite")
TRANCO_CSV = os.path.join(ROOT, "data", "raw", "tranco_top1m.csv")
OUT_DIR = os.path.join(ROOT, "data", "tranco_shards")

COMMERCE_PLATFORMS = {"salla", "zid", "shopify", "woocommerce", "magento", "salesforce-commerce", "sap-hybris", "opencart",
                      "prestashop", "bigcommerce", "expandcart", "youcan", "matjrah", "wuilt", "ecwid", "vtex", "nopcommerce"}
SAUDI_PATHS = ["/en-sa/", "/ar-sa/", "/sa-en/", "/sa-ar/", "/sa/", "/ksa/"]
SAUDI_SUBS = ["sa", "ksa", "saudi"]
NONRETAIL_TLD = re.compile(r"\.(?:gov|edu|mil|int)(?:\.[a-z]{2})?$|\.(?:ac|go|gob|gouv|govt|gv|nic|mil|edu|gov)\.[a-z]{2}$", re.I)
NONRETAIL_NAME = re.compile(r"(?:^|[.-])(?:cdn|cdns|api|apis|static|analytics|metrics|telemetry|tracking|tracker|adserver|adservice|adsystem|"
                            r"doubleclick|akamai|cloudfront|edgekey|edgesuite|fastly|dns|nameserver|ntp|ocsp|crl|pki|pool|"
                            r"push|notify|beacon|pixel|tag|tags|gtm|sentry|stats|log|logs)(?:[.-]|\d|$)", re.I)
HREFLANG_SA = re.compile(r"<link[^>]+hreflang=[\"'](?:ar|en)[-_]sa[\"'][^>]*>", re.I)
HREFLANG_ANY = re.compile(r"hreflang=[\"']([a-z]{2}(?:[-_][a-z]{2})?)[\"']", re.I)
HREF = re.compile(r"href=[\"']([^\"'<>\s]{1,300})[\"']", re.I)
SA_LINK = re.compile(r"/(?:en|ar)[-_]sa(?:/|$|\?)|/sa[-_](?:en|ar)(?:/|$|\?)|/(?:ksa|saudi|saudi-arabia)(?:[-_](?:en|ar))?(?:/|$)|^https?://(?:sa|ksa|saudi)\.", re.I)
STRONG_SAUDI = ("sa_tld", "currency_SAR_code", "sar_prices", "saudi_phone", "vat_number", "saudi_platform")
NETWORK_REASONS = ("rate_limited%", "fetch_failed:timeout%", "fetch_failed:connect_error%", "fetch_failed:http_error%",
                   "fetch_failed:http_5%", "verification_timeout%", "http_5%", "verifier_error%")
SECONDARY_REASONS = re.compile(r"^(?:blocked_or_challenge|js_rendered|partial_ecommerce|robots_disallowed|fetch_failed|verification_timeout|rate_limited|http_5|http_403)")


def state_path(shard):
    return os.path.join(OUT_DIR, f"shard_{shard}_state.tar.gz")


def work_dir(shard):
    """Working files; restored from the committed state checkpoint when this VM has none."""
    d = os.path.join(ROOT, "data", "cache", "tranco", f"shard_{shard}")
    if not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
        if os.path.exists(state_path(shard)):
            import tarfile
            with tarfile.open(state_path(shard)) as tf:
                tf.extractall(d)
        out_csv = os.path.join(OUT_DIR, f"shard_{shard}.csv")
        if not os.path.exists(os.path.join(d, "carryover.csv")) and os.path.exists(out_csv):
            import shutil
            shutil.copy(out_csv, os.path.join(d, "carryover.csv"))
    return d


def save_state(shard):
    import tarfile
    d = work_dir(shard)
    tmp = state_path(shard) + ".tmp"
    with tarfile.open(tmp, "w:gz") as tf:
        for name in sorted(os.listdir(d)):
            tf.add(os.path.join(d, name), arcname=name)
    os.replace(tmp, state_path(shard))


def carryover_rows(shard):
    p = os.path.join(work_dir(shard), "carryover.csv")
    if not os.path.exists(p):
        return []
    with open(p, newline="") as fh:
        return list(csv.DictReader(fh))


def load_slice(start, end):
    out = []
    with open(TRANCO_CSV, newline="") as fh:
        for row in csv.reader(fh):
            r = int(row[0])
            if start <= r <= end:
                out.append((r, row[1].strip().lower()))
    return out


def known_sets():
    """Roots/keys already in the DB (any status) and roots whose stored result is a network/rate-limit failure."""
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    roots, keys = set(), set()
    for k, r in con.execute("SELECT key, root_domain FROM candidates"):
        keys.add(k)
        if r:
            roots.add(r)
    cond = " OR ".join("v.reason LIKE ?" for _ in NETWORK_REASONS)
    recheck = {}
    for k, u, r, ph in con.execute(f"""SELECT c.key, c.url, c.root_domain, c.platform_hint FROM candidates c JOIN verifications v ON v.key=c.key
                                       WHERE c.status='unverified' AND ({cond})""", NETWORK_REASONS):
        recheck.setdefault(r, []).append({"key": k, "url": u, "root_domain": r, "platform_hint": ph})
    con.close()
    return roots, keys, recheck


class ScreenFetcher(Fetcher):
    """Fetcher with short timeouts and a smaller read cap for the cheap screening pass."""

    def __init__(self, concurrency, per_host, req_timeout=20.0):
        super().__init__(concurrency, per_host)
        self.client = httpx.AsyncClient(headers=self.client.headers, follow_redirects=True, max_redirects=8,
                                        limits=httpx.Limits(max_connections=concurrency * 2, max_keepalive_connections=concurrency // 2),
                                        timeout=httpx.Timeout(10.0, connect=6.0), verify=False, http2=False)
        self.req_timeout = req_timeout

    async def _raw_get(self, url, headers=None, read_limit=1_000_000):
        return await asyncio.wait_for(super()._raw_get(url, headers, read_limit=min(read_limit, 1_000_000)), self.req_timeout)


DNS_TEMP_FAILS = [0]


async def resolves(host, rec=None):
    for attempt in range(3):
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            return sorted({i[4][0] for i in infos})
        except socket.gaierror as e:
            if e.errno != socket.EAI_AGAIN:
                return []
            await asyncio.sleep(2 + 3 * attempt)
        except Exception:
            return []
    DNS_TEMP_FAILS[0] += 1
    if rec is not None:
        rec["dns_temp_fail"] = rec.get("dns_temp_fail", 0) + 1
    return []


def force_ipv4(loop):
    """Halve DNS traffic (no AAAA lookups); IPv6 egress is not used from this VM anyway."""
    orig = loop.getaddrinfo

    async def gai(host, port, *, family=0, type=0, proto=0, flags=0):
        return await orig(host, port, family=family or socket.AF_INET, type=type, proto=proto, flags=flags)
    loop.getaddrinfo = gai


def page_eval(html, url, final):
    a = analyze(html[:1_000_000], final)
    plat = a["platform"]
    ecom = (plat in COMMERCE_PLATFORMS or a["add_to_cart"] >= 1 or a["n_product_links"] >= 3
            or "Product" in a["ld_types"] or a["cart"] >= 2)
    score, sev = S.saudi_signals(html[:1_000_000], a["text"], url, final, plat, set(a["ld_currency"]))
    strong = [k for k in STRONG_SAUDI if k in sev]
    if SA_GEO.search(final) and ("sa_locale" in sev):
        strong.append("sa_locale_url")
    host = (urlsplit(final).hostname or "").lower()
    return {"ecom": ecom, "platform": plat, "score": round(score, 1), "strong": strong, "sev": sev,
            "sa_host": host.endswith(".sa") and host not in ("salla.sa", "www.salla.sa"), "title": a["title"][:120],
            "thin": len(a["text"]) < 1200 and html.count("<script") >= 3}


def is_hit(ev):
    if ev["sa_host"]:
        return ev["ecom"] or ev["thin"]
    if not ev["ecom"]:
        return False
    s = set(ev["strong"])
    # A Saudi phone number or a Saudi-path URL alone is common on global sites; ask for something more.
    if s <= {"saudi_phone"}:
        return ev["score"] >= 4
    return bool(s)


BLOCKED_HTTP = {401, 403, 429, 503}


async def screen_domain(f: ScreenFetcher, rank, domain, state):
    rec = {"rank": rank, "domain": domain, "home": None, "hits": [], "probes": 0}
    root = registrable_domain(domain)
    ext = _TLD(root)
    label = ext.domain
    is_sa = root.endswith(".sa")

    async def fetch(url, tries=1):
        rec["probes"] += 1
        return await f.get(url, tries=tries)

    def add_hit(url, final, via, ev, http=None, note=""):
        ident = identity(final if final else url) or identity(url)
        if not ident:
            return
        rec["hits"].append({"url": final or url, "key": ident["key"], "root": ident["root_domain"], "via": via,
                            "http": http, "ecom": ev.get("ecom") if ev else None, "strong": ev.get("strong") if ev else [],
                            "score": ev.get("score") if ev else None, "title": ev.get("title") if ev else "", "note": note})

    # homepage
    home_final, home_html, st, err = None, "", None, None
    for u in (f"https://{domain}/", f"https://www.{domain}/" if not domain.startswith("www.") else None):
        if not u:
            continue
        st, final, html, _, err = await fetch(u, tries=2)
        if st is None and err == "connect_error":
            st, final, html, _, err = await fetch("http://" + u[8:], tries=1)
        if st is not None or err == "robots_disallowed":
            home_final, home_html = final, html
            break
    rec["home"] = {"http": st, "err": err, "final": (home_final or "")[:200]}
    home_ev = None
    blocked = st in BLOCKED_HTTP or (st is not None and st >= 400 and bool(re.search(r"captcha|cf-chl|just a moment|access denied", home_html[:5000], re.I)))
    if st is not None and 200 <= st < 400 and home_html:
        home_ev = page_eval(home_html, f"https://{domain}/", home_final)
        rec["home"].update({"ecom": home_ev["ecom"], "platform": home_ev["platform"], "strong": home_ev["strong"], "score": home_ev["score"]})
        if is_hit(home_ev):
            add_hit(f"https://{domain}/", home_final, "homepage", home_ev, st)
    elif is_sa and (blocked or err == "robots_disallowed"):
        add_hit(f"https://{domain}/", home_final, "homepage_blocked", {}, st, note=err or f"http_{st}")
    if is_sa:
        return rec

    home_host = (urlsplit(home_final or "").hostname or "").lower()
    home_root = registrable_domain(home_host) if home_host else root
    ecom = bool(home_ev and home_ev["ecom"])
    have_sa_variant = any(h["via"] != "homepage" or SA_GEO.search(h["url"]) for h in rec["hits"])

    # Saudi locale links advertised by the homepage (hreflang / anchors), same brand only
    sa_links = []
    if home_html:
        for tag in HREFLANG_SA.findall(home_html[:400_000]):
            m = re.search(r"href=[\"']([^\"']+)", tag)
            if m:
                sa_links.append(urljoin(home_final, m.group(1)))
        for href in HREF.findall(home_html[:600_000]):
            if SA_LINK.search(href):
                full = urljoin(home_final, href)
                h = (urlsplit(full).hostname or "").lower()
                if h and registrable_domain(h) in (root, home_root):
                    sa_links.append(full)
    seen_urls = set()
    for u in list(dict.fromkeys(sa_links))[:3]:
        if have_sa_variant:
            break
        seen_urls.add(u)
        st2, fin2, h2, _, err2 = await fetch(u)
        if st2 and 200 <= st2 < 400 and h2:
            ev = page_eval(h2, u, fin2)
            if is_hit(ev) and SA_GEO.search(fin2):
                add_hit(u, fin2, "locale_link", ev, st2)
                have_sa_variant = True

    # blind Saudi path probes: only for ecommerce-looking homepages that do not already list their locales without SA
    locales = {x.lower().replace("_", "-") for x in HREFLANG_ANY.findall(home_html[:400_000])} if home_html else set()
    lists_other_locales = len(locales) >= 3 and not any(x.endswith("-sa") for x in locales)
    if ecom and not have_sa_variant and not lists_other_locales and not blocked:
        base = f"{urlsplit(home_final).scheme}://{urlsplit(home_final).netloc}"
        misses = 0
        for p in SAUDI_PATHS:
            u = base + p
            if u in seen_urls:
                continue
            st2, fin2, h2, _, err2 = await fetch(u)
            if err2 == "robots_disallowed":
                continue
            if st2 is None or st2 >= 400:
                misses += 1
                if st2 in BLOCKED_HTTP or err2 == "timeout":
                    break
                continue
            if not SA_GEO.search(fin2) or not h2:
                continue
            ev = page_eval(h2, u, fin2)
            if is_hit(ev):
                add_hit(u, fin2, "saudi_path", ev, st2)
                have_sa_variant = True
                break

    # Saudi subdomains (skip wildcard DNS zones unless the brand sells online) and .sa siblings
    rand = "zz" + "".join(random.choice(string.ascii_lowercase) for _ in range(10))
    subs = [f"{s}.{root}" for s in SAUDI_SUBS]
    sib = [f"{label}.sa", f"{label}.com.sa"] if label and len(label) >= 2 else []
    res = await asyncio.gather(resolves(f"{rand}.{root}", rec), *(resolves(h, rec) for h in subs), *(resolves(h, rec) for h in sib))
    wildcard, sub_ips, sib_ips = res[0], res[1:1 + len(subs)], res[1 + len(subs):]
    for h, ips in zip(subs, sub_ips):
        if not ips or have_sa_variant:
            continue
        if wildcard and (set(ips) == set(wildcard)) and not ecom:
            continue
        st2, fin2, h2, _, err2 = await fetch(f"https://{h}/")
        fh = (urlsplit(fin2 or "").hostname or "").lower()
        if st2 and 200 <= st2 < 400 and h2 and (fh.split(".")[0] in SAUDI_SUBS or fh.endswith(".sa") or SA_GEO.search(fin2)):
            ev = page_eval(h2, f"https://{h}/", fin2)
            if is_hit(ev):
                add_hit(f"https://{h}/", fin2, "saudi_subdomain", ev, st2)
                have_sa_variant = True
        elif st2 in BLOCKED_HTTP and ecom:
            add_hit(f"https://{h}/", fin2, "saudi_subdomain_blocked", {}, st2, note=f"http_{st2}")
    for h, ips in zip(sib, sib_ips):
        if not ips:
            ips = await resolves("www." + h, rec)
        if not ips:
            continue
        if h in state["sibling_seen"]:
            continue
        state["sibling_seen"].add(h)
        if h in state["known_roots"]:
            rec.setdefault("sibling_known", []).append(h)
            continue
        st2, fin2, h2, _, err2 = await fetch(f"https://{h}/")
        if st2 is None and err2 not in ("robots_disallowed",):
            st2, fin2, h2, _, err2 = await fetch(f"https://www.{h}/")
        fh = (urlsplit(fin2 or "").hostname or "").lower()
        if st2 and 200 <= st2 < 400 and h2:
            ev = page_eval(h2, f"https://{h}/", fin2)
            if is_hit(ev) and (fh.endswith(".sa") or SA_GEO.search(fin2) or set(ev["strong"]) - {"saudi_phone"}):
                add_hit(f"https://{h}/", fin2, "sa_sibling", ev, st2, note=f"sibling of {domain}")
        elif st2 in BLOCKED_HTTP or err2 == "robots_disallowed":
            add_hit(f"https://{h}/", fin2, "sa_sibling_blocked", {}, st2, note=f"sibling of {domain}; {err2 or 'http_%s' % st2}")
    return rec


async def run_screen(shard, start, end, part, parts, concurrency):
    loop = asyncio.get_running_loop()
    loop.set_default_executor(concurrent.futures.ThreadPoolExecutor(max_workers=256))
    force_ipv4(loop)
    wd = work_dir(shard)
    out_path = os.path.join(wd, f"screened_{part}.jsonl")
    done = set()
    if os.path.exists(out_path):
        with open(out_path) as fh:
            for line in fh:
                try:
                    done.add(json.loads(line)["domain"])
                except (ValueError, KeyError):
                    pass
    roots, keys, recheck = known_sets()
    carried = {int(r["tranco_rank"]) for r in carryover_rows(shard)}
    items = [(r, d) for i, (r, d) in enumerate(load_slice(start, end)) if i % parts == part and d not in done]
    print(f"[screen {part}/{parts}] {len(items)} domains to process ({len(done)} already done)", flush=True)
    f = ScreenFetcher(concurrency, 2)
    state = {"known_roots": roots, "sibling_seen": set()}
    out = open(out_path, "a")
    t0 = time.time()
    n = [0]
    q: asyncio.Queue = asyncio.Queue()
    for it in items:
        q.put_nowait(it)

    async def worker():
        while True:
            try:
                rank, domain = q.get_nowait()
            except asyncio.QueueEmpty:
                return
            root = registrable_domain(domain)
            if rank in carried:
                rec = {"rank": rank, "domain": domain, "skip": "carryover_checkpoint_csv"}
            elif root in roots:
                rec = {"rank": rank, "domain": domain, "skip": "known_recheck" if root in recheck else "known"}
            elif NONRETAIL_TLD.search(root) or root in NON_STORE_ROOTS or NONRETAIL_NAME.search(domain):
                rec = {"rank": rank, "domain": domain, "skip": "nonretail_name"}
            elif root in MARKETPLACE_ROOTS:
                rec = {"rank": rank, "domain": domain, "skip": "marketplace"}
            else:
                partial = {"rank": rank, "domain": domain}
                try:
                    rec = await asyncio.wait_for(screen_domain(f, rank, domain, state), 150)
                except asyncio.TimeoutError:
                    rec = partial | {"error": "screen_timeout"}
                except Exception as e:
                    rec = partial | {"error": f"{type(e).__name__}:{str(e)[:80]}"}
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n[0] += 1
            if n[0] % 200 == 0:
                out.flush()
                el = time.time() - t0
                print(f"[screen {part}] {n[0]}/{len(items)} {n[0] / el * 60:.0f}/min req={f.stats['requests']}", flush=True)

    await asyncio.gather(*(worker() for _ in range(concurrency)))
    out.close()
    open(os.path.join(wd, f"screened_{part}.done"), "w").write(str(time.time()))
    print(f"[screen {part}] finished {n[0]} in {time.time() - t0:.0f}s", flush=True)


# ---------------------------------------------------------------- archived homepages of blocked domains

ARCHIVE_UA = {"User-Agent": "saudi-ecom-directory-research/1.0 (polite archive client)"}


async def archive_home(client, domain, page_url=None):
    """Latest Wayback capture (<=365 days) of a page this VM cannot read live: Saudi locale links / Saudi shop signals."""
    import datetime as dt
    url = f"https://web.archive.org/web/{dt.datetime.utcnow():%Y%m%d}id_/{page_url or f'https://{domain}/'}"
    for attempt in range(3):
        try:
            r = await client.get(url, timeout=60)
        except httpx.HTTPError:
            await asyncio.sleep(5 * (attempt + 1))
            continue
        if r.status_code in (429, 503):
            await asyncio.sleep(20 * (attempt + 1))
            continue
        break
    else:
        return {"err": "archive_fetch_failed"}
    if r.status_code != 200:
        return {"err": f"archive_http_{r.status_code}"}
    m = re.search(r"/web/(\d{14})", str(r.url))
    ts = m.group(1) if m else ""
    try:
        age = (dt.datetime.utcnow() - dt.datetime.strptime(ts, "%Y%m%d%H%M%S")).days
    except ValueError:
        age = 9999
    html = r.text[:1_000_000]
    orig = re.sub(r"^https?://web\.archive\.org/web/\d+(?:id_)?/", "", str(r.url))
    out = {"ts": ts, "age_days": age, "orig": orig[:200]}
    if age > 365:
        out["err"] = "capture_too_old"
        return out
    ev = page_eval(html, f"https://{domain}/", orig)
    out.update({"ecom": ev["ecom"], "strong": ev["strong"], "score": ev["score"], "title": ev["title"], "thin": ev["thin"]})
    root = registrable_domain(domain)
    links = []
    for tag in HREFLANG_SA.findall(html[:400_000]):
        mm = re.search(r"href=[\"']([^\"']+)", tag)
        if mm:
            links.append(mm.group(1))
    for href in HREF.findall(html[:600_000]):
        if SA_LINK.search(href):
            links.append(href)
    sa_links = []
    for l in links:
        l = re.sub(r"^(?:https?://web\.archive\.org)?/web/\d+(?:[a-z]{2}_)?/", "", l)
        full = urljoin(orig, l)
        h = (urlsplit(full).hostname or "").lower()
        if h and registrable_domain(h) == root and (SA_GEO.search(full) or h.split(".")[0] in SAUDI_SUBS):
            sa_links.append(full.split("#")[0])
    out["sa_links"] = list(dict.fromkeys(sa_links))[:3]
    out["hit"] = bool(out["sa_links"]) or is_hit(ev)
    return out


async def run_archive(shard, concurrency):
    wd = work_dir(shard)
    out_path = os.path.join(wd, "archive.jsonl")
    done = set()
    if os.path.exists(out_path):
        with open(out_path) as fh:
            done = {json.loads(l)["domain"] for l in fh if l.strip()}
    todo = []
    for rec in read_screened(shard):
        h = rec.get("home") or {}
        if rec.get("skip") or rec["domain"] in done or rec["domain"].endswith(".sa") or rec.get("hits"):
            continue
        if rec.get("error") or h.get("http") in BLOCKED_HTTP or h.get("err") in ("timeout", "robots_disallowed", "connect_error"):
            todo.append(rec)
    print(f"[archive] {len(todo)} blocked/unreachable domains", flush=True)
    sem = asyncio.Semaphore(concurrency)
    out = open(out_path, "a")
    n = [0]
    async with httpx.AsyncClient(headers=ARCHIVE_UA, follow_redirects=True) as client:
        async def one(rec):
            async with sem:
                try:
                    a = await asyncio.wait_for(archive_home(client, rec["domain"]), 200)
                except Exception as e:
                    a = {"err": f"{type(e).__name__}"}
            hits = []
            if a.get("hit"):
                for u in a.get("sa_links") or [f"https://{rec['domain']}/"]:
                    ident = identity(u)
                    if ident:
                        hits.append({"url": u, "key": ident["key"], "root": ident["root_domain"], "via": "archived_homepage",
                                     "http": (rec.get("home") or {}).get("http"), "ecom": a.get("ecom"), "strong": a.get("strong"),
                                     "score": a.get("score"), "title": a.get("title"), "note": f"wayback capture {a.get('ts')}"})
                        break
            out.write(json.dumps({"rank": rec["rank"], "domain": rec["domain"], "archive": a, "hits": hits}, ensure_ascii=False) + "\n")
            out.flush()
            n[0] += 1
            if hits or n[0] % 100 == 0:
                print(f"[archive] {n[0]}/{len(todo)} {rec['domain']} {a.get('err') or ''} hits={[h['url'] for h in hits]}", flush=True)
        await asyncio.gather(*(one(r) for r in todo))
    out.close()
    open(os.path.join(wd, "archive.done"), "w").write(str(time.time()))


# ---------------------------------------------------------------- verification

def read_archive(shard):
    p = os.path.join(work_dir(shard), "archive.jsonl")
    if not os.path.exists(p):
        return []
    with open(p) as fh:
        return [json.loads(l) for l in fh if l.strip()]


def read_screened(shard):
    recs = []
    for p in sorted(glob.glob(os.path.join(work_dir(shard), "screened_*.jsonl"))):
        with open(p) as fh:
            for line in fh:
                try:
                    recs.append(json.loads(line))
                except ValueError:
                    pass
    return recs


SOFT_404 = re.compile(r"not found|\b404\b|page introuvable|不存在|找不到|nicht gefunden|no encontrada|non trovata|غير موجود|bulunamad", re.I)


def keep_hit(h):
    if h["via"] in ("homepage_blocked", "sa_sibling_blocked", "saudi_subdomain_blocked", "archived_homepage"):
        return True
    if SOFT_404.search(h.get("title") or ""):
        return False
    strong = set(h.get("strong") or []) - {"saudi_phone"}
    if not is_saudi_specific(h["key"], h["url"]) and strong == {"sar_prices"} and (h.get("score") or 0) < 4.5:
        return False
    return True


def hit_targets(shard, recheck):
    """Unique verification targets (one per identity key), keeping the best-ranked source domain."""
    roots, keys, _ = known_sets()
    tg = {}
    for rec in read_screened(shard) + read_archive(shard):
        if rec.get("skip") == "known_recheck":
            for c in recheck.get(registrable_domain(rec["domain"]), []):
                tg.setdefault(c["key"], {**c, "rank": rec["rank"], "source_domain": rec["domain"], "via": "db_recheck_network_error", "screen": {}})
            continue
        for h in rec.get("hits", []):
            if h["key"] in keys or h["root"] in roots or not keep_hit(h):
                continue
            ident = identity(h["url"])
            if not ident:
                continue
            if ident["key"] not in tg or rec["rank"] < tg[ident["key"]]["rank"]:
                tg[ident["key"]] = {**ident, "rank": rec["rank"], "source_domain": rec["domain"], "via": h["via"], "screen": h}
    return tg


def is_saudi_specific(key, url):
    host = (urlsplit(url).hostname or "").lower()
    return key.endswith(".sa") or "|sa" in key or host.split(".")[0] in ("sa", "ksa", "saudi") or bool(SA_GEO.search(url))


def tranco_guard(res, t):
    """Global (non-Saudi-specific) domains need SAR pricing evidence, not only Saudi contact details."""
    if res["status"] != "verified" or is_saudi_specific(t["key"], res.get("final_url") or t["url"]) or res.get("platform") in ("salla", "zid"):
        return res
    try:
        sev = json.loads(res.get("saudi_evidence") or "{}")
    except ValueError:
        sev = {}
    if not (sev.get("currency_SAR_code") or sev.get("sar_prices") or sev.get("shopify_shop_country") == "SA"):
        res["status"] = "unverified"
        res["reason"] = "global_domain_saudi_contact_without_SAR_pricing (manual review); " + res["reason"]
    return res


async def run_secondary(t, res):
    from .secondary import UA_BROWSER, UA_RESEARCH, check
    item = {"key": t["key"], "url": res.get("final_url") or t["url"], "name": res.get("store_name") or t["key"],
            "domains": [t["root_domain"]], "global_root": "|" not in t["key"] and not t["key"].endswith(".sa")}
    async with httpx.AsyncClient(headers=UA_RESEARCH, follow_redirects=True) as arch, \
            httpx.AsyncClient(headers=UA_BROWSER, follow_redirects=True) as live, \
            httpx.AsyncClient(headers=UA_BROWSER, follow_redirects=True) as brw:
        return await asyncio.wait_for(check((arch, live, brw), item), 420)


async def run_verify(shard, watch, concurrency, sec_concurrency, parts):
    force_ipv4(asyncio.get_running_loop())
    wd = work_dir(shard)
    out_path = os.path.join(wd, "verified.jsonl")
    done = {}
    if os.path.exists(out_path):
        with open(out_path) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                    done[r["key"]] = r
                except (ValueError, KeyError):
                    pass
    _, _, recheck = known_sets()
    f = Fetcher(concurrency, 2)
    sem_sec = asyncio.Semaphore(sec_concurrency)
    out = open(out_path, "a")

    arch_client = httpx.AsyncClient(headers=ARCHIVE_UA, follow_redirects=True)

    async def one(t):
        if t["via"] == "saudi_subdomain_blocked":
            host = urlsplit(t["url"]).hostname
            rand = "zz" + "".join(random.choice(string.ascii_lowercase) for _ in range(10))
            a, b = await asyncio.gather(resolves(host), resolves(f"{rand}.{t['root_domain']}"))
            if b and set(a) == set(b):
                rec = {"key": t["key"], "status": "dropped", "reason": "wildcard DNS: Saudi subdomain is not a distinct site", "rank": t["rank"]}
                out.write(json.dumps(rec) + "\n")
                done[t["key"]] = rec
                return
        try:
            res = await asyncio.wait_for(verify_one(f, {"key": t["key"], "url": t["url"], "root_domain": t["root_domain"],
                                                        "platform_hint": t.get("platform_hint")}), 240)
        except asyncio.TimeoutError:
            res = {"key": t["key"], "final_url": t["url"], "status": "unverified", "reason": "verification_timeout", "verified_at": _now(), "evidence_url": t["url"]}
        except Exception as e:
            res = {"key": t["key"], "final_url": t["url"], "status": "unverified", "reason": f"verifier_error:{type(e).__name__}:{str(e)[:80]}",
                   "verified_at": _now(), "evidence_url": t["url"]}
        res = tranco_guard(res, t)
        run_sec = False
        if res["status"] == "unverified" and SECONDARY_REASONS.match(res.get("reason") or "") and (
                is_saudi_specific(t["key"], res.get("final_url") or t["url"]) or t["via"] == "archived_homepage"):
            if t["via"] == "archived_homepage" or (t.get("screen") or {}).get("ecom"):
                run_sec = True
            else:
                async with sem_sec:
                    try:
                        a = await asyncio.wait_for(archive_home(arch_client, urlsplit(t["url"]).hostname, t["url"]), 200)
                    except Exception as e:
                        a = {"err": type(e).__name__}
                res["archive_check"] = a
                if a.get("err"):
                    res["reason"] += f"; no usable recent Wayback capture ({a['err']})"
                elif a.get("ecom") or a.get("sa_links") or (set(a.get("strong") or []) - {"sa_tld", "saudi_phone"}):
                    run_sec = True
                elif a.get("thin"):
                    res["reason"] += f"; Wayback capture {a.get('ts')} is a JS shell without ecommerce markers"
                else:
                    res["status"] = "rejected"
                    res["reason"] = (f"no_ecommerce_evidence_in_archived_page (Wayback {a.get('ts')}: {a.get('title') or ''}); live: " + res["reason"])[:400]
                    res["evidence_url"] = f"https://web.archive.org/web/{a.get('ts')}/{a.get('orig')}"
        if run_sec:
            async with sem_sec:
                try:
                    sec = await run_secondary(t, res)
                    oks = [e for e in sec["evidence"] if e.get("ok")]
                    res["secondary"] = {"verdict": sec["verdict"], "ok": [{k: e.get(k) for k in ("type", "url", "date", "detail")} for e in oks]}
                    if sec["verdict"] == "verified_secondary_evidence":
                        res["status"] = "verified_secondary_evidence"
                        res["reason"] = "verified_secondary_evidence: " + " | ".join(f"{e['type']}: {e['detail']} ({e.get('url')}, {e.get('date')})" for e in oks)
                        res["evidence_url"] = oks[0].get("url")
                        res["verified_at"] = _now()
                    else:
                        res["reason"] += f"; secondary evidence insufficient ({len(oks)} type(s): {', '.join(e['type'] for e in oks) or 'none'})"
                except Exception as e:
                    res["reason"] += f"; secondary_error:{type(e).__name__}"
        res.pop("cat_text", None)
        rec = {**res, "rank": t["rank"], "source_domain": t["source_domain"], "via": t["via"], "root_domain": t["root_domain"], "target_url": t["url"],
               "screen": t.get("screen") or {}}
        out.write(json.dumps(rec, ensure_ascii=False) + "\n")
        out.flush()
        done[t["key"]] = rec
        print(f"[verify] r{t['rank']} {t['key']} -> {rec['status']} {str(rec.get('reason'))[:90]}", flush=True)

    while True:
        tg = hit_targets(shard, recheck)
        todo = [t for k, t in tg.items() if k not in done]
        finished = len(glob.glob(os.path.join(wd, "screened_*.done"))) >= parts
        if todo:
            print(f"[verify] {len(todo)} new targets ({len(done)} done)", flush=True)
            sem = asyncio.Semaphore(concurrency)

            async def guarded(t):
                async with sem:
                    await one(t)
            await asyncio.gather(*(guarded(t) for t in todo))
            write_outputs(shard, None, None, partial=True)
            continue
        if not watch or finished:
            break
        await asyncio.sleep(60)
    out.close()


def _now():
    import datetime as dt
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- export

CSV_COLS = ["store_name", "canonical_storefront_url", "root_domain", "tranco_rank", "platform", "category", "status",
            "saudi_evidence", "verification_url", "verification_utc", "reason"]


def fmt_evidence(sev_json, screen):
    try:
        sev = json.loads(sev_json or "{}")
    except ValueError:
        sev = {}
    parts = []
    for k, v in sev.items():
        if v is True:
            parts.append(k)
        elif isinstance(v, list):
            parts.append(f"{k}={','.join(map(str, v))}")
        else:
            parts.append(f"{k}={v}")
    if screen and screen.get("via"):
        parts.append(f"found_via={screen['via']}")
    return "; ".join(parts)


def load_verified(shard):
    path = os.path.join(work_dir(shard), "verified.jsonl")
    recs = {}
    if os.path.exists(path):
        with open(path) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                    recs[r["key"]] = r
                except (ValueError, KeyError):
                    pass
    return recs


STATUS_ORDER = {"verified": 0, "verified_secondary_evidence": 1, "unverified": 2, "rejected": 3}


def write_outputs(shard, start, end, partial=False, runtime=None):
    os.makedirs(OUT_DIR, exist_ok=True)
    recs = load_verified(shard)
    # collapse records that resolved to the same storefront (e.g. brand.com|sa and sa.brand.com redirecting together)
    best = {}
    for r in recs.values():
        if r.get("status") not in STATUS_ORDER:
            continue
        g = r.get("final_key") or r["key"]
        if g not in best or (STATUS_ORDER.get(r["status"], 9), r["rank"]) < (STATUS_ORDER.get(best[g]["status"], 9), best[g]["rank"]):
            best[g] = r
    rows = []
    for r in sorted(best.values(), key=lambda x: (STATUS_ORDER.get(x["status"], 9), x["rank"])):
        reason = r.get("reason") or ""
        if r.get("via") in ("sa_sibling", "sa_sibling_blocked"):
            reason = f"{reason} [found as .sa sibling of {r['source_domain']}]"
        elif r.get("via") == "db_recheck_network_error":
            reason = f"{reason} [re-check of DB candidate stored as network/rate-limit failure]"
        canon = r.get("final_url") or r.get("target_url")
        if r["status"] == "verified_secondary_evidence":
            canon = r.get("target_url") or canon
        rows.append({
            "store_name": r.get("store_name") or r["key"],
            "canonical_storefront_url": canon,
            "root_domain": r.get("root_domain"),
            "tranco_rank": r["rank"],
            "platform": r.get("platform") or "",
            "category": r.get("category") or "",
            "status": r["status"],
            "saudi_evidence": fmt_evidence(r.get("saudi_evidence"), r.get("screen")),
            "verification_url": (r.get("evidence_url") if r["status"] == "verified_secondary_evidence"
                                 else (r.get("product_evidence") or r.get("evidence_url") or canon)),
            "verification_utc": r.get("verified_at"),
            "reason": reason,
        })
    have = {(r["root_domain"], r["canonical_storefront_url"]) for r in rows}
    rows += [c for c in carryover_rows(shard) if (c["root_domain"], c["canonical_storefront_url"]) not in have]
    rows.sort(key=lambda x: (STATUS_ORDER.get(x["status"], 9), int(x["tranco_rank"])))
    with open(os.path.join(OUT_DIR, f"shard_{shard}.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLS)
        w.writeheader()
        w.writerows(rows)
    save_state(shard)
    if partial:
        return rows
    screened = read_screened(shard)
    by_dom = {}
    for s in screened:
        by_dom[s["domain"]] = s
    n_slice = len(load_slice(start, end))
    archive = read_archive(shard)
    skipped_known = sum(1 for s in by_dom.values() if s.get("skip") in ("known", "known_recheck"))
    skipped_nonretail = sum(1 for s in by_dom.values() if s.get("skip") in ("nonretail_name", "marketplace"))
    screened_n = sum(1 for s in by_dom.values() if not s.get("skip"))
    errors = sum(1 for s in by_dom.values() if s.get("error") or (s.get("home") and s["home"].get("http") is None and s["home"].get("err") not in ("dns_not_resolved", "robots_disallowed")))
    no_dns = sum(1 for s in by_dom.values() if s.get("home") and s["home"].get("err") == "dns_not_resolved")
    raw_hits = sum(len(s.get("hits", [])) for s in by_dom.values())
    hit_domains = sum(1 for s in by_dom.values() if s.get("hits"))
    counts = {k: sum(1 for r in rows if r["status"] == k) for k in STATUS_ORDER}
    summary = {
        "shard": shard, "rank_start": start, "rank_end": end,
        "tranco_list": "https://tranco-list.eu/list/64VVX/1000000 (top-1m.csv.zip downloaded 2026-10-17)",
        "domains_in_slice": n_slice,
        "domains_processed": len(by_dom),
        "skipped_as_known": skipped_known,
        "carried_over_from_checkpoint_csv": sum(1 for s in by_dom.values() if s.get("skip") == "carryover_checkpoint_csv"),
        "rechecked_known_network_errors": sum(1 for s in by_dom.values() if s.get("skip") == "known_recheck"),
        "skipped_nonretail_by_name": skipped_nonretail,
        "screened": screened_n,
        "saudi_hits": len(rows),
        "saudi_hit_domains": hit_domains,
        "raw_hit_pages": raw_hits,
        "verified": counts["verified"],
        "verified_secondary_evidence": counts["verified_secondary_evidence"],
        "unverified": counts["unverified"],
        "rejected": counts["rejected"],
        "blocked_or_unreachable_checked_via_wayback": len(archive),
        "wayback_capture_usable": sum(1 for x in archive if not x["archive"].get("err")),
        "wayback_hits": sum(1 for x in archive if x.get("hits")),
        "errors": errors,
        "homepage_dns_not_resolved": no_dns,
        "runtime_seconds": runtime,
    }
    with open(os.path.join(OUT_DIR, f"shard_{shard}_summary.json"), "w") as fh:
        json.dump(summary, fh, indent=2)
    return rows, summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["screen", "archive", "verify", "checkpoint", "export"])
    ap.add_argument("--shard", type=int, required=True)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=0)
    ap.add_argument("--part", type=int, default=0)
    ap.add_argument("--parts", type=int, default=1)
    ap.add_argument("--concurrency", type=int, default=120)
    ap.add_argument("--sec-concurrency", type=int, default=4)
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--runtime", type=float, default=None)
    a = ap.parse_args()
    if a.cmd == "screen":
        asyncio.run(run_screen(a.shard, a.start, a.end, a.part, a.parts, a.concurrency))
    elif a.cmd == "archive":
        asyncio.run(run_archive(a.shard, a.concurrency))
    elif a.cmd == "verify":
        asyncio.run(run_verify(a.shard, a.watch, a.concurrency, a.sec_concurrency, a.parts))
    elif a.cmd == "checkpoint":
        write_outputs(a.shard, a.start, a.end, partial=True)
    else:
        rows, summary = write_outputs(a.shard, a.start, a.end, runtime=a.runtime)
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
