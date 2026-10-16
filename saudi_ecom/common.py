"""Shared helpers: URL normalization, store identity keys, constants."""
from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit, unquote

import tldextract

_TLD = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)  # bundled PSL snapshot, no network

BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ar-SA,ar;q=0.9,en-US;q=0.8,en;q=0.7",
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

# Hosts that are never stores themselves (search engines, social, infra, aggregators...).
NON_STORE_ROOTS = {
    "google.com", "google.com.sa", "bing.com", "duckduckgo.com", "yahoo.com", "youtube.com",
    "facebook.com", "instagram.com", "twitter.com", "x.com", "tiktok.com", "snapchat.com",
    "linkedin.com", "pinterest.com", "wikipedia.org", "wikimedia.org", "t.me", "telegram.me",
    "whatsapp.com", "wa.me", "apple.com", "play.google.com", "microsoft.com", "github.com",
    "reddit.com", "quora.com", "medium.com", "blogspot.com", "wordpress.com", "cloudflare.com",
    "zid.sa", "salla.com", "salla.network", "salla.dev", "shopify.com", "maroof.sa",
    "linktr.ee", "bit.ly", "goo.gl", "tinyurl.com", "archive.org", "commoncrawl.org",
    "trustpilot.com", "glassdoor.com", "indeed.com", "bayt.com", "zoominfo.com",
    "crunchbase.com", "dnb.com", "yelp.com", "tripadvisor.com", "foursquare.com",
    "gstatic.com", "googleapis.com", "googletagmanager.com", "doubleclick.net",
    "amazonaws.com", "cloudfront.net", "akamaihd.net", "jsdelivr.net", "cdnjs.com",
    "w3.org", "schema.org", "gov.sa", "edu.sa", "sch.sa", "zatca.gov.sa", "mc.gov.sa",
    "absher.sa", "spl.com.sa", "argaam.com", "sabq.org", "okaz.com.sa", "aleqt.com",
    "alriyadh.com", "spa.gov.sa", "arabnews.com", "saudigazette.com.sa", "mawdoo3.com",
    "hawaa.com", "sayidaty.net", "almrsal.com", "forbesmiddleeast.com", "zawya.com",
    "wamda.com", "magnitt.com", "similarweb.com", "semrush.com", "builtwith.com",
    "storeleads.app", "storeleads.com", "myip.ms", "whois.com", "who.is", "crt.sh",
    "expandcart.com", "youcan.shop", "wuilt.com", "matjrah.com", "tryzid.com",
    "salla.sa", "salla.store", "zid.store", "myshopify.com", "wix.com", "salla.com.sa", "zid.sa", "matjrah.store", "expandcart.com", "wixsite.com", "squarespace.com",
    "godaddy.com", "namecheap.com", "sedo.com", "dan.com", "afternic.com", "hugedomains.com",
    "nic.sa", "saudinic.net.sa", "stc.com.sa", "mobily.com.sa", "sa.zain.com",
    "careem.com", "hungerstation.com", "jahez.net", "mrsool.co", "talabat.com", "toyou.io",
    "thechefz.co", "ninjaapp.com", "nana.sa", "uber.com",
}

# Marketplaces / aggregators: excluded per scope (documented decision in RESUME.md).
MARKETPLACE_ROOTS = {
    "noon.com": "noon is a multi-seller marketplace (excluded as aggregator)",
    "amazon.sa": "Amazon.sa is a multi-seller marketplace (excluded as aggregator)",
    "amazon.com": "marketplace",
    "aliexpress.com": "marketplace", "temu.com": "marketplace", "haraj.com.sa": "classifieds",
    "opensooq.com": "classifieds", "sa.opensooq.com": "classifieds", "dubizzle.com": "classifieds",
    "ebay.com": "marketplace", "etsy.com": "marketplace", "alibaba.com": "B2B marketplace",
    "souq.com": "defunct marketplace (redirects to amazon)", "trendyol.com": "marketplace",
    "jollychic.com": "defunct", "floward.com": None, "ubuy.com.sa": "cross-border marketplace",
    "desertcart.com.sa": "cross-border marketplace", "desertcart.sa": "cross-border marketplace",
    "sharafdg.com": None, "nahdi.sa": None, "mumzworld.com": None,
    "tamara.co": "BNPL provider", "tabby.ai": "BNPL provider",
}
MARKETPLACE_ROOTS = {k: v for k, v in MARKETPLACE_ROOTS.items() if v}

SAUDI_LOCALE_RE = re.compile(r"(?:^|[/_.-])(?:en|ar)[-_]sa(?:$|[/_.-])|/(?:sa|ksa|saudi|saudi-arabia)(?:[-_](?:en|ar))?(?:/|$)|/sa-(?:en|ar)(?:/|$)|/saudi-(?:en|ar)(?:/|$)", re.I)
SAUDI_SUBDOMAIN_LABELS = {"sa", "ksa", "saudi", "en-sa", "ar-sa", "sa-en", "sa-ar"}

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
    domain, except dedicated Saudi storefronts of multi-country brands (sa.brand.com or
    brand.com/en-sa), which keep the Saudi-specific part.
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

    if host == "apple.com":
        m = SAUDI_LOCALE_RE.search(path + ("/" if not path.endswith("/") else ""))
        if m:
            return {"key": "apple.com|sa", "url": f"https://www.apple.com{path[: m.end()].rstrip('/')}/", "root_domain": root, "platform_hint": None}
    if root in NON_STORE_ROOTS or host in NON_STORE_ROOTS:
        return None
    if root.endswith(".gov.sa") or root.endswith(".edu.sa") or root.endswith(".sch.sa"):
        return None

    first_label = raw_host.split(".")[0]
    if first_label in SAUDI_SUBDOMAIN_LABELS and not root.endswith(".sa"):
        return {"key": host, "url": f"https://{raw_host}/", "root_domain": root, "platform_hint": None}

    if not root.endswith(".sa") or root in {"amazon.sa"}:
        m = SAUDI_LOCALE_RE.search(path + ("/" if not path.endswith("/") else ""))
        if m:
            prefix = path[: m.end()].rstrip("/") + "/"
            return {"key": f"{root}|sa", "url": f"https://{raw_host}{prefix}",
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
