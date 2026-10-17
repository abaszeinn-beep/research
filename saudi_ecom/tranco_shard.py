"""Screen a Tranco rank slice for Saudi physical-goods storefronts, then verify the hits.

  python3 -m saudi_ecom.tranco_shard --shard 3 --start 100001 --end 150000 --tranco /tmp/tranco/top-1m.csv

Stage 1 (cheap screen, aiohttp): robots.txt-respecting homepage fetch per domain; for non-.sa domains also
Saudi path variants (only when the homepage shows commerce or locale hints), sa./ksa./saudi. subdomains and
<label>.sa / <label>.com.sa siblings (only when DNS resolves and the zone is not wildcarded).
Stage 2: every hit goes through `verify.verify_one` (the existing per-platform verifier); hits the live
verifier cannot read (bot wall, JS-only) go through `secondary.check` (>=2 independent current proofs).
State is kept in a local SQLite file so a restart resumes where it stopped.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import random
import re
import socket
import sqlite3
import subprocess
import time
import urllib.robotparser
from collections import Counter, defaultdict
from urllib.parse import urlsplit

import aiohttp
import aiodns
import httpx

from . import signals as S
from .common import DEFAULT_HEADERS, MARKETPLACE_ROOTS, NON_STORE_ROOTS, _TLD, identity, registrable_domain
from .verify import CHALLENGE, SA_GEO, Fetcher, verify_one

PATH_VARIANTS = ["/en-sa/", "/ar-sa/", "/sa-en/", "/sa-ar/", "/sa/", "/ksa/"]
SUB_VARIANTS = ["sa", "ksa", "saudi"]
NETWORK_REASON = re.compile(r"^(?:fetch_failed|rate_limited|verification_timeout|http_5\d\d|verifier_error)", re.I)
BROWSER_REASON = re.compile(r"^(?:js_rendered|partial_ecommerce|no_ecommerce_evidence|insufficient_ecommerce|weak_ecommerce|fetch_failed:http_error|fetch_failed:timeout|verification_timeout)", re.I)
SECONDARY_REASON = re.compile(r"^(?:blocked_or_challenge|js_rendered|partial_ecommerce|robots_disallowed|fetch_failed|verification_timeout|rate_limited|http_5)", re.I)

NON_RETAIL_SUFFIX = re.compile(r"(?:^|\.)(?:gov|gob|gouv|govt|mil|edu|ac|sch|int|nhs)(?:\.[a-z]{2})?$|\.(?:gov|edu|mil|int)$", re.I)
NON_RETAIL_LABEL = re.compile(
    r"(?:^|[-.])(?:cdn|cdns|dns|ntp|api|apis|static|assets|edge|telemetry|tracking|tracker|analytics|metrics|adserver|adsrv|"
    r"adservice|ads|adtech|pixel|push|smtp|mail|mx|vpn|proxy|stun|turn|ocsp|crl|pki|update|updates|sync|login|auth|sso|"
    r"akamai|akamaized|cloudfront|fastly|edgekey|edgesuite|azureedge|googlevideo|gvt\d|nflxvideo|ttvnw|doubleclick|"
    r"bank|banking|casino|bet|betting|poker|porn|sex|xxx|news|gazette|times|daily|tribune|herald|journal|radio|tv|"
    r"wiki|forum|university|college|school|church|hospital)(?:\d*)(?:[-.]|$)", re.I)
ADULT_GAMBLING = re.compile(r"porn|xxx|\bsex|سكس|نيك|escort|hentai|casino|kasino|\bslots?\b|slot ?online|\btogel|toto\b|\bbet(?:ting)?\b|judi|gacor|poker|baccarat|bandar|قمار|مراهنات", re.I)
NON_RETAIL_CONTENT = re.compile(r'"@type"\s*:\s*"(?:NewsArticle|NewsMediaOrganization)"|og:type["\'][^>]*content=["\']article', re.I)

SAR_STRONG = re.compile(r"\d[\d,.]*\s*(?:ر\.?\s?س|SAR|﷼)(?![A-Za-z])|(?<![A-Za-z])(?:SAR|ر\.?\s?س|﷼)\s*\d", re.I)
RIYAL = re.compile(r"\d[\d,.]*\s*ريال|ريال\s*سعودي", re.I)
PHONE_966 = re.compile(r"(?:\+|00)\s?966[\s\-]?\(?[1-9]|wa\.me/966|whatsapp\.com/send\?phone=966")
SAUDI_SHIP = re.compile(r"(?:shipping|delivery|ship) (?:to|across|within|in) (?:the )?(?:KSA|Saudi)|التوصيل (?:إلى|الى|داخل|لجميع مدن) (?:المملكة|السعودية)|الشحن (?:إلى|الى|داخل|لجميع مناطق) (?:المملكة|السعودية)|شحن مجاني .{0,30}(?:المملكة|السعودية)", re.I)
HREFLANG_SA = re.compile(r"hreflang=[\"'](?:ar|en)[-_]SA[\"']", re.I)
SA_LINK = re.compile(r"href=[\"'][^\"']{0,120}?/(?:en-sa|ar-sa|sa-en|sa-ar|en_sa|ar_sa|ksa|saudi(?:-arabia)?|sa)/[\"']", re.I)
GEO_HINT = re.compile(r"hreflang=[\"'][a-z]{2}[-_][a-z]{2}[\"']|/(?:en|ar)-(?:ae|kw|qa|bh|om|sa|eg|us|gb)/|country[-_ ]?(?:selector|switch|picker)|select (?:your )?country|choose (?:your )?country|اختر الدولة|اختر بلدك", re.I)
SAUDI_TITLE = re.compile(r"السعودية|السعوديه|المملكة العربية|\bSaudi\b|\bKSA\b", re.I)
SHOP_WORDS = re.compile(r"تسوق|متجر|منتجات|اشتر|عروض|\bshop|\bstore\b|online shopping|\bbuy\b|\bproducts?\b|أونلاين|اونلاين|e-?commerce", re.I)
DENIED = re.compile(r"access to this page has been denied|request blocked|you have been blocked|access denied|security check", re.I)
HREFLANG_ALT = re.compile(r"<link[^>]+hreflang=[\"'](?:ar|en)[-_]sa[\"'][^>]*>", re.I)
COMMERCE_PLATFORMS = {"salla", "zid", "shopify", "woocommerce", "magento", "salesforce-commerce", "sap-hybris", "opencart", "prestashop",
                      "bigcommerce", "expandcart", "youcan", "matjrah", "vtex", "ecwid", "wuilt"}

UA = {**DEFAULT_HEADERS}
MAX_READ = 500_000
POOL = None


async def analyze_page(html, final):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(POOL, page_signals, html, final)


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Screener:
    def __init__(self, concurrency: int):
        self.sem = asyncio.Semaphore(concurrency)
        self.dns_sem = asyncio.Semaphore(200)
        self.host_sem: dict[str, asyncio.Semaphore] = defaultdict(lambda: asyncio.Semaphore(2))
        self.host_last: dict[str, float] = defaultdict(float)
        self.robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self.robots_lock: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.stats = Counter()
        self.resolver = aiodns.DNSResolver(timeout=4, tries=2)
        conn = aiohttp.TCPConnector(limit=concurrency + 50, limit_per_host=2, ttl_dns_cache=600, ssl=False,
                                    resolver=aiohttp.AsyncResolver(), enable_cleanup_closed=True)
        self.session = aiohttp.ClientSession(connector=conn, headers=UA, max_line_size=65536, max_field_size=65536,
                                             cookie_jar=aiohttp.DummyCookieJar())

    async def close(self):
        await self.session.close()

    async def resolves(self, host: str) -> bool:
        async with self.dns_sem:
            for qtype in ("A", "AAAA"):
                try:
                    r = await asyncio.wait_for(self.resolver.query(host, qtype), 10)
                    if r:
                        return True
                except Exception:
                    continue
        return False

    async def _get(self, url, timeout=12.0, limit=MAX_READ):
        host = (urlsplit(url).hostname or "").lower()
        async with self.sem, self.host_sem[host]:
            gap = time.monotonic() - self.host_last[host]
            if gap < 0.4:
                await asyncio.sleep(0.4 - gap)
            self.host_last[host] = time.monotonic()
            self.stats["requests"] += 1
            async with self.session.get(url, allow_redirects=True, max_redirects=8,
                                        timeout=aiohttp.ClientTimeout(total=timeout, sock_connect=6, sock_read=8)) as r:
                body = await r.content.read(limit)
                enc = r.charset or "utf-8"
                try:
                    text = body.decode(enc, errors="replace")
                except LookupError:
                    text = body.decode("utf-8", errors="replace")
                return r.status, str(r.url), text, r.headers.get("retry-after", "")

    async def get(self, url, timeout=12.0, limit=MAX_READ, tries=2):
        """Return (status, final_url, text, error). One bounded retry on 429/503/transient errors."""
        err = None
        for attempt in range(tries):
            try:
                st, final, text, ra = await self._get(url, timeout, limit)
                if st in (429, 503) and attempt < tries - 1 and not CHALLENGE.search(text[:5000]):
                    self.stats[f"http_{st}_retry"] += 1
                    await asyncio.sleep(min(float(ra), 8) if ra.isdigit() else 3 + random.random() * 2)
                    continue
                return st, final, text, None
            except aiohttp.ClientConnectorDNSError:
                return None, url, "", "dns_not_resolved"
            except aiohttp.TooManyRedirects:
                return None, url, "", "too_many_redirects"
            except (asyncio.TimeoutError, TimeoutError):
                return None, url, "", "timeout"
            except aiohttp.ClientConnectorError as e:
                err = "connect_error"
                if isinstance(getattr(e, "os_error", None), socket.gaierror):
                    return None, url, "", "dns_not_resolved"
            except (aiohttp.ClientError, UnicodeError, ValueError, OSError) as e:
                err = f"http_error:{type(e).__name__}"
            await asyncio.sleep(1 + random.random())
        return None, url, "", err

    async def allowed(self, url) -> bool:
        sp = urlsplit(url)
        base = f"{sp.scheme}://{sp.netloc}"
        async with self.robots_lock[base]:
            if base not in self.robots:
                rp = None
                try:
                    st, _, txt, _ = await self.get(base + "/robots.txt", timeout=8, limit=200_000, tries=1)
                    if st == 200 and "<html" not in txt[:500].lower():
                        rp = urllib.robotparser.RobotFileParser()
                        rp.parse(txt.splitlines())
                except Exception:
                    rp = None
                self.robots[base] = rp
        rp = self.robots[base]
        if rp is None:
            return True
        try:
            return rp.can_fetch("*", url) or rp.can_fetch(UA["User-Agent"], url)
        except Exception:
            return True

    async def fetch_page(self, url, timeout=12.0):
        if not await self.allowed(url):
            self.stats["robots_disallowed"] += 1
            return None, url, "", "robots_disallowed"
        return await self.get(url, timeout)


def page_signals(html: str, final_url: str) -> dict:
    """Cheap Saudi + commerce signals for screening (the verifier makes the real decision)."""
    head = html[:MAX_READ]
    text = S.visible_text(head, 300_000)
    plat = S.detect_platform(head, final_url)
    host = (urlsplit(final_url).hostname or "").lower()
    sig = {}
    if plat in ("salla", "zid"):
        sig["platform"] = plat
    n_sar = len(SAR_STRONG.findall(text))
    if n_sar:
        sig["sar_prices"] = n_sar
    if RIYAL.search(text):
        sig["riyal"] = len(RIYAL.findall(text))
    if S.SAR_CURRENCY_CODE.search(head):
        sig["sar_currency_code"] = True
    if plat == "shopify" and re.search(r'Shopify\.currency\s*=\s*\{[^}]*"active"\s*:\s*"SAR"', head):
        sig["shopify_sar"] = True
    m = PHONE_966.search(head)
    if m:
        sig["phone_966"] = m.group(0)[:20]
    if SAUDI_SHIP.search(text):
        sig["saudi_shipping"] = SAUDI_SHIP.search(text).group(0)[:60]
    if HREFLANG_SA.search(head) or re.search(r"og:locale[\"'][^>]*(?:ar|en)_SA", head, re.I):
        sig["hreflang_sa"] = True
    if SA_GEO.search(final_url):
        sig["sa_locale_url"] = final_url[:120]
    if host.endswith(".sa"):
        sig["sa_tld"] = host
    commerce = {
        "platform": plat,
        "add_to_cart": len(S.ADD_TO_CART.findall(head)),
        "cart": len(S.CART_CHECKOUT.findall(head)),
        "product_links": len(set(m.group(0) for m in S.PRODUCT_LINK.finditer(head))),
        "prices": n_sar + len(S.PRICE_ANY.findall(text)),
    }
    is_commerce = (plat in COMMERCE_PLATFORMS or commerce["add_to_cart"] >= 1 or commerce["cart"] >= 2
                   or commerce["product_links"] >= 3)
    parked = bool((len(text) < 4000 and S.PARKED.search(text[:4000])) or (len(text) < 3000 and S.PARKED_TITLE.search(S.title_of(head))))
    news = bool(NON_RETAIL_CONTENT.search(head[:200_000])) and commerce["add_to_cart"] == 0
    title = S.title_of(head)
    meta_txt = " ".join(x or "" for x in (title, S.meta(head, "og:site_name"), S.meta(head, "description"), S.meta(head, "og:title")))
    if SAUDI_TITLE.search(meta_txt):
        sig["saudi_title"] = SAUDI_TITLE.search(meta_txt).group(0)
    shop_words = bool(SHOP_WORDS.search(meta_txt))
    challenge = bool((CHALLENGE.search(head[:5000]) or DENIED.search(title)) and len(text) < 5000)
    adult = bool(ADULT_GAMBLING.search(meta_txt))
    strong = bool(sig.get("platform") or sig.get("sar_currency_code") or sig.get("shopify_sar") or n_sar >= 2)
    n_medium = sum(1 for k in ("riyal", "phone_966", "saudi_shipping", "hreflang_sa", "sa_locale_url", "saudi_title") if sig.get(k)) + (1 if n_sar else 0)
    if sig.get("sa_tld") and not sig.get("sa_locale_url"):
        n_medium += 1
    hit = not parked and not challenge and not adult and (strong or (n_medium >= 1 and is_commerce) or n_medium >= 2
                                            or (sig.get("saudi_title") and shop_words)) and not (news and not strong)
    alts = []
    for tag in HREFLANG_ALT.findall(head[:300_000]):
        m = re.search(r"href=[\"']([^\"']+)", tag)
        if m and m.group(1).startswith("http"):
            alts.append(m.group(1))
    return {"sig": sig, "commerce": commerce, "is_commerce": is_commerce, "hit": hit, "parked": parked, "challenge": challenge, "alts": alts,
            "geo_hint": bool(GEO_HINT.search(head[:300_000]) or SA_LINK.search(head[:300_000]) or sig.get("hreflang_sa")),
            "sa_link": bool(SA_LINK.search(head[:300_000]) or sig.get("hreflang_sa")), "adult": adult,
            "title": title[:120], "len": len(text)}


def fast_skip(domain: str) -> str | None:
    root = registrable_domain(domain)
    if root in NON_STORE_ROOTS or domain in NON_STORE_ROOTS:
        return "non_store_root"
    if root in MARKETPLACE_ROOTS:
        return "marketplace"
    if NON_RETAIL_SUFFIX.search(domain):
        return "gov_edu_suffix"
    label = _TLD(domain).domain or ""
    if NON_RETAIL_LABEL.search(label) or NON_RETAIL_LABEL.search(domain.split(".")[0]):
        return "infra_or_nonretail_name"
    if re.search(r"porn|xxx|sex|toto|togel|slot|casino|gacor|judi|poker|bet365|hentai|escort", label, re.I):
        return "adult_or_gambling_name"
    return None


class State:
    def __init__(self, path):
        self.con = sqlite3.connect(path, timeout=60)
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript("""
        CREATE TABLE IF NOT EXISTS screened(domain TEXT PRIMARY KEY, rank INT, outcome TEXT, detail TEXT, ts TEXT);
        CREATE TABLE IF NOT EXISTS hits(key TEXT PRIMARY KEY, url TEXT, root_domain TEXT, rank INT, source_domain TEXT, via TEXT,
                                        screen_signals TEXT, platform_hint TEXT, state TEXT DEFAULT 'pending', ts TEXT);
        CREATE TABLE IF NOT EXISTS results(key TEXT PRIMARY KEY, row TEXT, ts TEXT, res TEXT, secondary TEXT, browser TEXT);
        """)
        self.con.commit()

    def screened_set(self):
        return {r[0] for r in self.con.execute("SELECT domain FROM screened")}

    def mark(self, domain, rank, outcome, detail=""):
        self.con.execute("INSERT OR REPLACE INTO screened VALUES(?,?,?,?,?)", (domain, rank, outcome, detail[:2000], now()))

    def add_hit(self, ident, rank, src, via, sig):
        cur = self.con.execute("INSERT OR IGNORE INTO hits(key,url,root_domain,rank,source_domain,via,screen_signals,platform_hint,ts) VALUES(?,?,?,?,?,?,?,?,?)",
                               (ident["key"], ident["url"], ident["root_domain"], rank, src, via, json.dumps(sig, ensure_ascii=False),
                                ident.get("platform_hint"), now()))
        return cur.rowcount > 0


async def screen_domain(sc: Screener, st: State, domain: str, rank: int, known_roots: set, known_keys: set, on_hit):
    """Screen one Tranco domain and its Saudi variants. Returns (outcome, detail)."""
    is_sa = domain.endswith(".sa")
    home = f"https://{domain}/"
    s, final, html, err = await sc.fetch_page(home)
    if s is None and err in ("connect_error", "dns_not_resolved", "timeout") or (s is None and err and err.startswith("http_error")):
        s2, f2, h2, e2 = await sc.fetch_page(f"https://www.{domain}/")
        if s2 is not None:
            s, final, html, err = s2, f2, h2, None
        elif err == "connect_error":
            s3, f3, h3, e3 = await sc.fetch_page(f"http://{domain}/", timeout=10)
            if s3 is not None:
                s, final, html, err = s3, f3, h3, None
    outcome, detail = "no_saudi_signal", ""
    home_sig = None
    final_root = registrable_domain(urlsplit(final).hostname or domain) if s is not None else registrable_domain(domain)
    blocked = s is not None and (s in (401, 403, 429, 503) or (s >= 400 and CHALLENGE.search(html[:5000] or "")))
    if s is None:
        outcome, detail = ("error", err) if err not in ("dns_not_resolved", "robots_disallowed") else (err, "")
    elif final_root != registrable_domain(domain) and (final_root in known_roots):
        return "redirect_to_known", final[:200]
    elif final_root in MARKETPLACE_ROOTS:
        return "redirect_to_marketplace", final[:200]
    elif blocked:
        outcome, detail = "blocked", f"http_{s}"
        if is_sa:
            ident = identity(home)
            if ident and ident["key"] not in known_keys and await on_hit(ident, rank, domain, "homepage_blocked_sa_tld", {"sa_tld": domain, "blocked": s}):
                outcome = "hit"
    elif s >= 400:
        outcome, detail = "http_error", f"http_{s}"
    else:
        home_sig = await analyze_page(html, final)
        if home_sig["parked"]:
            outcome = "parked"
        elif home_sig["adult"]:
            return "adult_or_gambling", home_sig["title"][:80]
        elif home_sig["challenge"]:
            outcome, detail = "blocked", f"challenge_page_http_{s}"
            if is_sa:
                ident = identity(home)
                if ident and ident["key"] not in known_keys and await on_hit(ident, rank, domain, "homepage_blocked_sa_tld", {"sa_tld": domain, "blocked": s}):
                    outcome = "hit"
        elif home_sig["hit"] or (is_sa and (urlsplit(final).hostname or "").endswith(".sa")):
            ident = identity(final) or identity(home)
            if ident and ident["key"] not in known_keys and ident["root_domain"] not in MARKETPLACE_ROOTS:
                if await on_hit(ident, rank, domain, "homepage", home_sig["sig"] | {"commerce": home_sig["commerce"]}):
                    outcome = "hit"
            elif ident and ident["key"] in known_keys:
                outcome = "redirect_to_known"
    if is_sa:
        return outcome, detail

    # Saudi path variants on the same host: only for reachable homepages that look like shops or show geo/locale hints.
    variants_hit = 0
    if home_sig and outcome != "hit" and not home_sig["parked"] and not home_sig["challenge"] and (home_sig["is_commerce"] or home_sig["geo_hint"]):
        base_host = urlsplit(final).netloc
        scheme = urlsplit(final).scheme or "https"
        ctl_s, ctl_f, ctl_h, _ = await sc.get(f"{scheme}://{base_host}/xx-zz{random.randint(100, 999)}/", timeout=8, tries=1)
        soft404 = ctl_s == 200
        tried = set()
        alt_urls = [u for u in home_sig["alts"] if u.rstrip("/") != final.rstrip("/")][:2]
        for u in alt_urls + [f"{scheme}://{base_host}{p}" for p in PATH_VARIANTS]:
            p = urlsplit(u).path if u not in alt_urls else "hreflang:" + u[:80]
            vs, vf, vh, ve = await sc.fetch_page(u, timeout=10)
            if vs is None or vf in tried:
                continue
            tried.add(vf)
            ident = identity(vf)
            if not ident or not ("|" in ident["key"] or re.match(r"(?:sa|ksa|saudi)\.", ident["key"])
                                 or (ident["root_domain"].endswith(".sa") and ident["root_domain"] != registrable_domain(domain))):
                continue
            if ident["key"] in known_keys or ident["root_domain"] in MARKETPLACE_ROOTS:
                continue
            if vs in (401, 403, 429, 503):
                if home_sig["is_commerce"] and home_sig["sa_link"] and SA_GEO.search(vf):
                    if await on_hit(ident, rank, domain, f"path_variant_blocked:{p}", {"sa_locale_url": vf, "blocked": vs}):
                        variants_hit += 1
                    break
                continue
            if vs >= 400 or not SA_GEO.search(vf):
                continue
            vsig = await analyze_page(vh, vf)
            sig = vsig["sig"]
            if vsig["challenge"]:
                if home_sig["is_commerce"] and (home_sig["sa_link"] or u in alt_urls):
                    if await on_hit(ident, rank, domain, f"path_variant_blocked:{p}", {"sa_locale_url": vf, "blocked": "challenge_200"}):
                        variants_hit += 1
                    break
                continue
            saudi = bool(sig.get("sar_prices") or sig.get("sar_currency_code") or sig.get("shopify_sar") or sig.get("phone_966")
                         or sig.get("riyal") or sig.get("saudi_shipping"))
            if soft404 and not saudi:
                continue
            declared = u in alt_urls and bool(SA_GEO.search(vf)) and not vsig["adult"]
            if not vsig["parked"] and (vsig["hit"] or declared or (vsig["is_commerce"] and (saudi or sig.get("sa_locale_url")))):
                if declared:
                    sig = sig | {"declared_hreflang_sa": u}
                if await on_hit(ident, rank, domain, f"path_variant:{p}", sig | {"commerce": vsig["commerce"]}):
                    variants_hit += 1
                break

    # Saudi subdomains (skip wildcard zones) and .sa / .com.sa siblings.
    ext = _TLD(domain)
    label = ext.domain
    root = registrable_domain(domain)
    wildcard = await sc.resolves(f"zq{random.randint(10**6, 10**7)}x.{root}")
    probes = []
    if not wildcard:
        probes += [(f"{sub}.{root}", "subdomain") for sub in SUB_VARIANTS]
    if label and len(label) >= 3:
        probes += [(f"{label}.sa", "sibling"), (f"{label}.com.sa", "sibling")]
    for host, kind in probes:
        if kind == "sibling" and (host in known_roots):
            continue
        ident = identity(f"https://{host}/")
        if not ident or ident["key"] in known_keys:
            continue
        if not await sc.resolves(host):
            continue
        vs, vf, vh, ve = await sc.fetch_page(f"https://{host}/")
        if vs is None and ve in ("connect_error", "timeout"):
            vs, vf, vh, ve = await sc.fetch_page(f"http://{host}/", timeout=8)
        if vs is None:
            continue
        vroot = registrable_domain(urlsplit(vf).hostname or host)
        vident = identity(vf) or ident
        if vroot == root and kind == "subdomain" and not SA_GEO.search(vf):
            continue  # redirected back to the global site
        if vident["key"] in known_keys or vident["root_domain"] in known_roots and vident["root_domain"] != root or vident["root_domain"] in MARKETPLACE_ROOTS:
            continue
        parent_shop = bool(home_sig and (home_sig["is_commerce"] or home_sig["sa_link"]) and not home_sig["adult"])
        if vs in (401, 403, 429, 503):
            if kind == "subdomain" and parent_shop:
                if await on_hit(vident, rank, domain, f"{kind}_blocked:{host}", {"sa_locale_url": vf, "blocked": vs}):
                    variants_hit += 1
            continue
        if vs >= 400:
            continue
        vsig = await analyze_page(vh, vf)
        sig = vsig["sig"]
        if vsig["parked"]:
            continue
        if vsig["challenge"]:
            if kind == "subdomain" and parent_shop and await on_hit(vident, rank, domain, f"{kind}_blocked:{host}", {"sa_locale_url": vf, "blocked": "challenge_200"}):
                variants_hit += 1
            continue
        if vsig["hit"] or (kind == "sibling" and vsig["is_commerce"] and (sig.get("sa_tld") or sig.get("phone_966"))):
            if await on_hit(vident, rank, domain, f"{kind}:{host}", sig | {"commerce": vsig["commerce"]}):
                variants_hit += 1
    if variants_hit:
        outcome = "hit" if outcome != "hit" else outcome
        detail = (detail + f" variants_hit={variants_hit}").strip()
    return outcome, detail


# Manual QA of verified rows (page reviewed by hand): key -> (status, reason)
MANUAL_QA = {
    "vidaxl.gr": ("rejected", "manual_qa: Greek vidaXL store (EUR); the 'Saudi phone' match was an 800 toll-free number"),
    "graphisoft.com|sa": ("rejected", "manual_qa: software vendor (Archicad licences), digital-only"),
    "rush.com.sa": ("rejected", "manual_qa: RUSH Car Wash is a car-wash service, not a product store"),
    "aloha.sa": ("rejected", "manual_qa: general contracting / cleaning services company"),
    "logicool.co.jp|sa": ("unverified", "manual_qa: Logitech Saudi page has no cart or SAR prices (where-to-buy only); manual review"),
    "westerndigital.com|sa": ("unverified", "manual_qa: Western Digital /ar-sa shows one SAR price but no confirmed add-to-cart; manual review"),
    "alange-soehne.com": ("unverified", "manual_qa: verified page resolved to /us-en; /sa-en has no cart in static HTML; manual review"),
    "global.sa": ("unverified", "manual_qa: medical centre/clinic name with a small Zid catalogue; manual review"),
    "she.sa": ("unverified", "manual_qa: lice-treatment centre (service business) with a WooCommerce shop; manual review"),
    "cic.sa": ("unverified", "manual_qa: Construction Industries Company (B2B building products), purchase path unclear; manual review"),
    "rodina.sa": ("unverified", "manual_qa: custom kitchens & aluminium works, priced projects rather than catalogue products; manual review"),
}


def apply_manual_qa(st: State, secondary_keys: set | None = None):
    for key, (status, reason) in MANUAL_QA.items():
        r = st.con.execute("SELECT row FROM results WHERE key=?", (key,)).fetchone()
        if not r:
            continue
        row = json.loads(r[0])
        if row["status"] != status or not row["reason"].startswith("manual_qa"):
            row["status"], row["reason"] = status, reason + " (was: " + row["reason"][:120] + ")"
            st.con.execute("UPDATE results SET row=? WHERE key=?", (json.dumps(row, ensure_ascii=False), key))
    for key, r, sec in st.con.execute("SELECT key, row, secondary FROM results").fetchall():
        row = json.loads(r)
        if sec is None and row["status"] == "unverified" and SECONDARY_REASON.search(row["reason"]) and "secondary evidence" not in row["reason"]:
            row["reason"] = (row["reason"] + "; secondary evidence not attempted (no retail-storefront signal / not a retail brand)")[:500]
            st.con.execute("UPDATE results SET row=? WHERE key=?", (json.dumps(row, ensure_ascii=False), key))
    st.con.commit()


CSV_COLS = ["store_name", "canonical_storefront_url", "root_domain", "tranco_rank", "platform", "category", "status",
            "saudi_evidence", "verification_url", "verification_utc", "reason"]


def result_row(hit: dict, res: dict) -> dict:
    status = res.get("status") or "unverified"
    final = res.get("final_url") or hit["url"]
    canon = final if status in ("verified", "verified_secondary_evidence") else hit["url"]
    canon_ident = identity(canon) or {}
    ev = res.get("saudi_evidence") or ""
    try:
        evd = json.loads(ev) if ev else {}
    except ValueError:
        evd = {"raw": ev}
    if not evd:
        evd = json.loads(hit.get("screen_signals") or "{}")
        evd.pop("commerce", None)
    reason = res.get("reason") or ""
    if hit.get("via") and hit["via"] != "homepage":
        reason = f"{reason} [found via {hit['via']} of {hit['source_domain']}]"
    return {
        "store_name": (res.get("store_name") or "").strip()[:120],
        "canonical_storefront_url": canon,
        "root_domain": canon_ident.get("root_domain") or hit["root_domain"],
        "tranco_rank": hit["rank"],
        "platform": res.get("platform") or hit.get("platform_hint") or "",
        "category": res.get("category") or "",
        "status": status,
        "saudi_evidence": json.dumps(evd, ensure_ascii=False)[:600],
        "verification_url": res.get("product_evidence") if status == "verified" and res.get("product_evidence") else (res.get("evidence_url") or final),
        "verification_utc": res.get("verified_at") or now(),
        "reason": reason[:500],
    }


def write_outputs(st: State, out_dir: str, shard: int, summary: dict):
    rows = [json.loads(r[0]) for r in st.con.execute("SELECT row FROM results")]
    order = {"verified": 0, "verified_secondary_evidence": 1, "unverified": 2, "rejected": 3}
    rows.sort(key=lambda r: (order.get(r["status"], 9), int(r["tranco_rank"])))
    n_known_dup = sum(1 for r in rows if r.get("known_duplicate_of"))
    rows = [r for r in rows if not r.get("known_duplicate_of")]
    ok_roots, seen_keys, kept, n_dup = set(), set(), [], 0
    for r in rows:
        ident = identity(r["canonical_storefront_url"]) or {}
        k = ident.get("key") or r["canonical_storefront_url"]
        if r["status"] in ("verified", "verified_secondary_evidence"):
            if k in seen_keys:
                n_dup += 1
                continue
            ok_roots.add(r["root_domain"])
        elif r["root_domain"] in ok_roots or k in seen_keys:
            n_dup += 1
            continue
        seen_keys.add(k)
        kept.append(r)
    rows = kept
    summary["dropped_duplicate_rows"] = n_dup
    summary["dropped_redirects_to_known_store"] = n_known_dup
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"shard_{shard}.csv")
    with open(path + ".tmp", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in CSV_COLS})
    os.replace(path + ".tmp", path)
    c = Counter(r["status"] for r in rows)
    summary.update({"verified": c["verified"], "verified_secondary_evidence": c["verified_secondary_evidence"],
                    "unverified": c["unverified"], "rejected": c["rejected"], "result_rows": len(rows)})
    with open(os.path.join(out_dir, f"shard_{shard}_summary.json"), "w") as fh:
        json.dump(summary, fh, indent=2)


def git_checkpoint(out_dir, shard, msg):
    files = [os.path.join(out_dir, f"shard_{shard}.csv"), os.path.join(out_dir, f"shard_{shard}_summary.json")]
    try:
        subprocess.run(["git", "add", *files], check=True, capture_output=True, timeout=60)
        if subprocess.run(["git", "diff", "--cached", "--quiet"], timeout=60).returncode == 0:
            return
        subprocess.run(["git", "commit", "-m", msg, "--", *files], check=True, capture_output=True, timeout=60)
        br = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True).stdout.strip()
        for delay in (0, 4, 8, 16, 32):
            time.sleep(delay)
            if subprocess.run(["git", "push", "-u", "origin", br], capture_output=True, timeout=120).returncode == 0:
                print(f"[shard] pushed checkpoint: {msg}", flush=True)
                return
    except Exception as e:
        print("[shard] checkpoint failed", type(e).__name__, e, flush=True)


def make_browser_fetcher(browser, concurrency):
    """Renders HTML pages in headless Chromium for JS-only storefronts. A challenge page is returned as-is
    (status 403) without waiting it out, so bot walls stay unverified."""
    class BF(Fetcher):
        def __init__(self):
            super().__init__(concurrency * 4, 2)
            self.page_sem = asyncio.Semaphore(concurrency)

        async def get(self, url, headers=None, tries=2, check_robots=True):
            if headers or re.search(r"\.(?:json|xml|txt|gz)(?:\?|$)|/wp-json/|api\.", url):
                return await super().get(url, headers, tries, check_robots)
            if check_robots and not await self.allowed(url):
                return None, url, "", {}, "robots_disallowed"
            async with self.page_sem:
                ctx = await browser.new_context(locale="ar-SA", timezone_id="Asia/Riyadh", user_agent=DEFAULT_HEADERS["User-Agent"],
                                                viewport={"width": 1366, "height": 900})
                page = await ctx.new_page()
                try:
                    resp = await page.goto(url, wait_until="domcontentloaded", timeout=40000)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        pass
                    html = await page.content()
                    st = resp.status if resp else 200
                    if CHALLENGE.search(html[:6000]) or DENIED.search(S.title_of(html[:6000])):
                        st = 403
                    return st, page.url, html, {}, None
                except Exception as e:
                    return None, url, "", {}, f"browser_error:{type(e).__name__}"
                finally:
                    await ctx.close()
    return BF()


async def browser_stage(st: State, a):
    from playwright.async_api import async_playwright
    hit_cols = ("key", "url", "root_domain", "platform_hint", "rank", "source_domain", "via", "screen_signals")
    todo = []
    for row in st.con.execute(f"SELECT {','.join('h.' + c for c in hit_cols)}, r.res FROM hits h JOIN results r ON r.key=h.key "
                              "WHERE r.browser IS NULL AND r.secondary IS NULL").fetchall():
        hit = dict(zip(hit_cols, row[:-1]))
        res = json.loads(row[-1] or "{}")
        if res.get("status") in ("unverified", "rejected") and BROWSER_REASON.search(res.get("reason") or ""):
            todo.append((hit, res))
    print(f"[shard] browser pass for {len(todo)} hits", flush=True)
    if not todo:
        return
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        f = make_browser_fetcher(browser, a.browser_concurrency)
        sem = asyncio.Semaphore(a.browser_concurrency)

        async def one(hit, res):
            cand = {"key": hit["key"], "url": hit["url"], "root_domain": hit["root_domain"], "platform_hint": hit["platform_hint"]}
            async with sem:
                try:
                    r2 = await asyncio.wait_for(verify_one(f, cand), 300)
                except Exception as e:
                    r2 = {"status": "unverified", "reason": f"browser_verifier_error:{type(e).__name__}"}
            failed = str(r2.get("reason", "")).startswith(("browser_verifier_error", "fetch_failed"))
            use = res if failed else r2
            if not failed:
                use = dict(r2, reason=(r2.get("reason") or "") + " (headless-browser render)")
            if use.get("status") == "rejected" and (DENIED.search(use.get("store_name") or "") or CHALLENGE.search(use.get("store_name") or "")):
                use["status"], use["reason"] = "unverified", "blocked_or_challenge (browser)"
            row_out = result_row(hit, use)
            res_slim = {k: use.get(k) for k in ("status", "reason", "final_url", "store_name", "platform", "category", "saudi_evidence",
                                                "evidence_url", "product_evidence", "verified_at")}
            st.con.execute("UPDATE results SET row=?, res=?, browser=? WHERE key=?",
                           (json.dumps(row_out, ensure_ascii=False), json.dumps(res_slim, ensure_ascii=False), r2.get("status"), hit["key"]))
            st.con.commit()
            print(f"[shard] browser {hit['key']}: {res.get('status')} -> {use.get('status')} {str(use.get('reason'))[:80]}", flush=True)

        await asyncio.gather(*(one(h, r) for h, r in todo))
        await browser.close()


def restore_from_checkpoint(st: State, out_dir: str, shard: int, sl):
    """Rebuild state from the pushed shard CSV + summary (used when the local state DB was lost)."""
    sp = os.path.join(out_dir, f"shard_{shard}_summary.json")
    cp = os.path.join(out_dir, f"shard_{shard}.csv")
    if not (os.path.exists(sp) and os.path.exists(cp)):
        return {}
    summ = json.load(open(sp))
    through = int((summ.get("checkpoint") or {}).get("screened_through_rank") or 0)
    if not through:
        return {}
    n_rows = 0
    with open(cp, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if int(r["tranco_rank"]) > through:
                continue
            ident = identity(r["canonical_storefront_url"]) or {"key": r["canonical_storefront_url"], "url": r["canonical_storefront_url"],
                                                                "root_domain": r["root_domain"], "platform_hint": None}
            m = re.search(r" \[found via (\S+) of ([^\]]+)\]", r["reason"])
            via, src = (m.group(1), m.group(2)) if m else ("homepage", "")
            reason = re.sub(r" \[found via [^\]]*\]", "", r["reason"])
            st.con.execute("INSERT OR IGNORE INTO hits(key,url,root_domain,rank,source_domain,via,screen_signals,platform_hint,state,ts) VALUES(?,?,?,?,?,?,?,?,?,?)",
                           (ident["key"], r["canonical_storefront_url"], r["root_domain"], int(r["tranco_rank"]), src, via, r["saudi_evidence"],
                            ident.get("platform_hint"), "done", now()))
            res = {"status": r["status"], "reason": reason, "final_url": r["canonical_storefront_url"], "store_name": r["store_name"],
                   "platform": r["platform"], "category": r["category"], "saudi_evidence": r["saudi_evidence"],
                   "evidence_url": r["verification_url"], "product_evidence": r["verification_url"], "verified_at": r["verification_utc"]}
            browser = "restored" if "headless-browser render" in reason or "(browser)" in reason else None
            secondary = "restored" if r["status"] == "verified_secondary_evidence" or "secondary evidence insufficient" in reason else None
            st.con.execute("INSERT OR REPLACE INTO results(key,row,ts,res,secondary,browser) VALUES(?,?,?,?,?,?)",
                           (ident["key"], json.dumps(dict(r, tranco_rank=int(r["tranco_rank"])), ensure_ascii=False), now(),
                            json.dumps(res, ensure_ascii=False), secondary, browser))
            n_rows += 1
    for rank, dom in sl:
        if rank <= through:
            st.con.execute("INSERT OR IGNORE INTO screened VALUES(?,?,?,?,?)", (dom, rank, "restored", "", now()))
    st.con.commit()
    print(f"[shard] restored checkpoint: through rank {through}, {n_rows} result rows", flush=True)
    return summ["checkpoint"]


def watermark(st: State, sl):
    """Highest rank R such that every slice domain <= R is screened and every hit from ranks <= R is verified."""
    screened = {r[0] for r in st.con.execute("SELECT domain FROM screened")}
    pend = st.con.execute("SELECT min(rank) FROM hits WHERE state!='done'").fetchone()[0]
    through = sl[0][0] - 1 if sl else 0
    for rank, dom in sl:
        if dom not in screened or (pend is not None and rank >= pend):
            break
        through = rank
    oc = Counter(r[0] for r in st.con.execute("SELECT outcome FROM screened WHERE rank<=? AND outcome!='restored'", (through,)))
    return through, oc


async def run(a):
    import warnings
    warnings.filterwarnings("ignore")
    t0 = time.time()
    out_dir = a.out_dir
    st = State(a.state)
    main_db = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    known_roots, known_keys = set(), set()
    root_status = defaultdict(list)
    for key, root, status, reason in main_db.execute(
            "SELECT c.key, c.root_domain, c.status, v.reason FROM candidates c LEFT JOIN verifications v ON v.key=c.key"):
        known_roots.add(root)
        known_keys.add(key)
        root_status[root].append((key, status, reason or ""))
    recheck_roots = {r for r, lst in root_status.items()
                     if all(s in ("unverified", "pending", "in_progress") and (NETWORK_REASON.search(rs) or s != "unverified") for _, s, rs in lst)}

    sl = []
    with open(a.tranco) as fh:
        for rank, dom in csv.reader(fh):
            rank = int(rank)
            if a.start <= rank <= a.end:
                sl.append((rank, dom.strip().lower()))
    sl.sort()
    summary = {"shard": a.shard, "rank_start": a.start, "rank_end": a.end, "tranco_list_id": a.list_id, "domains_in_slice": len(sl)}
    prior = {}
    if not st.con.execute("SELECT 1 FROM screened LIMIT 1").fetchone():
        prior = restore_from_checkpoint(st, out_dir, a.shard, sl)
    else:
        row = st.con.execute("SELECT value FROM meta WHERE name='prior'").fetchone() if st.con.execute(
            "SELECT 1 FROM sqlite_master WHERE name='meta'").fetchone() else None
        prior = json.loads(row[0]) if row else {}
    st.con.execute("CREATE TABLE IF NOT EXISTS meta(name TEXT PRIMARY KEY, value TEXT)")
    st.con.execute("INSERT OR REPLACE INTO meta VALUES('prior', ?)", (json.dumps(prior),))
    st.con.commit()
    prior_oc = Counter(prior.get("screen_outcomes_through") or {})
    a.prior_runtime += int(prior.get("runtime_seconds") or 0)

    def checkpoint_info(el):
        through, oc = watermark(st, sl)
        return {"screened_through_rank": through, "screen_outcomes_through": dict(prior_oc + oc),
                "runtime_seconds": round(el) + a.prior_runtime, "updated_utc": now()}
    if a.retry_errors:
        n = st.con.execute("DELETE FROM screened WHERE outcome='error'").rowcount
        st.con.commit()
        print(f"[shard] retrying {n} domains whose screen failed with network errors", flush=True)
    done = st.screened_set()
    skipped_known, recheck, todo = [], [], []
    for rank, dom in sl:
        root = registrable_domain(dom)
        if root in known_roots:
            if root in recheck_roots:
                recheck.append((rank, dom, root))
            else:
                skipped_known.append((rank, dom))
        else:
            todo.append((rank, dom))
    summary.update({"skipped_as_known": len(skipped_known), "rechecked_known_network_errors": len(recheck)})
    print(f"[shard] slice={len(sl)} known={len(skipped_known)} recheck={len(recheck)} to_screen={len(todo)} already_screened={len(done)}", flush=True)
    for rank, dom in skipped_known:
        if dom not in done:
            st.mark(dom, rank, "skipped_known", "")
    st.con.commit()

    global POOL
    from concurrent.futures import ProcessPoolExecutor
    POOL = ProcessPoolExecutor(max_workers=a.workers)
    sc = Screener(a.concurrency)
    fetcher = Fetcher(a.verify_concurrency, 2)
    vq: asyncio.Queue = asyncio.Queue()
    hits_in_flight = set()

    async def on_hit(ident, rank, src, via, sig):
        if ident["key"] in hits_in_flight:
            return False
        hits_in_flight.add(ident["key"])
        new = st.add_hit(ident, rank, src, via, sig)
        st.con.commit()
        if new:
            await vq.put(ident["key"])
        return new

    for k, in st.con.execute("SELECT key FROM hits"):
        hits_in_flight.add(k)
    for k, in st.con.execute("SELECT key FROM hits WHERE state!='done'"):
        await vq.put(k)
    for rank, dom, root in recheck:
        if dom in done:
            continue
        for key, s, rs in root_status[root]:
            row = main_db.execute("SELECT url, root_domain, platform_hint FROM candidates WHERE key=?", (key,)).fetchone()
            await on_hit({"key": key, "url": row[0], "root_domain": row[1], "platform_hint": row[2]}, rank, dom,
                         "recheck_known_network_error", {"previous_reason": rs})
        st.mark(dom, rank, "recheck", "")
    st.con.commit()

    screening_done = asyncio.Event()

    async def verifier(i):
        while True:
            try:
                key = await asyncio.wait_for(vq.get(), 5)
            except asyncio.TimeoutError:
                if screening_done.is_set() and vq.empty():
                    return
                continue
            row = st.con.execute("SELECT key,url,root_domain,platform_hint,rank,source_domain,via,screen_signals FROM hits WHERE key=?", (key,)).fetchone()
            hit = dict(zip(("key", "url", "root_domain", "platform_hint", "rank", "source_domain", "via", "screen_signals"), row))
            cand = {"key": hit["key"], "url": hit["url"], "root_domain": hit["root_domain"], "platform_hint": hit["platform_hint"]}
            try:
                res = await asyncio.wait_for(verify_one(fetcher, cand), 240)
            except asyncio.TimeoutError:
                res = {"status": "unverified", "reason": "verification_timeout", "final_url": hit["url"], "evidence_url": hit["url"], "verified_at": now()}
            except Exception as e:
                res = {"status": "unverified", "reason": f"verifier_error:{type(e).__name__}:{str(e)[:80]}", "final_url": hit["url"],
                       "evidence_url": hit["url"], "verified_at": now()}
            if res.get("status") == "rejected" and (DENIED.search(res.get("store_name") or "") or CHALLENGE.search(res.get("store_name") or "")):
                res["status"], res["reason"] = "unverified", "blocked_or_challenge_http_200 (bot-wall page served with 200; was: " + (res.get("reason") or "")[:80] + ")"
            if res.get("status") == "verified" and S.SERVICE_NAME.search(res.get("store_name") or ""):
                res["status"], res["reason"] = "unverified", "service_like_store_name (manual review): " + S.SERVICE_NAME.search(res["store_name"]).group(0)
            row_out = result_row(hit, res)
            fk = res.get("final_key")
            if fk and fk != key and fk in known_keys:
                row_out["known_duplicate_of"] = fk
            res_slim = {k: res.get(k) for k in ("status", "reason", "final_url", "store_name", "platform", "category", "saudi_evidence",
                                                "evidence_url", "product_evidence", "verified_at")}
            st.con.execute("INSERT OR REPLACE INTO results(key,row,ts,res) VALUES(?,?,?,?)",
                           (key, json.dumps(row_out, ensure_ascii=False), now(), json.dumps(res_slim, ensure_ascii=False)))
            st.con.execute("UPDATE hits SET state='done' WHERE key=?", (key,))
            st.con.commit()
            stats["verified_" + res["status"]] += 1

    stats = Counter()
    dq: asyncio.Queue = asyncio.Queue()
    for rank, dom in todo:
        if dom not in done:
            dq.put_nowait((rank, dom))
    if a.limit:
        while dq.qsize() > a.limit:
            dq._queue.pop()
    total_todo = dq.qsize()

    async def screener_worker():
        while True:
            try:
                rank, dom = dq.get_nowait()
            except asyncio.QueueEmpty:
                return
            fs = fast_skip(dom)
            if fs:
                st.mark(dom, rank, "fast_skip", fs)
                stats["fast_skip"] += 1
                continue
            try:
                outcome, detail = await asyncio.wait_for(screen_domain(sc, st, dom, rank, known_roots, known_keys, on_hit), a.domain_timeout)
            except asyncio.TimeoutError:
                outcome, detail = "error", "domain_screen_timeout"
            except Exception as e:
                outcome, detail = "error", f"{type(e).__name__}:{str(e)[:100]}"
            st.mark(dom, rank, outcome, detail)
            stats[outcome] += 1
            stats["screened"] += 1
            if stats["screened"] % 200 == 0:
                st.con.commit()

    async def reporter():
        last_push = time.time()
        while True:
            await asyncio.sleep(60)
            st.con.commit()
            el = time.time() - t0
            print(f"[shard] {round(el/60,1)}min left={dq.qsize()}/{total_todo} vq={vq.qsize()} {dict(stats)} req={sc.stats['requests']}", flush=True)
            if time.time() - last_push > a.push_every:
                cp = checkpoint_info(el)
                write_outputs(st, out_dir, a.shard, summary | {"in_progress": True, "runtime_seconds": cp["runtime_seconds"], "checkpoint": cp})
                await asyncio.to_thread(git_checkpoint, out_dir, a.shard, f"Tranco shard {a.shard}: checkpoint ({total_todo - dq.qsize()}/{total_todo} screened)")
                last_push = time.time()

    rep = asyncio.create_task(reporter())
    verifiers = [asyncio.create_task(verifier(i)) for i in range(a.verify_concurrency)]
    await asyncio.gather(*[screener_worker() for _ in range(a.concurrency)])
    st.con.commit()
    screening_done.set()
    await asyncio.gather(*verifiers)
    await sc.close()
    if not a.no_browser:
        await browser_stage(st, a)
    hit_cols = ("key", "url", "root_domain", "platform_hint", "rank", "source_domain", "via", "screen_signals")
    secondary_items = []
    for row in st.con.execute(f"SELECT {','.join('h.' + c for c in hit_cols)}, r.res FROM hits h JOIN results r ON r.key=h.key WHERE r.secondary IS NULL").fetchall():
        hit = dict(zip(hit_cols, row[:-1]))
        res = json.loads(row[-1] or "{}")
        if res.get("status") == "unverified" and SECONDARY_REASON.search(res.get("reason") or ""):
            if not a.secondary_keys or hit["key"] in a.secondary_keys:
                secondary_items.append((hit, res))

    # Secondary evidence for hits the live verifier could not read (no bypass; archives, sitemaps, App Store).
    if secondary_items and not a.no_secondary:
        from . import secondary as SEC
        print(f"[shard] secondary evidence for {len(secondary_items)} hits", flush=True)
        sem = asyncio.Semaphore(a.secondary_concurrency)
        async with httpx.AsyncClient(headers=SEC.UA_RESEARCH, follow_redirects=True, timeout=60) as arch, \
                httpx.AsyncClient(headers=SEC.UA_BROWSER, follow_redirects=True, timeout=30) as live, \
                httpx.AsyncClient(headers=SEC.UA_BROWSER, follow_redirects=True, timeout=30) as brw:
            async def one(hit, res):
                name = res.get("store_name") or _TLD(hit["root_domain"]).domain or hit["key"]
                item = {"key": hit["key"], "url": hit["url"], "name": name, "domains": [hit["root_domain"]],
                        "global_root": "|" not in hit["key"] and not hit["root_domain"].endswith(".sa")}
                async with sem:
                    try:
                        r = await asyncio.wait_for(SEC.check((arch, live, brw), item), 600)
                    except Exception as e:
                        print("[shard] secondary error", hit["key"], type(e).__name__, flush=True)
                        return
                oks = [e for e in r["evidence"] if e.get("ok")]
                print(f"[shard] secondary {hit['key']} -> {r['verdict']} {[e['type'] for e in oks]}", flush=True)
                if r["verdict"] == "verified_secondary_evidence":
                    ev_text = " | ".join(f"{e['type']}: {e['detail']} ({e.get('url')}, {e.get('date')})" for e in oks)
                    res2 = dict(res, status="verified_secondary_evidence", reason="verified_secondary_evidence: " + ev_text,
                                evidence_url=oks[0].get("url"), product_evidence=oks[0].get("url"), verified_at=now(),
                                store_name=res.get("store_name") or name)
                    row_out = result_row(hit, res2)
                    st.con.execute("UPDATE results SET row=?, ts=?, secondary=? WHERE key=?",
                                   (json.dumps(row_out, ensure_ascii=False), now(), r["verdict"], hit["key"]))
                    st.con.commit()
                else:
                    row = json.loads(st.con.execute("SELECT row FROM results WHERE key=?", (hit["key"],)).fetchone()[0])
                    row["reason"] = (row["reason"] + f"; secondary evidence insufficient ({[e['type'] for e in oks] or 'none'})")[:500]
                    st.con.execute("UPDATE results SET row=?, secondary=? WHERE key=?", (json.dumps(row, ensure_ascii=False), r["verdict"], hit["key"]))
                    st.con.commit()
            await asyncio.gather(*(one(h, r) for h, r in secondary_items))

    rep.cancel()
    oc = prior_oc + Counter(r[0] for r in st.con.execute("SELECT outcome FROM screened WHERE outcome!='restored'"))
    summary["checkpoint"] = checkpoint_info(time.time() - t0) | {"stages_complete": ["screen", "http_verify", "browser", "secondary"]}
    summary.update({
        "screened": sum(v for k, v in oc.items() if k not in ("skipped_known", "recheck")),
        "screen_outcomes": dict(oc),
        "saudi_hits": st.con.execute("SELECT count(*) FROM hits").fetchone()[0],
        "errors": oc["error"],
        "runtime_seconds": round(time.time() - t0) + a.prior_runtime,
        "generated_utc": now(),
    })
    apply_manual_qa(st)
    write_outputs(st, out_dir, a.shard, summary)
    print("[shard] done", json.dumps(summary), flush=True)
    if a.push:
        git_checkpoint(out_dir, a.shard, f"Tranco shard {a.shard}: final results")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, required=True)
    ap.add_argument("--start", type=int, required=True)
    ap.add_argument("--end", type=int, required=True)
    ap.add_argument("--tranco", required=True)
    ap.add_argument("--list-id", default="")
    ap.add_argument("--db", default="data/saudi_ecom.sqlite")
    ap.add_argument("--state", default="/tmp/tranco_shard_state.sqlite")
    ap.add_argument("--out-dir", default="data/tranco_shards")
    ap.add_argument("--concurrency", type=int, default=200)
    ap.add_argument("--verify-concurrency", type=int, default=24)
    ap.add_argument("--domain-timeout", type=int, default=150)
    ap.add_argument("--push-every", type=int, default=1800)
    ap.add_argument("--prior-runtime", type=int, default=0)
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--no-secondary", action="store_true")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--retry-errors", action="store_true")
    ap.add_argument("--browser-concurrency", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0, help="screen only the first N remaining domains (testing)")
    ap.add_argument("--secondary-keys", default="", help="comma-separated hit keys to run secondary evidence on (default: all eligible)")
    ap.add_argument("--secondary-concurrency", type=int, default=3)
    a = ap.parse_args()
    a.secondary_keys = {k for k in a.secondary_keys.split(",") if k}
    asyncio.run(run(a))
