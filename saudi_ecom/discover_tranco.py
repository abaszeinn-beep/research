"""Screen the current Tranco top-1M list for Saudi ecommerce storefronts.

Resumable via the jobs table (kind ``tranco_screen``). Hits are inserted with
``db.add_candidates`` (source ``tranco_screen:<list id>``) and left for the
existing verifier. Nothing here marks a store verified.

Phases, in rank order:
  * every ``.sa`` / ``.com.sa`` domain not already a candidate (full list)
  * other TLDs through ``--full-rank`` (default 200000): homepage Saudi signals,
    Saudi-path links, ``/en-sa`` and ``/sa`` when the rank is inside ``--path-rank``
    or the homepage geo-redirects, plus DNS siblings (``brand.sa``, ``brand.com.sa``,
    ``sa.`` / ``ksa.`` / ``saudi.``) fetched only when they resolve
  * homepage-only sweep from full-rank to ``--wide-rank`` when time allows

Robots.txt Disallow is honored. Challenges are not bypassed.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import re
import socket
import time
import zipfile
from collections import defaultdict
from urllib.parse import urljoin, urlsplit

import httpx

from . import db, signals as S
from .common import (
    DEFAULT_HEADERS,
    NON_STORE_ROOTS,
    SAUDI_SUBDOMAIN_LABELS,
    clean_host,
    identity,
    registrable_domain,
)
from .verify import FOREIGN_GEO, SA_GEO

RAW = __import__("os").path.join(__import__("os").path.dirname(__file__), "..", "data", "raw")
LIST_URL = "https://tranco-list.eu/top-1m.csv.zip"
LIST_API = "https://tranco-list.eu/api/lists/date/latest"
CHALLENGE = re.compile(
    r"just a moment\.\.\.|cf-chl|challenge-platform/h/|attention required! \| cloudflare|"
    r"captcha|are you a robot|incapsula|perimeterx|px-captcha|vercel security checkpoint",
    re.I,
)
HREF = re.compile(r"""href=["']([^"'#\s]+)""", re.I)
SA_PATH = re.compile(r"/(?:en-sa|ar-sa|sa-en|sa-ar|en_sa|ar_sa|saudi-en|saudi-ar)(?:/|$)", re.I)
SA_HOST = re.compile(r"^(?:sa|ksa|saudi|en-sa|ar-sa)\.", re.I)
SKIP_SUFFIX = (".gov.sa", ".edu.sa", ".med.sa", ".sch.sa", ".gov", ".edu", ".mil", ".int")
LABEL_SKIP = {
    "google", "www", "mail", "cdn", "api", "static", "blog", "news", "app", "apps",
    "m", "shop", "store", "online", "web", "secure", "login", "account", "support",
    "help", "docs", "status", "dev", "test", "staging", "beta", "demo", "img", "images",
    "media", "assets", "ns1", "ns2", "smtp", "ftp", "vpn", "portal", "admin",
}
# Bare "SR" is too common in Latin text; require an explicit riyal marker.
STRICT_SAR = re.compile(
    r"(?:\d[\d,.]{0,12}\s*(?:ر\.?\s?س|ريال|﷼|\bSAR\b))|(?:(?:\bSAR\b|ر\.?\s?س|﷼)\s*\d)|"
    r"[\"']SAR[\"']|currency(?:Code)?[\"']?\s*[:=]\s*[\"']SAR[\"']",
    re.I,
)
PHYSICAL_PLATFORMS = {
    "salla", "zid", "shopify", "woocommerce", "magento", "salesforce-commerce", "opencart",
    "prestashop", "bigcommerce", "expandcart", "youcan", "matjrah", "vtex", "ecwid",
}
# Global properties that show a currency and a cart but do not sell physical goods.
NOT_PHYSICAL_ROOTS = {
    "primevideo.com", "netflix.com", "spotify.com", "disneyplus.com", "hulu.com", "tv.apple.com",
    "dropbox.com", "box.com", "zoom.us", "slack.com", "notion.so", "microsoft.com", "office.com",
    "live.com", "icloud.com", "apple.com", "google.com", "youtube.com", "facebook.com",
    "instagram.com", "whatsapp.com", "linkedin.com", "twitter.com", "x.com", "tiktok.com",
    "snapchat.com", "reddit.com", "github.com", "gitlab.com", "paypal.com", "stripe.com",
    "booking.com", "airbnb.com", "agoda.com", "expedia.com", "uber.com", "careem.com",
    "wikipedia.org", "amazon.com", "aws.amazon.com", "adobe.com", "canva.com", "figma.com",
    "openai.com", "anthropic.com", "zoom.com", "webex.com", "docusign.com", "salesforce.com",
    "shopify.com", "wordpress.com", "blogspot.com", "medium.com",
}


def platform_of(html: str):
    for name, rx in S.PLATFORM_MARKERS:
        if rx.search(html):
            return name
    return None


class Screener:
    def __init__(self, concurrency: int):
        self.sem = asyncio.Semaphore(concurrency)
        self.client = httpx.AsyncClient(
            headers={**DEFAULT_HEADERS, "User-Agent": DEFAULT_HEADERS["User-Agent"]},
            follow_redirects=True,
            timeout=httpx.Timeout(12.0, connect=6.0),
            limits=httpx.Limits(max_connections=concurrency * 2, max_keepalive_connections=concurrency),
            verify=False,
        )
        self.robots: dict[str, object] = {}
        self.robots_lock: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.host_last: dict[str, float] = defaultdict(float)

    async def aclose(self):
        await self.client.aclose()

    async def _read(self, url, limit):
        async with self.client.stream("GET", url) as r:
            chunks, n = [], 0
            async for ch in r.aiter_bytes():
                chunks.append(ch)
                n += len(ch)
                if n >= limit:
                    break
            body = b"".join(chunks)
            enc = r.encoding or "utf-8"
            try:
                text = body.decode(enc, errors="replace")
            except LookupError:
                text = body.decode("utf-8", errors="replace")
            return r.status_code, str(r.url), text

    async def allowed(self, url) -> bool:
        import urllib.robotparser
        sp = urlsplit(url)
        base = f"{sp.scheme}://{sp.netloc}"
        async with self.robots_lock[base]:
            if base not in self.robots:
                rp = None
                try:
                    async with self.sem:
                        st, _, txt = await asyncio.wait_for(self._read(base + "/robots.txt", 40_000), 2)
                    if st == 200 and "<html" not in txt[:400].lower():
                        rp = urllib.robotparser.RobotFileParser()
                        rp.parse(txt.splitlines())
                except Exception:
                    rp = None
                self.robots[base] = rp
        rp = self.robots[base]
        if rp is None:
            return True
        try:
            return rp.can_fetch("*", url)
        except Exception:
            return True

    async def get(self, url, limit=140_000):
        if not await self.allowed(url):
            return None, url, "", "robots_disallowed"
        host = (urlsplit(url).hostname or "").lower()
        gap = time.monotonic() - self.host_last[host]
        if gap < 0.4:
            await asyncio.sleep(0.4 - gap)
        async with self.sem:
            self.host_last[host] = time.monotonic()
            try:
                st, final, text = await asyncio.wait_for(self._read(url, limit), 6)
                return st, final, text, None
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                msg = str(e).lower()
                if "name or service not known" in msg or "nodename" in msg or "no address" in msg or "getaddrinfo" in msg:
                    return None, url, "", "dns"
                return None, url, "", "connect"
            except (httpx.ReadTimeout, httpx.TimeoutException, asyncio.TimeoutError):
                return None, url, "", "timeout"
            except httpx.HTTPError:
                return None, url, "", "http_error"


def same_org(domain: str, final: str) -> bool:
    """Keep a hit only when the final host is the domain we probed, or its Saudi sibling."""
    host = clean_host(urlsplit(final or "").hostname or "")
    if not host:
        return False
    fr, dr = registrable_domain(host), registrable_domain(domain)
    if fr == dr:
        return True
    return host.endswith(".sa") and host.split(".")[0] == dr.split(".")[0]


def looks_like_store(html: str, final: str, domain: str):
    """Return a short reason when the page is a plausible Saudi storefront for physical goods.

    A currency mention plus the word "cart" is not enough on a global domain: SaaS and
    streaming sites list SAR in a billing widget. Non-.sa pages need a commerce platform
    or real product links together with more than one SAR marker, or a Saudi URL.
    """
    if not html or S.PARKED.search(html[:25000]) or S.CLOSED.search(html[:25000]):
        return None
    if CHALLENGE.search(html[:6000]):
        return None
    if not same_org(domain, final):
        return None
    host = clean_host(urlsplit(final).hostname or "")
    root = registrable_domain(host)
    if root in NON_STORE_ROOTS or root in NOT_PHYSICAL_ROOTS or host in NOT_PHYSICAL_ROOTS:
        return None
    sample = html[:180000]
    plat = platform_of(sample)
    if plat not in PHYSICAL_PLATFORMS:
        plat = None
    sar_n = len(STRICT_SAR.findall(sample))
    sar_code = bool(S.SAR_CURRENCY_CODE.search(sample))
    strong_sar = sar_n >= 2 or (sar_code and sar_n >= 1)
    products = bool(S.PRODUCT_LINK.search(sample))
    cart = bool(S.ADD_TO_CART.search(sample) or S.CART_CHECKOUT.search(sample))
    is_sa = domain.endswith(".sa") or host.endswith(".sa")
    saudi_url = bool(SA_GEO.search(final or "") or (host.split(".")[:1] and host.split(".")[0] in SAUDI_SUBDOMAIN_LABELS))
    if plat in ("salla", "zid") and (is_sa or strong_sar or saudi_url or S.SAUDI_PHONE.search(sample)):
        return f"platform:{plat}"
    if is_sa and (plat or products or (cart and (strong_sar or sar_n >= 1))):
        return f"sa_tld+{plat or ('products' if products else 'cart')}"
    if saudi_url and (plat or products) and (strong_sar or plat in ("salla", "zid", "shopify", "woocommerce", "magento")):
        return f"locale+{plat or 'products'}"
    if strong_sar and (plat or products) and (cart or plat):
        return f"sar+{plat or 'products'}"
    return None


def saudi_links(html: str, base: str, domain: str):
    root = registrable_domain(domain)
    out = []
    for href in HREF.findall(html or "")[:400]:
        absu = urljoin(base, href)
        sp = urlsplit(absu)
        host = clean_host(sp.hostname or "")
        if not host:
            continue
        if not (SA_PATH.search(sp.path or "") or SA_HOST.match(host)):
            continue
        hroot = registrable_domain(host)
        if hroot != root and not host.endswith(".sa"):
            continue
        if absu not in out:
            out.append(absu)
        if len(out) >= 2:
            break
    return out


def dns_resolves(host: str) -> bool:
    try:
        socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        return True
    except Exception:
        return False


def sibling_hosts(domain: str, rank: int):
    """brand.sa / brand.com.sa always; sa./ksa./saudi. subdomains for the top 100k."""
    root = registrable_domain(domain)
    label = root.split(".")[0]
    if len(label) < 4 or label in LABEL_SKIP or not re.match(r"^[a-z0-9-]+$", label):
        return []
    hosts = [f"{label}.sa", f"{label}.com.sa"]
    if rank <= 100_000 and not root.endswith(".sa"):
        hosts += [f"sa.{root}", f"ksa.{root}", f"saudi.{root}"]
    return hosts


def load_list(path):
    rows = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or "," not in line:
                continue
            rank, dom = line.split(",", 1)
            dom = dom.strip().lower().rstrip(".")
            if dom.startswith("www."):
                dom = dom[4:]
            try:
                rows.append((int(rank), dom))
            except ValueError:
                continue
    return rows


def known_roots(con) -> set[str]:
    known = {r[0] for r in con.execute("SELECT DISTINCT root_domain FROM candidates") if r[0]}
    for (doms,) in con.execute("SELECT domains FROM reference_stores"):
        for d in (doms or "").split():
            known.add(registrable_domain(d))
    return known


def done_jobs(con) -> set[str]:
    return {r[0] for r in con.execute("SELECT job FROM jobs WHERE kind='tranco_screen' AND status='done'")}


def retry_jobs(con) -> set[str]:
    return {r[0] for r in con.execute("SELECT job FROM jobs WHERE kind='tranco_screen' AND status='retry'")}


TRANSIENT = {"dns", "timeout", "connect", "http_error"}


def flush(con, jobs, hits):
    if not jobs and not hits:
        return 0
    new = 0
    for _ in range(8):
        try:
            con.execute("BEGIN IMMEDIATE")
            if jobs:
                con.executemany(
                    "INSERT INTO jobs VALUES (?,?,?,?,?,?,?) ON CONFLICT(kind,job) DO UPDATE SET status=excluded.status,n=excluded.n,n_new=excluded.n_new,ts=excluded.ts,info=excluded.info",
                    jobs,
                )
            con.execute("COMMIT")
            break
        except Exception:
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
            time.sleep(1)
    if hits:
        # group by detail so source rows stay accurate; one source string is shared
        by = defaultdict(list)
        for url, pr, detail in hits:
            by[detail].append((url, pr))
        for detail, items in by.items():
            new += db.add_candidates(con, items, source=detail[0], detail=detail[1], priority=0)
    return new


def download(dest_csv: str) -> str:
    import os
    os.makedirs(os.path.dirname(dest_csv), exist_ok=True)
    list_id = "latest"
    try:
        meta = httpx.get(LIST_API, timeout=30, headers={"User-Agent": "saudi-ecom-directory-research/1.0"})
        if meta.status_code == 200:
            list_id = meta.json().get("list_id") or list_id
            print(f"[tranco] latest list {list_id} date={meta.json().get('date')}", flush=True)
    except httpx.HTTPError as e:
        print("[tranco] list api failed", type(e).__name__, flush=True)
    r = httpx.get(LIST_URL, timeout=180, follow_redirects=True, headers={"User-Agent": "saudi-ecom-directory-research/1.0"})
    r.raise_for_status()
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    name = zf.namelist()[0]
    with zf.open(name) as src, open(dest_csv, "wb") as dst:
        dst.write(src.read())
    id_path = dest_csv + ".id"
    open(id_path, "w").write(list_id)
    print(f"[tranco] wrote {dest_csv} ({os.path.getsize(dest_csv)} bytes) id={list_id}", flush=True)
    return list_id


async def resolve_siblings(rows, full_rank, known: set, finished: set):
    """Resolve brand.sa / brand.com.sa / sa.|ksa.|saudi. siblings. HTTP is done later, only for names that exist."""
    import concurrent.futures
    hosts = []
    seen = set()
    for rank, domain in rows:
        if domain.endswith(".sa") or rank > full_rank:
            continue
        for host in sibling_hosts(domain, rank):
            root = registrable_domain(host)
            if root in known or root in NON_STORE_ROOTS or host in seen or host in finished:
                continue
            seen.add(host)
            hosts.append((rank, host))
    print(f"[tranco] sibling names to resolve: {len(hosts)}", flush=True)
    if not hosts:
        return []
    # Keep this well below a flood: the shared resolver also serves the verifier and other workers.
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=24)
    loop = asyncio.get_running_loop()
    sem = asyncio.Semaphore(24)
    good = []

    async def chk(rank, host):
        async with sem:
            try:
                ok = await loop.run_in_executor(ex, dns_resolves, host)
            except Exception:
                ok = False
        if ok:
            good.append((rank, host))
            if len(good) <= 15:
                print(f"[tranco] dns ok {host} (parent rank {rank})", flush=True)

    for i in range(0, len(hosts), 4000):
        chunk = hosts[i:i + 4000]
        await asyncio.gather(*(chk(r, h) for r, h in chunk))
        print(f"[tranco] sibling dns {min(i + 4000, len(hosts))}/{len(hosts)} resolved={len(good)}", flush=True)
    ex.shutdown(wait=False)
    return good


