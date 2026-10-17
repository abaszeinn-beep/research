"""US-market page signals: USD, US phone / address / shipping, Canada and other-market markers, categories."""
from __future__ import annotations

import html as htmlmod
import re
from collections import Counter

from saudi_ecom.signals import (  # noqa: F401  (generic, language-neutral helpers)
    PARKED, jsonld_types, meta, store_name, title_of, visible_text,
)

PARKED_TITLE = re.compile(r"coming soon|under construction|^404|not found|parked|for sale|suspended|default page|welcome to nginx|index of /|account suspended|launching soon", re.I)
CLOSED = re.compile(
    r"store is (?:currently )?closed|store (?:is )?(?:temporarily )?(?:unavailable|closed)|this store is unavailable|"
    r"temporarily closed|maintenance mode|we.ll be back soon|be right back|opening soon|password-page|"
    r"enter store using password|this shop is unavailable|shop is currently closed|we are no longer (?:taking|accepting) orders|"
    r"(?:we have|we.ve) (?:permanently )?closed (?:our|the) (?:online )?(?:store|shop|doors)|closing (?:our|the) (?:online )?(?:store|shop) permanently|"
    r"store has been (?:closed|deactivated)|this site (?:is|has been) (?:temporarily )?(?:disabled|deactivated)|site is under maintenance|"
    r"this store does not exist|shop not found|store not found|website (?:has )?expired|this site has been archived",
    re.I,
)

# ------------------------------------------------------------------ platform fingerprints
PLATFORM_MARKERS = [
    ("shopify", re.compile(r"cdn\.shopify\.com|Shopify\.theme|myshopify\.com", re.I)),
    ("salesforce-commerce", re.compile(r"demandware\.static|/on/demandware\.store/|dwanalytics|demandware\.edgesuite", re.I)),
    ("magento", re.compile(r"Magento_|mage/cookies|text/x-magento-init|/static/version\d+/frontend/|Magento_PageCache|mage-cache-storage", re.I)),
    ("bigcommerce", re.compile(r"stencil-utils|BCData|data-stencil|bigcommerce\.com/s-[a-z0-9]+/stencil/|bigcommerce\.com/r-[a-z0-9]+/|mybigcommerce\.com|bigcommerce\.com/s-[a-z0-9]+/templates/", re.I)),
    ("woocommerce", re.compile(r"wp-content/plugins/woocommerce|woocommerce-(?:page|cart|checkout|no-js|js)|wc-block-|wc_add_to_cart_params|/wc/store/|wc-ajax=", re.I)),
    ("wix", re.compile(r"static\.wixstatic\.com|wixstores|wix-ecommerce|_wixCIDX|wix-bolt|X-Wix-|parastorage\.com", re.I)),
    ("squarespace", re.compile(r"static1\.squarespace\.com|squarespace-cdn\.com|Static\.SQUARESPACE_CONTEXT|sqs-add-to-cart|squarespace\.com/universal", re.I)),
    ("volusion", re.compile(r"volusion|/v/vspfiles/|vspfiles/templates", re.I)),
    ("shift4shop", re.compile(r"3dcart|shift4shop|3dcartstores\.com|/assets/templates/.*?3dc|_3dc_", re.I)),
    ("prestashop", re.compile(r"var prestashop\b|prestashop[ =]|/modules/ps_|PrestaShop", re.I)),
    ("opencart", re.compile(r"index\.php\?route=(?:product|common|checkout)|catalog/view/theme|catalog/view/javascript", re.I)),
    ("ecwid", re.compile(r"app\.ecwid\.com|ecwid_|Ecwid\.|ecwid-|xprodcdn|company\.site", re.I)),
    ("square", re.compile(r"square\.site|squareup\.com/|weebly\.com|editmysite\.com|cdn\d*\.editmysite|square-online|sq-online", re.I)),
    ("bigcartel", re.compile(r"bigcartel\.com|assets\.bigcartel|bigcartel", re.I)),
    ("shopware", re.compile(r"shopware|sw-cms|/bundles/storefront/|data-shopware", re.I)),
    ("sap-hybris", re.compile(r"/_ui/responsive|hybris|ACC\.config", re.I)),
    ("vtex", re.compile(r"vteximg|vtex\.(?:com|render)|vtexassets", re.I)),
    ("nopcommerce", re.compile(r"nopcommerce|nop-ajax", re.I)),
    ("lightspeed", re.compile(r"lightspeedhq|webshopapp\.com|seoshop", re.I)),
    ("weebly", re.compile(r"weebly", re.I)),
]
PRECEDENCE = ["shopify", "salesforce-commerce", "magento", "bigcommerce", "volusion", "shift4shop", "bigcartel", "square",
              "squarespace", "wix", "ecwid", "woocommerce", "prestashop", "opencart", "shopware", "sap-hybris", "vtex",
              "lightspeed", "nopcommerce", "weebly"]
