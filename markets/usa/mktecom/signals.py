"""Page analysis: parked/closed detection, platform, ecommerce, market relevance, category (market-parameterized)."""
from __future__ import annotations

import html as htmlmod
import re
from collections import Counter

from .market import M, area_code_market

PARKED = re.compile(
    r"domain (?:name )?(?:is|may be) for sale|buy this domain|this domain is for sale|"
    r"parked (?:free|domain)|sedoparking|parkingcrew|bodis\.com|hugedomains|dan\.com/|afternic|"
    r"domain has expired|this domain has expired|renew (?:this|your) domain|"
    r"account (?:has been )?suspended|this account has been suspended|website (?:is )?expired|"
    r"welcome to nginx|apache2? (?:ubuntu |debian )?default page|it works!|"
    r"index of /|default web site page|future home of something quite cool|"
    r"web hosting by|under construction|"
    r"site not found|no such app|there is nothing here|domain not configured|"
    r"this site can.t be reached",
    re.I,
)
PARKED_TITLE = re.compile(r"coming soon|under construction|404|not found|parked|for sale|suspended|default page|welcome to nginx|index of", re.I)
CLOSED = re.compile(
    r"store is (?:currently )?closed|"
    r"store (?:is )?(?:temporarily )?unavailable|this store is unavailable|store unavailable|"
    r"temporarily closed|maintenance mode|we.ll be back soon|"
    r"opening soon|password-page|enter store using password|"
    r"this shop is unavailable|sorry, this shop is currently unavailable|we are (?:permanently )?closed|"
    r"no longer (?:accepting|taking) (?:online )?orders|has closed (?:its|our) (?:online )?(?:store|doors)|"
    r"going out of business|ceased operations",
    re.I,
)

PLATFORM_MARKERS = [
    ("shopify", re.compile(r"cdn\.shopify\.com|Shopify\.theme|shopify-section|myshopify\.com", re.I)),
    ("woocommerce", re.compile(r"woocommerce|wc-ajax|wp-content/plugins/woocommerce|wc-block", re.I)),
    ("magento", re.compile(r"Magento_|mage/cookies|text/x-magento-init|/static/version\d+/frontend/", re.I)),
    ("salesforce-commerce", re.compile(r"demandware|/on/demandware\.store|dwanalytics|/dw/image/|sfcc-", re.I)),
    ("sap-hybris", re.compile(r"/_ui/responsive|hybris|ACC\.config", re.I)),
    ("bigcommerce", re.compile(r"bigcommerce\.com|cdn\d*\.bigcommerce|stencil-utils|mybigcommerce\.com", re.I)),
    ("opencart", re.compile(r"index\.php\?route=(?:product|common|checkout)|catalog/view/theme", re.I)),
    ("prestashop", re.compile(r"prestashop|/modules/ps_|var prestashop", re.I)),
    ("wix", re.compile(r"wixstores|static\.wixstatic\.com|wix-ecommerce|_wixCIDX|wix-thunderbolt", re.I)),
    ("squarespace", re.compile(r"static1\.squarespace\.com|squarespace-cdn|Static\.SQUARESPACE_CONTEXT|sqs-block", re.I)),
    ("ecwid", re.compile(r"app\.ecwid\.com|ecwid_|Ecwid\.", re.I)),
    ("volusion", re.compile(r"volusion|/v/vspfiles/", re.I)),
    ("shift4shop", re.compile(r"3dcart|shift4shop|3dcartstores", re.I)),
    ("bigcartel", re.compile(r"bigcartel", re.I)),
    ("square", re.compile(r"square\.site|squarecdn|weebly-|editmysite\.com", re.I)),
    ("lightspeed", re.compile(r"lightspeed|seoshop|shoplightspeed", re.I)),
    ("vtex", re.compile(r"vtex\.|vteximg|vtexassets", re.I)),
    ("nopcommerce", re.compile(r"nopcommerce", re.I)),
    ("odoo", re.compile(r"website_sale|/web/assets/\d", re.I)),
    ("commercetools", re.compile(r"commercetools", re.I)),
    ("oracle-commerce", re.compile(r"oracle commerce|/atg/|occ-|cx-cloud", re.I)),
    ("miva", re.compile(r"mivamerchant|/mm5/merchant\.mvc", re.I)),
    ("zen-cart", re.compile(r"zen ?cart|index\.php\?main_page=", re.I)),
    ("ekm", re.compile(r"ekmpowershop", re.I)),
]