def drop_wildcard_subdomains(resolved):
    """If sa., ksa. and saudi. all resolve under one parent, that zone is a wildcard, not a Saudi store."""
    from collections import defaultdict
    prefixes = ("sa.", "ksa.", "saudi.")
    seen = defaultdict(set)
    for _rank, host in resolved:
        for pfx in prefixes:
            if host.startswith(pfx):
                seen[host[len(pfx):]].add(pfx)
                break
    wild = {root for root, pfxs in seen.items() if len(pfxs) >= 3}
    kept = []
    for rank, host in resolved:
        parent = None
        for pfx in prefixes:
            if host.startswith(pfx):
                parent = host[len(pfx):]
                break
        if parent in wild:
            continue
        kept.append((rank, host))
    return kept, len(resolved) - len(kept)


async def screen(con, rows, list_id, full_rank, path_rank, wide_rank, concurrency, known, finished, retried):
    db.register_source(con, f"tranco_screen:{list_id}", "tranco", f"Tranco top-1M list {list_id} screened for Saudi storefront signals", notes="hits only; verification is separate")
    sc = Screener(concurrency)
    stats = defaultdict(int)
    pending_jobs = []
    pending_hits = []
    t0 = time.time()

    def queue_job(domain, rank, phase, result):
        result = result if isinstance(result, str) else "miss"
        status = "retry" if result in TRANSIENT and domain not in retried else "done"
        pending_jobs.append(("tranco_screen", domain, status, rank, 1 if result.startswith("hit") else 0, db.now(), f"{list_id}|{phase}|{result}"[:500]))

    async def consider(url, rank, phase, domain_for_sa=None):
        st, final, html, err = await sc.get(url)
        dom = domain_for_sa or registrable_domain(clean_host(urlsplit(url).hostname or ""))
        if err:
            return err, None
        if st in (403, 429, 503) or (html and CHALLENGE.search(html[:6000])):
            if dom.endswith(".sa") and rank <= 150_000:
                return "blocked_queue", url
            return f"blocked_{st or 'challenge'}", None
        why = looks_like_store(html or "", final or url, dom)
        if why and st == 200:
            return "hit:" + why, final or url
        return f"miss_{st}", (html, final or url)

    async def one(rank, domain):
        if domain in finished or domain in NON_STORE_ROOTS or domain.endswith(SKIP_SUFFIX):
            stats["skip"] += 1
            return
        root = registrable_domain(domain)
        if root in NON_STORE_ROOTS:
            stats["skip"] += 1
            return
        # A .sa root already in the candidate table was screened before. A global root
        # already in the table still gets Saudi-path and sibling probes (different identity key).
        if domain.endswith(".sa") and root in known:
            stats["known"] += 1
            finished.add(domain)
            return
        phase = "sa" if domain.endswith(".sa") else ("full" if rank <= full_rank else "wide")
        if not domain.endswith(".sa") and rank > wide_rank:
            return
        skip_home = (not domain.endswith(".sa")) and root in known
        if skip_home and rank > path_rank:
            stats["known"] += 1
            finished.add(domain)
            return
        home = f"https://{domain}/" if domain.endswith(".sa") else f"https://www.{domain}/"
        if skip_home:
            result, payload = "known_root", ("", home)
        else:
            result, payload = await consider(home, rank, phase, domain)
            if result == "dns" and not domain.endswith(".sa"):
                result, payload = await consider(f"https://{domain}/", rank, phase, domain)
        hit_url = None
        html = ""
        final = home
        if isinstance(result, str) and result.startswith("hit:"):
            hit_url = payload
        elif result == "blocked_queue":
            hit_url = payload
        elif isinstance(payload, tuple):
            html, final = payload
        # Saudi path variants for non-.sa (homepage, geo-redirect, or a failed homepage on a high rank)
        if not hit_url and not domain.endswith(".sa") and rank <= full_rank and (isinstance(payload, tuple) or (rank <= path_rank and result in {"timeout", "connect", "dns", "http_error"})):
            links = saudi_links(html, final, domain) if html else []
            geo = bool(FOREIGN_GEO.search(final or "")) and not SA_GEO.search(final or "")
            # Forced /en-sa and /sa fetches are limited to the very top, to domains that
            # geo-redirect, and to roots already in the DB. Everyone else is judged from
            # the homepage plus any Saudi link the homepage itself publishes.
            if skip_home or geo or not html or rank <= 2_000:
                origin = f"https://www.{domain}"
                for extra in (origin + "/en-sa/", origin + "/sa/"):
                    if extra not in links:
                        links.append(extra)
            for link in links[:3]:
                r2, p2 = await consider(link, rank, phase + "_path", domain)
                if isinstance(r2, str) and (r2.startswith("hit:") or r2 == "blocked_queue"):
                    result, hit_url = r2, p2
                    break
        if hit_url and identity(hit_url):
            pr = 8 if rank <= 20_000 else 7 if rank <= 100_000 else 6 if rank <= full_rank else 5
            pending_hits.append((hit_url, pr, (f"tranco_screen:{list_id}", f"rank {rank} {result}")))
            known.add(registrable_domain(clean_host(urlsplit(hit_url).hostname or domain)))
            stats["hits"] += 1
            print(f"[tranco] HIT rank={rank} {domain} -> {hit_url} ({result})", flush=True)
        else:
            stats["miss"] += 1
        queue_job(domain, rank, phase, result if isinstance(result, str) else "miss")
        finished.add(domain)
        stats["screened"] += 1

    sem = asyncio.Semaphore(concurrency)

    async def wrapped(item):
        async with sem:
            try:
                await one(*item)
            except Exception as e:
                stats["errors"] += 1
                print(f"[tranco] error {item} {type(e).__name__}: {e}", flush=True)

    async def run_rows(todo, wide):
        batch = []
        for rank, domain in todo:
            if domain in finished:
                continue
            if domain.endswith(".sa"):
                pass
            elif rank > wide or domain in finished:
                continue
            elif registrable_domain(domain) in known and rank > path_rank:
                stats["known"] += 1
                continue
            batch.append((rank, domain))
            if len(batch) >= 120:
                await asyncio.gather(*(wrapped(it) for it in batch))
                batch = []
                new = flush(con, pending_jobs, pending_hits)
                stats["new"] += new
                pending_jobs.clear()
                pending_hits.clear()
                db.heartbeat(con, "tranco_screen", "code-worker(asyncio)", concurrency, {k: int(stats[k]) for k in ("screened", "hits", "new", "known", "miss")})
                rate = stats["screened"] / max(time.time() - t0, 1)
                print(f"[tranco] screened={stats['screened']} hits={stats['hits']} new={stats['new']} known={stats['known']} {rate:.1f}/s", flush=True)
        if batch:
            await asyncio.gather(*(wrapped(it) for it in batch))
            stats["new"] += flush(con, pending_jobs, pending_hits)
            pending_jobs.clear()
            pending_hits.clear()

    # HTTP first. Sibling DNS runs after so a large resolver burst cannot turn the homepage pass into false DNS misses.
    await run_rows(rows, wide_rank)
    resolved = await resolve_siblings(rows, full_rank, set(known), set(finished))
    resolved, wild = drop_wildcard_subdomains(resolved)
    print(f"[tranco] wildcard subdomain names dropped: {wild}", flush=True)
    extra = [(r, h) for r, h in resolved if h not in finished and registrable_domain(h) not in known]
    print(f"[tranco] sibling hosts that resolve: {len(resolved)}; fetching {len(extra)}", flush=True)
    stats["dns_hit"] = len(resolved)
    await run_rows(extra, full_rank)
    await sc.aclose()
    print("[tranco] done", dict(stats), flush=True)
    return stats


