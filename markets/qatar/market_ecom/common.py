"""Shared helpers: URL normalization, store identity keys, constants (market-parameterized via market.M)."""
from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit, unquote

import tldextract

from .market import M

_TLD = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)  # bundled PSL snapshot, no network

BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": M.accept_language,
}

# Shared-platform hosting suffixes where the merchant identity is the subdomain.
SHARED_SUBDOMAIN_PLATFORMS = {
    "zid.store": "zid",
    "myshopify.com": "shopify",
    "expandcart.com": "expandcart",
    "matjrah.store": "matjrah",
    "youcan.shop": "youcan",
    "wuilt.com": "wuilt",
    "company.site": "ecwid",
    "ecwid.com": "ecwid",
    "wixsite.com": "wix",
    "square.site": "square",
    "salla.store": "salla",
    "mvp.zid.store": "zid",
    "bigcartel.com": "bigcartel",
    "storeify.app": "storeify",
    "tryzid.com": "zid",
    "lightspeedstores.com": "lightspeed",
    "odoo.com": "odoo",
    "shopsalla.com": "salla",
    "mybigcommerce.com": "bigcommerce",
    "shoplazza.com": "shoplazza",
    "myshopline.com": "shopline",
    "zammit.shop": "zammit",
    "webflow.io": "webflow",
    "squarespace.com": "squarespace",
}

# Shared hosts where the merchant identity is the first path segment.
SHARED_PATH_PLATFORMS = {"salla.sa": "salla", "s.salla.sa": "salla"}

SALLA_RESERVED = {
    "", "robots.txt", "sitemap.xml", "api", "ar", "en", "login", "register", "apps",
    "partners", "blog", "about", "contact", "pricing", "features", "themes", "help",
    "cdn-cgi", "favicon.ico", "store", "stores", "terms", "privacy", "marketplace",
    "ads.txt", "sellers", "s", ".well-known", "academy", "careers", "developers",
    "dashboard", "panel", "s.salla", "mobile", "app", "plans", "affiliate", "landing",
}

# Hosts that are never stores themselves (search engines, social, infra, platforms, media...).
NON_STORE_ROOTS = {
    "google.com", "bing.com", "duckduckgo.com", "yahoo.com", "youtube.com",
    "facebook.com", "instagram.com", "twitter.com", "x.com", "tiktok.com", "snapchat.com",
    "linkedin.com", "pinterest.com", "wikipedia.org", "wikimedia.org", "t.me", "telegram.me",
    "whatsapp.com", "wa.me", "play.google.com", "microsoft.com", "github.com",
    "reddit.com", "quora.com", "medium.com", "blogspot.com", "wordpress.com", "cloudflare.com",
    "zid.sa", "salla.com", "salla.network", "salla.dev", "shopify.com", "maroof.sa",
    "linktr.ee", "bit.ly", "goo.gl", "tinyurl.com", "archive.org", "commoncrawl.org",
    "trustpilot.com", "glassdoor.com", "indeed.com", "bayt.com", "zoominfo.com",
    "crunchbase.com", "dnb.com", "yelp.com", "tripadvisor.com", "foursquare.com",
    "gstatic.com", "googleapis.com", "googletagmanager.com", "doubleclick.net",
    "amazonaws.com", "cloudfront.net", "akamaihd.net", "jsdelivr.net", "cdnjs.com",
    "w3.org", "schema.org", "mawdoo3.com", "forbesmiddleeast.com", "zawya.com",
    "wamda.com", "magnitt.com", "similarweb.com", "semrush.com", "builtwith.com",
    "storeleads.app", "storeleads.com", "myip.ms", "whois.com", "who.is", "crt.sh",
    "expandcart.com", "youcan.shop", "wuilt.com", "matjrah.com", "tryzid.com",
    "salla.sa", "salla.store", "zid.store", "myshopify.com", "wix.com", "salla.com.sa", "matjrah.store", "wixsite.com", "squarespace.com",
    "godaddy.com", "namecheap.com", "sedo.com", "dan.com", "afternic.com", "hugedomains.com",
    "careem.com", "uber.com", "apps.apple.com", "itunes.apple.com", "bigcommerce.com", "magento.com", "adobe.com",
    "woocommerce.com", "wordpress.org", "opencart.com", "salesforce.com", "webflow.com", "webflow.io",
    "deliveroo.com", "talabat.com", "zomato.com", "glovoapp.com", "trip.com", "booking.com", "expedia.com",
    "wikidata.org", "tranco-list.eu", "duck.com", "startpage.com", "yandex.com", "baidu.com", "naver.com",
    "paypal.com", "stripe.com", "checkout.com", "tabby.ai", "tamara.co", "visa.com", "mastercard.com",
} | M.non_store_roots

MARKETPLACE_ROOTS = dict(M.marketplaces)

MARKET_LOCALE_RE = M.locale_re
MARKET_SUBDOMAIN_LABELS = M.subdomain_labels
MARKET_KEY_SUFFIX = "|" + M.code

TRACKING_PARAMS = re.compile(r"^(utm_|gclid|fbclid|msclkid|yclid|ref|_ga|mc_|srsltid|currency)", re.I)


