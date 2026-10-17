"""Market configuration. Every market-specific constant used by the pipeline lives here.

Select the market with the MARKET environment variable (default: kuwait). To add a market, add an
entry to MARKETS; the rest of the package reads only the derived values below.
"""
from __future__ import annotations

import os
import re

MARKETS = {
    "kuwait": {
        "name": "Kuwait",
        "prefix": "Kuwait",
        "cc": "KW",
        "iso2": "kw",
        "currency": "KWD",
        # price notations: KWD, KD, د.ك, دينار / دينار كويتي (prices often have 3 decimals, e.g. 12.500 KD)
        "currency_tokens_re": r"KWD|K\.?D\.?(?![a-z])|د\.?\s?ك|دينار(?:\s?كويتي)?|دك(?![\u0600-\u06FF])",
        "phone_re": r"(?:\+|00)\s?965[\s\-]?\(?[124569]\d|wa\.me/965|api\.whatsapp\.com/send\?phone=965|(?<![\d+])(?:965)?[569]\d{3}[\s\-]?\d{4}(?![\d])(?=[^<]{0,40}(?:kuwait|الكويت|whatsapp|واتس))",
        "tlds": ["kw"],
        "locale_labels": {"kw", "kuwait", "en-kw", "ar-kw", "kw-en", "kw-ar", "q8"},
        "accept_language": "ar-KW,ar;q=0.9,en-US;q=0.8,en;q=0.7",
        "places_re": (
            r"دولة الكويت|الكويت|Kuwait|"
            r"العاصمة|حولي|السالمية|الفروانية|الجهراء|الأحمدي|الاحمدي|مبارك الكبير|الفحيحيل|المنقف|الجابرية|الشويخ|الري|"
            r"خيطان|الرقعي|صباح السالم|الفنطاس|المهبولة|السالمي|الشرق|المرقاب|بنيد القار|الرميثية|مشرف|الزهراء|العارضية|"
            r"الأفنيوز|الافنيوز|مجمع 360|الكوت مول|مارينا مول|العاصمة مول|الحمراء|سوق شرق|الخيران|"
            r"\bHawalli\b|\bSalmiya\b|\bFarwaniya\b|\bJahra\b|\bAhmadi\b|Mubarak Al[- ]Kabeer|\bFahaheel\b|\bMangaf\b|\bJabriya\b|"
            r"\bShuwaikh\b|\bAl[- ]Rai\b|\bKhaitan\b|\bRigga[ie]\b|\bSabah Al[- ]Salem\b|\bFintas\b|\bMahboula\b|\bSharq\b|\bMirqab\b|"
            r"\bRumaithiya\b|\bMishref\b|\bArdiya\b|The Avenues|360 Mall|Al Kout Mall|Marina Mall|Assima Mall|Al Hamra|Gate Mall|"
            r"\bMurouj\b|Souq Sharq|Al Khiran"
        ),
        "pay_ship_re": r"\bK-?NET\b|كي ?نت|كي-نت|\bknet\b|Upayments|MyFatoorah|ماي فاتورة|\bTap Payments\b|Deema|ديما|توصيل داخل الكويت|delivery (?:in|across|within) kuwait|kuwait delivery|same[- ]day delivery kuwait|Kuwait Post|بريد الكويت",
        "cities": [
            ("الكويت", "Kuwait City"), ("حولي", "Hawalli"), ("السالمية", "Salmiya"), ("الفروانية", "Farwaniya"),
            ("الجهراء", "Jahra"), ("الأحمدي", "Ahmadi"), ("مبارك الكبير", "Mubarak Al-Kabeer"), ("الفحيحيل", "Fahaheel"),
            ("المنقف", "Mangaf"), ("الجابرية", "Jabriya"), ("الشويخ", "Shuwaikh"), ("الري", "Al Rai"),
        ],
        "malls": ["The Avenues", "360 Mall", "Al Kout Mall", "Marina Mall", "Assima Mall", "Al Hamra Mall", "Gate Mall",
                  "Murouj", "Souq Sharq", "Al Khiran Mall"],
        # global platform hosts where the store is identified by path (Saudi-specific Salla path stores are still read)
        "commerce_platform_country": "KW",
        "gov_suffixes": [".gov.kw", ".edu.kw", ".org.kw", ".net.kw"],
    },
}

MARKET_ID = os.environ.get("MARKET", "kuwait").lower()
M = MARKETS[MARKET_ID]
NAME = M["name"]
PREFIX = M["prefix"]
CC = M["cc"]
ISO2 = M["iso2"]
CURRENCY = M["currency"]
TLDS = M["tlds"]
LOCALE_LABELS = M["locale_labels"]
ACCEPT_LANGUAGE = M["accept_language"]
CITIES = M["cities"]
GOV_SUFFIXES = tuple(M["gov_suffixes"])