def main():
    import os
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=os.path.join(RAW, "tranco_latest.csv"))
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--full-rank", type=int, default=200_000)
    ap.add_argument("--path-rank", type=int, default=50_000)
    ap.add_argument("--wide-rank", type=int, default=400_000)
    ap.add_argument("--concurrency", type=int, default=24)
    ap.add_argument("--limit", type=int, default=0, help="screen at most this many not-yet-done domains (0 = all)")
    a = ap.parse_args()
    if a.download or not os.path.exists(a.csv):
        list_id = download(a.csv)
    else:
        id_path = a.csv + ".id"
        list_id = open(id_path).read().strip() if os.path.exists(id_path) else "cached"
    rows = load_list(a.csv)
    print(f"[tranco] {len(rows)} domains, id={list_id}", flush=True)
    con = db.connect()
    from . import reference
    ref = reference.connect()
    ref.close()
    known = known_roots(con)
    finished = done_jobs(con)
    retried = retry_jobs(con)
    print(f"[tranco] already known roots={len(known)} screened={len(finished)} retry={len(retried)}", flush=True)
    if a.limit:
        # keep rank order, cap the work queue
        kept = []
        for rank, domain in rows:
            if domain in finished:
                continue
            if not domain.endswith(".sa") and rank > a.wide_rank:
                continue
            kept.append((rank, domain))
            if len(kept) >= a.limit:
                break
        rows = kept
        print(f"[tranco] limited to {len(rows)} domains", flush=True)
    asyncio.run(screen(con, rows, list_id, a.full_rank, a.path_rank, a.wide_rank, a.concurrency, known, finished, retried))


if __name__ == "__main__":
    main()