ADD_TO_CART = re.compile(
    r"add[ -_]?to[ -_]?(?:cart|bag|basket)|addtocart|add-to-cart|buy now|shop now|añadir al carrito|agregar al carrito|"
    r"data-product-id|product-form|cart/add|\?add-to-cart=",
    re.I,
)
CART_CHECKOUT = re.compile(r"/cart\b|/checkout\b|/basket\b|shopping cart|shopping bag|checkout|mini-cart|cart-count|cart_count|carrito", re.I)
PRODUCT_LINK = re.compile(
    r"href=[\"'](?!data:)[^\"'<>\s]{0,200}?(?:/products?/[^\"'/?#]+|/p\d{5,}|/p/[^\"'/?#]+|-p-\d+|/item/[^\"'/?#]+|/dp/|/ip/|"
    r"product_id=\d+|route=product/product|/product-page/|/[a-z0-9-]+-\d{4,}\.html|/buy-[^\"'/?#]+|/pd/|/sku/|/prod\d+)[^\"'<>\s]{0,200}[\"']",
    re.I,
)
PRICE_LOCAL = M.price_re
PRICE_ANY = re.compile(r"(?:\d[\d,.]*\s*(?:USD|CAD|AUD|GBP|EUR|€|£|\$))|(?:(?:USD|CAD|AUD|GBP|EUR|C\$|A\$|\$|€|£)\s*\d)", re.I)
LOCAL_CURRENCY_CODE = M.currency_code_re
OTHER_CURRENCY_CODE = re.compile(
    r"[\"'](?:currency|currency_code|currencyCode|priceCurrency|active|shop_currency)[\"']\s*:\s*[\"'](%s)[\"']|"
    r"<meta[^>]+(?:product:price:currency|og:price:currency)[^>]+content=[\"'](%s)[\"']" % ("|".join(M.other_currencies), "|".join(M.other_currencies)), re.I)
FOREIGN_PRICE = re.compile(r"C\$\s?\d|CA\$\s?\d|A\$\s?\d|AU\$\s?\d|\d\s?CAD\b|\bCAD\s?\d|£\s?\d|€\s?\d|\d\s?€", re.I)
LOCALE_ATTR = re.compile(r"(?:lang|hreflang|content)=[\"'](?:%s)[\"']|og:locale[\"'][^>]*(?:en_US|es_US)" % "|".join(re.escape(c) for c in M.locale_codes), re.I)

PHYSICAL = re.compile(r"free shipping|shipping|ships (?:free|in|within|from)|in stock|out of stock|sold out|add to (?:cart|bag|basket)|"
                      r"size guide|size chart|pick ?up in store|in-store pickup|curbside|returns? policy|free returns|easy returns|track (?:your )?order|"
                      r"store locator|find a store|order status|gift registry|shop by (?:category|brand|department)|new arrivals|best ?sellers|"
                      r"\bsizes?\b|\bcolors?\b|quantity|\bqty\b|wishlist|compare at|regular price|sale price|pickup|delivery|departments?|registr(?:y|ies)|reorder|"
                      r"clearance|rollbacks?|weekly ad|coupons|same[- ]day|shop all|shop now|shop (?:women|men|kids|home|deals)|deals|brands|in stores?|"
                      r"curbside|ship to home|free delivery|order online|buy online|add to wish ?list|my cart|your cart|view cart|shopping (?:cart|bag)", re.I)