_c = ISO2
CUR_TOKENS = M["currency_tokens_re"]
# a price: number + currency token or currency token + number (3-decimal fils notation included)
PRICE_RE = re.compile(rf"(?:\d[\d,.]*\s*(?:{CUR_TOKENS}))|(?:(?:{CUR_TOKENS})\s*\d)", re.I)
CURRENCY_CODE_RE = re.compile(
    rf"[\"'](?:currency|currency_code|currencyCode|priceCurrency|active|shop_currency)[\"']\s*:\s*[\"']{CURRENCY}[\"']|data-currency=[\"']{CURRENCY}|"
    rf"Shopify\.currency\s*=\s*\{{[^}}]*{CURRENCY}|currency={CURRENCY}|<meta[^>]+(?:product:price:currency|og:price:currency)[^>]+{CURRENCY}", re.I)
OTHER_CURRENCIES = [c for c in ["SAR", "AED", "KWD", "QAR", "BHD", "OMR", "USD", "EGP", "JOD", "EUR", "GBP", "MAD", "TRY", "INR", "PKR"] if c != CURRENCY]
OTHER_CURRENCY_CODE_RE = re.compile(
    rf"[\"'](?:currency|currency_code|currencyCode|priceCurrency|active)[\"']\s*:\s*[\"']({'|'.join(OTHER_CURRENCIES)})[\"']", re.I)
PHONE_RE = re.compile(M["phone_re"], re.I)
PLACES_RE = re.compile(M["places_re"], re.I)
PAY_SHIP_RE = re.compile(M["pay_ship_re"], re.I)
LOCALE_HTML_RE = re.compile(
    rf"(?:lang|hreflang|content)=[\"'](?:ar|en)[-_]{_c}[\"']|/(?:en|ar)[-_]{_c}/|/{_c}[-_](?:en|ar)/|og:locale[\"'][^>]*(?:ar|en)_{_c}", re.I)

# Market storefront URL (path or subdomain) and "another country's storefront" URL
MKT_GEO = re.compile(
    rf"^https?://(?:www\.)?(?:{_c}|kuwait|q8|en-{_c}|ar-{_c}|{_c}-en|{_c}-ar)\.|[/_-](?:en|ar)[-_]{_c}\b|/{_c}(?:[-_/]|$)|/kuwait|\.{_c}(?:/|$|:)", re.I)
_others = "|".join(x for x in ["us", "uk", "ae", "uae", "eg", "sa", "ksa", "qa", "bh", "om", "jo", "eu", "intl", "global", "in", "pk", "tr", "fr", "de", "ca", "au", "kw"] if x != _c)
_others2 = "|".join(x for x in ["us", "gb", "ae", "sa", "qa", "bh", "om", "eg", "jo", "in", "kw"] if x != _c)
FOREIGN_GEO = re.compile(
    rf"^https?://(?:{_others})\.|/(?:en|ar)[-_](?:{_others2})(?:/|$)|/(?:{_others2}|uk|uae|ksa|saudi)(?:[-_](?:en|ar))?(?:/|$)|/(?:{_others2})-(?:en|ar)(?:/|$)", re.I)

# identity(): path segments that mark a dedicated market storefront on a multi-country domain
LOCALE_PATH_RE = re.compile(
    rf"(?:^|[/_.-])(?:en|ar)[-_]{_c}(?:$|[/_.-])|/(?:{_c}|kuwait|q8)(?:[-_](?:en|ar))?(?:/|$)|/{_c}-(?:en|ar)(?:/|$)|/kuwait-(?:en|ar)(?:/|$)", re.I)

PATH_VARIANTS = [f"/{_c}/en/", f"/{_c}-en/", f"/en-{_c}/", f"/{_c}/ar/", f"/ar-{_c}/", f"/{_c}-ar/", f"/en_{_c}/", f"/ar_{_c}/",
                 "/kuwait-en/", f"/{_c}_en/", f"/en/{_c}/", f"/{_c}/", "/kuwait/"]
HOST_VARIANTS = [f"{_c}.{{d}}", "kuwait.{d}", f"en-{_c}.{{d}}", "q8.{d}"]
CDX_PREFIXES = [f"{{d}}/{_c}", f"{{d}}/en-{_c}", f"{{d}}/ar-{_c}", f"{_c}.{{d}}/", f"{{d}}/en_{_c}", f"{{d}}/ar_{_c}", "kuwait.{d}/"]


def on_market_tld(host: str) -> bool:
    host = (host or "").lower().rstrip(".")
    return any(host.endswith("." + t) for t in TLDS)
