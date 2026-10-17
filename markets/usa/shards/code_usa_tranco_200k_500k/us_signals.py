"""US-market relevance signals, fast non-retail skip rules and category mapping for the USA shard pipeline.

Signals are grouped so that a single weak hint (for example a bare "$") never verifies a store:
  currency group  USD in store config / API / schema.org, or "$" prices (weak alone)
  location group  US street address with state + ZIP, US phone (non-Canadian area code), Shopify shop
                  country = US, explicit US shipping statement, .us TLD, /us or /en-us storefront path
A verified store needs a currency signal AND a location signal.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from saudi_ecom import signals as S  # noqa: E402

STATES = ("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA "
          "RI SC SD TN TX UT VT VA WA WV WI WY DC PR").split()
STATE_NAMES = ("Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida|Georgia|Hawaii|Idaho|Illinois|"
               "Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|"
               "Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|North Carolina|North Dakota|Ohio|Oklahoma|"
               "Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|"
               "West Virginia|Wisconsin|Wyoming")
US_ADDRESS = re.compile(r"[A-Za-z.]{3,}\s*,?\s+(?:%s|%s)\.?,?\s+(\d{5})(?:-\d{4})?\b" % ("|".join(STATES), STATE_NAMES))
CA_PROVINCES = "ON|QC|BC|AB|MB|SK|NS|NB|NL|PE|YT|NT|NU|Ontario|Quebec|Québec|British Columbia|Alberta|Manitoba|Saskatchewan|Nova Scotia|New Brunswick"
CA_ADDRESS = re.compile(r"\b(?:%s),?\s+[ABCEGHJ-NPRSTVXY]\d[A-Z]\s?\d[A-Z]\d\b" % CA_PROVINCES)

CA_AREA = set("204 226 236 249 250 263 289 306 343 354 365 367 368 382 403 416 418 428 431 437 438 450 468 474 506 514 519 548 "
              "579 581 584 587 604 613 639 647 672 683 705 709 742 753 778 780 782 807 819 825 867 873 879 902 905".split())
CARIB_AREA = set("242 246 264 268 284 345 441 473 649 658 664 721 758 767 784 809 829 849 868 869 876".split())
TOLL_FREE = set("800 833 844 855 866 877 888".split())
PHONE_TEXT = re.compile(r"(?<![\d\w+])(?:\+1[\s.\-]?\(?([2-9]\d{2})\)?[\s.\-]?([2-9]\d{2})[\s.\-]?(\d{4})|\(([2-9]\d{2})\)\s?([2-9]\d{2})[\s.\-](\d{4})|"
                        r"(?:1[\-.])?([2-9]\d{2})([\-.])([2-9]\d{2})\8(\d{4}))(?![\d\w])")
PHONE_TEL = re.compile(r"tel:\s*(?:\+?1)?[\s.\-()]*([2-9]\d{2})[\s.\-()]*([2-9]\d{2})[\s.\-]*(\d{4})\b", re.I)

US_SHIPPING = re.compile(
    r"free (?:standard |ground |economy )?shipping (?:on|for|to|over|in|within|across|throughout) (?:all |any |most )?(?:the )?"
    r"(?:US\b|U\.S\.|USA\b|domestic|contiguous|continental|lower 48|United States)|"
    r"(?:ship|ships|shipping|deliver|delivery|delivers)\s+(?:free\s+)?(?:from|within|to|in|across|throughout)\s+(?:all\s+(?:50\s+states|of\s+the)\s+)?(?:the\s+)?"
    r"(?:US\b|U\.S\.|USA\b|United States|contiguous|continental|lower 48|48 states|50 states)|"
    r"contiguous (?:US\b|U\.S\.|USA|United States|48)|continental (?:US\b|U\.S\.|USA|United States)|lower 48 states|"
    r"free US shipping|free U\.S\. shipping|US orders over|U\.S\. orders over|domestic orders over|"
    r"\bUSPS\b|United States Postal Service|(?:UPS|FedEx) Ground|APO/FPO|APO, FPO", re.I)
MADE_IN_USA = re.compile(r"made in (?:the )?(?:USA|U\.S\.A\.|U\.S\.|United States|America)|american[- ]made|proudly american|veteran[- ]owned", re.I)

USD_CODE = re.compile(
    r"[\"'](?:priceCurrency|currency|currency_code|currencyCode|active|shop_currency|presentment_currency|currency_iso)[\"']\s*:\s*[\"']USD[\"']|"
    r"data-currency(?:-code)?=[\"']USD|currency=USD|<meta[^>]+(?:product:price:currency|og:price:currency)[^>]+USD|"
    r"Shopify\.currency\s*=\s*\{[^}]*\"active\"\s*:\s*\"USD\"|itemprop=[\"']priceCurrency[\"'][^>]*content=[\"']USD", re.I)
OTHER_CODE = re.compile(
    r"[\"'](?:priceCurrency|currency|currency_code|currencyCode|active|shop_currency)[\"']\s*:\s*[\"'](CAD|GBP|EUR|AUD|NZD|INR|JPY|CNY|BRL|MXN|"
    r"CHF|SEK|NOK|DKK|PLN|CZK|RUB|UAH|TRY|ZAR|SGD|HKD|MYR|PHP|IDR|THB|KRW|AED|SAR|ILS|HUF|RON|BGN|CLP|COP|ARS|PEN|VND|TWD|PKR|NGN|EGP|KES)[\"']",
    re.I)
PRICE_USD_TEXT = re.compile(r"(?<![A-Za-z$])(?:US)?\$\s?\d{1,5}(?:,\d{3})*(?:\.\d{2})?(?![\d])|\d[\d,.]*\s?USD\b")
PRICE_FOREIGN_TEXT = re.compile(r"(?:CA\$|C\$|A\$|AU\$|NZ\$|HK\$|S\$|R\$|MX\$|£|€|₹|¥|₽|₩|zł|Kč|kr\b|CHF|R\s?\d)\s?\d|\d[\d.,]*\s?(?:€|£|zł|Kč|₽|руб|грн|kr\b|CHF|CAD|AUD|GBP|EUR)")
CITY_STATE = re.compile(r"(?<!Inc)(?<!LLC)(?<!Ltd)\b([A-Z][a-z]{2,}(?:[ .][A-Z][a-z]+){0,2}),\s(%s)\b(?![\s,]*\d)(?!-)" % "|".join(s for s in STATES if s not in ("IN", "OR", "ME", "OK", "HI", "DE", "PA")))
US_TZ = re.compile(r"\"timezone_string\"\s*:\s*\"((?:America\\?/(?:New_York|Chicago|Denver|Los_Angeles|Phoenix|Anchorage|Detroit|Boise|Indiana\\?/\w+|"
                   r"Kentucky\\?/\w+|North_Dakota\\?/\w+|Adak|Juneau|Sitka|Nome|Yakutat|Metlakatla|Menominee|Puerto_Rico))|Pacific\\?/Honolulu|US\\?/\w+)\"")
GOVERNING_LAW = re.compile(r"laws of the (?:State|Commonwealth) of (%s)\b|\b(%s) (?:limited liability company|corporation|LLC)\b" % (STATE_NAMES, STATE_NAMES))
EN_US = re.compile(r"(?:lang|hreflang)=[\"']en[-_]US[\"']|og:locale[\"'][^>]*en_US", re.I)
US_PATH = re.compile(r"^https?://(?:us|usa|shop-us|us-shop|store-us|en-us)\.|/(?:en[-_]us|us[-_]en|us|usa)(?:/|$)", re.I)


def us_phone(text: str, html: str):
    found = []
    for rx, src in ((PHONE_TEL, html[:800000]), (PHONE_TEXT, text[:200000])):
        for m in rx.finditer(src):
            g = [x for x in m.groups() if x and x not in "-."]
            area, exch = g[0], g[1]
            if area[1] == "9" or area.endswith("11") or exch == "555":
                continue
            found.append((area, m.group(0).strip()))
            if len(found) >= 12:
                break
    us = [p for a, p in found if a not in CA_AREA and a not in CARIB_AREA and a not in TOLL_FREE]
    ca = [p for a, p in found if a in CA_AREA]
    tf = [p for a, p in found if a in TOLL_FREE]
    return us, ca, tf


def us_signals(html: str, text: str, final_url: str, api: dict | None = None):
    """Return (groups, evidence dict, negatives dict). api: platform probe info (country/currency)."""
    api = api or {}
    ev, neg = {}, {}
    cur, loc = [], []
    host = re.sub(r"^https?://", "", final_url).split("/")[0].lower()
    h = html[:800000]
    usd_code = bool(USD_CODE.search(h))
    api_cur = api.get("currency")
    api_curs = set(api_cur if isinstance(api_cur, list) else [api_cur] if api_cur else [])
    if "USD" in api_curs:
        ev["platform_currency"] = "USD"
        cur.append("platform_currency_USD")
    if usd_code:
        ev["usd_currency_code"] = True
        cur.append("usd_code")
    usd_txt = len(PRICE_USD_TEXT.findall(text[:200000]))
    foreign_txt = len(PRICE_FOREIGN_TEXT.findall(text[:200000]))
    if usd_txt:
        ev["usd_prices"] = usd_txt
        if usd_txt >= 2 and usd_txt > foreign_txt:
            cur.append("usd_prices")
    oc = sorted({x.upper() for x in OTHER_CODE.findall(h)})
    if api_curs - {"USD"}:
        oc = sorted(set(oc) | (api_curs - {"USD"}))
    if oc:
        neg["other_currency"] = oc
    if foreign_txt > max(2, usd_txt):
        neg["foreign_price_strings"] = foreign_txt

    country = api.get("country")
    if country:
        ev["platform_shop_country"] = country
        if country == "US":
            loc.append("shop_country_US")
        else:
            neg["shop_country"] = country
    addr = US_ADDRESS.search(text[:300000])
    if addr:
        ev["us_address"] = addr.group(0)[-60:]
        loc.append("us_address")
    ca_addr = CA_ADDRESS.search(text[:300000])
    if ca_addr:
        neg["canada_address"] = ca_addr.group(0)
    if not addr:
        cs = CITY_STATE.search(text[:300000])
        if cs:
            ev["us_city_state"] = cs.group(0)[-40:]
            loc.append("us_city_state")
    gl = GOVERNING_LAW.search(text[:400000])
    if gl:
        ev["us_governing_law"] = gl.group(0)[:60]
        loc.append("us_governing_law")
    if api.get("timezone"):
        ev["store_timezone"] = api["timezone"]
        loc.append("store_timezone_US")
    us_ph, ca_ph, tf = us_phone(text, h)
    if us_ph:
        ev["us_phone"] = us_ph[0][:24]
        loc.append("us_phone")
    if ca_ph:
        neg["canada_phone"] = ca_ph[0][:24]
    if tf:
        ev["nanp_toll_free"] = tf[0][:24]
    ship = US_SHIPPING.findall(text[:300000])
    if ship:
        ev["us_shipping"] = sorted({s.strip() for s in ship})[:3]
        loc.append("us_shipping")
    if host.endswith(".us"):
        ev["us_tld"] = host
        loc.append("us_tld")
    if US_PATH.search(final_url):
        ev["us_storefront_path"] = True
        loc.append("us_path")
    if EN_US.search(h):
        ev["en_us_locale"] = True
    if MADE_IN_USA.search(text[:300000]):
        ev["made_in_usa"] = True
    if host.endswith(".ca"):
        neg["ca_tld"] = host
    if re.search(r"\b(?:CAD|Canadian dollars?)\b", text[:200000]) and not usd_code:
        neg["mentions_cad"] = True
    return {"currency": cur, "location": loc}, ev, neg


def decide_us(groups, ev, neg):
    """Return (status, reason). status in verified|unverified|rejected (US relevance only)."""
    cur, loc = groups["currency"], list(groups["location"])
    country = ev.get("platform_shop_country")
    canada = bool(neg.get("canada_address") or neg.get("ca_tld") or country == "CA" or "CAD" in neg.get("other_currency", []))
    strong_cur = [c for c in cur if c != "usd_prices"]
    weak_loc = {"us_city_state", "store_timezone_US"}
    if not strong_cur and loc and all(x in weak_loc for x in loc):
        loc = []
    if country and country != "US":
        explicit = [x for x in loc if x in ("us_address", "us_phone", "us_shipping", "us_path", "us_tld")]
        if strong_cur and ("us_shipping" in explicit or "us_address" in explicit or "us_phone" in explicit or "us_path" in explicit):
            return "verified", f"non-US-based merchant (shop country={country}) with dedicated US market: USD + {', '.join(explicit)}"
        return "rejected", f"non_us_store (shop country={country}, currency={','.join(neg.get('other_currency', [])) or 'USD display only'})"
    if cur and loc:
        if canada and not ("us_address" in loc or "us_phone" in loc or "shop_country_US" in loc or "us_shipping" in loc):
            return "unverified", "mixed_us_canada_signals (manual review)"
        if not strong_cur and loc == ["us_shipping"] and neg.get("other_currency"):
            return "unverified", "weak_us_signals ($ prices + US shipping but other store currency)"
        return "verified", "ecommerce + US evidence ok"
    if neg.get("other_currency") and not strong_cur:
        return "rejected", f"not_us_relevant (store currency {','.join(neg['other_currency'])})"
    if canada and not loc:
        return "rejected", "canada_store (Canadian address/currency/TLD, no US signals)"
    if neg.get("foreign_price_strings") and not cur:
        return "rejected", "not_us_relevant (non-USD price strings)"
    if cur and not loc:
        return "unverified", "weak_us_signals (USD/$ only, no US address/phone/shipping/country)"
    if loc and not cur:
        return "unverified", "weak_us_signals (US location signals but no USD pricing seen)"
    return "rejected", "no_us_signals"


# ---------- fast non-retail skip (lexical, before any request) ----------
SKIP_TLD_SUFFIX = (".gov", ".mil", ".edu", ".int", ".gov.uk", ".ac.uk", ".nhs.uk", ".police.uk", ".gouv.fr", ".gob.mx", ".gob.es",
                   ".gov.au", ".edu.au", ".gc.ca", ".gov.br", ".edu.br", ".gov.in", ".ac.in", ".edu.cn", ".gov.cn", ".ac.jp", ".go.jp",
                   ".ac.kr", ".go.kr", ".edu.tw", ".gov.tw", ".gov.ru", ".edu.pl", ".gov.pl", ".gv.at", ".ac.at", ".admin.ch",
                   ".bund.de", ".gov.it", ".edu.it", ".k12.ca.us", ".k12.tx.us", ".lib.ca.us", ".state.us", ".fed.us")
SKIP_SUBSTR = re.compile(
    r"cloudfront|akamai|fastly|cloudflare|amazonaws|azureedge|googleapis|gstatic|googlevideo|googleusercontent|ytimg|fbcdn|"
    r"doubleclick|adnxs|adsrv|adserver|criteo|taboola|outbrain|pubmatic|rubiconproject|openx|appnexus|"
    r"porn|xxx|hentai|xvideo|xnxx|xhamster|camgirl|onlyfans|chaturbate|casino|betting|gambl|sportsbook|"
    r"university|universit|dyndns|duckdns|no-ip|ddns", re.I)
SKIP_TOKENS = {"cdn", "api", "apis", "tracking", "tracker", "pixel", "analytics", "metrics", "telemetry", "ads", "adserver",
               "syndication", "beacon", "smtp", "mail", "dns", "ntp", "ocsp", "crl", "pki", "vpn", "proxy", "sex", "nude", "escort",
               "poker", "slots", "bet", "college", "school", "academy", "edu", "gov", "ministry", "police", "council",
               "news", "newspaper", "gazette", "times", "journal", "tribune", "herald", "radio", "tv", "weather",
               "hosting", "webhost", "vps", "server", "registrar"}


def fast_skip(domain: str):
    d = domain.lower()
    for s in SKIP_TLD_SUFFIX:
        if d.endswith(s):
            return f"gov_edu_tld:{s}"
    m = SKIP_SUBSTR.search(d)
    if m:
        return f"non_retail_name:{m.group(0)}"
    labels = d.rsplit(".", 1)[0]
    for tok in re.split(r"[.\-]", labels):
        if tok in SKIP_TOKENS or re.fullmatch(r"(?:cdn|ns|mx|api)\d+", tok):
            return f"non_retail_name:{tok}"
    return None


CATEGORY_MAP = {
    "Perfumes & Oud": "Fragrances",
    "Fashion - Abayas & Modest": "Fashion - Modest",
    "Fashion - Men": "Fashion - Men",
    "Coffee, Tea & Dates": "Coffee & Tea",
    "Religious Products": "Religious & Spiritual Goods",
    "General / Unclassified": "General Merchandise",
    "Department Store / General": "Department Store / General Merchandise",
}
EXTRA_CATEGORIES = [
    ("Firearms, Hunting & Tactical", re.compile(r"\b(?:ammo|ammunition|firearms?|rifles?|pistols?|handguns?|holsters?|tactical gear|optics|scopes?|reloading|airsoft|archery|crossbows?)\b", re.I)),
    ("Vape & Smoke Shop", re.compile(r"\b(?:vape|vapes|e-?liquids?|e-?juice|vaporizers?|cbd|thc|delta[- ]?8|kratom|hemp|glass pipes?|bongs?|rolling papers?|hookah|shisha|cigars?)\b", re.I)),
    ("Wine, Beer & Spirits", re.compile(r"\b(?:wine|wines|winery|bourbon|whiskey|whisky|vodka|tequila|spirits|craft beer|brewery|liquor)\b", re.I)),
    ("Collectibles & Trading Cards", re.compile(r"\b(?:trading cards?|pokemon cards?|sports cards?|collectibles?|funko|comics?|coins? (?:and|&) bullion|bullion|memorabilia)\b", re.I)),
    ("Musical Instruments & Audio", re.compile(r"\b(?:guitars?|bass(?:es)?|drums?|pianos?|keyboards? & synths|synthesizers?|amplifiers?|amps|pedals|ukuleles?|violins?|microphones?|pro audio|speakers?|headphones?|turntables?|vinyl records?)\b", re.I)),
]


def classify(texts, weights):
    cat, sub = S.classify_category(texts, weights)
    blob = " ".join(t[:20000] for t in texts[:4] if t)
    best = None
    for name, rx in EXTRA_CATEGORIES:
        n = len(rx.findall(blob))
        if n >= 4 and (best is None or n > best[1]):
            best = (name, n)
    if best and (cat in ("General / Unclassified", "Department Store / General", "Sports, Fitness & Outdoor", "Pharmacy & Wellness",
                         "Grocery & Food", "Computers & Electronics", "Toys & Hobbies", "Books & Stationery") or best[1] >= 10):
        sub, cat = CATEGORY_MAP.get(cat, cat), best[0]
        return cat, sub
    return CATEGORY_MAP.get(cat, cat), CATEGORY_MAP.get(sub, sub) if sub else ""