SAAS = re.compile(r"free trial|start (?:your )?free|sign up (?:for )?free|try (?:it )?(?:for )?free|per (?:user|seat|agent|host)|/mo\b|/month|/yr\b|"
                  r"billed (?:annually|monthly|yearly)|pricing plans?|subscription plans?|\bSaaS\b|\bAPI\b|download (?:now|the app|for free|free)|"
                  r"get started(?: for)? free|book a demo|request a demo|schedule a demo|watch (?:now|live|free)|streaming|episodes?|"
                  r"subscribe now|enterprise plan|cloud platform|integrations|\bplugins?\b|developers?|antivirus|\bVPN\b|software|"
                  r"online courses?|certificates?|enroll|tickets|flights|hotels|bookings?|insurance|loans?|credit cards?|casino|betting", re.I)

# Exclusions
DIGITAL = re.compile(
    r"gift ?cards? only|digital (?:downloads?|products?|codes?)|instant download|downloadable|printables?|"
    r"svg (?:files?|bundles?)|digital patterns?|e-?books?|online courses?|masterclass|presets|lightroom presets|"
    r"templates?|canva templates?|procreate brushes|fonts?\b|stock photos|game (?:codes?|keys?)|steam keys?|"
    r"software licen[cs]es?|license keys?|subscriptions? only|nfts?\b|crypto",
    re.I,
)
SERVICE = re.compile(
    r"book (?:an |your )?appointment|book now|schedule (?:a |your )?(?:consultation|appointment|service)|"
    r"\bclinic\b|\bsalon\b|\bspa\b|med ?spa|cleaning services|moving services|consulting|\brentals?\b|real estate|"
    r"law firm|attorneys?|insurance quotes?|mortgage|travel agency|recruit(?:ing|ment)|web design|marketing agency|"
    r"plumbing services|hvac services|roofing|landscaping services|tutoring|lessons|classes|workshops",
    re.I,
)
SERVICE_NAME = re.compile(
    r"\bconsultation\b|\bsessions?\b|\bcourses?\b|webinar|\bsubscription\b|\bmembership\b|\bbooking\b|\bappointment\b|"
    r"\bservices?\b|\bclass(?:es)?\b|\blessons?\b|\bcoaching\b|\btickets?\b|\badmission\b|\bregistration\b|\bdeposit\b|"
    r"\bdigital download\b|\bpdf\b|\be-?book\b|\btemplates?\b|\bpresets?\b|\bsvg\b|\bprintable\b|\bgift ?card\b|\be-?gift\b|"
    r"\bdonation\b|\btuition\b|\brepair service\b|\binstallation service\b|\bwarranty\b|\bprotection plan\b|\bnft\b", re.I)
RESTAURANT_NAME = re.compile(r"\brestaurant\b(?! (?:supplies|supply|equipment|depot))|\bpizzeria\b|\bgrill\b(?!s)|\bdiner\b|\bbistro\b|\btaqueria\b|\bsteakhouse\b|\bsushi bar\b", re.I)
CHARITY_PRODUCT = re.compile(r"\bdonat(?:e|ion)\b|\bsponsor a\b|\btithe\b", re.I)
SERVICE_ORG = re.compile(r"\bconsult(?:ing|ants?|ancy)\b|\bagency\b|\bacademy\b|\bservices\b(?! (?:supply|supplies))|\binstitute\b|\blaw\b|\bclinic\b|\bdental\b|\bdentistry\b|\bchiropractic\b|\binsurance\b|\brealty\b|\bmortgage\b|\bstaffing\b", re.I)
CHARITY = re.compile(r"\bdonat(?:e|ion)s?\b|\bcharity\b|\bnon-?profit\b|\b501\(c\)\(3\)|\bfoundation\b|\bministr(?:y|ies)\b|\bchurch\b|\btax-deductible\b", re.I)
ORG = re.compile(r"\bhospital\b|\buniversity\b|\bcollege\b|\bschool district\b|\bschool\b|\bacademy\b|\binstitute\b|\bmuseum\b|"
                 r"\bdepartment of\b|\bcity of\b|\bcounty\b|\bassociation\b|\bsociety\b|\bfederation\b|\bunion\b|\bchurch\b|"
                 r"\bclinic\b|\bmedical (?:center|group)\b|\bhealth system\b|\blaw (?:firm|office|group)\b|\bconsult(?:ing|ants)\b|"
                 r"\bsoftware\b|\bsaas\b|\bdigital agency\b|\bmarketing agency\b|\bhotel\b|\bresort\b|\bairlines?\b|\btravel\b|"
                 r"\bbank\b|\bcredit union\b|\binsurance\b|\bnews\b|\bmagazine\b|\bradio\b|\btv station\b|\bpodcast\b", re.I)
