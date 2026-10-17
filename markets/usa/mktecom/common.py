"""Shared helpers: URL normalization, store identity keys, constants (market-parameterized)."""
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
    "myshopify.com": "shopify",
    "mybigcommerce.com": "bigcommerce",
    "company.site": "ecwid",
    "ecwid.com": "ecwid",
    "wixsite.com": "wix",
    "square.site": "square",
    "squarespace.com": "squarespace",
    "bigcartel.com": "bigcartel",
    "lightspeedstores.com": "lightspeed",
    "shoplightspeed.com": "lightspeed",
    "odoo.com": "odoo",
    "weebly.com": "weebly",
    "webflow.io": "webflow",
    "volusion.com": "volusion",
    "3dcartstores.com": "shift4shop",
    "shift4shop.com": "shift4shop",
    "corecommerce.com": "corecommerce",
    "storenvy.com": "storenvy",
    "sellfy.store": "sellfy",
    "shopbase.com": "shopbase",
    "onshopbase.com": "shopbase",
    "myshoplaza.com": "shoplazza",
    "shopkeepapp.com": "shopkeep",
    "godaddysites.com": "godaddy",
    "mystrikingly.com": "strikingly",
    "ueniweb.com": "ueni",
    "shopsite.com": "shopsite",
    "squareup.com": "square",
}

SHARED_PATH_PLATFORMS: dict = {}

NON_STORE_ROOTS = set(M.non_store_roots)
MARKETPLACE_ROOTS = dict(M.marketplaces)

LOCALE_RE = M.locale_path_re
MARKET_SUBDOMAIN_LABELS = M.subdomain_labels

TRACKING_PARAMS = re.compile(r"^(utm_|gclid|fbclid|msclkid|yclid|ref|_ga|mc_|srsltid|currency|_pos|_sid|_ss|variant)", re.I)


def registrable_domain(host: str) -> str:
    ext = _TLD(host)
    if ext.domain and ext.suffix:
        return f"{ext.domain}.{ext.suffix}".lower()
    return host.lower()


def clean_host(host: str) -> str:
    host = (host or "").lower().strip(".")
    host = re.sub(r"^www\d?\.", "", host)
    host = re.sub(r"^m\.", "", host)
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
        _ = sp.port
    except ValueError:
        return None
    if not sp.hostname or "." not in sp.hostname:
        return None
    return sp


INFRA_SUBDOMAINS = {
    "mail", "webmail", "cpanel", "whm", "webdisk", "autodiscover", "autoconfig", "ftp", "smtp",
    "pop", "imap", "ns1", "ns2", "ns", "mx", "vpn", "remote", "api", "cdn", "static", "img",
    "images", "media", "assets", "blog", "news", "careers", "jobs", "portal", "lms", "elearning",
    "moodle", "erp", "crm", "hr", "test", "dev", "staging", "demo", "old", "beta", "mta-sts",
    "email", "owa", "sso", "login", "auth", "docs", "help", "support", "status", "track",
    "investors", "investor", "ir", "corporate", "about", "press", "community", "forum", "forums",
}
PLATFORM_RESERVED_SUBS = {"www", "api", "cdn", "app", "web", "help", "docs", "blog", "media", "static", "admin",
                          "partners", "community", "status", "developers", "apps", "themes", "accounts", "checkout"}


def identity(url: str):
    """Return dict(key, url, root_domain, platform_hint) for a candidate URL, or None.

    Shared-platform stores keep the merchant-specific identity (<x>.myshopify.com,
    store-<id>.mybigcommerce.com, <x>.wixsite.com/<site>). Independent sites collapse to the registrable
    domain, except dedicated market storefronts of multi-country brands (us.brand.com or brand.com/en-us),
    which keep the market-specific part.
    """
    sp = parse(url)
    if sp is None:
        return None
    raw_host = (sp.hostname or "").lower().strip(".")
    host = clean_host(raw_host)
    if re.match(r"^\d+\.\d+\.\d+\.\d+$", host):
        return None
    root = registrable_domain(host)
    path = unquote(sp.path or "/")

    for suf, plat in SHARED_SUBDOMAIN_PLATFORMS.items():
        if host.endswith("." + suf):
            sub = host[: -len(suf) - 1]
            if not sub or sub.split(".")[-1] in PLATFORM_RESERVED_SUBS:
                return None
            if suf == "wixsite.com":
                seg = path.strip("/").split("/")[0]
                if not seg:
                    return None
                return {"key": f"{host}/{seg.lower()}", "url": f"https://{host}/{seg}",
                        "root_domain": suf, "platform_hint": plat}
            return {"key": host, "url": f"https://{host}/", "root_domain": suf, "platform_hint": plat}
    if host in SHARED_SUBDOMAIN_PLATFORMS:
        return None

    if root in NON_STORE_ROOTS or host in NON_STORE_ROOTS:
        return None
    suffix = root.split(".", 1)[1] if "." in root else root
    if suffix in {"gov", "edu", "mil"} or re.search(r"\.(?:gov|edu|mil|k12\.[a-z]{2}\.us)$", host):
        return None

    first_label = raw_host.split(".")[0]
    if first_label in MARKET_SUBDOMAIN_LABELS:
        return {"key": host, "url": f"https://{raw_host}/", "root_domain": root, "platform_hint": None}

    if not root.endswith(tuple("." + t for t in M.cctlds)):
        m = LOCALE_RE.search(path + ("/" if not path.endswith("/") else ""))
        if m and m.start() <= 12:
            prefix = path[: m.end()].rstrip("/") + "/"
            return {"key": f"{root}|{M.code}", "url": f"https://{raw_host}{prefix}",
                    "root_domain": root, "platform_hint": None}

    fetch_host = raw_host
    sub = host[: -len(root)].rstrip(".") if host != root else ""
    if sub and (sub.split(".")[-1] in INFRA_SUBDOMAINS or len(sub.split(".")) > 1):
        fetch_host = root
    return {"key": root, "url": f"https://{fetch_host}/", "root_domain": root, "platform_hint": None}


def strip_tracking(url: str) -> str:
    sp = parse(url)
    if sp is None:
        return url
    q = "&".join(p for p in (sp.query or "").split("&") if p and not TRACKING_PARAMS.match(p.split("=")[0]))
    return urlunsplit((sp.scheme.lower(), sp.netloc.lower(), sp.path or "/", q, ""))