HOSTED_HINT = {"mybigcommerce.com": "bigcommerce", "bigcartel.com": "bigcartel", "square.site": "square",
               "company.site": "ecwid", "wixsite.com": "wix", "squarespace.com": "squarespace",
               "3dcartstores.com": "shift4shop", "myvolusion.com": "volusion", "weebly.com": "square"}


def detect_platform(html: str, url: str) -> str:
    h = html[:600000]
    found = {name for name, rx in PLATFORM_MARKERS if rx.search(h)}
    host = re.sub(r"^https?://", "", url).split("/")[0].lower()
    for suf, p in HOSTED_HINT.items():
        if host.endswith("." + suf):
            return p
    # Ecwid/Square embeds inside Wix/WordPress sites: the cart belongs to the embed
    if "ecwid" in found and ("woocommerce" not in found):
        if re.search(r"app\.ecwid\.com/script\.js|Ecwid\.init|xProductBrowser", h):
            return "ecwid"
    for p in PRECEDENCE:
        if p in found:
            if p == "weebly":
                return "square"
            return p
    return "custom/unknown"


# ------------------------------------------------------------------ ecommerce markers
ADD_TO_CART = re.compile(
    r"add[ -_]?to[ -_]?(?:cart|bag|basket)|addtocart|add-to-cart|buy now|single_add_to_cart_button|form-action-addToCart|"
    r"sqs-add-to-cart-button|data-hook=\"add-to-cart\"|product-form__cart|cart/add|\?add-to-cart=|action=\"/cart\.php\"|"
    r"Cart-AddProduct|\"addToCart\"|btn-cart|add_to_cart",
    re.I,
)
CART_CHECKOUT = re.compile(r"/cart\b|/checkout\b|/basket\b|cart\.php|view_cart|shoppingcart\.asp|checkout/cart|Cart-Show|mini-cart|minicart|cart-count|cart_count|cart-qty|cartCount", re.I)
PRODUCT_LINK = re.compile(
    r"href=[\"'](?!data:)([^\"'<>\s]{0,200}?(?:/products?/[^\"'/?#]+|/product-page/[^\"'/?#]+|/[a-z0-9-]+/p/[a-z0-9-]+|_p_\d+\.html|-p/[^\"'/?#]+\.htm|"
    r"productdetails\.asp\?|/catalog/product/view/|route=product/product|id_product=\d+|-p\d{6,}\b|/item/[^\"'/?#]+|"
    r"/shop/[a-z0-9-]+/[a-z0-9-]+/?[\"']|/[a-z0-9-]+-\d{3,}\.html|/p/\d+|/dp/|/pd/)[^\"'<>\s]{0,200})[\"']",
    re.I,
)
PRICE_USD = re.compile(r"(?<![A-Za-z])(?:US\s?\$|USD\s?\$?)\s?\d[\d,]*(?:\.\d{2})?|\d[\d,]*(?:\.\d{2})?\s?USD\b", re.I)
PRICE_DOLLAR = re.compile(r"(?<![A-Za-z\$])\$\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})(?!\d)|(?<![A-Za-z\$])\$\s?\d{1,5}(?![\d.,])")
PRICE_OTHER = re.compile(r"(?:C\$|CA\$|CAD|A\$|AU\$|AUD|NZ\$|NZD|£|€|GBP|EUR|₹|INR|Rs\.?|R\$|MX\$|AED|SAR|¥|JPY|₱|PHP\b|zł|kr\b|CHF)\s?\d|\d[\d,.]*\s?(?:CAD|AUD|NZD|GBP|EUR|INR|zł|kr|€|£|AED|SAR)\b")
CUR_CODE = re.compile(r"[\"'](?:currency|currency_code|currencyCode|priceCurrency|selectedCurrency|defaultCurrency|baseCurrency|shopCurrency|store_currency|default_currency_code)[\"']\s*:\s*[\"']([A-Z]{3})[\"']|"
                      r"(?:product:price:currency|og:price:currency)[\"'][^>]{0,40}content=[\"']([A-Z]{3})|content=[\"']([A-Z]{3})[\"'][^>]{0,40}(?:product:price:currency|og:price:currency)|"
                      r"data-currency(?:-code)?=[\"']([A-Z]{3})|itemprop=[\"']priceCurrency[\"'][^>]{0,40}content=[\"']([A-Z]{3})|content=[\"']([A-Z]{3})[\"'][^>]{0,20}itemprop=[\"']priceCurrency", re.I)