RESTAURANT = re.compile(r"order online for (?:pickup|delivery)|our menu|view menu|food menu|restaurant|order food|\bdine[- ]in\b|takeout|take-out|catering menu|happy hour|reservations?", re.I)

CATEGORIES = [
    ("Fragrance", r"perfumes?|fragrances?|cologne|eau de parfum|eau de toilette|edp|edt|parfum|attar|oud|incense"),
    ("Beauty & Cosmetics", r"makeup|cosmetics?|skincare|skin care|serums?|moisturi[sz]ers?|cleansers?|lipsticks?|mascara|foundation|concealer|eyeliner|lashes|nail polish|nails|beauty|toners?|sunscreen|spf"),
    ("Personal Care & Grooming", r"personal care|shaving|razors?|beard|grooming|shampoo|conditioner|hair care|deodorants?|body wash|soaps?|oral care|toothpaste"),
    ("Fashion - Women", r"women.s (?:clothing|fashion|apparel)|dresses|blouses|skirts|lingerie|bras|swimwear|maxi dress|womenswear|boutique"),
    ("Fashion - Men", r"men.s (?:clothing|fashion|apparel)|menswear|suits|ties|dress shirts|chinos"),
    ("Fashion - Kids", r"kids.? (?:clothing|apparel|fashion)|children.s (?:clothing|apparel)|toddler clothing|baby clothes|girls.? clothing|boys.? clothing"),
    ("Fashion - Activewear & Streetwear", r"activewear|athleisure|leggings|sportswear|streetwear|hoodies|sweatshirts|joggers|yoga pants"),
    ("Fashion & Apparel", r"apparel|clothing|clothes|fashion|t-?shirts?|tees|shirts|jeans|denim|jackets|outerwear|coats|sweaters|pants|shorts|socks|underwear|pajamas|uniforms|scrubs|hats|caps"),
    ("Shoes", r"shoes|footwear|sneakers|boots|sandals|heels|loafers|slippers|cleats"),
    ("Bags & Luggage", r"handbags?|purses?|totes?|backpacks?|luggage|suitcases?|wallets?|duffel|crossbody"),
    ("Jewelry & Watches", r"jewelry|jewellery|necklaces?|bracelets?|earrings?|rings|engagement rings?|wedding bands?|diamonds?|gold|sterling silver|pendants?|watches|wristwatch(?:es)?|charms"),
    ("Eyewear", r"eyewear|eyeglasses|sunglasses|glasses frames|prescription glasses|contact lenses|contacts"),
    ("Mobiles & Accessories", r"phone cases?|iphone cases?|cell phones?|smartphones?|chargers?|charging cables?|power banks?|screen protectors?|phone accessories|airpods cases?"),
    ("Computers & Electronics", r"electronics|computers?|laptops?|desktops?|monitors?|keyboards?|mice|printers?|cameras?|camera gear|lenses|drones?|headphones|earbuds|speakers|audio|home theater|tvs?|televisions?|smart home|routers?|networking|pc parts|graphics cards?|hard drives?|ssds?"),
    ("Gaming", r"gaming|video games|consoles?|playstation|xbox|nintendo|gaming chairs?|gamers?|board games|tabletop games|trading cards?|tcg|pokemon cards?|dice"),
    ("Home Appliances", r"appliances?|refrigerators?|washers?|dryers?|dishwashers?|ranges|ovens|microwaves?|vacuums?|air purifiers?|humidifiers?|blenders?|air fryers?|espresso machines?|coffee makers?|grills"),
    ("Furniture", r"furniture|sofas?|couches?|sectionals?|chairs|tables|desks|beds|bed frames?|dressers?|bookcases?|cabinets|recliners?|patio furniture|outdoor furniture"),
    ("Home Decor", r"home decor|decor|wall art|rugs?|area rugs?|curtains|drapes|pillows covers|throw pillows|candles?|vases?|mirrors?|frames|wallpaper|artificial flowers|seasonal decor|christmas decor"),
    ("Kitchen & Dining", r"kitchenware|cookware|bakeware|knives|cutlery|kitchen|dinnerware|tableware|glassware|drinkware|mugs|tumblers|water bottles|pots and pans|cast iron|utensils|barware"),
    ("Bedding & Bath", r"bedding|sheets|comforters?|duvets?|quilts?|mattress(?:es)?|pillows?|blankets?|towels?|bath mats?|shower curtains?|linens"),
    ("Home Improvement & Hardware", r"hardware|tools|power tools|hand tools|home improvement|plumbing|faucets?|fixtures|paint|flooring|cabinetry|doors|windows|hvac|ceiling fans?|garage|fasteners|screws|door hardware"),
    ("Lighting & Electrical", r"lighting|lamps?|chandeliers?|pendants lights|led|light bulbs?|electrical|wiring|switches|outlets|light fixtures?"),
    ("Building Materials", r"building materials|lumber|tiles?|tile|stone|countertops|roofing|siding|insulation|concrete|drywall|decking|pavers"),
    ("Industrial & Tools", r"industrial|mro|machinery|safety equipment|ppe|welding|compressors?|generators?|pumps?|hydraulics?|pneumatics?|bearings|abrasives|material handling|janitorial|test equipment"),
    ("Electronic Components", r"electronic components|arduino|raspberry pi|sensors?|microcontrollers?|resistors?|capacitors?|pcbs?|connectors|semiconductors?|robotics kits?"),
    ("Toys & Hobbies", r"toys?|dolls?|lego|puzzles?|plush|stuffed animals|action figures?|hobby|hobbies|model kits?|rc cars?|collectibles|games for kids|educational toys|stem toys"),
    ("Baby & Maternity", r"baby|babies|infant|newborn|diapers?|strollers?|car seats?|nursery|maternity|breastfeeding|baby gear|cribs?"),
    ("Books, Media & Stationery", r"books?|bookstore|novels?|comics?|graphic novels|manga|vinyl|records|cds|dvds|blu-ray|stationery|journals?|notebooks?|planners?|pens|pencils|greeting cards?|calendars"),
    ("Office & School Supplies", r"office supplies|school supplies|paper|ink|toner|office furniture|labels|envelopes|shipping supplies"),
    ("Sports, Fitness & Outdoor", r"sports?|sporting goods|fitness|gym equipment|exercise|weights|dumbbells|yoga|camping|hiking|outdoor gear|backpacking|climbing|fishing|kayaks?|paddle ?boards?|golf|tennis|pickleball|baseball|basketball|football|soccer|hockey|lacrosse|skate(?:boards?)?|ski|snowboards?|surf|swim|running"),
    ("Hunting, Firearms Accessories & Tactical", r"hunting|firearms?|guns?|ammo|ammunition|optics|scopes|holsters?|tactical|archery|bows|crossbows|knives|reloading|gun parts|airsoft"),
    ("Bikes & Micromobility", r"bikes?|bicycles?|e-?bikes?|cycling|mountain bikes?|scooters?|e-scooters?|skates"),
    ("Automotive Parts & Accessories", r"auto parts|car parts|truck parts|automotive|car accessories|truck accessories|jeep|off-?road|performance parts|motorcycle parts|powersports|atv|utv|rv parts|marine parts|boat parts|wheels|rims|exhaust|brakes|car care|detailing|motor oil"),
    ("Tires & Wheels", r"tires?|tyres?|wheels and tires|tire shop"),
    ("Grocery & Food", r"grocery|groceries|food|snacks?|pantry|organic food|meat|beef|steaks?|seafood|cheese|spices|seasonings?|sauces?|hot sauce|olive oil|honey|jerky|baking|flour|gluten-free|vegan food|meal kits?|produce"),
    ("Coffee & Tea", r"coffee|coffee beans|espresso|roasters?|roastery|tea|teas|matcha|loose leaf"),
    ("Candy, Chocolate & Bakery", r"chocolates?|candy|candies|sweets|cookies|cakes?|bakery|fudge|toffee|desserts?|gummies|popcorn|caramels?"),
    ("Beverages, Wine & Spirits", r"wine|wines|spirits|whiskey|bourbon|vodka|tequila|beer|craft beer|liquor|sake|cider|seltzer|beverages?|drinks|kombucha|soda"),
    ("Flowers, Gifts & Party", r"flowers?|florist|bouquets?|gifts?|gift baskets?|gift boxes|personalized gifts|party supplies|balloons|wedding favors|engraved|custom gifts"),
    ("Pets", r"pets?|dogs?|cats?|dog food|cat food|pet supplies|treats|aquariums?|fish|reptiles?|birds?|horses?|equine|tack|litter|collars?|leashes"),
    ("Health, Vitamins & Supplements", r"vitamins?|supplements?|protein|wellness|health|nutrition|probiotics?|collagen|cbd|hemp|herbal|essential oils|sleep aids?|pre-?workout"),
    ("Pharmacy & Medical Supplies", r"pharmacy|medical supplies|medical equipment|mobility|wheelchairs?|walkers|incontinence|first aid|diabetic supplies|cpap|compression|orthotics?|braces|hearing aids?|scrubs|dental supplies|lab supplies"),
    ("Garden & Agriculture", r"garden|gardening|plants?|seeds|bulbs|nursery|lawn|lawn care|fertilizers?|soil|planters?|hydroponics?|grow lights?|irrigation|greenhouses?|farm supplies|feed|livestock|poultry"),
    ("Religious & Spiritual", r"christian|bibles?|catholic|rosar(?:y|ies)|church supplies|jewish|judaica|islamic|crystals|tarot|spiritual|metaphysical"),
    ("Arts, Crafts & Sewing", r"art supplies|crafts?|craft supplies|yarn|knitting|crochet|sewing|fabric|quilting|beads|beading|scrapbooking|paints|canvas|embroidery|cricut|vinyl sheets|resin"),
    ("Music & Instruments", r"guitars?|basses|drums?|pianos?|keyboards instruments|musical instruments?|amps?|amplifiers?|pedals|ukuleles?|violins?|band instruments|pro audio|dj gear|synths?"),
    ("Wholesale & B2B", r"wholesale|bulk|b2b|distributor|for resellers|dealer pricing|trade accounts?|net 30|case packs?"),
    ("Department Store / General Merchandise", r"department store|general merchandise|everything store|variety store|dollar store|superstore|discount store"),
    ("Packaging & Shipping Supplies", r"packaging|boxes|mailers|poly bags|labels|shipping supplies|custom packaging|stickers?"),
    ("Cleaning & Household", r"cleaning supplies|cleaning products|detergents?|laundry|household essentials|paper towels|trash bags|air fresheners?|disinfectants?"),
    ("Smoke & Vape Accessories", r"vapes?|vaporizers?|e-?liquids?|e-?juice|smoke shop|glass pipes|rolling papers|hookahs?|cigars?|tobacco"),
    ("Party, Costumes & Seasonal", r"costumes?|halloween|cosplay|wigs|masquerade|party favors"),
]


