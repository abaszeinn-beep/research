"""Market configuration. Every market-specific constant used by the pipeline lives here.

Select the market with the env var ECOM_MARKET (default: qatar). Adding a market = adding a
MarketConfig entry; the rest of the package reads only `M` (the active config).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
WORK_DIR = os.path.dirname(HERE)

ALL_GEO_CODES = ["us", "uk", "gb", "ae", "uae", "eg", "kw", "qa", "bh", "om", "jo", "sa", "ksa", "eu", "intl", "global",
                 "in", "pk", "tr", "fr", "de", "ca", "au", "lb", "iq", "ma", "dz", "tn"]
COUNTRY_WORDS = {"sa": "saudi|saudi-arabia|ksa", "ae": "uae|emirates|united-arab-emirates|dubai", "kw": "kuwait", "qa": "qatar",
                 "bh": "bahrain", "om": "oman", "eg": "egypt", "jo": "jordan", "lb": "lebanon", "iq": "iraq"}


@dataclass
class MarketConfig:
    key: str                      # "qatar"
    prefix: str                   # output prefix, e.g. "Qatar"
    country: str                  # English country name
    country_ar: str
    iso: str                      # ISO-3166 alpha-2, upper ("QA")
    code: str                     # lower-case geo code used in paths/subdomains ("qa")
    path_words: list              # extra path/subdomain words ("qatar")
    tld: str                      # ccTLD without dot ("qa")
    currency: str                 # ISO-4217 ("QAR")
    currency_rx: str              # regex alternatives for the currency symbol/words (used around digits)
    phone_cc: str                 # "974"
    phone_local_rx: str = ""      # optional extra local phone pattern
    cities: list = field(default_factory=list)       # regex alternatives (English + Arabic); places/malls/areas
    pay_ship_rx: str = ""          # local payment / shipping / logistics words
    registration_rx: str = ""      # commercial registration wording
    non_store_suffixes: tuple = ()  # gov/edu suffixes that are never stores
    accept_language: str = "en-US,en;q=0.9,ar;q=0.8"
    itunes_country: str = ""
    ddg_region: str = "wt-wt"
    marketplaces: dict = field(default_factory=dict)
    non_store_roots: set = field(default_factory=set)
    local_platform_names: tuple = ()  # platform names that by themselves indicate this market (e.g. salla/zid for SA)

    # ---------------- derived ----------------
    def __post_init__(self):
        c = self.code
        words = "|".join(self.path_words)
        self.locale_re = re.compile(
            rf"(?:^|[/_.-])(?:en|ar)[-_]{c}(?:$|[/_.-])|/(?:{c}|{words})(?:[-_](?:en|ar))?(?:/|$)|/{c}-(?:en|ar)(?:/|$)|/(?:{words})-(?:en|ar)(?:/|$)",
            re.I)
        self.subdomain_labels = {c, *self.path_words, f"en-{c}", f"ar-{c}", f"{c}-en", f"{c}-ar"}
        others = [g for g in ALL_GEO_CODES if g not in (c, *self.path_words)]
        o = "|".join(others)
        o_cc = "|".join(g for g in others if len(g) == 2)
        other_words = "|".join(v for k, v in COUNTRY_WORDS.items() if k != c)
        self.foreign_geo_re = re.compile(
            rf"^https?://(?:{o})\.|/(?:en|ar)[-_](?:{o_cc})(?:/|$)|/(?:{o})(?:[-_](?:en|ar))?(?:/|$)|/(?:{o_cc})-(?:en|ar)(?:/|$)|/(?:{other_words})-(?:en|ar)(?:/|$)",
            re.I)
        self.market_geo_re = re.compile(
            rf"^https?://(?:{c}|{words}|en-{c}|ar-{c})\.|[/_-](?:en|ar)[-_]{c}\b|/{c}(?:[-_/]|$)|/(?:{words})|\.{self.tld}(?:/|$|:)",
            re.I)
        cur = self.currency_rx
        self.price_rx = re.compile(rf"(?:(?<![\d,.])\d[\d,.]{{0,15}}\s{{0,3}}(?:{cur}))|(?:(?:{cur})\s{{0,3}}\d)", re.I)
        self.currency_code_rx = re.compile(
            rf"[\"'](?:currency|currency_code|currencyCode|priceCurrency|active)[\"']\s*:\s*[\"']{self.currency}[\"']|data-currency=[\"']{self.currency}"
            rf"|Shopify\.currency\s*=\s*\{{[^}}]*{self.currency}|currency={self.currency}|<meta[^>]+(?:product:price:currency|og:price:currency)[^>]+{self.currency}",
            re.I)
        self.phone_rx = re.compile(
            rf"(?:\+|00)\s?{self.phone_cc}[\s\-]?\(?\d|wa\.me/{self.phone_cc}|api\.whatsapp\.com/send\?phone=\+?{self.phone_cc}|tel:\+?{self.phone_cc}"
            + (f"|{self.phone_local_rx}" if self.phone_local_rx else ""))
        self.places_rx = re.compile("|".join(self.cities), re.I)
        self.pay_ship = re.compile(self.pay_ship_rx, re.I) if self.pay_ship_rx else re.compile(r"(?!x)x")
        self.registration = re.compile(self.registration_rx, re.I) if self.registration_rx else re.compile(r"(?!x)x")
        self.hreflang_rx = re.compile(
            rf"(?:lang|hreflang|content)=[\"'](?:ar|en)[-_]{self.iso}[\"']|/(?:en|ar)[-_]{c}/|/{c}[-_](?:en|ar)/|og:locale[\"'][^>]*(?:ar|en)_{self.iso}",
            re.I)
        self.db_path = os.environ.get("ECOM_DB", os.path.join(WORK_DIR, "data", f"{self.key}_ecom.sqlite"))
        self.xlsx = os.path.join(WORK_DIR, f"{self.prefix}_Ecommerce_Master_Directory.xlsx")
        self.csv = os.path.join(WORK_DIR, f"{self.prefix}_Ecommerce_Master_Directory.csv")
        self.ua_research = {"User-Agent": f"{self.key}-ecom-directory-research/1.0 (polite index client)"}

    def is_cctld_host(self, host: str) -> bool:
        host = (host or "").lower().rstrip(".")
        return host == self.tld or host.endswith("." + self.tld)


QATAR_CITIES_EN = [
    r"\bQatar\b", r"\bDoha\b", r"Al[ -]?Rayyan", r"\bRayyan\b", r"Al[ -]?Wakrah", r"\bWakra\b", r"\bLusail\b", r"Al[ -]Khor\b",
    r"Umm[ -]Salal", r"Al[ -]Daayen", r"\bMesaieed\b", r"\bMesaied\b", r"\bDukhan\b", r"Al[ -]Shamal", r"Madinat ash Shamal",
    r"West Bay", r"The Pearl", r"Porto Arabia", r"\bMsheireb\b", r"Al[ -]Sadd\b", r"Al[ -]Gharrafa", r"Salwa Road",
    r"Industrial Area,? Doha", r"\bVillaggio\b", r"Mall of Qatar", r"Place Vend[oô]me", r"Doha Festival City", r"City Cent(?:er|re) Doha",
    r"\bLagoona\b", r"Tawar Mall", r"Hyatt Plaza", r"Gulf Mall", r"Landmark Mall", r"Al[ -]Hilal", r"Abu Hamour", r"Bin Mahmoud",
    r"Al[ -]Sakhama", r"Al[ -]Thumama", r"Old Airport", r"Al[ -]Mansoura", r"Al[ -]Muntazah", r"Al[ -]Waab", r"Ain Khaled",
]
QATAR_CITIES_AR = [
    "دولة قطر", "(?<![\u0600-\u06FF])قطر(?![\u0600-\u06FF])", "الدوحة", "الدوحه", "الريان", "الوكرة", "الوكره", "لوسيل", "الخور",
    "أم صلال", "ام صلال", "الضعاين", "مسيعيد", "الشمال قطر", "اللؤلؤة", "مشيرب", "السد", "الغرافة", "طريق سلوى", "المنطقة الصناعية",
    "فيلاجيو", "مول قطر", "بلاس فاندوم", "دوحة فستيفال سيتي", "سيتي سنتر الدوحة", "لاجونا", "طوار مول", "حياة بلازا", "الخليج مول", "لاندمارك",
]

QATAR = MarketConfig(
    key="qatar", prefix="Qatar", country="Qatar", country_ar="قطر", iso="QA", code="qa", path_words=["qatar"], tld="qa",
    currency="QAR",
    currency_rx=r"\bQAR\b|(?<![\u0600-\u06FF])ر\.?\s?ق\.?(?![\u0600-\u06FF])|ريال قطري|\bQR(?!\s?code)(?=\s?\d)|(?<=\d)\s?QR\b(?!\s?code)|(?<=\d)\s?QRs\b",
    phone_cc="974",
    cities=QATAR_CITIES_EN + QATAR_CITIES_AR,
    pay_ship_rx=r"qatar post|بريد قطر|skip ?cash|\bdibsy\b|\bnaps\b|\bq-?pay\b|ooredoo money|\bQNB\b|\bCBQ\b|doha bank|"
                r"delivery (?:in|across|all over|within) (?:doha|qatar)|deliver(?:y|ing)? to (?:all areas in )?qatar|التوصيل (?:داخل|في|لجميع مناطق) (?:قطر|الدوحة)|توصيل (?:داخل|في) (?:قطر|الدوحة)|"
                r"free (?:shipping|delivery) (?:in|across|within) qatar|ships? (?:to|within) qatar",
    registration_rx=r"(?:C\.?\s?R\.?\s?(?:No|Number|#)|Commercial Registration(?: No| Number)?|CR\s?No|السجل التجاري|سجل تجاري|رقم السجل)\s*[:.#]?\s*\d{4,7}\b",
    non_store_suffixes=(".gov.qa", ".edu.qa", ".sch.qa", ".mil.qa"),
    accept_language="en-QA,en;q=0.9,ar-QA;q=0.8,ar;q=0.7",
    itunes_country="qa",
    ddg_region="xa-en",
    marketplaces={
        "snoonu.com": "Snoonu is a multi-vendor delivery marketplace / aggregator (excluded per brief)",
        "snoonu.qa": "Snoonu is a multi-vendor delivery marketplace / aggregator (excluded per brief)",
        "talabat.com": "talabat is a multi-vendor delivery aggregator (excluded per brief)",
        "noon.com": "noon is a multi-seller marketplace (excluded per brief)",
        "amazon.com": "Amazon is a multi-seller marketplace (excluded per brief)",
        "amazon.ae": "Amazon is a multi-seller marketplace (excluded per brief)",
        "amazon.sa": "Amazon is a multi-seller marketplace (excluded per brief)",
        "qatarliving.com": "Qatar Living is a classifieds portal (excluded per brief)",
        "qsale.qa": "Q-Sale is a classifieds marketplace (excluded per brief)",
        "babqatar.qa": "Bab Qatar is a free classifieds marketplace",
        "dohaads.net": "Doha Ads is a classifieds/advertising marketplace",
        "ddb.qa": "Doha Ads (ddb.qa) is a classifieds/advertising marketplace",
        "yesstyle.com": "YesStyle is a global cross-border store; currency switcher only, no Qatar storefront",
        "qatarsale.com": "Qatar Sale is a classifieds marketplace",
        "mzadqatar.com": "Mzad Qatar is a classifieds / auction marketplace",
        "mzad.qa": "Mzad Qatar is a classifieds / auction marketplace",
        "rafeeq.qa": "Rafeeq is a multi-vendor delivery aggregator",
        "rafeeq.app": "Rafeeq is a multi-vendor delivery aggregator",
        "carriage.com": "delivery aggregator", "deliveroo.com": "delivery aggregator",
        "opensooq.com": "classifieds", "qa.opensooq.com": "classifieds", "dubizzle.com": "classifieds", "dubizzle.qa": "classifieds",
        "aliexpress.com": "marketplace", "temu.com": "marketplace", "ebay.com": "marketplace", "etsy.com": "marketplace",
        "alibaba.com": "B2B marketplace", "trendyol.com": "multi-seller marketplace", "shein.com": None,
        "ubuy.qa": "cross-border marketplace (Ubuy)", "ubuy.com.qa": "cross-border marketplace (Ubuy)", "desertcart.qa": "cross-border marketplace (desertcart)",
        "desertcart.com": "cross-border marketplace (desertcart)", "farfetch.com": "multi-boutique luxury marketplace",
        "souq.com": "defunct marketplace (redirects to amazon)", "tamara.co": "BNPL provider", "tabby.ai": "BNPL provider",
        "fordeal.com": "cross-border marketplace", "joom.com": "marketplace", "wish.com": "marketplace",
        "qatarcars.com": None, "hatla2ee.com": "car classifieds", "yallamotor.com": "car classifieds / listings",
        "propertyfinder.qa": "real estate portal", "olx.com": "classifieds",
    },
    non_store_roots={
        "qatarliving.com", "gulf-times.com", "thepeninsulaqatar.com", "qna.org.qa", "aljazeera.net", "aljazeera.com", "dohanews.co",
        "iloveqatar.net", "marhaba.qa", "qatar-tribune.com", "al-sharq.com", "alraya.com", "lusailnews.net", "alarab.qa",
        "visitqatar.com", "hukoomi.gov.qa", "moci.gov.qa", "qatarairways.com", "qnb.com",
        "qatarpost.qa", "q-tickets.com", "snoonu.com", "talabat.com", "rafeeq.qa", "bayt.com", "indeed.com", "linkedin.com",
        "qatarday.com", "doha.directory", "qatarbusinessdirectory.com", "yellowpages.qa", "qatcom.com", "qatardirectory.com",
    },
    local_platform_names=(),
)

SAUDI = MarketConfig(
    key="saudi", prefix="Saudi_Arabia", country="Saudi Arabia", country_ar="السعودية", iso="SA", code="sa",
    path_words=["ksa", "saudi", "saudi-arabia"], tld="sa", currency="SAR",
    currency_rx=r"ر\.?\s?س|SAR|ريال|﷼|SR\b", phone_cc="966",
    phone_local_rx=r"(?<!\d)05\d[\s\-]?\d{3}[\s\-]?\d{4}(?!\d)|(?<!\d)9200\d{5}(?!\d)",
    cities=[r"Saudi Arabia", r"\bKSA\b", r"\bRiyadh\b", r"\bJeddah\b", "السعودية", "الرياض", "جدة"],
    pay_ship_rx=r"\bmada\b|مدى|stc ?pay|سمسا|\bSMSA\b|البريد السعودي|naqel|aramex|tamara|tabby",
    non_store_suffixes=(".gov.sa", ".edu.sa", ".sch.sa"),
    accept_language="ar-SA,ar;q=0.9,en-US;q=0.8,en;q=0.7", itunes_country="sa", ddg_region="xa-ar",
    marketplaces={"noon.com": "marketplace", "amazon.sa": "marketplace"},
    local_platform_names=("salla", "zid"),
)

MARKETS = {"qatar": QATAR, "saudi": SAUDI}
M: MarketConfig = MARKETS[os.environ.get("ECOM_MARKET", "qatar")]
M.marketplaces = {k: v for k, v in M.marketplaces.items() if v}