# ------------------------------------------------------------------ US relevance
CA_AREA = set("204 226 236 249 250 257 263 289 306 343 354 365 367 368 382 387 403 416 418 428 431 437 438 450 460 468 474 506 514 519 548 579 581 584 587 600 604 613 639 647 672 683 705 709 742 753 778 780 782 807 819 825 867 873 879 902 905 942".split())
CARIB_AREA = set("242 246 264 268 284 345 441 473 649 658 664 721 758 767 784 809 829 849 868 869 876".split())
TOLLFREE = set("800 833 844 855 866 877 888".split())
PHONE = re.compile(r"(?:tel:\s*)?(?<![\d\-.])(?:\+?1[\s.\-]?)?\(?([2-9]\d{2})\)?[\s.\-]{0,2}([2-9]\d{2})[\s.\-]([0-9]{4})(?![\d\-])")
STATES = ("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC PR").split()
STATE_NAMES = ("Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming")
US_ADDRESS = re.compile(r"[A-Za-z][A-Za-z .'\-]{1,30},?\s+(?:%s|%s)\.?,?\s+(\d{5})(?:-\d{4})?\b" % ("|".join(STATES), STATE_NAMES))
SCHEMA_US = re.compile(r"[\"']addressCountry[\"']\s*:\s*(?:\{[^}]{0,80}[\"']name[\"']\s*:\s*)?[\"'](?:US|USA|United States(?: of America)?)[\"']", re.I)
SCHEMA_OTHER_COUNTRY = re.compile(r"[\"']addressCountry[\"']\s*:\s*[\"'](CA|GB|UK|AU|NZ|IE|IN|DE|FR|NL|ES|IT|PH|ZA|AE|SG|MX|BR|Canada|United Kingdom|Australia|India)[\"']", re.I)
US_SHIP = re.compile(
    r"free (?:standard |ground )?shipping (?:on|for) (?:all )?(?:orders? )?(?:within (?:the )?)?(?:U\.?S\.?A?|United States|domestic|continental|contiguous)|"
    r"(?:ships?|shipping|delivery) (?:from|within|to|across|throughout|anywhere in) (?:the )?(?:U\.?S\.?A?\b|United States|continental U|contiguous U|lower 48|all 50 states)|"
    r"contiguous (?:U\.?S|United States|48)|continental (?:U\.?S|United States)|lower 48|all 50 states|(?:domestic|US|U\.S\.) orders|"
    r"free shipping (?:in|within) the (?:U\.?S|USA|United States)|\bUSPS\b|Priority Mail|made in (?:the )?(?:U\.?S\.?A|America|United States)|"
    r"proudly (?:american|made in)|veteran[- ]owned|family[- ]owned (?:and operated )?(?:in|since)|sales tax|ships? (?:only )?to (?:the )?(?:US|U\.S\.|USA)",
    re.I,
)
CA_WORDS = re.compile(r"\b(?:Ontario|Quebec|Québec|British Columbia|Alberta|Manitoba|Saskatchewan|Nova Scotia|New Brunswick|Newfoundland|Toronto|Vancouver|Montreal|Montréal|Calgary|Edmonton|Ottawa|Winnipeg)\b|\bCanada\b(?:'s)?|ships? (?:from|within) Canada|free shipping (?:in|within|across) Canada")
CA_POSTAL = re.compile(r"\b(?:AB|BC|MB|NB|NL|NS|NT|NU|ON|PE|QC|SK|YT)\.?,?\s+[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z]\s?\d[ABCEGHJ-NPRSTV-Z]\d\b")
OTHER_MARKET_WORDS = re.compile(r"\b(?:United Kingdom|Australia|New Zealand|India|Ireland|Philippines|South Africa|Nigeria|Pakistan|Singapore|Malaysia)\b|\bGST\b|\bVAT\b|\bPost(?:code)\b|Royal Mail|Australia Post|\bNZ Post\b", re.I)
LOCALE_US = re.compile(r"(?:hreflang|lang)=[\"']en-us[\"']|og:locale[\"'][^>]{0,30}content=[\"']en_US", re.I)
LOCALE_OTHER = re.compile(r"(?:<html[^>]+lang)=[\"']((?:en-(?:gb|ca|au|nz|in|ie|za|ph|sg))|(?:fr|de|es|it|nl|pt|pl|sv|da|fi|no|nb|cs|ro|hu|el|tr|ru|uk|ja|zh|ko|ar|he|id|th|vi)(?:[-_][a-z]{2})?)[\"']", re.I)


