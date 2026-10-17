"""US store identity / URL normalization (platform-aware), reusing the Saudi PSL helpers."""
from __future__ import annotations

import re
from urllib.parse import unquote

from saudi_ecom.common import clean_host, parse, registrable_domain, strip_tracking  # noqa: F401

# Hosting suffix -> platform, where the merchant identity is the subdomain.
SHARED_SUBDOMAIN_PLATFORMS = {
    "mybigcommerce.com": "bigcommerce",
    "bigcartel.com": "bigcartel",
    "square.site": "square",
    "company.site": "ecwid",
    "ecwid.com": "ecwid",
    "wixsite.com": "wix",
    "squarespace.com": "squarespace",
    "3dcartstores.com": "shift4shop",
    "shift4shop.com": "shift4shop",
    "myvolusion.com": "volusion",
    "volusion.store": "volusion",
    "shopwaredemo.de": "shopware",
    "weebly.com": "square",
    "editorx.io": "wix",
    "wix.com": None,
}
SHARED_RESERVED_SUBS = {
    "www", "api", "cdn", "app", "web", "help", "docs", "blog", "media", "static", "admin", "partners", "support",
    "login", "account", "accounts", "status", "developer", "developers", "community", "store", "shop", "my", "dashboard",
    "images", "img", "assets", "mail", "email", "forum", "forums", "news", "careers", "jobs", "go", "info", "en", "es",
}

NON_STORE_ROOTS = {
    "google.com", "bing.com", "duckduckgo.com", "yahoo.com", "youtube.com", "facebook.com", "instagram.com", "twitter.com",
    "x.com", "tiktok.com", "snapchat.com", "linkedin.com", "pinterest.com", "wikipedia.org", "wikimedia.org", "apple.com",
    "microsoft.com", "github.com", "reddit.com", "quora.com", "medium.com", "blogspot.com", "wordpress.com", "wordpress.org",
    "cloudflare.com", "shopify.com", "myshopify.com", "bigcommerce.com", "woocommerce.com", "magento.com", "adobe.com",
    "salesforce.com", "demandware.net", "wix.com", "squarespace.com", "volusion.com", "shift4shop.com", "3dcart.com",
    "prestashop.com", "opencart.com", "ecwid.com", "squareup.com", "square.site", "bigcartel.com", "shopware.com",
    "linktr.ee", "bit.ly", "archive.org", "commoncrawl.org", "trustpilot.com", "yelp.com", "bbb.org", "gstatic.com",
    "googleapis.com", "amazonaws.com", "cloudfront.net", "w3.org", "schema.org", "godaddy.com", "namecheap.com",
    "sedo.com", "dan.com", "afternic.com", "hugedomains.com", "wixsite.com", "weebly.com", "editorx.io", "company.site",
    "mybigcommerce.com", "3dcartstores.com", "storeleads.app", "builtwith.com", "similarweb.com", "paypal.com", "stripe.com",
    "gravatar.com", "jetpack.com", "wp.com", "doubleclick.net", "googletagmanager.com", "jsdelivr.net", "fontawesome.com",
}

MARKETPLACE_ROOTS = {
    "amazon.com": "marketplace", "ebay.com": "marketplace", "etsy.com": "marketplace", "temu.com": "marketplace",
    "aliexpress.com": "marketplace", "aliexpress.us": "marketplace", "alibaba.com": "B2B marketplace",
    "poshmark.com": "marketplace", "mercari.com": "marketplace", "walmart.com": None, "wish.com": "marketplace",
    "shein.com": None, "depop.com": "marketplace", "grailed.com": "marketplace", "stockx.com": "marketplace",
    "goat.com": "marketplace", "reverb.com": "marketplace", "offerup.com": "classifieds", "craigslist.org": "classifieds",
    "faire.com": "wholesale marketplace", "newegg.com": None, "storenvy.com": "marketplace", "redbubble.com": "POD marketplace",
    "teepublic.com": "POD marketplace", "zazzle.com": "POD marketplace", "spreadshirt.com": "POD marketplace",
    "society6.com": "POD marketplace", "cafepress.com": "POD marketplace", "bonanza.com": "marketplace",
    "ruby lane": None, "rubylane.com": "marketplace", "chairish.com": "marketplace", "1stdibs.com": "marketplace",
    "therealreal.com": "consignment marketplace", "thredup.com": "marketplace", "vinted.com": "marketplace",
    "tradesy.com": "marketplace", "houzz.com": "marketplace", "wayfair.com": None, "overstock.com": None,
    "joom.com": "marketplace", "dhgate.com": "marketplace", "banggood.com": None, "fruugo.us": "marketplace",
    "ubuy.com": "cross-border marketplace", "desertcart.com": "cross-border marketplace", "hollar.com": None,
}
MARKETPLACE_ROOTS = {k: v for k, v in MARKETPLACE_ROOTS.items() if v}