def _wrap(alt: str) -> str:
    return rf"\b(?:{alt})\b"


def compile_terms(rx: str):
    return re.compile("|".join(_wrap(a) for a in rx.split("|")), re.I)


CATEGORY_RES = [(name, compile_terms(rx)) for name, rx in CATEGORIES]

TAG_RE = re.compile(r"<[^>]+>")
SCRIPT_RE = re.compile(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", re.I | re.S)


def visible_text(html: str, limit=200000) -> str:
    t = SCRIPT_RE.sub(" ", html[:limit])
    t = TAG_RE.sub(" ", t)
    t = htmlmod.unescape(t)
    return re.sub(r"\s+", " ", t)


def meta(html: str, name: str):
    m = re.search(r"<meta[^>]+(?:property|name)=[\"']%s[\"'][^>]*content=[\"']([^\"']*)" % re.escape(name), html[:300000], re.I)
    if not m:
        m = re.search(r"<meta[^>]+content=[\"']([^\"']*)[\"'][^>]*(?:property|name)=[\"']%s[\"']" % re.escape(name), html[:300000], re.I)
    return htmlmod.unescape(m.group(1)).strip() if m else None


def title_of(html: str):
    m = re.search(r"<title[^>]*>(.*?)</title>", html[:300000], re.I | re.S)
    return re.sub(r"\s+", " ", htmlmod.unescape(m.group(1))).strip() if m else ""


GENERIC_TITLE_PARTS = re.compile(
    r"^(?:home|home ?page|welcome|official (?:site|store|website|online store)|online (?:store|shop|shopping)|"
    r"shop|store|index|united states|usa|us|shop online|default|main|homepage|free shipping.*|new arrivals|sale)$", re.I)


def _norm_letters(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


JUNK_NAME = re.compile(r"\.(?:html?|php|aspx?)$|^google[0-9a-f]{8,}|^https?://|^[\W\d_]+$", re.I)


def store_name(html: str, fallback: str, host: str = "") -> str:
    n = _store_name(html, fallback, host)
    if JUNK_NAME.search(n or ""):
        h = re.sub(r"^www\d?\.", "", (host or fallback).lower())
        return h.split(".")[0] if h else fallback
    return n


def _store_name(html: str, fallback: str, host: str = "") -> str:
    label = ""
    if host:
        h = host.lower().split(":")[0]
        h = re.sub(r"^www\d?\.", "", h)
        label = _norm_letters(h.split(".")[0])
    for cand in (meta(html, "og:site_name"), meta(html, "application-name"), meta(html, "apple-mobile-web-app-title")):
        if cand and 1 < len(cand) < 60 and not GENERIC_TITLE_PARTS.match(cand.strip()):
            return cand.strip()
    t = title_of(html)
    if t:
        parts = [p.strip() for p in re.split(r"\s[|\-–—:•·]\s|\s?\|\s?|\s[-–—]\s", t) if p.strip()]
        parts = [p for p in parts if not GENERIC_TITLE_PARTS.match(p)]
        if parts:
            if label and len(label) >= 3:
                for p in parts:
                    pl = _norm_letters(p)
                    if pl and (label in pl or pl in label) and len(p) <= 60:
                        return p
            cands = sorted({parts[0], parts[-1]}, key=len)
            name = cands[0] if len(cands[0]) >= 2 else parts[0]
            return name[:80]
    if label:
        return label
    return fallback


PLATFORM_PRECEDENCE = ["shopify", "bigcommerce", "magento", "salesforce-commerce", "sap-hybris", "oracle-commerce", "commercetools",
                       "woocommerce", "volusion", "shift4shop", "miva", "opencart", "prestashop", "zen-cart", "squarespace", "wix",
                       "ecwid", "bigcartel", "square", "lightspeed", "vtex", "nopcommerce", "odoo", "ekm"]


def detect_platform(html: str, url: str):
    found = []
    for name, rx in PLATFORM_MARKERS:
        if rx.search(html[:400000]):
            found.append(name)
    if ".myshopify.com" in url:
        found.insert(0, "shopify")
    if ".mybigcommerce.com" in url:
        found.insert(0, "bigcommerce")
    for p in PLATFORM_PRECEDENCE:
        if p in found:
            return p
    return "custom/unknown"


def jsonld_types(html: str):
    types = set()
    offers_currency = set()
    for m in re.finditer(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", html[:2_000_000], re.I | re.S):
        blob = m.group(1)
        types.update(re.findall(r"\"@type\"\s*:\s*\"([A-Za-z]+)\"", blob))
        offers_currency.update(x.upper() for x in re.findall(r"\"priceCurrency\"\s*:\s*\"([A-Za-z]{3})\"", blob))
        if re.search(r"\"addressCountry\"\s*:\s*\"(?:US|USA|United States)\"", blob):
            types.add("__address_us")
    return types, offers_currency


def phones(html: str):
    """Classify NANP phone numbers on the page into US / CA / TOLLFREE counts."""
    c = Counter()
    for m in M.phone_re.finditer(html[:600000]):
        code = next((g for g in m.groups() if g), None)
        if code:
            c[area_code_market(code)] += 1
    return c


def market_signals(html: str, text: str, url: str, final_url: str, platform: str, api_currency: set | None = None):
    """Score market relevance from combined signals. Returns (score, evidence dict)."""
    ev = {}
    score = 0.0
    host = re.sub(r"^https?://", "", final_url).split("/")[0].lower().split(":")[0]
    if any(host.endswith("." + t) for t in M.cctlds):
        ev["cctld"] = host
        score += M.cctld_weight
    path = "/" + final_url.split("/", 3)[3] if final_url.count("/") >= 3 else "/"
    if LOCALE_ATTR.search(html[:300000]) or M.locale_path_re.search(path[:20]) or host.split(".")[0] in M.subdomain_labels:
        ev["locale"] = True
        score += 1.5 if (M.locale_path_re.search(path[:20]) or host.split(".")[0] in M.subdomain_labels) else 0.5
    n_prices = len(PRICE_LOCAL.findall(text))
    code = bool(LOCAL_CURRENCY_CODE.search(html[:800000]))
    if api_currency and M.currency in api_currency:
        code = True
    if code:
        ev[f"currency_{M.currency}_code"] = True
        score += 2.5
    if n_prices:
        ev["local_prices"] = n_prices
        score += 1.5 if n_prices >= 2 else 0.5
    oc = set(x.upper() for g in OTHER_CURRENCY_CODE.findall(html[:800000]) for x in g if x)
    if api_currency:
        oc |= {c for c in api_currency if c and c != M.currency}
    fp = len(FOREIGN_PRICE.findall(text))
    if oc and not code:
        ev["other_currency"] = sorted(oc)
        score -= 3
    elif fp >= 3 and not code:
        ev["foreign_prices"] = fp
        score -= 2
    ph = phones(html)
    if ph["US"]:
        ev["us_phone"] = ph["US"]
        score += 2.0
    elif ph["TOLLFREE"]:
        ev["nanp_tollfree_phone"] = ph["TOLLFREE"]
        score += 0.75
    if ph["CA"] and not ph["US"]:
        ev["canadian_phone"] = ph["CA"]
        score -= 1.0
    am = M.address_re.search(text)
    if am:
        ev["us_address"] = am.group(0)[:40]
        score += 2.0
    words = M.places_re.findall(text[:60000])
    if words:
        ev["places"] = sorted(set(words))[:5]
        score += 1.0 if len(words) >= 2 else 0.5
    sp = M.ship_pay_re.findall(text[:80000])
    if sp:
        uniq = sorted(set(s.lower() for s in sp))
        ev["shipping_payment"] = uniq[:6]
        score += min(2.0, 0.5 * len(uniq))
    fpl = M.foreign_place_re.findall(text[:60000])
    if fpl and len(fpl) >= 3 and not ph["US"]:
        ev["foreign_places"] = sorted(set(fpl))[:4]
        score -= 1.0
    if M.foreign_cctld_re.search(host):
        ev["foreign_cctld"] = host
        score -= 2.5
    return score, ev


def classify_category(texts, weights=None):
    """texts: list of strings; weights: per-text multiplier (title/meta weigh more than body)."""
    weights = weights or [1] * len(texts)
    acc = Counter()
    for t, w in zip(texts, weights):
        if not t:
            continue
        t = t[:30000]
        for name, rx in CATEGORY_RES:
            n = len(rx.findall(t))
            if n:
                acc[name] += w * min(n, 25)
    scores = sorted(((v, k) for k, v in acc.items()), reverse=True)
    if not scores:
        return "General / Unclassified", ""
    top = scores[0][1]
    second = scores[1][1] if len(scores) > 1 and scores[1][0] >= max(2, scores[0][0] * 0.5) else ""
    return top, second