def phones(html: str):
    us, ca, tf = [], [], []
    for m in PHONE.finditer(html[:800000]):
        area = m.group(1)
        if m.group(2) in ("555",) or area in ("123", "555"):
            continue
        num = f"{area}-{m.group(2)}-{m.group(3)}"
        if area in TOLLFREE:
            tf.append(num)
        elif area in CA_AREA:
            ca.append(num)
        elif area in CARIB_AREA:
            continue
        else:
            us.append(num)
    return us, ca, tf


def currencies(html: str) -> Counter:
    c = Counter()
    for m in CUR_CODE.finditer(html[:1_500_000]):
        code = next((g for g in m.groups() if g), "").upper()
        if code:
            c[code] += 1
    return c


def us_signals(html: str, text: str, final_url: str, api: dict | None = None):
    """Return (score, evidence dict, verdict hint). api may hold platform data: currency, country, weight_unit, timezone."""
    api = api or {}
    ev: dict = {}
    score = 0.0
    host = re.sub(r"^https?://", "", final_url).split("/")[0].lower()
    cur = currencies(html)
    for k in ("currency",):
        v = api.get(k)
        if isinstance(v, (list, set, tuple)):
            for x in v:
                cur[str(x).upper()] += 3
        elif v:
            cur[str(v).upper()] += 3
    usd_code = cur.get("USD", 0)
    other_codes = {k: v for k, v in cur.items() if k not in ("USD",) and len(k) == 3 and k.isalpha()}
    usd_text = len(PRICE_USD.findall(text))
    dollar = len(PRICE_DOLLAR.findall(text))
    other_prices = len(PRICE_OTHER.findall(text))
    if usd_code:
        ev["currency_USD"] = usd_code
        score += 2.5
    if usd_text:
        ev["usd_prices"] = usd_text
        score += 1.5
    if dollar:
        ev["dollar_prices"] = dollar
        score += 1.0 if dollar >= 2 else 0.5
    if other_codes and not usd_code:
        ev["other_currency"] = sorted(other_codes)[:4]
    if other_prices and other_prices > dollar + usd_text:
        ev["other_currency_prices"] = other_prices
    us_ph, ca_ph, tf = phones(html)
    if us_ph:
        ev["us_phone"] = us_ph[0]
        score += 2.0
    if tf:
        ev["toll_free_phone"] = tf[0]
        score += 0.5
    if ca_ph:
        ev["canada_phone"] = ca_ph[0]
    addr = US_ADDRESS.findall(text[:300000])
    if addr:
        m = US_ADDRESS.search(text[:300000])
        ev["us_address"] = m.group(0).strip()[-60:]
        score += 2.5
    if SCHEMA_US.search(html[:800000]):
        ev["schema_country_US"] = True
        score += 2.0
    sc_other = SCHEMA_OTHER_COUNTRY.search(html[:800000])
    if sc_other:
        ev["schema_country_other"] = sc_other.group(1)
    ship = US_SHIP.findall(text[:400000])
    if ship:
        ev["us_shipping_or_origin"] = sorted({s.strip()[:40] for s in ship})[:3]
        score += 1.5 if len(set(ship)) >= 2 else 1.0
    if host.endswith(".us"):
        ev["us_tld"] = True
        score += 2.0
    if re.search(r"/en[-_]us(?:/|$)|^https?://(?:us|usa)\.", final_url, re.I):
        ev["us_locale_path"] = True
        score += 1.5
    if LOCALE_US.search(html[:200000]):
        ev["en_us_locale"] = True
        score += 0.25
    lo = LOCALE_OTHER.search(html[:5000])
    if lo:
        ev["html_lang"] = lo.group(1)
    for k in ("country", "weight_unit", "timezone"):
        if api.get(k):
            ev["platform_" + k] = api[k]
    if api.get("country") in ("US", "USA", "United States"):
        score += 3.0
    elif api.get("country"):
        score -= 2.0
    if str(api.get("weight_unit", "")).lower() in ("lbs", "lb", "oz", "pounds"):
        score += 0.5
    if str(api.get("timezone", "")).startswith(("America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles", "America/Phoenix", "America/Anchorage", "Pacific/Honolulu", "America/Detroit", "America/Indiana", "America/Kentucky", "US/")):
        ev["us_timezone"] = api["timezone"]
        score += 1.0
    ca_words = len(CA_WORDS.findall(text[:300000]))
    ca_post = CA_POSTAL.findall(text[:300000])
    if ca_post:
        ev["canada_address"] = True
    if ca_words >= 3:
        ev["canada_mentions"] = ca_words
    return score, ev


