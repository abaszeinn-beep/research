"""USA shard pipeline: screen Tranco domains and verify US ecommerce stores on the live site.

One process handles the slice ranks where (rank % nworkers == worker). Each process keeps its own SQLite state
file (resumable: processed domains are skipped on restart).

Per domain: lexical fast-skip -> robots.txt -> homepage (https, www, http fallbacks) -> cheap ecommerce screen.
Domains with ecommerce signals ("store hits") get full verification: platform probes (Shopify meta.json /
products.json, WooCommerce Store API), listing/product page, sitemap, contact/shipping page, US relevance signals.
Bot-walled domains are recorded as blocked (with hints) for the secondary-evidence pass; nothing is bypassed.

  python3 pipeline.py --worker 0 --nworkers 4 --concurrency 200
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import gzip
import json
import random
import re
import sqlite3
import sys
import time
import urllib.robotparser
import zlib
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, urlsplit, unquote

import aiohttp

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[3]))

import us_signals as U  # noqa: E402
from saudi_ecom import signals as S  # noqa: E402
from saudi_ecom.common import registrable_domain  # noqa: E402

STATE = HERE.parents[3] / "data" / "usa_tranco_200k_500k"
SLICE = STATE / "slice.csv"
TRANCO_ID = "64VVX"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
           "Accept-Language": "en-US,en;q=0.9", "Accept-Encoding": "gzip, deflate"}
HOME_BYTES = 700_000
CHALLENGE = re.compile(r"just a moment\.\.\.|cf-chl|challenge-platform/h/|attention required! \| cloudflare|"
                       r"request could not be satisfied|pardon our interruption|px-captcha|perimeterx|"
                       r"captcha-delivery|_incapsula_resource|ddos-guard|sucuri website firewall|are you a robot|"
                       r"access to this page has been denied|verify you are human|checking your browser", re.I)

MARKETPLACES = {
    "amazon": "Amazon marketplace", "ebay": "eBay marketplace", "etsy": "Etsy marketplace", "temu": "Temu marketplace",
    "aliexpress": "AliExpress marketplace", "alibaba": "Alibaba B2B marketplace", "poshmark": "Poshmark marketplace",
    "mercari": "Mercari marketplace", "wish": "Wish marketplace", "depop": "Depop marketplace", "grailed": "Grailed marketplace",
    "offerup": "OfferUp classifieds", "craigslist": "Craigslist classifieds", "reverb": "Reverb marketplace",
    "stockx": "StockX resale marketplace", "goat": "GOAT resale marketplace", "thredup": "thredUP resale marketplace",
    "therealreal": "consignment marketplace", "vinted": "Vinted marketplace", "dhgate": "DHgate marketplace",
    "shein": "SHEIN (marketplace model)", "fruugo": "Fruugo marketplace", "ubuy": "Ubuy cross-border marketplace",
    "desertcart": "cross-border marketplace", "joom": "Joom marketplace", "bonanza": "Bonanza marketplace",
    "ruten": "marketplace", "rakuten": "Rakuten marketplace", "mercadolibre": "marketplace", "mercadolivre": "marketplace",
    "allegro": "marketplace", "ozon": "marketplace", "wildberries": "marketplace", "avito": "classifieds", "olx": "classifieds",
    "kijiji": "classifieds", "gumtree": "classifieds", "facebook": "social", "instagram": "social",
    "tiktok": "social", "pinterest": "social", "storenvy": "marketplace", "bigcartel": "platform", "shopify": "platform",
    "faire": "wholesale marketplace", "chairish": "marketplace", "1stdibs": "marketplace", "redbubble": "print-on-demand marketplace",
    "teepublic": "print-on-demand marketplace", "spreadshirt": "print-on-demand marketplace", "zazzle": "print-on-demand marketplace",
    "society6": "print-on-demand marketplace", "cafepress": "print-on-demand marketplace", "threadless": "print-on-demand marketplace",
    "discogs": "marketplace", "abebooks": "marketplace", "biblio": "marketplace", "newegg": None, "walmart": None,
    "shopline": "ecommerce SaaS vendor", "shoplazza": "ecommerce SaaS vendor", "volusion": "ecommerce SaaS vendor",
    "ecwid": "ecommerce SaaS vendor", "lightspeedhq": "ecommerce SaaS vendor", "squarespace": "website SaaS vendor",
    "wix": "website SaaS vendor", "weebly": "website SaaS vendor", "godaddy": "hosting/SaaS vendor", "bigcommerce": "ecommerce SaaS vendor",
    "woocommerce": "ecommerce software vendor", "magento": "ecommerce software vendor", "prestashop": "ecommerce software vendor",
    "opencart": "ecommerce software vendor", "shopware": "ecommerce software vendor", "nuvemshop": "ecommerce SaaS vendor",
    "tiendanube": "ecommerce SaaS vendor", "shopbase": "ecommerce SaaS vendor", "sellfy": "digital SaaS vendor", "gumroad": "digital SaaS vendor",
    "shift4shop": "ecommerce SaaS vendor", "3dcart": "ecommerce SaaS vendor", "cs-cart": "ecommerce software vendor", "x-cart": "ecommerce software vendor",
    "miva": "ecommerce SaaS vendor", "americommerce": "ecommerce SaaS vendor", "spreecommerce": "ecommerce software vendor",
    "printful": "print-on-demand service", "printify": "print-on-demand service", "gelato": "print-on-demand service",
    "wayfair": None, "target": None, "bestbuy": None, "overstock": None,
}
MARKETPLACES = {k: v for k, v in MARKETPLACES.items() if v}

COMMERCE_PLATFORMS = {"shopify", "woocommerce", "magento", "bigcommerce", "salesforce-commerce", "sap-hybris", "prestashop",
                      "opencart", "ecwid", "vtex", "nopcommerce", "volusion", "shift4shop", "squarespace-commerce", "wix-stores",
                      "shopware", "lightspeed", "bigcartel", "square-online", "cs-cart", "zencart", "oscommerce", "x-cart",
                      "miva", "americommerce", "shoplazza", "shopline", "nuvemshop", "commercetools", "spree", "solidus",
                      "oracle-commerce", "kibo", "elastic-path", "salesforce-b2c", "storeden", "weebly-commerce", "godaddy-commerce",
                      "duda-commerce", "shopbase", "sellfy", "gumroad", "thinkific", "kajabi", "teachable", "podia"}
DIGITAL_PLATFORMS = {"sellfy", "gumroad", "thinkific", "kajabi", "teachable", "podia"}
EXTRA_MARKERS = [
    ("bigcommerce", re.compile(r"cdn\d*\.bigcommerce\.com|bigcommerce\.com/s-|stencil-utils|data-stencil", re.I)),
    ("volusion", re.compile(r"volusion|/v/vspfiles/", re.I)),
    ("shift4shop", re.compile(r"3dcart|shift4shop|3dcartstores", re.I)),
    ("squarespace-commerce", re.compile(r"static1\.squarespace\.com.{0,20000}(?:sqs-add-to-cart|ProductItem|commerce-)|\"isCommerceEnabled\"\s*:\s*true|sqs-add-to-cart-button", re.I | re.S)),
    ("wix-stores", re.compile(r"wixstores|wix-ecommerce|\"ecom\".{0,40}wix|data-hook=\"add-to-cart\"", re.I)),
    ("shopware", re.compile(r"shopware|sw-plugin|/bundles/storefront/", re.I)),
    ("lightspeed", re.compile(r"lightspeedhq|seoshop|webshopapp\.com|ecom\.lightspeed", re.I)),
    ("bigcartel", re.compile(r"bigcartel\.com|big cartel", re.I)),
    ("square-online", re.compile(r"editmysite\.com|square\.site|squareup\.com/online|weebly\.com/.{0,40}store", re.I)),
    ("cs-cart", re.compile(r"cs-cart|cscart", re.I)),
    ("zencart", re.compile(r"zen-cart|zencart|main_page=product_info", re.I)),
    ("oscommerce", re.compile(r"oscommerce|product_info\.php\?products_id", re.I)),
    ("x-cart", re.compile(r"x-cart|xcart", re.I)),
    ("miva", re.compile(r"mivamerchant|miva merchant|mm5/merchant\.mvc|/mm5/", re.I)),
    ("americommerce", re.compile(r"americommerce", re.I)),
    ("shoplazza", re.compile(r"shoplazza", re.I)),
    ("shopline", re.compile(r"shopline|shoplineapp", re.I)),
    ("nuvemshop", re.compile(r"nuvemshop|tiendanube", re.I)),
    ("spree", re.compile(r"spree_|spreecommerce|Spree\.", re.I)),
    ("godaddy-commerce", re.compile(r"img1\.wsimg\.com.{0,20000}(?:olstore|ols-|commerce)|godaddy online store", re.I | re.S)),
    ("shopbase", re.compile(r"shopbase|onshopbase", re.I)),
    ("sellfy", re.compile(r"sellfy\.com", re.I)),
    ("gumroad", re.compile(r"gumroad\.com/js|gumroad-button", re.I)),
    ("kajabi", re.compile(r"kajabi", re.I)),
    ("thinkific", re.compile(r"thinkific", re.I)),
    ("teachable", re.compile(r"teachable\.com|teachablecdn", re.I)),
    ("podia", re.compile(r"podia\.com", re.I)),
]
PRODUCT_LINK = re.compile(
    r"href=[\"'](?!data:)([^\"'<>\s]{0,200}?(?:/products?/[^\"'/?#]+|/p\d{5,}|/p/[^\"'/?#]+|-p-\d+|/item/[^\"'/?#]+|/dp/|"
    r"product_id=\d+|products_id=\d+|route=product/product|/product-page/|/[a-z0-9-]+-\d{4,}\.html|/[a-z0-9-]+/\d{5,}|/pd/|/shop/[a-z0-9-]+/[a-z0-9-]+)[^\"'<>\s]{0,200})[\"']",
    re.I)
PRODUCT_CARD = re.compile(r"class=[\"'][^\"']*\b(?:product-item-link|product-miniature|woocommerce-LoopProduct-link|add_to_cart_button|"
                          r"product_type_(?:simple|variable)|card-figure|productCard|product-card|product-tile|product_item|productitem|"
                          r"grid-product|product-thumb|ProductItem|product-grid-item|productGrid|card__heading)\b", re.I)
CARD_LINK = re.compile(r"<a[^>]+href=[\"']([^\"'#<>\s]{3,200})[\"'][^>]*class=[\"'][^\"']*\b(?:product-item-link|woocommerce-LoopProduct-link|"
                       r"product-thumbnail|card-figure__link|product-title|product-name|productitem--image-link)\b", re.I)
FOREIGN_TLD = re.compile(r"\.(?:de|fr|it|es|nl|be|pl|cz|sk|hu|ro|bg|gr|pt|se|no|dk|fi|ee|lv|lt|at|ch|ru|ua|by|kz|tr|il|ir|in|pk|bd|lk|id|my|th|vn|ph|"
                         r"cn|tw|hk|jp|kr|br|ar|cl|pe|mx|uy|ve|ec|za|ng|ke|eg|ma|sa|ae|qa|kw|au|nz|uk|ie|ca|hr|si|rs|ba|md|ge|am|az|is)$")
ADD_TO_CART = re.compile(r"add[ \-_]?to[ \-_]?(?:cart|bag|basket)|addtocart|add-to-cart|\?add-to-cart=|cart/add|data-product-id|product-form__cart|"
                         r"buy (?:it )?now|addToBag|add_to_cart", re.I)
CART = re.compile(r"/cart\b|/checkout\b|/basket\b|shopping[ -]cart|mini-?cart|cart-count|cart_count|cart-icon|header__cart|view cart", re.I)
PRICE = re.compile(r"(?:\$|USD|US\$|£|€|CA\$|A\$)\s?\d{1,5}(?:[,.]\d{3})*(?:[.,]\d{2})?")
LISTING_HINT = re.compile(r"href=[\"'](?!data:)([^\"'#<>\s]{0,200}?(?:/collections/all|/collections/[^\"']+|/shop/?|/store/?|/products/?|/catalog[^\"']*|"
                          r"/categor(?:y|ies)/[^\"']+|product-category/[^\"']+|/c/[^\"']+|/all-products|/new-arrivals?|/best-?sellers?|/sale/?)[^\"'#<>\s]{0,200})[\"']", re.I)
CONTACT_HINT = re.compile(r"href=[\"']([^\"'#<>\s]{0,200}?(?:shipping|delivery|contact|about|faq|policies|terms)[^\"'#<>\s]{0,120})[\"']", re.I)
SITEMAP_PRODUCT = re.compile(r"<loc>\s*(https?://[^<\s]{0,300}?(?:/products?/[^</]+|/product-[^</\s]+|/catalog/product/[^</]+|/p/[^</]+|/p\d{5,}|-p-\d+|/dp/[^<]+|/item/[^</]+|/pd/[^<]+)/?)\s*</loc>", re.I)
WOO_DEMO = re.compile(r"^(?:hoodie(?: with (?:logo|zipper|pocket))?|beanie(?: with logo)?|album|single|t-shirt(?: with logo)?|cap|sunglasses|polo|belt|long sleeve tee|v-neck t-shirt|logo collection|wordpress pennant|sample product.*|product name|test product.*|lorem ipsum.*)$", re.I)
NON_PHYSICAL_NAME = re.compile(r"\b(?:e-?book|ebook|pdf|download(?:able)?|digital (?:download|product|file|art|pattern|planner)|printable|svg|template|preset|"
                               r"course|masterclass|webinar|membership|subscription box|gift ?card|e-?gift|voucher|consultation|coaching|session|"
                               r"lesson|class|workshop|ticket|admission|registration|donation|license|software|plugin|theme|font|lut|"
                               r"service|appointment|booking|reading|tarot reading|sponsorship|deposit|tuition)\b", re.I)
SAAS_SITE = re.compile(r"\b(?:request a demo|book a demo|get a demo|schedule a demo|free trial|start (?:your )?free trial|start for free|"
                       r"sign up (?:for )?free|talk to sales|contact sales|per user|per seat|/mo\b|per month|billed annually|saas|"
                       r"api docs|developer docs|integrations|enterprise plan|cloud platform|our platform|software platform|"
                       r"cybersecurity|vulnerability|dashboard|workflow automation)\b", re.I)
PLAN_NAME = re.compile(r"^(?:the )?(?:basic|standard|premium|pro|plus|starter|silver|gold(?:en)?|platinum|bronze|enterprise|business|personal|"
                       r"free|lite|advanced|ultimate|diamond|essential|professional|team|agency|monthly|annual|yearly|lifetime)"
                       r"(?: (?:plan|package|membership|listing|tier|license|subscription|account|access|ad|monthly|annual|yearly))?$", re.I)
SERVICE_SITE = re.compile(r"\b(?:book (?:an |your )?appointment|schedule (?:a |your )?(?:consultation|appointment|service)|our services|"
                          r"law firm|attorneys?|dental|dentist|clinic|salon|spa services|real estate|realtor|insurance|mortgage|"
                          r"plumbing services|hvac services|contractor|roofing|landscaping services|cleaning services|church|ministry|"
                          r"nonprofit|non-profit|501\(c\)|charity|donate now|tour(?:s)? package|hotel|resort|vacation rental)\b", re.I)
RESTAURANT_SITE = re.compile(r"\b(?:order online for (?:pickup|delivery)|our menu|view menu|full menu|restaurant|pizzeria|takeout|dine[- ]in|"
                             r"catering menu|order pickup|doordash|grubhub|ubereats|uber eats)\b", re.I)
PARKED = re.compile(r"domain (?:name )?(?:is|may be) for sale|buy this domain|this domain is for sale|parked (?:free|domain)|sedoparking|"
                    r"parkingcrew|bodis\.com|hugedomains|afternic|dan\.com|domain has expired|account (?:has been )?suspended|"
                    r"welcome to nginx|apache2? (?:ubuntu |debian )?default page|it works!|index of /|future home of something|"
                    r"site not found|no such app|domain not configured|website coming soon|launching soon|under construction", re.I)
CLOSED = re.compile(r"store is (?:currently )?closed|this store is unavailable|store unavailable|temporarily closed|maintenance mode|"
                    r"we.ll be back soon|opening soon|enter store using password|password-page|this shop is unavailable|"
                    r"sorry, this shop is currently unavailable|we are no longer (?:taking|accepting) orders|out of business|"
                    r"permanently closed|has closed its doors|closing our (?:online )?store", re.I)


def now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


FAST_PLATFORMS = [  # (platform, substrings in lowercased html); first match wins, specific SaaS before generic
    ("shopify", ("cdn.shopify.com", "shopify.theme", "myshopify.com", "shopify-section")),
    ("magento", ("text/x-magento-init", "mage/cookies", "magento_", "/static/version")),
    ("salesforce-commerce", ("demandware", "/on/demandware.store", "dwanalytics")),
    ("bigcommerce", ("cdn11.bigcommerce.com", "bigcommerce.com/s-", "stencil-utils", "data-stencil", ".bigcommerce.com")),
    ("sap-hybris", ("/_ui/responsive", "acc.config")),
    ("vtex", ("vteximg", "vtexassets", "vtex.render")),
    ("woocommerce", ("woocommerce", "wc-block", "wc-ajax")),
    ("prestashop", ("prestashop", "var prestashop")),
    ("opencart", ("index.php?route=product", "index.php?route=common", "catalog/view/theme", "route=checkout")),
    ("ecwid", ("app.ecwid.com", "ecwid_")),
    ("volusion", ("/v/vspfiles/", "volusion")),
    ("shift4shop", ("3dcart", "shift4shop")),
    ("squarespace-commerce", ("sqs-add-to-cart", "\"iscommerceenabled\":true", "productitem-details", "commerce-product-item")),
    ("wix-stores", ("wixstores", "wix-ecommerce")),
    ("shopware", ("/bundles/storefront/", "shopware")),
    ("lightspeed", ("webshopapp.com", "lightspeedhq", "seoshop")),
    ("bigcartel", ("bigcartel.com",)),
    ("square-online", ("editmysite.com", "square.site", "squareup.com/online")),
    ("nopcommerce", ("nopcommerce",)),
    ("cs-cart", ("cs-cart", "cscart")),
    ("zencart", ("main_page=product_info", "zen-cart", "zencart")),
    ("oscommerce", ("product_info.php?products_id", "oscommerce", "oscsid=")),
    ("x-cart", ("x-cart", "xcart")),
    ("miva", ("mm5/merchant.mvc", "mivamerchant", "/mm5/")),
    ("americommerce", ("americommerce",)),
    ("shoplazza", ("shoplazza",)),
    ("shopline", ("shoplineapp", "shopline.")),
    ("nuvemshop", ("nuvemshop", "tiendanube")),
    ("shopbase", ("onshopbase", "shopbase")),
    ("spree", ("spree_", "spreecommerce")),
    ("odoo", ("website_sale", "/web/assets/")),
    ("sellfy", ("sellfy.com",)),
    ("gumroad", ("gumroad.com/js", "gumroad-button")),
    ("kajabi", ("kajabi-cdn", "kajabi.com")),
    ("thinkific", ("thinkific",)),
    ("teachable", ("teachablecdn", "teachable.com")),
    ("podia", ("podia.com",)),
    ("squarespace", ("static1.squarespace.com", "squarespace_context")),
    ("wix", ("static.wixstatic.com", "wix.com")),
    ("godaddy", ("img1.wsimg.com",)),
]


def detect_platform(html, headers, url):
    hl = {k.lower(): v for k, v in (headers or {}).items()}
    if any(k in hl for k in ("x-shopid", "x-shopify-stage", "x-sorting-hat-shopid", "x-shardid")) or "shopify" in hl.get("powered-by", "").lower():
        return "shopify"
    if "magento" in hl.get("x-magento-tags", "").lower() or "x-magento-cache-debug" in hl:
        return "magento"
    if "bigcommerce" in hl.get("platform", "").lower() or "x-bc-storefront" in hl:
        return "bigcommerce"
    low = html[:400000].lower()
    if ".myshopify.com" in url:
        return "shopify"
    for name, subs in FAST_PLATFORMS:
        for s in subs:
            if s in low:
                if name == "godaddy":
                    return "godaddy-commerce" if ("olstore" in low or "ols-" in low) else "custom/unknown"
                return name
    return "custom/unknown"


def cheap_signals(html, url, headers):
    h = html[:HOME_BYTES]
    plat = detect_platform(h, headers, url)
    links = {m.group(1) for m in PRODUCT_LINK.finditer(h)}
    cards = PRODUCT_CARD.findall(h)
    if not links and cards:
        links = {m.group(1) for m in CARD_LINK.finditer(h)}
    types, ld_cur = S.jsonld_types(h)
    return {"platform": plat, "product_links": len(links), "links": list(links)[:40], "cards": len(cards), "add_to_cart": len(ADD_TO_CART.findall(h)),
            "cart": len(CART.findall(h)), "prices": len(PRICE.findall(h)), "ld_types": types, "ld_currency": ld_cur}


def is_hit(c):
    if c["platform"] in COMMERCE_PLATFORMS:
        return True
    if c["ld_types"] & {"Product", "Offer", "AggregateOffer"}:
        return True
    if c["add_to_cart"] and (c["product_links"] >= 2 or c["prices"] >= 3):
        return True
    if c["cart"] >= 2 and c["product_links"] >= 4 and c["prices"] >= 3:
        return True
    return False


class Fetcher:
    def __init__(self, concurrency, shopify_rps=0.0):
        self.concurrency = concurrency
        self.sem = asyncio.Semaphore(concurrency)
        self.shopify_sem = asyncio.Semaphore(max(4, concurrency // 12))
        self.stats = Counter()
        self.session = None
        self.shopify_rps = shopify_rps
        self.shop_next = 0.0
        self.shop_lock = asyncio.Lock()
        self.ip_cache: dict[str, bool] = {}
        self.resolver = None

    async def is_shopify_host(self, host):
        if host in self.ip_cache:
            return self.ip_cache[host]
        val = False
        try:
            infos = await asyncio.wait_for(self.resolver.resolve(host, 443), 6)
            val = any(i["host"].startswith("23.227.") and 32 <= int(i["host"].split(".")[2]) <= 63 for i in infos)
        except Exception:
            val = False
        self.ip_cache[host] = val
        return val

    async def pace(self, url):
        """Shopify rate-limits per client IP across all shops; space requests to Shopify-hosted stores globally."""
        if not self.shopify_rps or self.resolver is None:
            return
        host = urlsplit(url).hostname or ""
        if not await self.is_shopify_host(host):
            return
        async with self.shop_lock:
            t = time.monotonic()
            wait = self.shop_next - t
            self.shop_next = max(t, self.shop_next) + 1.0 / self.shopify_rps
        if wait > 0:
            self.stats["shopify_paced"] += 1
            await asyncio.sleep(wait)

    async def start(self):
        try:
            resolver = aiohttp.AsyncResolver(nameservers=["8.8.8.8", "1.1.1.1", "8.8.4.4", "1.0.0.1"], timeout=4, tries=2)
        except Exception:
            resolver = None
        self.resolver = resolver
        conn = aiohttp.TCPConnector(limit=self.concurrency * 2, limit_per_host=2, ttl_dns_cache=600, ssl=False,
                                    resolver=resolver, enable_cleanup_closed=True, force_close=False)
        self.session = aiohttp.ClientSession(connector=conn, headers=HEADERS, cookie_jar=aiohttp.DummyCookieJar(),
                                             auto_decompress=True, max_line_size=16384, max_field_size=16384)

    async def close(self):
        await self.session.close()

    async def get(self, url, limit=HOME_BYTES, total=18, tries=2, headers=None):
        """Return (status, final_url, text, headers, error)."""
        last = None
        for attempt in range(tries):
            await self.pace(url)
            async with self.sem:
                try:
                    to = aiohttp.ClientTimeout(total=total, connect=7, sock_read=10)
                    async with self.session.get(url, timeout=to, allow_redirects=True, max_redirects=8, headers=headers) as r:
                        buf = bytearray()
                        async for chunk in r.content.iter_chunked(65536):
                            buf += chunk
                            if len(buf) >= limit:
                                break
                        self.stats["requests"] += 1
                        cs = r.charset or "utf-8"
                        try:
                            text = bytes(buf).decode(cs, errors="replace")
                        except LookupError:
                            text = bytes(buf).decode("utf-8", errors="replace")
                        st = r.status
                        hd = dict(r.headers)
                        final = str(r.url)
                    if st == 429:
                        self.stats["http_429"] += 1
                    if st in (429, 502, 504) and attempt < tries - 1 and not CHALLENGE.search(text[:5000]):
                        last = f"http_{st}"
                        ra = hd.get("Retry-After", "")
                        delay = min(float(ra), 20) if ra.isdigit() else 4
                    else:
                        return st, final, text, hd, None
                except aiohttp.ClientConnectorError as e:
                    msg = str(e)
                    if "Name or service not known" in msg or "Domain name not found" in msg or "No address" in msg or "DNS" in msg or "Could not contact DNS" in msg:
                        return None, url, "", {}, "dns_not_resolved"
                    last, delay = "connect_error", 2
                    if attempt >= 0:
                        return None, url, "", {}, last
                except aiohttp.TooManyRedirects:
                    return None, url, "", {}, "too_many_redirects"
                except asyncio.TimeoutError:
                    last, delay = "timeout", 2
                    return None, url, "", {}, last
                except (aiohttp.ClientError, UnicodeError, ValueError, OSError, zlib.error, AssertionError, LookupError) as e:
                    last, delay = f"http_error:{type(e).__name__}", 2
            await asyncio.sleep(delay + random.random())
        return None, url, "", {}, last


class Site:
    """Per-domain request helper: robots.txt compliance and politeness gap between requests to the same host."""

    def __init__(self, f: Fetcher, base: str):
        self.f, self.base, self.rp, self.last = f, base, None, 0.0
        self.sitemaps = []

    async def load_robots(self):
        st, final, txt, _, err = await self.f.get(self.base + "/robots.txt", limit=200_000, total=10, tries=1)
        if st == 200 and "<html" not in txt[:600].lower() and "<!doctype" not in txt[:300].lower():
            rp = urllib.robotparser.RobotFileParser()
            try:
                rp.parse(txt.splitlines())
                self.rp = rp
                self.sitemaps = list(rp.site_maps() or [])
            except Exception:
                self.rp = None
        return st, err

    def allowed(self, url):
        if self.rp is None:
            return True
        try:
            return self.rp.can_fetch(UA, url) or self.rp.can_fetch("*", url)
        except Exception:
            return True

    async def get(self, url, **kw):
        if not self.allowed(url):
            self.f.stats["robots_disallowed"] += 1
            return None, url, "", {}, "robots_disallowed"
        gap = time.monotonic() - self.last
        if gap < 0.4:
            await asyncio.sleep(0.4 - gap)
        self.last = time.monotonic()
        return await self.f.get(url, **kw)


def mk_row(domain, rank, **kw):
    row = {"store_name": "", "canonical_storefront_url": "", "root_domain": registrable_domain(domain), "platform": "", "category": "",
           "status": "", "us_evidence": "", "verification_url": "", "verification_utc": now(),
           "discovery_source": f"tranco_top1m:{TRANCO_ID}", "tranco_rank": rank, "reason": ""}
    row.update(kw)
    return row


def canonical(final_url):
    sp = urlsplit(final_url)
    host = (sp.hostname or "").lower()
    m = U.US_PATH.search(final_url)
    path = "/"
    if m and m.group(0).startswith("/"):
        path = m.group(0) if m.group(0).endswith("/") else m.group(0) + "/"
    return f"https://{host}{path}"


async def shopify_probe(site: Site, base):
    out = {}
    async with site.f.shopify_sem:
        st, _, txt, _, _ = await site.get(base + "/meta.json", limit=200_000, total=12, tries=2)
        if st == 200 and txt.strip().startswith("{"):
            try:
                mj = json.loads(txt)
                out.update({k: mj.get(k) for k in ("name", "currency", "country", "province", "city", "myshopify_domain", "domain", "published_products_count")})
                out["meta_url"] = base + "/meta.json"
            except ValueError:
                pass
        st, _, txt, _, _ = await site.get(base + "/products.json?limit=30", limit=2_000_000, total=15, tries=2)
    if st == 200 and txt.strip().startswith("{"):
        try:
            prods = json.loads(txt).get("products") or []
            ship = sum(1 for p in prods if any(v.get("requires_shipping") for v in (p.get("variants") or [])))
            avail = sum(1 for p in prods if any(v.get("available") for v in (p.get("variants") or [])))
            out.update({"n": len(prods), "requires_shipping": ship, "available": avail,
                        "names": [p.get("title") or "" for p in prods][:30], "types": [p.get("product_type") or "" for p in prods][:30],
                        "latest": max((p.get("updated_at") or "" for p in prods), default=""),
                        "sample_url": base + "/products/" + prods[0]["handle"] if prods else None, "products_url": base + "/products.json"})
        except (ValueError, KeyError, TypeError, AttributeError):
            pass
    elif st == 429:
        out["rate_limited"] = True
    return out or None


async def woo_probe(site: Site, base):
    st, _, txt, _, _ = await site.get(base + "/wp-json/wc/store/v1/products?per_page=20", limit=2_000_000, total=15, tries=1)
    if st != 200 or not txt.strip().startswith("["):
        st, _, txt, _, _ = await site.get(base + "/wp-json/wc/store/products?per_page=20", limit=2_000_000, total=15, tries=1)
    if st == 200 and txt.strip().startswith("["):
        try:
            prods = json.loads(txt)
        except ValueError:
            return None
        if not isinstance(prods, list):
            return None
        cur = sorted({(p.get("prices") or {}).get("currency_code") for p in prods if isinstance(p, dict) and p.get("prices")} - {None})
        names = [re.sub(r"<[^>]+>|\s+", " ", (p.get("name") or "")).strip() for p in prods if isinstance(p, dict)]
        return {"n": len(names), "currency": cur, "names": names[:20], "demo": sum(1 for n in names if WOO_DEMO.match(n)),
                "sample_url": prods[0].get("permalink") if prods and isinstance(prods[0], dict) else None,
                "purchasable": sum(1 for p in prods if isinstance(p, dict) and p.get("is_purchasable")),
                "virtual_hint": sum(1 for n in names if NON_PHYSICAL_NAME.search(n)), "products_url": base + "/wp-json/wc/store/v1/products"}
    return None


async def sitemap_probe(site: Site, base):
    maps = site.sitemaps[:3] or [base + "/sitemap.xml"]
    for sm in maps:
        st, _, txt, _, _ = await site.get(sm, limit=3_000_000, total=15, tries=1)
        if st != 200 or "<loc>" not in (txt or ""):
            continue
        prods = SITEMAP_PRODUCT.findall(txt)
        children = re.findall(r"<sitemap>\s*<loc>\s*([^<]+)</loc>", txt, re.I)
        if prods and not children:
            return {"sitemap": sm, "product_urls": len(prods), "sample_url": prods[0].strip()}
        named = [c.strip() for c in children if re.search(r"product", c, re.I)]
        for ch in named[:1]:
            st2, _, t2, _, _ = await site.get(ch, limit=3_000_000, total=15, tries=1)
            if st2 == 200 and t2:
                locs = re.findall(r"<loc>\s*([^<\s]{1,500})\s*</loc>", t2)
                locs = [l for l in locs if not re.search(r"\.(?:jpe?g|png|webp|gif)(?:\?|$)", l, re.I)]
                if len(locs) >= 3:
                    return {"sitemap": ch, "product_urls": len(locs), "sample_url": locs[0]}
    return None


def same_site(u, final):
    a, b = (urlsplit(u).hostname or "").lower(), (urlsplit(final).hostname or "").lower()
    return a == b or a.removeprefix("www.") == b.removeprefix("www.")


async def verify_store(site: Site, domain, rank, final, html, hdrs, c):
    """Full verification of a store hit. Returns a CSV row dict (+ internal 'detail')."""
    text = S.visible_text(html)
    title = S.title_of(html)
    host = urlsplit(final).hostname or domain
    base = f"{urlsplit(final).scheme}://{urlsplit(final).netloc}"
    name = S.store_name(html, domain, host)
    froot = registrable_domain(host.lower())
    row = mk_row(domain, rank, store_name=name, canonical_storefront_url=canonical(final), root_domain=froot,
                 platform=c["platform"], verification_url=final)
    detail = {"home": final}

    def done(status, reason, **kw):
        row.update(status=status, reason=reason, verification_utc=now(), **kw)
        row["detail"] = detail
        return row

    label = froot.split(".")[0]
    if label in MARKETPLACES:
        return done("rejected", f"excluded_marketplace_or_platform: {MARKETPLACES[label]}")
    short = len(text) < 4000
    head = title + " " + text[:4000]
    pk = PARKED.search(head) if short else None
    if pk:
        return done("rejected", "parked_or_placeholder: " + pk.group(0)[:60])
    cl = CLOSED.search(head) if (len(text) < 6000 or "password-page" in html[:30000]) else None
    if cl or ("password-page" in html[:30000] and len(text) < 6000):
        return done("rejected", "store_closed_or_password_protected" + (": " + cl.group(0) if cl else ""))

    plat = c["platform"]
    if plat in DIGITAL_PLATFORMS:
        return done("rejected", f"digital_products_platform ({plat})")
    probe = None
    try:
        if plat == "shopify":
            probe = await shopify_probe(site, base)
        elif plat == "woocommerce":
            probe = await woo_probe(site, base)
    except Exception as e:
        probe = {"error": type(e).__name__}
    detail["probe"] = {k: v for k, v in (probe or {}).items() if k not in ("names", "types")}
    if plat == "shopify" and probe and probe.get("domain") and not str(probe["domain"]).endswith(".myshopify.com"):
        pd = registrable_domain(str(probe["domain"]).lower().removeprefix("www."))
        if pd != froot:
            detail["shopify_primary_domain"] = probe["domain"]

    # Clearly non-US storefronts are rejected on US relevance before spending requests on product evidence.
    g0, e0, n0 = U.us_signals(html, text, final, {k: v for k, v in (probe or {}).items() if k in ("country", "currency")})
    s0, r0 = U.decide_us(g0, e0, n0)
    if s0 == "rejected" and not r0.startswith("no_us_signals"):
        row["us_evidence"] = json.dumps(e0, ensure_ascii=False)[:600]
        return done("rejected", r0 + " (homepage)")
    if not g0["currency"] and not g0["location"] and FOREIGN_TLD.search(froot) and (n0.get("foreign_price_strings") or not c["prices"]):
        return done("rejected", f"not_us_relevant (foreign ccTLD .{froot.rsplit('.', 1)[-1]}, no USD/US signals)")

    extra_html, extra_url = "", None
    if c["product_links"] < 3 and c["cards"] < 3 and not (probe and probe.get("n")):
        cands = [urljoin(final, m.group(1)) for m in LISTING_HINT.finditer(html[:800_000])]
        cands = [u for u in cands if same_site(u, final) and not re.search(r"\.(?:jpe?g|png|css|js)(?:\?|$)", u, re.I)]
        default = {"woocommerce": "/shop/", "shopify": "/collections/all"}.get(plat)
        if default:
            cands.append(base + default)
        if cands:
            st2, fin2, h2, _, _ = await site.get(cands[0], total=15, tries=1)
            if st2 != 200 and default and cands[0] != base + default:
                st2, fin2, h2, _, _ = await site.get(base + default, total=15, tries=1)
            if st2 == 200:
                extra_html, extra_url = h2, fin2
                c2 = cheap_signals(h2, fin2, {})
                for k in ("product_links", "add_to_cart", "cart", "prices", "cards"):
                    c[k] = max(c[k], c2[k])
                c["links"] = c["links"] or c2["links"]
                c["cards"] = max(c["cards"], c2["cards"])
                c["ld_types"] |= c2["ld_types"]
                c["ld_currency"] |= c2["ld_currency"]

    product_html, product_url = "", None
    sample = (probe or {}).get("sample_url")
    if not sample and c["links"]:
        for l in c["links"]:
            u = urljoin(extra_url or final, l)
            if same_site(u, final) and not re.search(r"\.(?:jpe?g|png|webp|pdf)(?:\?|$)", u, re.I):
                sample = u
                break
    smp = None
    if not sample and not (probe and probe.get("n")):
        try:
            smp = await sitemap_probe(site, base)
        except Exception:
            smp = None
        if smp:
            detail["sitemap"] = smp
            sample = smp["sample_url"]
    if sample and plat not in ("shopify",) and not (plat == "woocommerce" and probe and probe.get("n")):
        st3, fin3, h3, _, _ = await site.get(sample, total=15, tries=1)
        if st3 == 200 and h3:
            product_html, product_url = h3, fin3
            c3 = cheap_signals(h3, fin3, {})
            detail["product_page"] = {"url": fin3, "add_to_cart": c3["add_to_cart"], "prices": c3["prices"], "ld": sorted(c3["ld_types"] & {"Product", "Offer"})}
            c["add_to_cart"] = max(c["add_to_cart"], c3["add_to_cart"])
            c["ld_types"] |= c3["ld_types"]
            c["ld_currency"] |= c3["ld_currency"]
            c["prices"] = max(c["prices"], c3["prices"])

    # ecommerce evidence
    product_ev, purchase_ev = [], []
    if probe and probe.get("n"):
        product_ev.append(f"{probe['n']} products via {plat} {'products.json' if plat == 'shopify' else 'Store API'}")
    if c["product_links"] >= 2:
        product_ev.append(f"{c['product_links']} product links")
    if c["cards"] >= 3:
        product_ev.append(f"{c['cards']} product-card markers ({plat})")
    if c["ld_types"] & {"Product", "Offer", "AggregateOffer"}:
        product_ev.append("schema.org Product/Offer")
    if smp:
        product_ev.append(f"{smp['product_urls']} product URLs in sitemap")
    if detail.get("product_page"):
        pp = detail["product_page"]
        if pp["ld"] or (pp["prices"] and pp["add_to_cart"]):
            product_ev.append("product page with price/offer")
    if c["add_to_cart"]:
        purchase_ev.append("add-to-cart")
    if c["cart"] >= 2:
        purchase_ev.append("cart/checkout")
    if plat in COMMERCE_PLATFORMS and plat not in ("wix-stores", "squarespace-commerce", "godaddy-commerce", "square-online"):
        purchase_ev.append(f"{plat} cart/checkout")
    if plat == "shopify" and probe and probe.get("n"):
        purchase_ev.append("shopify /cart endpoint")
    detail["product_ev"], detail["purchase_ev"] = product_ev, purchase_ev
    evidence_url = (probe or {}).get("products_url") or product_url or (smp or {}).get("sitemap") or extra_url or final
    row["verification_url"] = product_url or (probe or {}).get("sample_url") or evidence_url

    # exclusions
    pnames = [n for n in ((probe or {}).get("names") or []) if n]
    if plat == "shopify" and probe and probe.get("n"):
        if probe.get("requires_shipping", 0) == 0:
            return done("rejected", "no_shippable_products (shopify products.json requires_shipping=0)", verification_url=probe.get("products_url"))
        if probe.get("available", 0) == 0:
            detail["note_unavailable"] = True
    if plat in ("woocommerce", "shopify") and probe and probe.get("n") == 0 and c["product_links"] < 2 and not smp:
        return done("rejected", f"no_products_listed ({plat} {'products.json' if plat == 'shopify' else 'Store API'} returned 0 products)",
                    verification_url=probe.get("products_url") or final)
    if plat == "woocommerce" and probe and probe.get("n"):
        if probe["demo"] >= max(2, probe["n"] // 2):
            return done("rejected", f"theme_demo_products_only ({probe['demo']}/{probe['n']})")
        if probe["purchasable"] == 0:
            return done("rejected", f"catalog_or_affiliate_only (woocommerce Store API: 0/{probe['n']} products purchasable)",
                        verification_url=probe.get("products_url"))
    if pnames:
        plans = [n for n in pnames if PLAN_NAME.match(n.strip())]
        if len(plans) >= max(1, (len(pnames) + 1) // 2):
            return done("rejected", f"pricing_plans_or_packages_not_products ({len(plans)}/{len(pnames)}; e.g. {' / '.join(plans[:3])})")
        dig = [n for n in pnames if NON_PHYSICAL_NAME.search(n)]
        share = len(dig) / len(pnames)
        if (len(pnames) >= 3 and share >= 0.6) or (len(pnames) < 3 and len(dig) == len(pnames)):
            return done("rejected", f"mostly_digital_or_services_by_product_names ({len(dig)}/{len(pnames)}; e.g. {' / '.join(d[:40] for d in dig[:3])})")
    if not product_ev and not purchase_ev:
        return done("rejected", "no_ecommerce_evidence")
    if not product_ev or not purchase_ev:
        if len(text) < 1500 and html.count("<script") >= 5:
            return done("unverified", "js_rendered_partial_evidence: " + ",".join(product_ev + purchase_ev))
        if not purchase_ev:
            return done("rejected", "no_purchase_path (product markup only): " + ",".join(product_ev))
        if "add-to-cart" not in purchase_ev:
            return done("rejected", "no_products_found (homepage, listing page, platform API and sitemap checked; only cart/plugin markers: "
                        + ",".join(purchase_ev) + ")")
        return done("unverified", "insufficient_product_evidence: " + ",".join(purchase_ev))
    if plat in ("custom/unknown", "wix", "wix-stores", "odoo", "squarespace-commerce", "godaddy-commerce", "square-online", "nopcommerce") or (plat == "woocommerce" and not (probe and probe.get("n"))):
        strong = c["product_links"] >= 3 or c["cards"] >= 3 or bool(c["ld_types"] & {"Product", "Offer"}) or bool(smp and smp["product_urls"] >= 5) or "product page with price/offer" in product_ev
        if not (c["add_to_cart"] >= 1 and strong):
            return done("unverified", "weak_ecommerce_evidence_generic_platform: " + ",".join(product_ev + purchase_ev))
    blob = title + " " + (S.meta(html, "description") or "") + " " + text[:8000]
    n_saas = len(set(m.lower() for m in SAAS_SITE.findall(blob + " " + text[8000:30000])))
    if n_saas >= 3 and not (probe and probe.get("n")) and plat in ("custom/unknown", "wix", "squarespace", "godaddy-commerce"):
        return done("rejected", f"likely_saas_or_software ({n_saas} SaaS markers)")
    if plat == "custom/unknown" and c["cart"] == 0 and not (c["ld_types"] & {"Product"}):
        return done("unverified", "no_cart_or_checkout_path_found (custom platform; manual review): " + ",".join(product_ev + purchase_ev))
    weak_products = not (probe and probe.get("n")) and c["product_links"] < 10
    if weak_products:
        if len(RESTAURANT_SITE.findall(blob)) >= 3:
            return done("rejected", "likely_restaurant_or_food_service")
        if len(SERVICE_SITE.findall(blob)) >= 3 and c["add_to_cart"] < 2:
            return done("unverified", "likely_services_or_organization_site (manual review)")

    # US relevance; fetch a shipping/contact page when location evidence is missing
    api = {}
    if probe:
        if probe.get("country"):
            api["country"] = probe["country"]
        if probe.get("currency"):
            api["currency"] = probe["currency"]
    all_html = html + extra_html[:300000] + product_html[:300000]
    all_text = text + " " + S.visible_text(extra_html)[:60000] + " " + S.visible_text(product_html)[:60000]
    if plat == "woocommerce" or "/wp-content/" in html[:200000]:
        stw, finw, tw, _, _ = await site.get(base + "/wp-json/?_fields=name,timezone_string,gmt_offset", limit=300_000, total=12, tries=1)
        if stw == 200:
            mt = U.US_TZ.search(tw[:300000])
            if mt:
                api["timezone"] = mt.group(1).replace("\\/", "/")
                detail["wp_json"] = finw
    groups, ev, neg = U.us_signals(all_html, all_text, final, api)
    if not groups["location"] and not (api.get("country") and api["country"] != "US"):
        pages = []
        if plat == "shopify":
            pages = [base + "/policies/shipping-policy", base + "/pages/contact"]
        hints = [urljoin(final, m.group(1)) for m in CONTACT_HINT.finditer(html[:800000])]
        hints = [u for u in hints if same_site(u, final) and not re.search(r"\.(?:jpe?g|png|pdf|css|js)(?:\?|$)", u, re.I)]
        hints.sort(key=lambda u: (0 if re.search(r"shipping|delivery", u, re.I) else 1 if "contact" in u.lower() else 2 if re.search(r"terms|conditions", u, re.I) else 3))
        for u in list(dict.fromkeys(pages + hints))[:3]:
            st4, fin4, h4, _, _ = await site.get(u, total=12, tries=1)
            if st4 == 200 and h4:
                g2, e2, n2 = U.us_signals(h4, S.visible_text(h4), final, api)
                for k in ("us_address", "us_phone", "us_shipping", "us_governing_law", "us_city_state"):
                    if k in e2 and k not in ev:
                        ev[k] = e2[k]
                        ev[k + "_page"] = fin4
                        groups["location"].append(k)
                for k in ("canada_address", "canada_phone"):
                    if k in n2:
                        neg[k] = n2[k]
                if groups["location"]:
                    break
    status, reason = U.decide_us(groups, ev, neg)
    detail["us_groups"], detail["neg"] = groups, neg
    row["us_evidence"] = json.dumps(ev, ensure_ascii=False)[:600]
    cat_texts = [title + " " + name, S.meta(html, "description") or "", S.meta(html, "keywords") or "",
                 " ".join(pnames + ((probe or {}).get("types") or [])), text[:6000]]
    cat, sub = U.classify(cat_texts, [6, 4, 2, 3, 1])
    row["category"] = cat if not sub else f"{cat}"
    detail["subcategory"] = sub
    if status == "verified":
        reason = reason + "; " + "; ".join(product_ev[:3]) + "; purchase: " + ", ".join(purchase_ev[:2])
        if detail.get("note_unavailable"):
            reason += "; note: sampled products currently sold out"
    elif status == "rejected" and reason.startswith(("not_us", "non_us", "canada", "no_us")):
        pass
    return done(status, reason)


async def process(f: Fetcher, domain, rank):
    skip = U.fast_skip(domain)
    if skip:
        return {"stage": "skipped", "status": "skipped", "reason": skip}
    label = registrable_domain(domain).split(".")[0]
    if label in MARKETPLACES and registrable_domain(domain) == domain:
        row = mk_row(domain, rank, store_name=label, canonical_storefront_url=f"https://{domain}/", status="rejected",
                     reason=f"excluded_marketplace_or_platform: {MARKETPLACES[label]}", verification_url=f"https://{domain}/")
        return {"stage": "hit", "status": "rejected", "reason": row["reason"], "row": row}
    tries = [f"https://{domain}", f"https://www.{domain}", f"http://{domain}"]
    st = err = None
    final = html = ""
    hdrs = {}
    site = None
    for base in tries:
        site = Site(f, base)
        rst, rerr = await site.load_robots()
        if rerr == "dns_not_resolved":
            if base == f"https://{domain}":
                continue
            st, err = None, rerr
            break
        if not site.allowed(base + "/"):
            return {"stage": "screen", "status": "robots_disallowed", "reason": "robots.txt disallows homepage"}
        st, final, html, hdrs, err = await site.get(base + "/", tries=1)
        if st is not None:
            break
        if err == "timeout":
            break
    if st is None:
        return {"stage": "screen", "status": "error", "reason": err or "unreachable"}
    froot = registrable_domain((urlsplit(final).hostname or domain).lower())
    head = html[:8000]
    if st in (401, 403, 429, 503) or (st >= 400 and CHALLENGE.search(head)) or (st == 200 and CHALLENGE.search(head) and len(html) < 30000):
        hint = {"http": st, "final": final, "sitemaps": site.sitemaps[:5], "platform": detect_platform(html, hdrs, final),
                "server": hdrs.get("Server", "")[:40], "robots": site.rp is not None, "final_root": froot}
        return {"stage": "screen", "status": "blocked", "reason": f"blocked_or_challenge_http_{st}", "hint": hint}
    if st >= 400:
        return {"stage": "screen", "status": "http_error", "reason": f"http_{st}"}
    c = cheap_signals(html, final, hdrs)
    if not is_hit(c):
        return {"stage": "screen", "status": "non_store", "reason": f"platform={c['platform']},atc={c['add_to_cart']},links={c['product_links']}",
                "hint": {"final_root": froot} if froot != registrable_domain(domain) else None}
    row = await verify_store(site, domain, rank, final, html, hdrs, c)
    detail = row.pop("detail", {})
    return {"stage": "hit", "status": row["status"], "reason": row["reason"], "row": row, "detail": detail}


def connect(worker):
    STATE.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(STATE / f"w{worker}.sqlite", timeout=60)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("""CREATE TABLE IF NOT EXISTS results(domain TEXT PRIMARY KEY, rank INT, stage TEXT, status TEXT, reason TEXT,
                   row TEXT, detail TEXT, hint TEXT, ts TEXT, elapsed REAL)""")
    con.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)")
    return con


async def main(worker, nworkers, concurrency, limit, redo, shopify_rps):
    con = connect(worker)
    con.execute("CREATE TABLE IF NOT EXISTS redo_log(domain TEXT, old_status TEXT, old_reason TEXT, ts TEXT)")
    if redo:
        todo = [(r[1], r[0]) for r in con.execute(f"SELECT domain, rank FROM results WHERE {redo} ORDER BY rank")]
        con.executemany("INSERT INTO redo_log SELECT domain,status,reason,? FROM results WHERE domain=?", [(now(), d) for _, d in todo])
        con.commit()
    else:
        done_set = {r[0] for r in con.execute("SELECT domain FROM results")}
        todo = []
        with open(SLICE) as fh:
            for line in fh:
                rank, dom = line.strip().split(",", 1)
                rank = int(rank)
                if rank % nworkers == worker and dom not in done_set:
                    todo.append((rank, dom.strip().lower()))
        con.execute("INSERT OR IGNORE INTO meta VALUES('started', ?)", (now(),))
    if limit:
        todo = todo[:limit]
    print(f"[w{worker}] todo={len(todo)} redo={bool(redo)}", flush=True)
    con.commit()
    f = Fetcher(concurrency, shopify_rps)
    await f.start()
    q: asyncio.Queue = asyncio.Queue()
    for t in todo:
        q.put_nowait(t)
    stats = Counter()
    pending_rows = []
    t0 = time.time()

    def flush():
        if pending_rows:
            con.executemany("INSERT OR REPLACE INTO results VALUES(?,?,?,?,?,?,?,?,?,?)", pending_rows)
            con.commit()
            pending_rows.clear()

    async def consumer():
        while True:
            try:
                rank, dom = q.get_nowait()
            except asyncio.QueueEmpty:
                return
            ts = time.monotonic()
            try:
                res = await asyncio.wait_for(process(f, dom, rank), 150)
            except asyncio.TimeoutError:
                res = {"stage": "screen", "status": "error", "reason": "domain_timeout_150s"}
            except Exception as e:
                res = {"stage": "screen", "status": "error", "reason": f"pipeline_error:{type(e).__name__}:{str(e)[:80]}"}
            stats[res["status"]] += 1
            stats["total"] += 1
            pending_rows.append((dom, rank, res["stage"], res["status"], res.get("reason", "")[:500],
                                 json.dumps(res.get("row"), ensure_ascii=False) if res.get("row") else None,
                                 json.dumps(res.get("detail"), ensure_ascii=False, default=list)[:4000] if res.get("detail") else None,
                                 json.dumps(res.get("hint"), ensure_ascii=False) if res.get("hint") else None,
                                 now(), round(time.monotonic() - ts, 2)))
            if len(pending_rows) >= 200:
                flush()

    async def reporter():
        while True:
            await asyncio.sleep(60)
            flush()
            el = time.time() - t0
            print(f"[w{worker}] {round(el/60,1)}min rate={stats['total']/el*60:.0f}/min {dict(stats)} req={f.stats['requests']} 429={f.stats['http_429']}", flush=True)

    rep = asyncio.create_task(reporter())
    await asyncio.gather(*[consumer() for _ in range(concurrency)])
    rep.cancel()
    flush()
    if redo:
        con.execute("INSERT OR REPLACE INTO meta VALUES(?, ?)", (f"redo_finished:{redo[:80]}", now()))
    else:
        con.execute("INSERT OR REPLACE INTO meta VALUES('finished', ?)", (now(),))
        con.execute("INSERT OR REPLACE INTO meta VALUES('concurrency', ?)", (str(concurrency),))
    con.commit()
    await f.close()
    print(f"[w{worker}] finished {dict(stats)} in {round((time.time()-t0)/60,1)} min", flush=True)


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("--worker", type=int, default=0)
    ap.add_argument("--nworkers", type=int, default=4)
    ap.add_argument("--concurrency", type=int, default=200)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--redo", default="", help="SQL condition on results; re-process matching domains of this worker")
    ap.add_argument("--shopify-rps", type=float, default=0.0, help="global pacing for Shopify-hosted requests (0 = off)")
    a = ap.parse_args()
    try:
        import uvloop
        uvloop.install()
    except ImportError:
        pass
    asyncio.run(main(a.worker, a.nworkers, a.concurrency, a.limit, a.redo, a.shopify_rps))
