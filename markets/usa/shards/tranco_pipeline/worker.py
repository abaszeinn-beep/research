#!/usr/bin/env python3
"""Screen + verify a Tranco rank slice for active US physical-product online stores.

One asyncio process handles every domain where rank % N == worker index. Each domain is
processed sequentially by one task (DNS -> robots.txt -> homepage -> platform probes ->
product page -> policy pages), so per-host politeness is inherent; many domains run in
parallel under a bounded pool. Results are appended to JSONL (one line per domain) and the
run is resumable: domains already present in any results file are skipped.

Shopify-hosted domains (A record in Shopify's edge range) are deferred by the main workers
and processed by a single `--mode shopify` process under a global adaptive rate limit,
because Shopify's edge throttles all stores together per client.
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
import warnings
from collections import Counter, OrderedDict
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
warnings.filterwarnings("ignore", category=DeprecationWarning)

import aiodns  # noqa: E402
import aiohttp  # noqa: E402

import us_signals as U  # noqa: E402
from saudi_ecom.common import registrable_domain  # noqa: E402

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
           "Accept-Language": "en-US,en;q=0.9"}
WORK = os.path.join(ROOT, "data", "work", "usa_tranco_500k_1m")
TRANCO = os.path.join(ROOT, "data", "raw", "top-1m.csv")
LO, HI = 500_001, 1_000_000
SHOPIFY_EDGE = "23.227.38."

GENERIC_TLDS = {"com", "net", "org", "us", "ca", "co", "io", "shop", "store", "online", "site", "app", "info", "biz", "xyz",
                "me", "cc", "top", "club", "life", "world", "live", "tech", "space", "pro", "boutique", "clothing", "art",
                "design", "fashion", "jewelry", "beauty", "supply", "supplies", "market", "deals", "sale", "gifts", "pet",
                "coffee", "wine", "auto", "parts", "tools", "golf", "fit", "bike", "garden", "furniture", "toys", "games",
                "shoes", "bargains", "kitchen", "farm", "health", "care", "studio", "company", "inc", "llc", "global",
                "plus", "one", "nyc", "la", "miami", "vegas", "boston", "today", "style", "luxury", "bio", "eco", "organic",
                "ink", "work", "works", "email", "page", "website", "digital", "media", "network", "solutions", "group",
                "ai", "gg", "tv", "fm", "ly", "to", "mx"}
SKIP_TLD = re.compile(r"\.(?:gov|mil|edu|int)$|\.(?:gov|mil|edu|ac|gob|go|govt|nic)\.[a-z]{2}$|\.k12\.[a-z]{2}\.us$")
SKIP_NAME = re.compile(
    r"(?:^|[.-])(?:cdn|cdns|api|apis|static|assets|img|images|media|pixel|track|tracking|tracker|analytics|metrics|telemetry|"
    r"adserver|adservice|adsrv|ads|adtech|doubleclick|adnxs|rtb|ssp|dsp|dns|ns\d?|mx|smtp|mail|imap|vpn|proxy|cloudfront|akamai|"
    r"edgekey|edgesuite|fastly|azureedge|cloudflare|amazonaws|googleapis|gstatic|push|notify|sync|beacon|stats|statistic|log|logs|"
    r"update|updates|download|downloads|torrent|crack|keygen|warez|apk)(?:$|[.-]|\d)|"
    r"porn|xxx|sexy?(?:cam|chat|tube)|hentai|xvideo|camgirl|escort|onlyfans|nude|milf|fuck|"
    r"casino|betting|sportsbet|\bbet\d|poker|slots?\d|gambl|lottery|"
    r"^\d+\.[a-z]+$|^[a-z0-9]{20,}\.[a-z]+$",
    re.I,
)
NONRETAIL_ROOTS = {"wordpress.com", "blogspot.com", "github.io", "herokuapp.com", "netlify.app", "vercel.app", "wixsite.com",
                   "squarespace.com", "shopify.com", "bigcommerce.com", "wix.com", "godaddysites.com", "weebly.com",
                   "myshopify.com", "cloudfront.net", "azurewebsites.net", "web.app", "firebaseapp.com", "pages.dev",
                   "workers.dev", "glitch.me", "repl.co", "onrender.com", "fly.dev"}
DEDICATED_PLATFORMS = {"shopify", "bigcommerce", "salesforce-commerce", "sap-hybris", "square-online", "ecwid", "volusion",
                       "shift4shop", "miva", "bigcartel", "lightspeed", "vtex", "salesforce-b2c-pwa"}

ATC_LOW = re.compile(U.ADD_TO_CART.pattern)
CART_LOW = re.compile(U.CART.pattern)
PARKED_LOW = re.compile(U.PARKED.pattern.lower())
CHALLENGE_LOW = re.compile(U.CHALLENGE.pattern.lower())
CLOSED_LOW = re.compile(U.CLOSED.pattern.lower())


def tier(domain: str) -> int:
    return 1 if domain.rsplit(".", 1)[-1] in GENERIC_TLDS else 2


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Resp:
    __slots__ = ("status", "url", "text", "headers", "err", "ctype")

    def __init__(self, status=None, url="", text="", headers=None, err=None):
        self.status, self.url, self.text, self.err = status, url, text, err
        self.headers = headers or {}
        self.ctype = (self.headers.get("Content-Type") or self.headers.get("content-type") or "").lower()


class Net:
    def __init__(self, conc: int, shopify_conc: int):
        self.conc = conc
        self.shopify_sem = asyncio.Semaphore(shopify_conc)
        self.robots: OrderedDict = OrderedDict()
        self.stats = Counter()
        self.rate = 0.0
        self.max_rate = 0.0
        self.next_slot = 0.0
        self.rate_lock = asyncio.Lock()
        self.use_curl = False

    async def start(self):
        self.dns = aiodns.DNSResolver(timeout=5, tries=2)
        conn = aiohttp.TCPConnector(limit=self.conc * 2, limit_per_host=2, ttl_dns_cache=300, ssl=False,
                                    resolver=aiohttp.AsyncResolver(), enable_cleanup_closed=True)
        self.session = aiohttp.ClientSession(connector=conn, headers=HEADERS, cookie_jar=aiohttp.DummyCookieJar(),
                                             max_line_size=32768, max_field_size=32768)

    async def close(self):
        await self.session.close()

    async def resolve(self, host: str):
        """A records for host; [] on NXDOMAIN/no answer, None on resolver error/timeout."""
        try:
            res = await self.dns.query(host, "A")
            return [x.host for x in res]
        except aiodns.error.DNSError as e:
            code = e.args[0] if e.args else None
            return [] if code in (1, 4) else None
        except Exception:  # noqa: BLE001
            return None

    async def throttle(self):
        """Global adaptive token bucket (Shopify-edge mode only)."""
        if not self.rate:
            return
        async with self.rate_lock:
            now = time.monotonic()
            wait = max(0.0, self.next_slot - now)
            self.next_slot = max(now, self.next_slot) + 1.0 / self.rate
        if wait:
            await asyncio.sleep(wait)

    def on_status(self, status):
        if not self.rate:
            return
        if status == 429:
            self.stats["edge_429"] += 1
            self.rate = max(0.2, self.rate * 0.6)
            self.next_slot = time.monotonic() + 20
        elif status and status < 500:
            self.rate = min(self.max_rate, self.rate + 0.02)

    async def _curl_get(self, url, max_bytes, timeout, headers=None) -> Resp:
        marker = "\n__CURLMETA__"
        cmd = ["curl", "-s", "-k", "-L", "--max-redirs", "8", "--compressed", "--connect-timeout", "7",
               "--max-time", str(int(timeout)), "-A", UA, "-H", "Accept: " + HEADERS["Accept"],
               "-H", "Accept-Language: " + HEADERS["Accept-Language"],
               "-w", marker + "%{http_code} %{url_effective} %{content_type}", url]
        try:
            p = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            out, _ = await asyncio.wait_for(p.communicate(), timeout + 5)
        except (asyncio.TimeoutError, OSError):
            try:
                p.kill()
            except Exception:  # noqa: BLE001
                pass
            return Resp(url=url, err="timeout")
        rc = p.returncode
        text = out.decode("utf-8", errors="replace")
        body, _, meta_s = text.rpartition(marker)
        parts = meta_s.split(" ", 2)
        code = int(parts[0]) if parts and parts[0].isdigit() else 0
        if rc == 6:
            return Resp(url=url, err="dns")
        if rc in (35, 51, 58, 60):
            return Resp(url=url, err="ssl")
        if rc == 47:
            return Resp(url=url, err="too_many_redirects")
        if rc == 28:
            return Resp(url=url, err="timeout")
        if rc == 7 or code == 0:
            return Resp(url=url, err="connect" if rc == 7 else f"http_error:curl_{rc}")
        self.stats["requests"] += 1
        hdrs = {"Content-Type": parts[2] if len(parts) > 2 else ""}
        return Resp(code, parts[1] if len(parts) > 1 else url, body[:max_bytes], hdrs)

    async def _get(self, url, max_bytes, timeout, headers=None) -> Resp:
        if self.use_curl:
            return await self._curl_get(url, max_bytes, timeout, headers)
        try:
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=timeout, sock_connect=7, sock_read=timeout),
                                        headers=headers, allow_redirects=True, max_redirects=8) as r:
                chunks, size = [], 0
                while size < max_bytes:
                    ch = await r.content.read(65536)
                    if not ch:
                        break
                    chunks.append(ch)
                    size += len(ch)
                body = b"".join(chunks)
                try:
                    text = body.decode(r.charset or "utf-8", errors="replace")
                except LookupError:
                    text = body.decode("utf-8", errors="replace")
                self.stats["requests"] += 1
                return Resp(r.status, str(r.url), text, dict(r.headers))
        except aiohttp.ClientConnectorDNSError:
            return Resp(url=url, err="dns")
        except (aiohttp.ClientConnectorCertificateError, aiohttp.ClientSSLError):
            return Resp(url=url, err="ssl")
        except aiohttp.TooManyRedirects:
            return Resp(url=url, err="too_many_redirects")
        except (asyncio.TimeoutError, aiohttp.ServerTimeoutError):
            return Resp(url=url, err="timeout")
        except aiohttp.ClientConnectorError:
            return Resp(url=url, err="connect")
        except (aiohttp.ClientError, UnicodeError, ValueError, OSError, LookupError) as e:
            return Resp(url=url, err="http_error:" + type(e).__name__)
        except Exception as e:  # noqa: BLE001  one bad host must not kill the worker
            return Resp(url=url, err="error:" + type(e).__name__)

    async def get(self, url, max_bytes=900_000, timeout=15, headers=None, tries=2, robots=True, shopify=False) -> Resp:
        if robots and not await self.allowed(url):
            self.stats["robots_disallowed"] += 1
            return Resp(url=url, err="robots_disallowed")
        delay = 1.5
        r = Resp(url=url, err="not_attempted")
        for attempt in range(tries):
            await self.throttle()
            if shopify:
                async with self.shopify_sem:
                    r = await self._get(url, max_bytes, timeout, headers)
                    await asyncio.sleep(0.15)
            else:
                r = await self._get(url, max_bytes, timeout, headers)
            self.on_status(r.status)
            if r.err in ("dns", "ssl", "too_many_redirects", "robots_disallowed"):
                return r
            if r.status in (429, 502, 503, 504) and attempt < tries - 1 and not CHALLENGE_LOW.search(r.text[:6000].lower()):
                ra = r.headers.get("Retry-After", "")
                delay = max(delay, min(float(ra), 12) if ra.isdigit() else delay)
                self.stats[f"retry_{r.status}"] += 1
            elif r.err in ("timeout", "connect") and attempt < tries - 1:
                self.stats["retry_" + r.err] += 1
            else:
                return r
            await asyncio.sleep(delay + random.random())
            delay = min(delay * 2, 12)
        return r

    async def load_robots(self, origin: str):
        """RFC 9309: 4xx => allow all; 5xx/unreachable => disallow (recorded)."""
        if origin in self.robots:
            for _ in range(60):
                if self.robots.get(origin) != "pending":
                    break
                await asyncio.sleep(0.25)
            return self.robots.get(origin)
        self.robots[origin] = "pending"
        r = await self.get(origin + "/robots.txt", max_bytes=300_000, timeout=9, tries=1, robots=False)
        if r.err:
            val = "unreachable:" + r.err
        elif r.status and 500 <= r.status < 600:
            val = "unreachable:http_%d" % r.status
        elif r.status == 200 and "<html" not in r.text[:600].lower() and "<!doctype" not in r.text[:200].lower():
            rp = urllib.robotparser.RobotFileParser()
            try:
                rp.parse(r.text.splitlines()[:3000])
                val = rp
            except Exception:  # noqa: BLE001
                val = None
        else:
            val = None
        self.robots[origin] = val
        while len(self.robots) > 3000:
            k, v = next(iter(self.robots.items()))
            if v == "pending":
                self.robots.move_to_end(k)
                break
            self.robots.popitem(last=False)
        return val

    async def allowed(self, url: str) -> bool:
        sp = urlsplit(url)
        val = await self.load_robots(f"{sp.scheme}://{sp.netloc}")
        if val is None or val == "pending":
            return True
        if isinstance(val, str):
            return False
        try:
            return val.can_fetch(UA, url) and val.can_fetch("*", url)
        except Exception:  # noqa: BLE001
            return True

    def robots_sitemaps(self, origin: str):
        val = self.robots.get(origin)
        if isinstance(val, urllib.robotparser.RobotFileParser):
            try:
                return list(val.site_maps() or [])
            except Exception:  # noqa: BLE001
                return []
        return []


def origin_of(url: str) -> str:
    sp = urlsplit(url)
    return f"{sp.scheme}://{sp.netloc}"


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def same_site(url: str, base_root: str) -> bool:
    h = host_of(url)
    return bool(h) and registrable_domain(h) == base_root


def quick_screen(html: str, url: str):
    h = html[:900_000]
    low = h.lower()
    plat = U.detect_platform(html, url, low[:600_000])
    atc = len(ATC_LOW.findall(low))
    cart = len(CART_LOW.findall(low))
    links = {m.group(1) for m in U.PRODUCT_LINK.finditer(h)}
    types, _ = U.jsonld(h) if "ld+json" in low else (set(), set())
    has_product_ld = bool(types & {"Product", "Offer", "AggregateOffer", "ProductGroup"})
    text = U.visible_text(h)
    prices = len(U.PRICE_USD.findall(text)) + len(U.PRICE_OTHER.findall(text))
    if plat in U.ECOM_PLATFORMS:
        hit = True
    elif plat in ("wix", "squarespace", "weebly", "odoo"):
        hit = (atc >= 1 or cart >= 1) and (len(links) >= 1 or prices >= 2 or has_product_ld)
    else:
        hit = (atc >= 1 and (len(links) >= 2 or prices >= 2 or has_product_ld)) or \
              (cart >= 1 and len(links) >= 3 and prices >= 2) or (has_product_ld and cart >= 1)
    return hit, {"platform": plat, "atc": atc, "cart": cart, "plinks": len(links), "prices": prices,
                 "ld_product": has_product_ld}, text, links


def parse_json(text):
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


LISTING_HREF = re.compile(r"href=[\"']([^\"'#<>\s]{0,200}?(?:/collections/all|/collections/[^\"'/?#<>\s]+|/shop/?|/store/?|"
                          r"/products/?|/catalog[^\"'<>\s]*|/category/[^\"'<>\s]+|/product-category/[^\"'<>\s]+|/categories/[^\"'<>\s]+|"
                          r"/c/[^\"'<>\s]+|/all-products|/new-arrivals?|/best-?sellers?)[\"'?#])", re.I)
POLICY_HREF = re.compile(r"href=[\"']([^\"'#<>\s]{0,200}?(?:shipping|delivery|contact|about|faq|returns?|policies)[^\"'#<>\s]{0,80})[\"']", re.I)
SITEMAP_PRODUCT = re.compile(r"<loc>\s*(https?://[^<\s]{0,300}?(?:/products?/[^<]+|/product-[^<\s]+|/p/[^<]+|/item/[^<]+|/pd/[^<]+|-p\d{3,}[^<\s]*))\s*</loc>", re.I)


def pick_product_link(links, base_url, base_root):
    out = []
    for l in links:
        u = urljoin(base_url, l.strip())
        if not u.startswith("http") or not same_site(u, base_root):
            continue
        if re.search(r"/(?:cart|checkout|account|login|blog|news|policies|pages)/|\.(?:jpg|png|gif|css|js|pdf)(?:\?|$)", u, re.I):
            continue
        out.append(u)
    out.sort(key=lambda u: (0 if re.search(r"/products?/", u) else 1, 1 if U.SERVICE_PRODUCT_NAME.search(u.replace("-", " ")) else 0, len(u)))
    return out


def canonical(url: str) -> str:
    sp = urlsplit(url)
    host = (sp.hostname or "").lower()
    m = re.match(r"^/(?:en-us|us|en_us|us-en)(?:/|$)", sp.path or "/", re.I)
    path = m.group(0) if m else "/"
    if not path.endswith("/"):
        path += "/"
    return f"https://{host}{path}"


class Verifier:
    def __init__(self, net: Net, shopify_mode: bool = False):
        self.net = net
        self.shopify_mode = shopify_mode

    async def process(self, domain: str, rank: int) -> dict:
        rec = {"d": domain, "r": rank}
        root = registrable_domain(domain)
        if SKIP_TLD.search(domain):
            rec["s"] = "skip_gov_edu"
            return rec
        if SKIP_NAME.search(domain):
            rec["s"] = "skip_infra_adult"
            return rec
        if root in NONRETAIL_ROOTS:
            rec["s"] = "skip_platform_host"
            return rec
        if root in U.MARKETPLACE_ROOTS:
            return self.row(rec, domain, "https://" + domain + "/", "rejected", reason="marketplace/aggregator (excluded by scope)")
        if not self.shopify_mode:
            a, b = await asyncio.gather(self.net.resolve(domain), self.net.resolve("www." + domain))
            if a == [] and b == []:
                rec["s"] = "unreachable"
                rec["e"] = "dns"
                return rec
            if any(ip.startswith(SHOPIFY_EDGE) for ip in (a or []) + (b or [])):
                rec["s"] = "deferred_shopify"
                return rec

        home, last_err = None, None
        for base in (f"https://{domain}", f"https://www.{domain}", f"http://www.{domain}"):
            rb = await self.net.load_robots(base)
            if isinstance(rb, str) and rb.startswith("unreachable:"):
                last_err = rb.split(":", 1)[1]
                if last_err in ("dns", "connect", "ssl", "timeout") or last_err.startswith(("http_error", "error")):
                    continue
                if last_err.startswith("http_5"):
                    rec["s"] = "robots_5xx"
                    rec["e"] = last_err
                    return rec
            if not await self.net.allowed(base + "/"):
                rec["s"] = "robots_disallow_home"
                return rec
            r = await self.net.get(base + "/", robots=False, timeout=16)
            if r.err in ("dns", "connect", "ssl", "timeout") or (r.err or "").startswith(("http_error", "error")):
                last_err = r.err
                continue
            home = r
            break
        if home is None:
            rec["s"] = "unreachable"
            rec["e"] = last_err
            return rec
        rec["u"] = home.url
        st = home.status or 0
        html = home.text or ""
        low = html[:80000].lower()
        challenged = bool(CHALLENGE_LOW.search(low[:20000]))
        if st == 429 and not challenged:
            rec["s"] = "rate_limited"
            rec["e"] = "http_429"
            return rec
        if challenged or (st in (403, 429, 503) and len(html) < 30000):
            rec["s"] = "challenged"
            rec["e"] = f"http_{st}"
            plat = U.detect_platform(html, home.url)
            if plat != "custom/unknown":
                rec["p"] = plat
            return rec
        if st >= 400:
            rec["s"] = f"http_{st}"
            return rec
        if "html" not in home.ctype and "<html" not in low[:3000]:
            rec["s"] = "not_html"
            return rec
        final_root = registrable_domain(host_of(home.url) or domain)
        if final_root != root:
            rec["redir"] = final_root
            if final_root in U.MARKETPLACE_ROOTS:
                rec["s"] = "redirect_marketplace"
                return rec
        if PARKED_LOW.search(low[:60000]) or (len(U.visible_text(html[:60000]).strip()) < 40 and "<script" not in low[:60000]):
            rec["s"] = "parked_or_empty"
            return rec

        hit, q, text, links = quick_screen(html, home.url)
        if not hit:
            if CLOSED_LOW.search(low) and q["platform"] in U.ECOM_PLATFORMS:
                return self.row(rec, domain, home.url, "rejected", platform=q["platform"], html=html,
                                reason="storefront closed / password-protected")
            rec["s"] = "nonstore"
            return rec
        rec["q"] = q
        try:
            return await asyncio.wait_for(self.deep(rec, domain, home, html, text, links, q), 150)
        except asyncio.TimeoutError:
            return self.row(rec, domain, home.url, "unverified", platform=q["platform"], html=html,
                            reason="verification timed out (slow host)")

    def row(self, rec, domain, url, status, platform="", html="", reason="", category="", us_ev=None, vurl="", name=None):
        host = host_of(url) or domain
        rec["s"] = "hit"
        rec["row"] = {
            "store_name": name or (U.store_name(html, host) if html else domain.split(".")[0]),
            "canonical_storefront_url": canonical(url),
            "root_domain": registrable_domain(host),
            "platform": platform or (U.detect_platform(html, url) if html else ""),
            "category": category,
            "status": status,
            "us_evidence": "; ".join(f"{k}={v if not isinstance(v, list) else '|'.join(map(str, v))}" for k, v in (us_ev or {}).items()),
            "verification_url": vurl or url,
            "verification_utc": now_utc(),
            "discovery_source": "tranco_top1m_500001_1000000" + (f" (redirect from {domain})" if registrable_domain(host) != registrable_domain(domain) else ""),
            "tranco_rank": rec["r"],
            "reason": reason,
        }
        return rec

    async def deep(self, rec, domain, home, html, text, links, q):
        net = self.net
        url = home.url
        org = origin_of(url)
        root = registrable_domain(host_of(url))
        plat = q["platform"]
        await net.allowed(org + "/")
        api: dict = {}
        htmls, texts = [html], [text]
        names, ptypes = [], []
        product_ev, purchase_ev, sample_url, vurl = None, None, None, ""
        physical_note = ""
        title = U.title_of(html)
        desc = U.meta(html, "description") or U.meta(html, "og:description") or ""

        if CLOSED_LOW.search(html[:80000].lower()) and q["plinks"] < 2:
            return self.row(rec, domain, url, "rejected", plat, html, "storefront closed / password-protected / coming soon")

        if plat == "shopify":
            r = await net.get(org + "/meta.json", timeout=10, shopify=True)
            mj = parse_json(r.text) if r.status == 200 else None
            if isinstance(mj, dict):
                api["currency"] = mj.get("currency")
                api["country"] = mj.get("country")
                api["shop_name"] = mj.get("name")
            elif r.status == 429:
                rec["rl"] = 1
            r = await net.get(org + "/products.json?limit=50", timeout=12, shopify=True, max_bytes=3_000_000)
            if r.status == 429:
                rec["rl"] = 1
            pj = parse_json(r.text) if r.status == 200 else None
            if isinstance(pj, dict) and isinstance(pj.get("products"), list):
                prods = pj["products"]
                ship = sum(1 for p in prods if any(v.get("requires_shipping") for v in (p.get("variants") or [])))
                avail = sum(1 for p in prods if any(v.get("available") for v in (p.get("variants") or [])))
                names = [p.get("title") or "" for p in prods]
                ptypes = [p.get("product_type") or "" for p in prods]
                api["n"], api["ship"], api["avail"] = len(prods), ship, avail
                if prods:
                    product_ev = f"shopify products.json: {len(prods)} products ({ship} require shipping, {avail} available)"
                    best = next((p for p in prods if not U.SERVICE_PRODUCT_NAME.search(p.get("title") or "")
                                 and any(v.get("requires_shipping") for v in (p.get("variants") or []))), prods[0])
                    sample_url = org + "/products/" + best.get("handle", "")
                    vurl = org + "/products.json"
                    if avail:
                        purchase_ev = "shopify cart (available variants in products.json)"
                    if ship == 0 and len(prods) >= 3:
                        return self.row(rec, domain, url, "rejected", plat, html, "digital/non-shippable products only (Shopify requires_shipping=false)",
                                        vurl=vurl, name=api.get("shop_name"))
                    if ship < len(prods) * 0.3:
                        physical_note = f"mostly non-shipping items ({ship}/{len(prods)})"
                elif r.status == 200:
                    return self.row(rec, domain, url, "rejected", plat, html, "Shopify store with no published products", vurl=org + "/products.json")
        elif plat == "woocommerce":
            r = await net.get(org + "/wp-json/wc/store/v1/products?per_page=30", timeout=12, max_bytes=3_000_000)
            pj = parse_json(r.text) if r.status == 200 else None
            if isinstance(pj, list) and pj:
                pj = [p for p in pj if isinstance(p, dict)]
                api["currency"] = sorted({(p.get("prices") or {}).get("currency_code") for p in pj if p.get("prices")} - {None})
                names = [re.sub(r"<[^>]+>|\s+", " ", (p.get("name") or "")).strip() for p in pj]
                purch = sum(1 for p in pj if p.get("is_purchasable"))
                api["n"], api["purchasable"] = len(pj), purch
                product_ev = f"WooCommerce Store API: {len(pj)} products ({purch} purchasable)"
                vurl = org + "/wp-json/wc/store/v1/products"
                sample_url = next((p.get("permalink") for p in pj if p.get("permalink")), None)
                if purch:
                    purchase_ev = "WooCommerce Store API is_purchasable"

        cand_links = pick_product_link(links, url, root)
        if not sample_url and cand_links:
            sample_url = cand_links[0]
        if not sample_url:
            m = [urljoin(url, x) for x in LISTING_HREF.findall(html[:900_000])]
            m = [x for x in m if same_site(x, root)]
            if m:
                r = await net.get(m[0], timeout=14)
                if r.status == 200 and r.text:
                    htmls.append(r.text)
                    pl = {mm.group(1) for mm in U.PRODUCT_LINK.finditer(r.text[:900_000])}
                    cl = pick_product_link(pl, r.url, root)
                    if cl:
                        sample_url = cl[0]
        if not sample_url:
            maps = net.robots_sitemaps(org) or [org + "/sitemap.xml"]
            for sm in maps[:2]:
                r = await net.get(sm, timeout=12, max_bytes=2_000_000)
                if r.status != 200 or "<loc>" not in r.text:
                    continue
                prods = SITEMAP_PRODUCT.findall(r.text)
                if not prods:
                    ch = [c for c in re.findall(r"<sitemap>\s*<loc>\s*([^<]+)</loc>", r.text, re.I) if re.search(r"product", c, re.I)]
                    if ch:
                        r2 = await net.get(ch[0].strip(), timeout=12, max_bytes=2_000_000)
                        if r2.status == 200:
                            prods = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", r2.text)
                if prods:
                    sample_url = prods[0].strip()
                    if not product_ev:
                        product_ev = f"sitemap product URLs ({len(prods)})"
                    break

        prod_page_ok = False
        if plat == "shopify" and api.get("n"):
            prod_page_ok = True
        elif sample_url:
            r = await net.get(sample_url, timeout=15, shopify=plat == "shopify")
            if r.status == 429:
                rec["rl"] = 1
            if r.status == 200 and r.text:
                ph = r.text
                htmls.append(ph)
                pt = U.visible_text(ph)
                texts.append(pt)
                types, _ = U.jsonld(ph)
                p_atc = len(ATC_LOW.findall(ph[:900_000].lower()))
                p_price = len(U.PRICE_USD.findall(pt)) + len(U.PRICE_OTHER.findall(pt))
                if types & {"Product", "ProductGroup"} or (p_atc and p_price) or re.search(r"og:type[\"'][^>]*content=[\"']product", ph[:100000], re.I):
                    prod_page_ok = True
                    if not product_ev:
                        product_ev = "product page " + ("schema.org Product" if types & {"Product", "ProductGroup"} else "with price + add-to-cart")
                    vurl = r.url
                    if p_atc and not purchase_ev:
                        purchase_ev = "add-to-cart on product page"
                    if not names:
                        names = [U.title_of(ph)]
        if not product_ev and q["ld_product"] and q["prices"] >= 2:
            product_ev = "homepage schema.org Product offers"
        if not product_ev and plat in U.ECOM_PLATFORMS and q["plinks"] >= 2 and q["prices"] >= 2:
            product_ev = f"homepage product cards with prices ({q['plinks']} product links)"
            vurl = vurl or url
        if not purchase_ev:
            if plat in U.ECOM_PLATFORMS and product_ev and plat != "woocommerce":
                purchase_ev = f"{plat} storefront cart"
            elif q["atc"]:
                purchase_ev = "add-to-cart on homepage"
            elif plat == "woocommerce" and q["cart"]:
                purchase_ev = "WooCommerce cart"

        decision, ev, why = U.us_signals(htmls, texts, url, api)
        if decision == "weak" and (product_ev or prod_page_ok):
            extra = []
            if plat == "shopify":
                extra += [org + "/policies/shipping-policy", org + "/pages/contact"]
            pol = [urljoin(url, x) for x in POLICY_HREF.findall(html[:900_000])]
            pol = [x for x in dict.fromkeys(pol) if same_site(x, root)]
            pol.sort(key=lambda x: (0 if "ship" in x.lower() else 1 if "contact" in x.lower() else 2))
            for x in pol:
                if x not in extra:
                    extra.append(x)
            for x in extra[:3]:
                r = await net.get(x, timeout=12, shopify=plat == "shopify")
                if r.status == 200 and r.text:
                    htmls.append(r.text)
                    texts.append(U.visible_text(r.text))
            decision, ev, why = U.us_signals(htmls, texts, url, api)

        alltext = " ".join(texts)[:200_000]
        name_blob = " ".join(names)
        digital_names = sum(1 for n in names if U.DIGITAL.search(n))
        cat = U.classify_category([title, desc, name_blob, " ".join(ptypes), text[:20000]], [3, 2, 3, 3, 1])
        store_nm = api.get("shop_name") or U.store_name(html, host_of(url))
        if U.ADULT.search(title + " " + desc) or U.GAMBLING.search(title + " " + desc):
            return self.row(rec, domain, url, "rejected", plat, html, "adult/gambling (out of scope)", cat, ev, vurl, store_nm)
        if names and len(names) >= 3 and digital_names >= len(names) * 0.7:
            return self.row(rec, domain, url, "rejected", plat, html, "digital-only products", cat, ev, vurl, store_nm)
        service_names = sum(1 for n in names if U.SERVICE_PRODUCT_NAME.search(n))
        if names and service_names >= max(1, len(names) * 0.6):
            return self.row(rec, domain, url, "rejected", plat, html, "products are services/tickets/bookings/gift cards, not physical goods",
                            cat, ev, vurl, store_nm)
        weak_products = not (prod_page_ok or (api.get("n") or 0) > 0)
        if U.SERVICE_TITLE.search(title) and (weak_products or len(names) <= 1):
            return self.row(rec, domain, url, "rejected", plat, html, "site title indicates services/media/organisation, not a product store",
                            cat, ev, vurl, store_nm)
        if not product_ev and plat not in DEDICATED_PLATFORMS and not rec.get("rl"):
            rec["s"] = "nonstore_deep"
            rec.pop("row", None)
            return rec
        if not product_ev and rec.get("rl"):
            return self.row(rec, domain, url, "unverified", plat, html, "rate_limited (HTTP 429) by platform edge; retry later",
                            cat, ev, vurl, store_nm)
        if weak_products:
            if len(U.RESTAURANT.findall(alltext)) >= 3:
                return self.row(rec, domain, url, "rejected", plat, html, "restaurant/food service", cat, ev, vurl, store_nm)
            if len(U.SAAS.findall(alltext)) >= 2:
                return self.row(rec, domain, url, "rejected", plat, html, "SaaS/software (no physical products)", cat, ev, vurl, store_nm)
            if len(U.SERVICE.findall(alltext)) >= 3:
                return self.row(rec, domain, url, "rejected", plat, html, "services business (no physical product catalog)", cat, ev, vurl, store_nm)
        if len(U.MARKETPLACE_TEXT.findall(alltext)) >= 2:
            return self.row(rec, domain, url, "unverified", plat, html, "possible multi-vendor marketplace (manual review)", cat, ev, vurl, store_nm)

        if decision in ("non_us", "canada"):
            return self.row(rec, domain, url, "rejected", plat, html, "not US-targeted: " + why, cat, ev, vurl, store_nm)
        if not product_ev:
            return self.row(rec, domain, url, "unverified", plat, html, "no product pages found", cat, ev, vurl, store_nm)
        if not purchase_ev:
            return self.row(rec, domain, url, "unverified", plat, html, product_ev + "; no purchase path found", cat, ev, vurl, store_nm)
        if decision == "us":
            reason = f"{product_ev}; {purchase_ev}; {why}" + (f"; note: {physical_note}" if physical_note else "")
            return self.row(rec, domain, url, "verified", plat, html, reason, cat, ev, vurl, store_nm)
        return self.row(rec, domain, url, "unverified", plat, html, f"US relevance weak: {why}; {product_ev}", cat, ev, vurl, store_nm)


def load_slice(worker: int, nworkers: int, only_tier: int | None):
    out = []
    with open(TRANCO) as f:
        for line in f:
            rank_s, dom = line.strip().split(",", 1)
            rank = int(rank_s)
            if rank < LO:
                continue
            if rank > HI:
                break
            if rank % nworkers != worker:
                continue
            t = tier(dom)
            if only_tier and t != only_tier:
                continue
            out.append((t, rank, dom.lower()))
    out.sort()
    return [(r, d) for _, r, d in out]


def iter_results(prefix="results_w"):
    if not os.path.isdir(WORK):
        return
    for fn in sorted(os.listdir(WORK)):
        if fn.startswith(prefix) and fn.endswith(".jsonl"):
            with open(os.path.join(WORK, fn)) as f:
                for line in f:
                    try:
                        yield json.loads(line)
                    except ValueError:
                        pass


def deferred(retry_status: str):
    """Domains handed to the Shopify-edge queue (plus optional extra statuses to retry)."""
    want = {"deferred_shopify"} | set(filter(None, retry_status.split(",")))
    out = {}
    for rec in iter_results():
        if rec.get("s") in want or (rec.get("rl") and "rl" in want):
            out[rec["d"]] = rec["r"]
    return sorted(((r, d) for d, r in out.items()), key=lambda x: (tier(x[1]), x[0]))


def done_set(prefix="results_w"):
    return {rec["d"] for rec in iter_results(prefix) if "d" in rec}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--worker", type=int, default=0)
    ap.add_argument("--of", type=int, default=1)
    ap.add_argument("--concurrency", type=int, default=150)
    ap.add_argument("--shopify-concurrency", type=int, default=6)
    ap.add_argument("--tier", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--mode", choices=["main", "shopify"], default="main")
    ap.add_argument("--rate", type=float, default=1.5, help="shopify mode: initial global req/s")
    ap.add_argument("--max-rate", type=float, default=4.0)
    ap.add_argument("--retry-status", default="", help="shopify mode: extra statuses to (re)process, e.g. rate_limited,rl")
    ap.add_argument("--domains", default="", help="comma list for ad-hoc testing (results printed, not saved)")
    args = ap.parse_args()
    os.makedirs(WORK, exist_ok=True)
    net = Net(args.concurrency, args.shopify_concurrency)
    await net.start()
    v = Verifier(net, shopify_mode=args.mode == "shopify")
    net.use_curl = args.mode == "shopify"
    if args.domains:
        for d in args.domains.split(","):
            print(json.dumps(await v.process(d.strip(), 0), ensure_ascii=False))
        await net.close()
        return
    if args.mode == "shopify":
        net.rate, net.max_rate = args.rate, args.max_rate
        net.use_curl = True
        done = done_set(prefix="results_shopify")
        items = [(r, d) for r, d in deferred(args.retry_status) if d not in done]
        out_path = os.path.join(WORK, "results_shopify.jsonl")
    else:
        items = load_slice(args.worker, args.of, args.tier or None)
        done = done_set()
        items = [x for x in items if x[1] not in done]
        out_path = os.path.join(WORK, f"results_w{args.worker}.jsonl")
    if args.limit:
        items = items[: args.limit]
    out = open(out_path, "a", buffering=1)
    q: asyncio.Queue = asyncio.Queue()
    for it in items:
        q.put_nowait(it)
    del items
    t0 = time.time()
    cnt = Counter()
    print(f"{args.mode} worker {args.worker}/{args.of}: {q.qsize()} domains to process (skipped {len(done)} done)", flush=True)
    del done

    async def runner():
        while True:
            try:
                rank, dom = q.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                rec = await asyncio.wait_for(v.process(dom, rank), 200)
            except asyncio.TimeoutError:
                rec = {"d": dom, "r": rank, "s": "error", "e": "domain_timeout"}
            except Exception as e:  # noqa: BLE001
                rec = {"d": dom, "r": rank, "s": "error", "e": f"{type(e).__name__}: {str(e)[:120]}"}
            rec["t"] = int(time.time())
            out.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
            cnt[rec["s"]] += 1
            if rec["s"] == "hit":
                cnt["row_" + rec["row"]["status"]] += 1

    async def reporter():
        while True:
            await asyncio.sleep(60)
            n = sum(v for k, v in cnt.items() if not k.startswith("row_"))
            el = time.time() - t0
            print(f"[{now_utc()}] {args.mode}{args.worker} done={n} rate={n / el:.1f}/s remaining={q.qsize()} "
                  f"reqs={net.stats['requests']} edge_rate={net.rate:.2f} {dict(cnt.most_common(16))}", flush=True)

    rep = asyncio.create_task(reporter())
    await asyncio.gather(*(runner() for _ in range(args.concurrency)))
    rep.cancel()
    out.close()
    await net.close()
    print(f"worker {args.worker} finished in {time.time() - t0:.0f}s {dict(cnt)}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
