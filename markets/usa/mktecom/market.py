"""Market configuration. Every market-specific constant used by the pipeline lives here.

Select a market with the MKT_MARKET environment variable (default: usa). Adding a market means adding
one Market(...) entry; the discovery/verification/export code reads only from `M`.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}
US_METROS = [
    "New York", "Los Angeles", "Chicago", "Houston", "Phoenix", "Philadelphia", "San Antonio", "San Diego",
    "Dallas", "Austin", "Jacksonville", "San Jose", "Fort Worth", "Columbus", "Charlotte", "Indianapolis",
    "San Francisco", "Seattle", "Denver", "Nashville", "Oklahoma City", "Boston", "El Paso", "Portland",
    "Las Vegas", "Detroit", "Memphis", "Louisville", "Baltimore", "Milwaukee", "Albuquerque", "Tucson",
    "Fresno", "Sacramento", "Kansas City", "Atlanta", "Miami", "Raleigh", "Omaha", "Minneapolis", "Tulsa",
    "Cleveland", "Tampa", "Orlando", "New Orleans", "Pittsburgh", "Cincinnati", "St. Louis", "Salt Lake City",
    "Honolulu", "Anchorage", "Boise", "Richmond", "Birmingham", "Buffalo", "Brooklyn", "Charleston",
    "Savannah", "Asheville", "Scottsdale", "Santa Monica", "Burlington", "Providence", "Hartford",
    "Des Moines", "Madison", "Little Rock", "Jackson", "Billings", "Fargo", "Sioux Falls", "Cheyenne",
    "Wilmington", "Manchester", "Portland Maine", "Baton Rouge", "Spokane", "Reno", "Grand Rapids",
]
# Canadian area codes: a +1 number with one of these is Canadian, not US.
CA_AREA_CODES = set(
    "204 226 236 249 250 257 263 289 306 343 354 365 367 368 382 387 403 416 418 428 431 437 438 450 460 468 474 "
    "506 514 519 548 579 581 584 587 600 604 613 622 633 639 644 647 655 672 677 683 688 705 709 742 753 778 780 "
    "782 807 819 825 851 867 873 879 902 905 942".split())
TOLL_FREE = {"800", "833", "844", "855", "866", "877", "888"}


@dataclass
class Market:
    code: str
    prefix: str
    name: str
    currency: str
    accept_language: str
    cctlds: tuple                         # registrable suffixes that imply the market (weak for .us)
    cctld_weight: float
    locale_codes: tuple                   # e.g. en-us, es-us
    locale_path_re: re.Pattern            # dedicated market storefront path on a global domain
    subdomain_labels: set                 # us.brand.com
    price_re: re.Pattern                  # prices in the market currency
    currency_code_re: re.Pattern          # currency code in store config / structured data
    phone_re: re.Pattern
    places_re: re.Pattern
    address_re: re.Pattern
    ship_pay_re: re.Pattern
    foreign_geo_re: re.Pattern            # redirect to another country's storefront
    foreign_cctld_re: re.Pattern
    foreign_place_re: re.Pattern
    other_currencies: tuple
    shopify_country: str
    appstore_country: str
    marketplaces: dict = field(default_factory=dict)
    non_store_roots: set = field(default_factory=set)


_STATE_ABBR = "|".join(US_STATES)
_STATE_NAMES = "|".join(re.escape(v) for v in US_STATES.values())
_METROS = "|".join(re.escape(c) for c in US_METROS)

USA = Market(
    code="usa",
    prefix="USA",
    name="United States",
    currency="USD",
    accept_language="en-US,en;q=0.9,es-US;q=0.6",
    cctlds=("us",),
    cctld_weight=2.0,
    locale_codes=("en-us", "es-us", "en_us", "es_us"),
    locale_path_re=re.compile(r"(?:^|/)(?:en|es)[-_]us(?:/|$)|/us(?:[-_](?:en|es))?(?:/|$)|/usa(?:/|$)|/us-(?:en|es)(?:/|$)|/en/us(?:/|$)", re.I),
    subdomain_labels={"us", "usa", "en-us", "us-en", "shop-us", "store-us", "usshop"},
    price_re=re.compile(r"(?:US\$|USD)\s?\d[\d,]*(?:\.\d{2})?|\d[\d,]*(?:\.\d{2})?\s?(?:USD|US\$)|(?<![A-Za-z$])\$\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?(?![\d,])", re.I),
    currency_code_re=re.compile(
        r"[\"'](?:currency|currency_code|currencyCode|priceCurrency|active|shop_currency|presentmentCurrency)[\"']\s*:\s*[\"']USD[\"']|"
        r"data-currency(?:-code)?=[\"']USD|Shopify\.currency\s*=\s*\{[^}]{0,40}USD|currency=USD|"
        r"<meta[^>]+(?:product:price:currency|og:price:currency)[^>]+USD|itemprop=[\"']priceCurrency[\"'][^>]{0,40}USD", re.I),
    phone_re=re.compile(r"tel:\+?1?[\s.\-]?\(?([2-9]\d{2})\)?[\s.\-]?\d{3}[\s.\-]?\d{4}|(?:\+1[\s.\-]?)?\(([2-9]\d{2})\)\s?\d{3}[\s.\-]\d{4}|(?:\+1[\s.\-])?(?<![\d.])([2-9]\d{2})[.\-]\d{3}[.\-]\d{4}(?![\d.])", re.I),
    places_re=re.compile(rf"\bUnited States\b|\bU\.S\.A\.?|\bUSA\b|\b(?:{_STATE_NAMES})\b|\b(?:{_METROS})\b"),
    address_re=re.compile(rf"\b(?:{_STATE_ABBR}|{_STATE_NAMES})\.?,?\s+\d{{5}}(?:-\d{{4}})?\b"),
    ship_pay_re=re.compile(
        r"free (?:standard )?shipping (?:on|for) (?:all )?(?:U\.?S\.?|domestic|USA) orders|ships? (?:from|within|to) (?:the )?(?:U\.?S\.?A?|United States|contiguous)|"
        r"contiguous (?:U\.?S\.?|United States)|lower 48|continental (?:U\.?S\.?|United States)|\bUSPS\b|UPS Ground|\bFedEx\b|"
        r"sales tax|Made in (?:the )?USA|American[- ]made|free shipping (?:on orders )?over \$\d+|Afterpay|Affirm|Klarna|Sezzle|Shop Pay|"
        r"Venmo|Apple Pay|PayPal|California Proposition 65|Prop(?:osition)? 65|CCPA|Do Not Sell (?:or Share )?My Personal Information", re.I),
    foreign_geo_re=re.compile(
        r"^https?://(?:uk|ca|au|eu|de|fr|it|es|nl|jp|in|mx|br|ae|sa|nz|ie|intl|global|int)\.|"
        r"/(?:en|fr|es|de|it|nl|ja|pt)[-_](?:gb|uk|ca|au|nz|ie|de|fr|it|es|nl|jp|mx|br|in|ae|sa|eu|int)(?:/|$)|"
        r"/(?:uk|gb|ca|au|nz|ie|de|fr|it|es|nl|jp|mx|br|in|ae|eu|int|intl)(?:[-_/](?:en|fr|es|de|it))?(?:/|$)", re.I),
    foreign_cctld_re=re.compile(r"\.(?:ca|co\.uk|uk|com\.au|au|de|fr|it|es|nl|be|ch|at|se|no|dk|fi|ie|nz|co\.nz|jp|in|co\.in|br|com\.br|mx|com\.mx|pl|pt|cz|ru|cn|hk|sg|my|ph|za|co\.za|ae|sa|tr|kr|tw|ar|cl|co|eu)$", re.I),
    foreign_place_re=re.compile(r"\bCanada\b|\b(?:Ontario|Quebec|British Columbia|Alberta|Manitoba|Saskatchewan|Nova Scotia|New Brunswick)\b|\b[ABCEGHJKLMNPRSTVXY]\d[A-Z] \d[A-Z]\d\b|\bUnited Kingdom\b|\bAustralia\b|\bGST\b|\bHST\b"),
    other_currencies=("CAD", "AUD", "GBP", "EUR", "NZD", "INR", "JPY", "MXN", "BRL", "SAR", "AED", "CHF", "SEK", "NOK", "DKK", "PLN", "SGD", "HKD", "ZAR", "PHP", "MYR", "KRW", "CNY", "TRY"),
    shopify_country="US",
    appstore_country="us",
)

# Marketplaces / aggregators excluded per scope (documented in RESUME.md). None = reviewed and kept as a retailer.
USA.marketplaces = {k: v for k, v in {
    "amazon.com": "Amazon is a multi-seller marketplace (brief: excluded; Amazon brand stores are not standalone stores)",
    "ebay.com": "multi-seller marketplace", "etsy.com": "multi-seller marketplace (handmade)",
    "temu.com": "marketplace (third-party sellers, cross-border)", "aliexpress.com": "cross-border marketplace",
    "aliexpress.us": "cross-border marketplace", "alibaba.com": "B2B marketplace",
    "poshmark.com": "peer-to-peer resale marketplace", "mercari.com": "peer-to-peer marketplace",
    "craigslist.org": "classifieds", "offerup.com": "classifieds marketplace", "depop.com": "peer-to-peer marketplace",
    "grailed.com": "peer-to-peer marketplace", "stockx.com": "resale marketplace (bid/ask exchange)",
    "goat.com": "resale marketplace", "reverb.com": "multi-seller marketplace (music gear)",
    "wish.com": "cross-border marketplace", "bonanza.com": "multi-seller marketplace", "ruby lane": None,
    "rubylane.com": "multi-seller marketplace (antiques)", "chairish.com": "multi-seller marketplace (furniture)",
    "1stdibs.com": "multi-dealer marketplace", "faire.com": "B2B wholesale marketplace",
    "houzz.com": "marketplace + services directory", "groupon.com": "deals aggregator",
    "instacart.com": "grocery delivery aggregator (orders from other retailers)", "doordash.com": "delivery aggregator",
    "ubereats.com": "delivery aggregator", "postmates.com": "delivery aggregator", "shipt.com": "delivery aggregator",
    "rakuten.com": "cashback/affiliate aggregator", "shopstyle.com": "affiliate aggregator", "lyst.com": "fashion aggregator",
    "dhgate.com": "cross-border marketplace", "banggood.com": None, "joom.com": "cross-border marketplace",
    "fruugo.us": "cross-border marketplace", "ubuy.com": "cross-border reseller marketplace", "desertcart.us": "cross-border marketplace",
    "tiktok.com": "social commerce platform (TikTok Shop sellers are not standalone stores)",
    "facebook.com": "Facebook Marketplace (classifieds)", "nextdoor.com": "classifieds",
    "letgo.com": "classifieds", "vinted.com": "peer-to-peer marketplace", "tradesy.com": "defunct resale marketplace",
    "vestiairecollective.com": "peer-to-peer luxury resale marketplace", "thredup.com": None, "therealreal.com": None,
    "farfetch.com": "multi-boutique luxury marketplace", "storenvy.com": "multi-seller marketplace",
    "bigcartel.com": None, "zazzle.com": "print-on-demand marketplace (third-party designers)",
    "redbubble.com": "print-on-demand marketplace (third-party artists)", "teepublic.com": "print-on-demand marketplace",
    "spreadshirt.com": "print-on-demand marketplace", "society6.com": "print-on-demand marketplace",
    "cafepress.com": "print-on-demand marketplace", "threadless.com": "print-on-demand marketplace (artist shops)",
    "google.com": "search engine / Google Shopping aggregator", "shopping.google.com": "aggregator",
    "pricegrabber.com": "price comparison", "shopzilla.com": "price comparison", "slickdeals.net": "deals aggregator",
    "dealnews.com": "deals aggregator", "camelcamelcamel.com": "price tracker",
    "wayfair.com": None, "walmart.com": None, "shein.com": None, "newegg.com": None, "target.com": None,
    "overstock.com": None, "bestbuy.com": None, "zulily.com": None, "macys.com": None,
    "carvana.com": "used-car retailer (vehicles; excluded as auto dealer, not a parts/goods store)",
    "cars.com": "car classifieds", "autotrader.com": "car classifieds", "cargurus.com": "car classifieds",
    "carmax.com": "used-car dealer (vehicles)", "zillow.com": "real estate", "turo.com": "car rental marketplace",
    "airbnb.com": "lodging marketplace", "booking.com": "travel", "expedia.com": "travel",
    "stubhub.com": "ticket marketplace", "ticketmaster.com": "tickets (non-physical)", "seatgeek.com": "tickets",
    "fiverr.com": "services marketplace", "upwork.com": "services marketplace", "thumbtack.com": "services marketplace",
    "taskrabbit.com": "services marketplace", "angi.com": "services marketplace",
    "swappa.com": "peer-to-peer marketplace (phones)", "decluttr.com": None, "backmarket.com": "refurbished-electronics marketplace (third-party refurbishers)",
    "discogs.com": "multi-seller marketplace (music)", "abebooks.com": "multi-seller marketplace (books)",
    "biblio.com": "multi-seller marketplace (books)", "alibris.com": "multi-seller marketplace (books)",
    "tcgplayer.com": "multi-seller marketplace (trading cards)", "whatnot.com": "live-auction marketplace",
    "hibid.com": "auction aggregator", "liveauctioneers.com": "auction aggregator", "shopgoodwill.com": "auction marketplace (charity)",
    "govdeals.com": "government auction marketplace", "proxibid.com": "auction marketplace",
    "opensea.io": "digital NFT marketplace",
}.items() if v}

USA.non_store_roots = {
    "google.com", "bing.com", "duckduckgo.com", "yahoo.com", "youtube.com", "facebook.com", "instagram.com",
    "twitter.com", "x.com", "tiktok.com", "snapchat.com", "linkedin.com", "pinterest.com", "wikipedia.org",
    "wikimedia.org", "t.me", "whatsapp.com", "wa.me", "play.google.com", "microsoft.com", "github.com",
    "reddit.com", "quora.com", "medium.com", "blogspot.com", "wordpress.com", "cloudflare.com", "shopify.com",
    "linktr.ee", "bit.ly", "goo.gl", "tinyurl.com", "archive.org", "commoncrawl.org", "trustpilot.com",
    "glassdoor.com", "indeed.com", "zoominfo.com", "crunchbase.com", "dnb.com", "yelp.com", "tripadvisor.com",
    "foursquare.com", "gstatic.com", "googleapis.com", "googletagmanager.com", "doubleclick.net", "amazonaws.com",
    "cloudfront.net", "akamaihd.net", "akamaized.net", "akamai.net", "jsdelivr.net", "cdnjs.com", "w3.org", "schema.org",
    "similarweb.com", "semrush.com", "builtwith.com", "storeleads.app", "myip.ms", "whois.com", "who.is", "crt.sh",
    "myshopify.com", "wix.com", "wixsite.com", "squarespace.com", "bigcommerce.com", "mybigcommerce.com",
    "godaddy.com", "namecheap.com", "sedo.com", "dan.com", "afternic.com", "hugedomains.com", "gov", "edu", "mil",
    "apple.com.cn", "icloud.com", "live.com", "office.com", "outlook.com", "msn.com", "bbc.co.uk", "cnn.com",
    "nytimes.com", "forbes.com", "bloomberg.com", "reuters.com", "wsj.com", "washingtonpost.com", "usatoday.com",
    "bbb.org", "manta.com", "mapquest.com", "yellowpages.com", "superpages.com", "chamberofcommerce.com",
    "fandom.com", "imdb.com", "spotify.com", "netflix.com", "zoom.us", "dropbox.com", "adobe.com", "salesforce.com",
    "oracle.com", "ibm.com", "akamai.com", "fastly.com", "fastly.net", "edgekey.net", "edgesuite.net", "azureedge.net",
    "windows.net", "azure.com", "office365.com", "sharepoint.com", "googleusercontent.com", "ggpht.com", "ytimg.com",
    "fbcdn.net", "twimg.com", "cdninstagram.com", "tiktokcdn.com", "app-measurement.com", "googlesyndication.com",
    "googleadservices.com", "adnxs.com", "criteo.com", "taboola.com", "outbrain.com", "rubiconproject.com",
    "pubmatic.com", "casalemedia.com", "scorecardresearch.com", "quantserve.com", "hotjar.com", "segment.io",
    "segment.com", "mixpanel.com", "amplitude.com", "optimizely.com", "newrelic.com", "nr-data.net", "sentry.io",
    "doubleverify.com", "moatads.com", "bluekai.com", "demdex.net", "omtrdc.net", "2o7.net", "everesttech.net",
    "klaviyo.com", "mailchimp.com", "list-manage.com", "sendgrid.net", "hubspot.com", "hs-scripts.com", "zendesk.com",
    "intercom.io", "stripe.com", "paypal.com", "braintreegateway.com", "affirm.com", "afterpay.com", "klarna.com",
    "yotpo.com", "okendo.io", "judge.me", "stamped.io", "gorgias.chat", "rechargeapps.com", "boldapps.net",
    "shopifycdn.com", "shopifysvc.com", "shopifycloud.com", "shop.app",
}

MARKETS = {"usa": USA}
M: Market = MARKETS[os.environ.get("MKT_MARKET", "usa").lower()]


def area_code_market(code: str) -> str:
    """'US', 'CA' or 'TOLLFREE' for a NANP area code."""
    if code in TOLL_FREE:
        return "TOLLFREE"
    if code in CA_AREA_CODES:
        return "CA"
    return "US"