def us_verdict(score: float, ev: dict):
    """Return (status, reason) for US relevance only."""
    usd = bool(ev.get("currency_USD") or ev.get("usd_prices"))
    dollar = usd or bool(ev.get("dollar_prices"))
    location = [k for k in ("us_phone", "us_address", "schema_country_US", "us_shipping_or_origin", "us_tld", "us_locale_path", "us_timezone") if ev.get(k)]
    if ev.get("platform_country") in ("US", "USA", "United States"):
        location.append("platform_country")
    canada = bool(ev.get("canada_address") or (ev.get("canada_phone") and not ev.get("us_phone")) or
                  ev.get("platform_country") in ("CA", "Canada") or ev.get("schema_country_other") in ("CA", "Canada"))
    other = ev.get("other_currency") and not usd
    if other and ("CAD" in ev["other_currency"]):
        return "rejected", "canadian_store (CAD currency)"
    if other:
        return "rejected", f"non_us_currency ({','.join(ev['other_currency'])})"
    pc = ev.get("platform_country")
    if pc and pc not in ("US", "USA", "United States") and not (ev.get("us_address") or ev.get("us_phone") or ev.get("schema_country_US")):
        if pc in ("CA", "Canada"):
            return "rejected", "canadian_store (platform country CA)"
        return "rejected", f"non_us_store (platform country {pc})"
    if ev.get("other_currency_prices") and not usd and not ev.get("dollar_prices"):
        return "rejected", "non_us_prices"
    if canada and not (ev.get("us_address") or ev.get("us_phone") or ev.get("schema_country_US") or ev.get("platform_country") in ("US",)):
        if ev.get("us_shipping_or_origin") and usd:
            return "unverified", "canada_and_us_mixed_signals (manual review)"
        return "rejected", "canadian_store (Canadian address/phone/platform country, no US location)"
    if dollar and location and score >= 4:
        return "verified", "usd+us_location: " + ",".join(location)
    if dollar and location:
        return "unverified", f"weak_us_signals (score={score:.1f})"
    if dollar:
        return "unverified", "dollar_prices_but_no_us_location_signal"
    if location and score >= 3.5:
        return "unverified", "us_location_but_no_price_currency_seen"
    return "rejected" if score < 1 else "unverified", f"insufficient_us_signals (score={score:.1f})"


