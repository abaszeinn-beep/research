"""Market configuration. Select with MARKET=<code> (default: uae).

Every market-specific constant used by the pipeline (currency, phone, ccTLD, locale paths, cities,
payment/shipping providers, marketplaces) lives here so the same code can run for another market by
adding one entry to MARKETS.
"""
from __future__ import annotations

import os
import re
from types import SimpleNamespace

AR = "\u0600-\u06FF"

UAE = dict(
    code="uae",
    iso2="AE",
    prefix="UAE",
    name="United Arab Emirates",
    cctld="ae",
    # registrable suffixes under the ccTLD that are not stores
    non_store_suffixes=(".gov.ae", ".ac.ae", ".sch.ae", ".mil.ae", ".edu.ae"),
    accept_language="en-AE,en;q=0.9,ar-AE;q=0.8,ar;q=0.7",
    browser_locale="en-AE",
    timezone="Asia/Dubai",
    itunes_country="ae",
    shopify_country="AE",
    currency="AED",
    # locale path segments / subdomain labels used by multi-country sites for their UAE storefront
    locale_re=r"(?:^|[/_.-])(?:en|ar)[-_]ae(?:$|[/_.-])|/(?:ae|uae|united-arab-emirates)(?:[-_](?:en|ar))?(?:/|$)|/(?:ae|uae)-(?:en|ar)(?:/|$)|/en/ae(?:/|$)|/ar/ae(?:/|$)",
    sub_labels={"ae", "uae", "en-ae", "ar-ae", "ae-en", "ae-ar", "uae-en", "uae-ar"},
    geo_re=r"^https?://(?:ae|uae|en-ae|ar-ae|ae-en|ae-ar)\.|[/_-](?:en|ar)[-_]ae\b|/ae(?:[-_/]|$)|/uae(?:[-_/]|$)|/en/ae\b|/united-arab-emirates|\.ae(?:/|$)",
    foreign_geo_re=(r"^https?://(?:us|uk|sa|ksa|saudi|eg|kw|qa|bh|om|jo|eu|intl|in|pk|tr|fr|de|ca|au|en-sa|ar-sa|kuwait|qatar|bahrain|oman)\."
                    r"|/(?:en|ar)[-_](?:us|gb|sa|kw|qa|bh|om|eg|jo|in)(?:/|$)|/(?:us|uk|sa|ksa|saudi|kw|qa|bh|om|eg|jo|saudi-arabia|kuwait|qatar|bahrain|oman)(?:[-_](?:en|ar))?(?:/|$)"
                    r"|/(?:sa|kw|qa|bh|om|eg)-(?:en|ar)(?:/|$)"),
    path_variants=["/ae-en/", "/en-ae/", "/ae/en/", "/ae/", "/uae/", "/en_ae/", "/ar-ae/", "/ae-ar/", "/ar_ae/", "/uae-en/",
                   "/en/ae/", "/ae_en/", "/uae/en/", "/united-arab-emirates/"],
    host_variants=["ae.{d}", "uae.{d}", "en-ae.{d}", "ae-en.{d}"],
    cdx_prefixes=["{d}/ae", "{d}/en-ae", "{d}/ar-ae", "ae.{d}/", "{d}/en_ae", "uae.{d}/", "{d}/uae"],
    cctld_variants=["{l}.ae", "{l}.co.ae", "{l}uae.com", "{l}-uae.com", "{l}.com.ae"],
    price_re=(r"(?:\d[\d,.]*\s*(?:AED\b|د\.?\s?إ\.?|درهم|Dhs?\b\.?))|(?:(?:\bAED|د\.?\s?إ|\bDhs?\b\.?)\s*\d)"),
    # used on archived pages (raw HTML, tags between symbol and number)
    price_html_re=(r'(?:\bAED|د\.?\s?إ|درهم|\bDhs?\b)(?:\s|&nbsp;|<[^<>]{0,120}>){0,6}\d|\d[\d,.]*(?:\s|&nbsp;|<[^<>]{0,120}>){0,6}(?:AED\b|د\.?\s?إ|درهم|\bDhs?\b)'
                   r'|"(?:priceCurrency|currency|currencyCode|currency_code)"\s*:\s*"AED"'),
    currency_code_re=(r"[\"'](?:currency|currency_code|currencyCode|priceCurrency|active)[\"']\s*:\s*[\"']AED[\"']|data-currency=[\"']AED"
                      r"|Shopify\.currency\s*=\s*\{[^}]*AED|currency=AED|<meta[^>]+(?:product:price:currency|og:price:currency)[^>]+AED"),
    other_currencies=["SAR", "KWD", "QAR", "BHD", "OMR", "USD", "EGP", "JOD", "EUR", "GBP", "MAD", "TRY", "INR", "PKR"],
    other_price_re=(r"(?:\d[\d,.]*\s*(?:SAR|ر\.س|KWD|د\.ك|QAR|ر\.ق|BHD|OMR|USD|EGP|ج\.م|JOD|\$|€|£))|(?:(?:SAR|KWD|QAR|BHD|OMR|USD|EGP|\$|€|£)\s*\d)"),
    phone_strong_re=r"(?:\+|00)\s?971[\s\-]?\(?\d|wa\.me/971|api\.whatsapp\.com/send\?phone=971|tel:\+?971",
    phone_local_re=r"(?<!\d)05[0245689][\s\-]?\d{3}[\s\-]?\d{4}(?!\d)|(?<!\d)0[2-79][\s\-]\d{3}[\s\-]?\d{4}(?!\d)|(?<!\d)600[\s\-]?\d{2}[\s\-]?\d{4}(?!\d)|(?<!\d)800[\s\-]?\d{4,7}(?!\d)",
    vat_re=r"(?:TRN|Tax Registration (?:Number|No)|VAT (?:Reg(?:istration)?\.? )?(?:No|Number)|الرقم الضريبي|رقم التسجيل الضريبي)\.?\s*[:#.\-]?\s*(1\d{14})(?!\d)",
    registration_re=(r"(?:trade licen[cs]e|commercial licen[cs]e|licen[cs]e (?:no|number)|رخصة تجارية|رقم الرخصة)\s*[:.#]?\s*[A-Z0-9\-/]{4,}"
                     r"|\bDMCC\b|Dubai Economy|Department of Economic Development|\bDED\b|free ?zone|المنطقة الحرة|دائرة التنمية الاقتصادية"),
    trust_re=r"\bDubai Economy\b|consumerrights\.ae|tamm\.abudhabi",
    places_re=(r"الإمارات العربية المتحدة|الامارات العربية المتحدة|الإمارات|الامارات|United Arab Emirates|\bU\.?A\.?E\b|"
               r"دبي|أبوظبي|ابوظبي|أبو ظبي|ابو ظبي|الشارقة|عجمان|رأس الخيمة|راس الخيمة|الفجيرة|أم القيوين|ام القيوين|العين|"
               r"\bDubai\b|Abu Dhabi|\bSharjah\b|\bAjman\b|Ras Al[ -]Khaimah|\bRAK\b|\bFujairah\b|Umm Al[ -]Quwain|\bAl Ain\b|"
               r"Dubai Mall|Mall of the Emirates|Yas Mall|Deira|Mirdif|Jumeirah|Dubai Marina|Business Bay|Al Quoz|Jebel Ali|Khalifa City|Mussafah|Al Barsha"),
    pay_ship_re=(r"Emirates Post|بريد الإمارات|aramex|أرامكس|\btabby\b|تابي|\btamara\b|تمارا|Quiqup|Fetchr|Jeebly|Shipa|\bSmsa\b|"
                 r"5% VAT|VAT 5%|ضريبة القيمة المضافة|cash on delivery|الدفع عند الاستلام|same[- ]day delivery|next[- ]day delivery|"
                 r"delivery (?:across|all over|within) (?:the )?UAE|free (?:delivery|shipping) (?:in|across|within) (?:the )?UAE|ship(?:ping)? to (?:the )?UAE"),
    domain_label_re=r"uae|dubai|emirates|abudhabi|sharjah|ajman|alain",
    regional_platforms={"salla", "zid", "expandcart"},
    city_pairs=[("دبي", "Dubai"), ("أبوظبي", "Abu Dhabi"), ("الشارقة", "Sharjah"), ("عجمان", "Ajman"), ("رأس الخيمة", "Ras Al Khaimah"),
                ("الفجيرة", "Fujairah"), ("أم القيوين", "Umm Al Quwain"), ("العين", "Al Ain")],
    marketplaces={
        "noon.com": "noon is a multi-seller marketplace (excluded as aggregator)",
        "amazon.ae": "Amazon.ae is a multi-seller marketplace (excluded as aggregator)",
        "amazon.com": "marketplace", "amazon.sa": "marketplace",
        "dubizzle.com": "Dubizzle is a classifieds site (excluded)", "dubizzle.ae": "classifieds",
        "opensooq.com": "classifieds", "aliexpress.com": "marketplace", "temu.com": "marketplace",
        "ebay.com": "marketplace", "etsy.com": "marketplace", "alibaba.com": "B2B marketplace",
        "souq.com": "defunct marketplace (redirects to amazon)", "trendyol.com": "marketplace",
        "desertcart.ae": "cross-border marketplace", "desertcart.com": "cross-border marketplace",
        "ubuy.ae": "cross-border marketplace", "ubuy.com": "cross-border marketplace",
        "farfetch.com": "multi-boutique luxury marketplace", "tamara.co": "BNPL provider", "tabby.ai": "BNPL provider",
        "instashop.com": "multi-store delivery aggregator", "instashop.ae": "multi-store delivery aggregator",
        "talabat.com": "food/grocery delivery aggregator", "careem.com": "delivery super-app aggregator",
        "deliveroo.ae": "food delivery aggregator", "noonfood.com": "aggregator", "yallamotor.com": "car classifieds",
        "dubicars.com": "car classifieds", "cars24.ae": "used-car marketplace", "carswitch.com": "used-car marketplace",
        "propertyfinder.ae": "property portal", "bayut.com": "property portal",
        "dragonmart.ae": "mall directory / multi-seller", "getthat.com": "multi-seller marketplace",
        "jamalon.com": None, "sharafdg.com": None,
    },
    non_store_roots={
        "gulfnews.com", "khaleejtimes.com", "thenationalnews.com", "emaratalyoum.com", "albayan.ae", "alkhaleej.ae",
        "wam.ae", "u.ae", "aeda.ae", "nic.ae", "tdra.gov.ae", "timeoutdubai.com", "whatson.ae", "zawya.com",
        "arabianbusiness.com", "gulfbusiness.com", "visitdubai.com", "dubaitourism.gov.ae", "yellowpages.ae",
        "yellowpages-uae.com", "connect.ae", "dubaidetails.com", "edarabia.com", "gulftalent.com", "dubizzle.com",
        "bayut.com", "propertyfinder.ae", "rta.ae", "dewa.gov.ae", "emiratesnbd.com", "adcb.com", "mashreq.com",
        "fab.ae", "emirates.com", "etihad.com", "flydubai.com", "dubaiairports.ae", "expo2020dubai.com",
    },
)

MARKETS = {"uae": UAE}


def _load(code: str) -> SimpleNamespace:
    cfg = dict(MARKETS[code])
    cfg["marketplaces"] = {k: v for k, v in cfg["marketplaces"].items() if v}
    m = SimpleNamespace(**cfg)
    m.LOCALE_RE = re.compile(m.locale_re, re.I)
    m.GEO = re.compile(m.geo_re, re.I)
    m.FOREIGN_GEO = re.compile(m.foreign_geo_re, re.I)
    m.tld_suffix = "." + m.cctld
    m.key_suffix = "|" + m.cctld
    return m


M = _load(os.environ.get("MARKET", "uae"))


def on_cctld(host_or_root: str) -> bool:
    h = (host_or_root or "").lower().rstrip(".")
    return h.endswith(M.tld_suffix) and not h.endswith(M.non_store_suffixes)