def registrable_domain(host: str) -> str:
    ext = _TLD(host)
    if ext.domain and ext.suffix:
        return f"{ext.domain}.{ext.suffix}".lower()
    return host.lower()


def clean_host(host: str) -> str:
    host = (host or "").lower().strip().rstrip(".")
    host = host.split("@")[-1].split(":")[0]
    if host.startswith("www.") or re.match(r"^www\d\.", host):
        host = host.split(".", 1)[1]
    return host


def parse(url: str):
    url = (url or "").strip()
    if not url:
        return None
    if url.startswith("//"):
        url = "https:" + url
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    try:
        sp = urlsplit(url)
    except ValueError:
        return None
    if not sp.hostname or "." not in sp.hostname:
        return None
    return sp


def identity(url: str):
    """Return dict(key, url, root_domain, platform_hint) for a candidate URL, or None.

    Shared-platform stores keep the merchant-specific identity (salla.sa/<slug>,
    <slug>.zid.store, <x>.myshopify.com). Independent sites collapse to the registrable
    domain, except dedicated market storefronts of multi-country brands (qa.brand.com or
    brand.com/en-qa), which keep the market-specific part (key `brand.com|qa`, or the host).
    """
    sp = parse(url)
    if sp is None:
        return None
    raw_host = (sp.hostname or "").lower()
    host = clean_host(raw_host)
    if re.match(r"^\d+\.\d+\.\d+\.\d+$", host):
        return None
    root = registrable_domain(host)
    path = unquote(sp.path or "/")

    if host in SHARED_PATH_PLATFORMS:
        seg = path.strip("/").split("/")[0] if path.strip("/") else ""
        seg = seg.strip().lower()
        if seg in SALLA_RESERVED or "." in seg or len(seg) < 2 or len(seg) > 60:
            return None
        if not re.match(r"^[a-z0-9_\-\u0600-\u06ff]+$", seg):
            return None
        return {
            "key": f"salla.sa/{seg}",
            "url": f"https://salla.sa/{seg}",
            "root_domain": "salla.sa",
            "platform_hint": "salla",
        }

    for suf, plat in SHARED_SUBDOMAIN_PLATFORMS.items():
        if host.endswith("." + suf):
            sub = host[: -len(suf) - 1]
            if not sub or sub in {"www", "api", "cdn", "app", "web", "help", "docs", "blog", "media", "static", "admin", "partners"}:
                return None
            if suf == "wixsite.com":
                seg = path.strip("/").split("/")[0]
                if not seg:
                    return None
                return {"key": f"{host}/{seg.lower()}", "url": f"https://{host}/{seg}",
                        "root_domain": suf, "platform_hint": plat}
            return {"key": host, "url": f"https://{host}/", "root_domain": suf, "platform_hint": plat}

    if root in NON_STORE_ROOTS or host in NON_STORE_ROOTS:
        if root == "apple.com":
            m = MARKET_LOCALE_RE.search(path + ("/" if not path.endswith("/") else ""))
            if m:
                return {"key": "apple.com" + MARKET_KEY_SUFFIX, "url": f"https://www.apple.com{path[: m.end()].rstrip('/')}/", "root_domain": root, "platform_hint": None}
        return None
    if any(root.endswith(s) or ("." + root).endswith(s) for s in M.non_store_suffixes):
        return None

    first_label = raw_host.split(".")[0]
    if first_label in MARKET_SUBDOMAIN_LABELS and not M.is_cctld_host(root):
        return {"key": host, "url": f"https://{raw_host}/", "root_domain": root, "platform_hint": None}

    if not M.is_cctld_host(root):
        m = MARKET_LOCALE_RE.search(path + ("/" if not path.endswith("/") else ""))
        if m:
            prefix = path[: m.end()].rstrip("/") + "/"
            return {"key": root + MARKET_KEY_SUFFIX, "url": f"https://{raw_host}{prefix}",
                    "root_domain": root, "platform_hint": None}

    fetch_host = raw_host
    sub = host[: -len(root)].rstrip(".") if host != root else ""
    if sub and (sub.split(".")[-1] in INFRA_SUBDOMAINS or len(sub.split(".")) > 1):
        fetch_host = root
    return {"key": root, "url": f"https://{fetch_host}/", "root_domain": root, "platform_hint": None}


INFRA_SUBDOMAINS = {
    "mail", "webmail", "cpanel", "whm", "webdisk", "autodiscover", "autoconfig", "ftp", "smtp",
    "pop", "imap", "ns1", "ns2", "ns", "mx", "vpn", "remote", "api", "cdn", "static", "img",
    "images", "media", "assets", "blog", "news", "careers", "jobs", "portal", "lms", "elearning",
    "moodle", "erp", "crm", "hr", "test", "dev", "staging", "demo", "old", "beta", "mta-sts",
    "email", "owa", "sso", "login", "auth", "docs", "help", "support", "status", "track",
}


def strip_tracking(url: str) -> str:
    sp = parse(url)
    if sp is None:
        return url
    q = "&".join(p for p in (sp.query or "").split("&") if p and not TRACKING_PARAMS.match(p.split("=")[0]))
    return urlunsplit((sp.scheme.lower(), sp.netloc.lower(), sp.path or "/", q, ""))