# ------------------------------------------------------------------ exclusions
DIGITAL = re.compile(r"\b(?:e-?books?|pdf|printables?|digital (?:download|product|file|pattern|art|planner|template)s?|instant download|svg files?|"
                     r"presets?|lightroom|procreate|templates?|courses?|masterclass|webinar|e-?course|online class(?:es)?|membership|subscription box|"
                     r"gift cards?|e-?gift|license key|software|plugin|wordpress theme|stock photos?|fonts?|mp3|beats?|sample packs?|audiobook)\b", re.I)
SERVICE = re.compile(r"\b(?:book (?:an |your )?(?:appointment|session|consultation|now)|appointments?|consultations?|coaching|therapy|counseling|"
                     r"treatments?|facials?|peels?|microneedling|waxing|botox|fillers?|readings?|sessions?|access|deposit|bookings?|admissions?|"
                     r"registrations?|tuition|daycare|childcare|camp|retreat|"
                     r"massage|facials?|lash extensions?|haircuts?|salon|spa services|tattoo|cleaning services?|lawn care|plumbing services|"
                     r"repair services?|tutoring|lessons?|classes|workshops?|tickets?|admission|registration|tuition|donations?|donate|"
                     r"sponsorship|membership dues|photography sessions?|rentals?|reservations?|catering|events? booking)\b", re.I)
RESTAURANT = re.compile(r"\b(?:order online for pickup|online ordering|order for pickup|pickup or delivery|curbside pickup|our menu|view menu|full menu|"
                        r"dine[- ]in|takeout|take-out|appetizers|entrees|entrées|burgers?|pizza|tacos|sandwiches|wings|brunch|happy hour|"
                        r"catering menu|restaurant|bar & grill|grill|bistro|cafe|café|food truck|doordash|grubhub|ubereats|uber eats)\b", re.I)
ORG_NAME = re.compile(r"\b(?:church|ministr(?:y|ies)|school|university|college|academy|district|county|city of|foundation|association|society|"
                      r"club|league|union|chamber|hospital|clinic|dental|dentist|chiropractic|law (?:firm|office)|attorneys?|realty|real estate|"
                      r"insurance|consulting|agency|marketing|church|temple|synagogue|mosque|pta|booster|scouts?|museum|library|theatre|theater|"
                      r"festival|conference|summit|charity|non-?profit|rescue|shelter)\b", re.I)
