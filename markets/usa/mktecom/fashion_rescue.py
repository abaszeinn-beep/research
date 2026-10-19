"""Rescue fashion-looking unverified candidates with cheap platform probes + gender signals.

  python3 -m mktecom.fashion_rescue run --input /tmp/rescue.tsv --table rescue --concurrency 12

Per store: Shopify /meta.json, /products.json, /collections.json (+ contact/shipping pages when no US signal yet);
WooCommerce store API; otherwise homepage + contact/shipping pages. Accept = purchase path + USD + >=1 strict US signal.
Gender is derived from collection handles, product_type, tags and nav/category slugs only.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import sqlite3
import time
import urllib.robotparser
from collections import Counter
from urllib.parse import urlsplit

import httpx

from .common import DEFAULT_HEADERS
from .market import M

DB = "data/usa_ecom.sqlite"
STRICT_SHIP = re.compile(r"ships? (?:from|within|to|only to) (?:the )?(?:U\.?S\.?A?\.?|United States|contiguous|continental)|contiguous (?:U\.?S\.?|United States)|lower 48|continental (?:U\.?S\.?|United States)|\bUSPS\b|UPS Ground|Made in (?:the )?USA|sales tax|Proposition 65|Prop 65|CCPA|domestic (?:U\.?S\.? )?(?:orders|shipping)|U\.?S\.? orders", re.I)
WOMEN_T = {"women", "womens", "woman", "ladies", "lady", "female", "womenswear", "womans", "her", "girls", "misses", "juniors", "maternity", "bridal", "bridesmaid"}
MEN_T = {"men", "mens", "man", "male", "menswear", "him", "guys", "gents", "boys"}
UNI_T = {"unisex", "genderless", "gender", "everyone"}
APP_T = re.compile(r"shirt|tee|top|blouse|dress|gown|skirt|pant|jean|denim|short|legging|jacket|coat|outerwear|sweater|hoodie|sweatshirt|cardigan|knit|swim|bikini|bra\b|underwear|lingerie|brief|boxer|sock|robe|pajama|sleep|lounge|activewear|apparel|clothing|romper|jumpsuit|suit|blazer|vest|polo|jersey|tank|tunic|kimono|scrub|uniform|set\b|bodysuit|trouser|chino|jogger|sweatpant|fleece|parka|poncho|cape|wrap|abaya|hijab|thobe", re.I)
NON_APP_T = re.compile(r"shoe|sneaker|boot|sandal|jewel|necklace|earring|ring|bracelet|bag|purse|wallet|watch|candle|home|decor|gift card|gift|sticker|poster|mug|print|book|beauty|skin|supplement|accessor|hat|cap\b|belt|scarf|glove|sunglass|pin\b|patch|keychain|toy|pet|food|coffee|tea\b", re.I)


class Bucket:
    def __init__(self, delay: float):
        self.delay = delay
        self.base = delay
        self.next_t = 0.0

    async def wait(self):
        now = time.monotonic()
        t = max(now, self.next_t)
        self.next_t = t + self.delay
        if t > now:
            await asyncio.sleep(t - now)


class Limiter:
    """Adaptive delay per rate-limit bucket: one shared bucket for the Shopify edge, one per other host."""

    def __init__(self, conc: int):
        self.sem = asyncio.Semaphore(conc)
        self.buckets: dict[str, Bucket] = {"shopify": Bucket(0.4)}
        self.shop_hosts: set[str] = set()
        self.n429 = 0
        self.nreq = 0

    def bucket(self, host: str) -> Bucket:
        if host in self.shop_hosts or host.endswith(".myshopify.com"):
            return self.buckets["shopify"]
        return self.buckets.setdefault(host, Bucket(0.4))

    @property
    def delay(self):
        return self.buckets["shopify"].delay


class Client:
    def __init__(self, conc: int):
        self.http = httpx.AsyncClient(headers=DEFAULT_HEADERS, follow_redirects=True, timeout=httpx.Timeout(15.0, connect=8.0), verify=False,
                                      limits=httpx.Limits(max_connections=conc * 2))
        self.lim = Limiter(conc)
        self.robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    async def allowed(self, origin: str, path: str) -> bool:
        if origin not in self.robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = await self.http.get(origin + "/robots.txt")
                if r.status_code == 200 and "<html" not in r.text[:200].lower():
                    rp.parse(r.text.splitlines())
                    self.robots[origin] = rp
                else:
                    self.robots[origin] = None
            except Exception:
                self.robots[origin] = None
        rp = self.robots[origin]
        return True if rp is None else rp.can_fetch(DEFAULT_HEADERS["User-Agent"], origin + path)

    async def get(self, origin: str, path: str, tries: int = 4):
        if not await self.allowed(origin, path):
            return None, "robots"
        host = urlsplit(origin).netloc
        for i in range(tries):
            bk = self.lim.bucket(host)
            await bk.wait()
            self.lim.nreq += 1
            try:
                r = await self.http.get(origin + path)
            except Exception as e:
                return None, type(e).__name__
            if "x-shopid" in r.headers or "x-shopify-stage" in r.headers:
                self.lim.shop_hosts.add(host)
            if r.status_code == 429:
                self.lim.n429 += 1
                bk = self.lim.bucket(host)
                bk.delay = min(bk.delay * 1.4 + 0.1, 5.0)
                ra = r.headers.get("retry-after")
                await asyncio.sleep(min(float(ra) if ra and ra.isdigit() else 2 * (i + 1) + random.random() * 2, 20))
                continue
            bk = self.lim.bucket(host)
            bk.delay = max(bk.base, bk.delay * 0.95)
            return r, None
        return None, "429"


def tokens(s: str) -> list[str]:
    return [t for t in re.split(r"[^a-z]+", s.lower()) if t]


def gender_counts(strings):
    w = m = u = 0
    for s in strings:
        tk = set(tokens(s))
        hw, hm = bool(tk & WOMEN_T), bool(tk & MEN_T)
        if hw and not hm:
            w += 1
        elif hm and not hw:
            m += 1
        elif tk & UNI_T:
            u += 1
    return w, m, u


def nav_slugs(html: str) -> list[str]:
    return [h.strip("/").split("/")[-1] for h in re.findall(r'href=["\'](?:https?://[^/"\']+)?(/[^"\'#?\s]*(?:women|womens|men|mens|ladies|collections/|product-category/|category/)[^"\'#?\s]*)', html, re.I)][:120]


def strip_html(h: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>", " ", h, flags=re.S | re.I))


def us_signals(text: str) -> list[str]:
    out = []
    if M.address_re.search(text):
        out.append("us_address")
    if M.phone_re.search(text):
        out.append("us_phone")
    if STRICT_SHIP.search(text):
        out.append("us_shipping")
    return out


async def probe(c: Client, key: str, url: str, name: str) -> dict:
    sp = urlsplit(url if url.startswith("http") else "https://" + url)
    origin = f"{sp.scheme}://{sp.netloc}"
    res = {"key": key, "origin": origin, "platform": None, "currency": None, "country": None, "purchase": False, "us": [], "types": [], "tags": [],
           "handles": [], "navslugs": [], "prices": 0, "usd_price": False, "notes": []}
    r, err = await c.get(origin, "/meta.json")
    meta = None
    if r is not None and r.status_code == 200:
        try:
            meta = r.json()
            if isinstance(meta, dict) and ("myshopify_domain" in meta or "currency" in meta):
                res["platform"] = "shopify"
        except Exception:
            meta = None
    if res["platform"] == "shopify":
        res["currency"], res["country"] = meta.get("currency"), meta.get("country")
        r, err = await c.get(origin, "/products.json?limit=60")
        prods = []
        if r is not None and r.status_code == 200:
            try:
                prods = r.json().get("products", [])
            except Exception:
                pass
        for p in prods:
            res["types"].append(p.get("product_type") or "")
            tg = p.get("tags") or []
            res["tags"] += tg if isinstance(tg, list) else str(tg).split(",")
            res["handles"].append(p.get("handle") or "")
            for v in p.get("variants", [])[:1]:
                try:
                    if float(v.get("price") or 0) > 0:
                        res["prices"] += 1
                except Exception:
                    pass
                if v.get("available"):
                    res["purchase"] = True
        r, err = await c.get(origin, "/collections.json?limit=100")
        if r is not None and r.status_code == 200:
            try:
                res["navslugs"] = [x.get("handle", "") for x in r.json().get("collections", [])]
            except Exception:
                pass
        if not res["types"] and len(res["navslugs"]) < 3:
            r, err = await c.get(origin, "/")
            if r is not None and r.status_code == 200:
                res["navslugs"] += nav_slugs(r.text[:600000])
        res["usd_price"] = res["currency"] == "USD" and res["prices"] > 0
        if res["country"] == "US":
            res["us"].append("shopify_country_US")
        if not res["us"] or not res["prices"]:
            texts = []
            for pth in ("/pages/contact", "/policies/shipping-policy", "/pages/shipping"):
                r, err = await c.get(origin, pth)
                if r is not None and r.status_code == 200:
                    texts.append(strip_html(r.text)[:30000])
                if len(us_signals(" ".join(texts))) >= 1 and res["country"] == "US":
                    break
            res["us"] += us_signals(" ".join(texts))
        if not prods:
            res["notes"].append("no_products_json")
        return res
    r, err = await c.get(origin, "/wp-json/wc/store/v1/products?per_page=40")
    if r is not None and r.status_code == 200:
        try:
            ps = r.json()
            if isinstance(ps, list) and ps:
                res["platform"] = "woocommerce"
                for p in ps:
                    pr = p.get("prices", {})
                    res["currency"] = res["currency"] or pr.get("currency_code")
                    if (pr.get("price") or "0") not in ("0", ""):
                        res["prices"] += 1
                    if p.get("is_purchasable", True) and p.get("is_in_stock", True):
                        res["purchase"] = True
                    res["types"] += [x.get("name", "") for x in p.get("categories", [])]
                    res["navslugs"] += [x.get("slug", "") for x in p.get("categories", [])]
                    res["tags"] += [x.get("name", "") for x in p.get("tags", [])]
                res["usd_price"] = res["currency"] == "USD" and res["prices"] > 0
        except Exception:
            pass
    r, err = await c.get(origin, "/")
    html = ""
    if r is not None and r.status_code == 200:
        html = r.text[:600000]
    elif err:
        res["notes"].append("home:" + err)
    elif r is not None:
        res["notes"].append(f"home:{r.status_code}")
    if html:
        low = html.lower()
        if res["platform"] is None:
            res["platform"] = "bigcommerce" if "bigcommerce" in low else "wix" if "wix.com" in low or "wixstatic" in low else "squarespace" if "squarespace" in low else "custom"
        if re.search(r"add[ _-]to[ _-](?:cart|bag)|data-product-id|\"@type\":\s*\"Product\"|/cart\b|/checkout|addtocart", low):
            res["purchase"] = res["purchase"] or True
        text = strip_html(html)
        if not res["usd_price"]:
            res["usd_price"] = bool(M.price_re.search(text)) and not re.search(r"\b(?:CAD|GBP|EUR|AUD|INR|AED|SAR)\b|[£€₹]", text[:20000])
        res["us"] += us_signals(text + " " + " ".join(re.findall(r'href=["\']tel:[^"\']+', html)))
        res["navslugs"] += nav_slugs(html)
        if not res["us"]:
            for pth in ("/contact", "/contact-us", "/pages/contact", "/shipping", "/pages/shipping-policy", "/shipping-policy", "/policies/shipping-policy"):
                r, err = await c.get(origin, pth)
                if r is not None and r.status_code == 200:
                    res["us"] += us_signals(strip_html(r.text)[:30000])
                    if res["us"]:
                        break
    res["us"] = sorted(set(res["us"]))
    return res


def verdict(res: dict) -> str:
    if not res["purchase"]:
        return "no_purchase_path"
    if not res["usd_price"]:
        return "no_usd_pricing"
    if not res["us"]:
        return "no_us_signal"
    return "accepted"


async def run(args):
    con = sqlite3.connect(DB, timeout=60)
    con.execute("CREATE TABLE IF NOT EXISTS %s(key TEXT PRIMARY KEY, verdict TEXT, data TEXT, ts TEXT)" % args.table)
    done = {r[0] for r in con.execute("select key from %s" % args.table)}
    items = [l.rstrip("\n").split("\t") for l in open(args.input) if l.strip()]
    items = [i for i in items if i[0] not in done]
    random.Random(1).shuffle(items)
    c = Client(args.concurrency)
    cnt = Counter()

    async def one(it):
        async with c.lim.sem:
            try:
                res = await asyncio.wait_for(probe(c, it[0], it[1], it[2] if len(it) > 2 else ""), 240)
            except Exception as e:
                res = {"key": it[0], "notes": ["err:" + type(e).__name__], "purchase": False, "us": [], "usd_price": False}
            v = verdict(res)
            if "err:" in " ".join(res.get("notes", [])) or any(n.startswith("home:") for n in res.get("notes", [])) and not res.get("purchase"):
                v = "fetch_failed"
            cnt[v] += 1
            con.execute("INSERT OR REPLACE INTO %s VALUES(?,?,?,?)" % args.table, (it[0], v, json.dumps(res), time.strftime("%Y-%m-%dT%H:%M:%S")))
            con.commit()
            if sum(cnt.values()) % 50 == 0:
                print(dict(cnt), "delay=%.2f 429s=%d req=%d" % (c.lim.delay, c.lim.n429, c.lim.nreq), flush=True)

    await asyncio.gather(*(one(i) for i in items))
    print("done", dict(cnt), flush=True)


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("--input", required=True)
    ap.add_argument("--table", default="rescue")
    ap.add_argument("--concurrency", type=int, default=12)
    asyncio.run(run(ap.parse_args()))