US_LOCALE_RE = re.compile(r"(?:^|/)(?:en[-_]us|us[-_]en|us)(?:/|$)", re.I)
US_SUBDOMAIN_LABELS = {"us", "usa", "en-us", "shop-us", "us-shop", "store-us"}
INFRA_SUBDOMAINS = {
    "mail", "webmail", "cpanel", "whm", "webdisk", "autodiscover", "autoconfig", "ftp", "smtp", "pop", "imap", "ns1", "ns2",
    "ns", "mx", "vpn", "remote", "api", "cdn", "static", "img", "images", "media", "assets", "blog", "news", "careers",
    "jobs", "portal", "lms", "erp", "crm", "hr", "test", "dev", "staging", "demo", "old", "beta", "mta-sts", "email", "owa",
    "sso", "login", "auth", "docs", "help", "support", "status", "track", "shop", "store", "secure", "checkout", "m",
    "en", "es", "fr", "de", "ca", "uk", "au", "eu", "intl", "global",
}
NON_US_CCTLD = re.compile(
    r"\.(?:ca|uk|au|nz|ie|de|fr|es|it|nl|be|ch|at|se|no|dk|fi|pl|cz|sk|hu|ro|bg|gr|pt|ru|ua|by|tr|il|in|pk|bd|lk|"
    r"cn|hk|tw|jp|kr|sg|my|id|ph|th|vn|br|ar|cl|co\.za|za|mx|pe|ve|ec|uy|ng|ke|gh|eg|ma|ae|sa|qa|kw|bh|om|ir|kz|lt|lv|ee|"
    r"si|hr|rs|ba|mk|al|is|lu|cy|mt|md|ge|am|az|uz|tn|dz)$")


def identity(url: str):
    """Return dict(key, url, root_domain, platform_hint) or None."""
    sp = parse(url)
    if sp is None:
        return None
    raw_host = (sp.hostname or "").lower().rstrip(".")
    host = clean_host(raw_host)
    if re.match(r"^\d+\.\d+\.\d+\.\d+$", host):
        return None
    path = unquote(sp.path or "/")
    for suf, plat in SHARED_SUBDOMAIN_PLATFORMS.items():
        if host.endswith("." + suf):
            if plat is None:
                return None
            sub = host[: -len(suf) - 1]
            if not sub or sub.split(".")[-1] in SHARED_RESERVED_SUBS:
                return None
            if suf in ("wixsite.com", "editorx.io"):
                seg = path.strip("/").split("/")[0].lower()
                if not seg or seg in ("product-page", "shop", "cart", "category"):
                    return None
                return {"key": f"{host}/{seg}", "url": f"https://{host}/{seg}", "root_domain": suf, "platform_hint": plat}
            return {"key": host, "url": f"https://{host}/", "root_domain": suf, "platform_hint": plat}
    root = registrable_domain(host)
    if root in NON_STORE_ROOTS or host in NON_STORE_ROOTS:
        return None
    if root.endswith((".gov", ".edu", ".mil")) or root in ("gov", "edu"):
        return None
    first = raw_host.split(".")[0]
    if first in US_SUBDOMAIN_LABELS and host != root:
        return {"key": host, "url": f"https://{raw_host}/", "root_domain": root, "platform_hint": None}
    m = US_LOCALE_RE.match(path)
    if m and len(path) > 1:
        prefix = path[: m.end()].rstrip("/") + "/"
        return {"key": f"{root}|us", "url": f"https://{raw_host}{prefix}", "root_domain": root, "platform_hint": None}
    fetch_host = raw_host
    sub = host[: -len(root)].rstrip(".") if host != root else ""
    if sub and (sub.split(".")[-1] in INFRA_SUBDOMAINS or len(sub.split(".")) > 1):
        fetch_host = root
    return {"key": root, "url": f"https://{fetch_host}/", "root_domain": root, "platform_hint": None}