FOOD_NAME = re.compile(r"\b(?:catering|caterers?|bbq|barbecue|bar-?b-?que|grill|kitchen|cafe|café|eats|eatery|bistro|pizzeria|pizza|taqueria|tacos|diner|"
                       r"deli|restaurant|smokehouse|food truck|burgers?|wings|sushi|ramen|noodles?|brunch|juice bar|coffee house|coffeehouse|tavern|pub|saloon|cantina)\b", re.I)
MARKETPLACE_TEXT = re.compile(r"\b(?:sell on our marketplace|become a (?:seller|vendor)|vendor dashboard|multi-?vendor|sold by (?:third[- ]party )?sellers)\b", re.I)

# ------------------------------------------------------------------ categories (physical-product industries)
CATEGORIES = [
    ("Apparel & Fashion", r"apparel|clothing|clothes|t-?shirts?|tees|shirts?|hoodies?|sweatshirts?|dress(?:es)?|leggings|jeans|pants|jackets?|outerwear|boutique|fashion|womens?wear|menswear|lingerie|swimwear|activewear|athleisure|socks|hats?|caps|beanies|uniforms?|scrubs"),
    ("Shoes & Footwear", r"shoes|footwear|sneakers|boots|sandals|heels|slippers|loafers"),
    ("Jewelry & Watches", r"jewel(?:ry|lery)|necklaces?|bracelets?|earrings?|rings?|pendants?|charms?|diamonds?|gold|sterling silver|watches|wristwatch(?:es)?|gemstones?|beads?"),
    ("Bags & Accessories", r"handbags?|purses?|totes?|backpacks?|wallets?|luggage|belts?|sunglasses|eyewear|scarves|keychains?|accessories"),
    ("Beauty & Cosmetics", r"beauty|cosmetics?|makeup|skin ?care|skincare|serums?|moisturi[sz]ers?|lipsticks?|lip gloss|lashes|nails?|nail polish|fragrances?|perfumes?|cologne|soaps?|bath bombs?|body butter|lotions?"),
    ("Health & Wellness", r"supplements?|vitamins?|protein|nutrition|wellness|cbd|hemp|kratom|herbal|herbs|essential oils?|probiotics?|collagen|keto|medical supplies|mobility|first aid|hearing aids?|pharmacy"),
    ("Home & Garden", r"home decor|decor|furniture|rugs?|curtains|pillows?|bedding|sheets|towels|candles?|wall art|mirrors?|lighting|lamps?|garden|gardening|plants?|seeds?|planters?|patio|outdoor furniture|kitchenware|cookware|bakeware|tableware|mugs?|tumblers?|cutting boards?|knives"),
    ("Food & Beverage", r"coffee|tea|spices?|sauces?|hot sauce|bbq|jerky|snacks?|candy|chocolates?|cookies|baked goods|honey|maple syrup|jams?|olive oil|gourmet|wine|wines|beer|spirits|bourbon|whiskey|meats?|seafood|cheese|popcorn|nuts|seasonings?|baking mix(?:es)?|gift baskets?"),
    ("Pets", r"pets?|dogs?|cats?|puppy|kitten|pet supplies|dog treats|cat toys|collars?|leashes|aquariums?|aquatics?|fish|reptiles?|birds?|horses?|equine|tack"),
    ("Sports & Outdoors", r"sports?|fitness|gym|workout|yoga|golf|tennis|pickleball|baseball|softball|basketball|football|soccer|hockey|lacrosse|volleyball|cycling|bikes?|bicycles?|camping|hiking|outdoor gear|fishing|tackle|lures?|hunting|archery|kayaks?|paddle|surf|skate|snowboard|ski|climbing|martial arts|boxing"),
    ("Firearms & Tactical", r"firearms?|guns?|ammo|ammunition|holsters?|tactical|optics|scopes?|rifles?|pistols?|knives|ar-?15|reloading|gun parts"),
    ("Automotive & Powersports", r"auto parts|car parts|truck parts|automotive|vehicles?|jeep|offroad|off-road|exhaust|wheels|tires|motorcycle|atv|utv|powersports|car care|detailing|trailer|towing|diesel|performance parts|marine parts|boat"),
    ("Electronics & Computers", r"electronics|computers?|laptops?|tablets?|phones?|phone cases?|chargers?|cables|headphones|speakers|audio|cameras?|drones?|gaming|video games?|consoles?|smart home|security cameras?|batteries|led|solar|radios?|ham radio"),
    ("Tools, Hardware & Industrial", r"tools?|hardware|fasteners|bolts|screws|power tools|hand tools|industrial|machinery|equipment|welding|hydraulics?|pneumatic|plumbing|electrical supplies|hvac|safety supplies|ppe|janitorial|abrasives|bearings|valves|pumps?|generators?"),
    ("Toys, Games & Hobbies", r"toys?|games?|board games|puzzles?|dolls?|plush|lego|action figures?|collectibles?|trading cards?|pokemon|comics?|models?|model trains|rc|hobby|hobbies|miniatures|dice|tabletop|crafts?"),
    ("Arts, Crafts & Sewing", r"art supplies|paints?|canvas|yarn|knitting|crochet|fabric|quilting|sewing|embroidery|vinyl|stickers?|stamps?|scrapbooking|beading|resin|pottery|ceramics?|handmade|stained glass"),
    ("Baby & Kids", r"baby|babies|infant|toddler|kids|children|nursery|maternity|diapers?|strollers?"),
    ("Books, Music & Media", r"books?|bookstore|novels?|bibles?|records?|vinyl records|cds?|dvds?|music|instruments?|guitars?|drums|pianos?|sheet music|magazines?"),
    ("Office & School Supplies", r"office supplies|stationery|paper|notebooks?|planners?|pens?|ink|toner|printing|labels|school supplies|envelopes|greeting cards|cards"),
    ("Party, Gifts & Flowers", r"gifts?|gift shop|personalized|custom gifts|party supplies|balloons|flowers?|florist|bouquets?|wedding|bridal|favors|seasonal|christmas|halloween|holiday decor|ornaments?"),
    ("Religious & Spiritual", r"christian|catholic|rosar(?:y|ies)|crosses?|spiritual|crystals?|tarot|metaphysical|incense|sage|judaica"),
    ("Agriculture & Farm", r"farm|ranch|livestock|feed|poultry|chickens?|cattle|tractor|agricultur(?:e|al)|irrigation|beekeeping|hydroponics?|grow lights?"),
    ("Vape & Smoke", r"vapes?|vaporizers?|e-?liquids?|e-?juice|smoke shop|glass pipes?|bongs?|hookahs?|cigars?|tobacco|rolling papers"),
    ("Building & Home Improvement", r"flooring|tiles?|cabinets?|countertops?|doors|windows|roofing|lumber|building materials|paint|faucets?|sinks?|bathroom fixtures|home improvement|fireplaces?|stoves?|grills?|smokers?|appliances?|water filters?|filtration"),
    ("Medical & Lab Supplies", r"medical (?:supplies|equipment|devices)|lab supplies|laboratory|scientific|dental supplies|veterinary supplies|diagnostic|surgical|chemicals?"),
    ("Packaging & Business Supplies", r"packaging|boxes|mailers|shipping supplies|bags wholesale|labels|signs?|banners|displays?|restaurant supplies|retail supplies|wholesale"),
]
CATEGORY_RES = [(n, re.compile(r"\b(?:%s)\b" % rx, re.I)) for n, rx in CATEGORIES]


def classify(texts, weights):
    acc = Counter()
    for t, w in zip(texts, weights):
        if not t:
            continue
        t = t[:30000]
        for name, rx in CATEGORY_RES:
            n = len(rx.findall(t))
            if n:
                acc[name] += w * min(n, 20)
    if not acc:
        return "General Merchandise"
    return acc.most_common(1)[0][0]


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", htmlmod.unescape(s or "")).strip()
