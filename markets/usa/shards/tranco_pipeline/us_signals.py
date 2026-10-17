"""US-market page signals: ecommerce markers, platform fingerprints, US relevance, exclusions, category."""
from __future__ import annotations

import html as htmlmod
import re
from collections import Counter

PARKED = re.compile(
    r"domain (?:name )?(?:is|may be) for sale|buy this domain|this domain is for sale|make an offer on this domain|"
    r"parked (?:free|domain)|sedoparking|parkingcrew|bodis\.com|hugedomains\.com|dan\.com/|afternic|domain is parked|"
    r"domain has expired|this domain has expired|renew (?:this|your) domain|"
    r"account (?:has been )?suspended|this account has been suspended|website (?:is )?expired|"
    r"welcome to nginx|apache2? (?:ubuntu |debian )?default page|<title>it works!|"
    r"<title>index of /|default web site page|future home of something quite cool|"
    r"site not found|no such app|there is nothing here|domain not configured|this site can.t be reached|"
    r"website coming soon|site is under construction|launching soon",
    re.I,
)
CLOSED = re.compile(
    r"store is (?:currently |temporarily )?closed|this store is unavailable|store unavailable|"
    r"temporarily closed|maintenance mode|we.ll be back soon|we are currently closed|no longer accepting orders|"
    r"opening soon|enter store using password|password-page|template-password|"
    r"this shop is unavailable|sorry, this shop is currently unavailable|shop is closed|"
    r"we have closed our (?:online )?(?:store|shop)|permanently closed|closing our doors",
    re.I,
)
CHALLENGE = re.compile(
    r"just a moment\.\.\.|cf-chl|challenge-platform/h/|attention required! \| cloudflare|"
    r"<title>access denied|request could not be satisfied|pardon our interruption|"
    r"are you a robot|incapsula incident|perimeterx|px-captcha|_incapsula_resource|distil_r_captcha|ddos-guard|"
    r"sucuri website firewall|verify you are human|captcha-delivery\.com|geo\.captcha-delivery|"
    r"please enable js and disable any ad blocker|kasada|akamai bot manager|<title>robot check",
    re.I,
)

PLATFORM_SUBSTR = {
    "shopify": ["cdn.shopify.com", "shopify.theme", "shopify-section", "myshopify.com", "/cdn/shop/"],
    "bigcommerce": ["bigcommerce.com", "stencil-utils", "data-stencil"],
    "woocommerce": ["woocommerce", "wc-ajax", "wc-block"],
    "magento": ["magento_", "mage/cookies", "text/x-magento-init", "mage.cookies"],
    "salesforce-commerce": ["demandware.static", "/on/demandware.store", "dwanalytics", "/dw/shop/"],
    "sap-hybris": ["/_ui/responsive/", "acc.config", "yacceleratorstorefront"],
    "squarespace": ["static1.squarespace.com", "squarespace-commerce", "static.squarespace_context"],
    "wix": ["wixstores", "static.wixstatic.com", "wix-ecommerce", "wix-bolt"],
    "square-online": ["square.site", "editmysite.com", "squareup.com/online"],
    "ecwid": ["app.ecwid.com", "ecwid_", "ecwid."],
    "volusion": ["volusion", "/v/vspfiles/"],
    "shift4shop": ["3dcart", "shift4shop"],
    "prestashop": ["prestashop"],
    "opencart": ["index.php?route=product", "index.php?route=common", "index.php?route=checkout", "catalog/view/theme"],
    "shopware": ["shopware", "sw-plugin"],
    "lightspeed": ["lightspeedhq", "seoshop", "webshopapp.com", "ecom.lightspeed"],
    "miva": ["mivamerchant", "/mm5/merchant.mvc"],
    "bigcartel": ["bigcartel"],
    "nopcommerce": ["nopcommerce", "nop-ajax"],
    "vtex": ["vteximg.com", "vtexassets", "vtex-io"],
    "salesforce-b2c-pwa": ["commercecloud", "mobify"],
    "odoo": ["website_sale"],
    "zen-cart": ["zen-cart", "zencart", "main_page=product_info"],
    "oscommerce": ["oscommerce", "product_info.php?products_id"],
    "cs-cart": ["cs-cart", "dispatch=products.view"],
    "weebly": ["weebly.com", "wsite-com-product"],
}
PLATFORM_ORDER = ["shopify", "bigcommerce", "salesforce-commerce", "magento", "sap-hybris", "woocommerce", "squarespace",
                  "wix", "square-online", "ecwid", "volusion", "shift4shop", "miva", "bigcartel", "lightspeed", "shopware",
                  "prestashop", "opencart", "vtex", "salesforce-b2c-pwa", "nopcommerce", "zen-cart", "oscommerce",
                  "cs-cart", "weebly", "odoo"]
ECOM_PLATFORMS = set(PLATFORM_ORDER) - {"squarespace", "wix", "weebly", "odoo"}

ADD_TO_CART = re.compile(
    r"add[ _-]?to[ _-]?(?:cart|bag|basket)|addtocart|add-to-cart|\?add-to-cart=|cart/add|data-add-to-cart|"
    r"product-form__cart|btn-cart|add_to_cart|buy it now|buy now",
    re.I,
)
CART = re.compile(r"/cart\b|/checkout\b|/basket\b|mini-?cart|cart-count|cart_count|cart-icon|shopping[ -]?(?:cart|bag)|view cart|my cart", re.I)
PRODUCT_LINK = re.compile(
    r"href=[\"'](?!data:)([^\"'<>\s]{0,200}?(?:/products?/[^\"'/?#<>\s]+|/p/[^\"'/?#<>\s]+|/item/[^\"'/?#<>\s]+|"
    r"/shop/[^\"'?#<>\s]+/[^\"'/?#<>\s]+|product_id=\d+|route=product/product|/product-page/|/[a-z0-9-]+-p\d{3,}(?:\.html?)?|"
    r"/[a-z0-9-]{6,}\.html|/pd/[^\"'<>\s]+|/dp/[^\"'<>\s]+|products_id=\d+)[^\"'<>\s]{0,200})[\"']",
    re.I,
)
PRICE_USD = re.compile(r"(?<![A-Za-z])(?:US\s?\$|\$)\s?\d{1,5}(?:,\d{3})*(?:\.\d{2})?(?!\d)|\d+(?:\.\d{2})?\s?USD\b")
PRICE_OTHER = re.compile(
    r"(?:€|£|¥|₹|₽|R\$|zł|kr\b|CHF|AU\$|A\$|C\$|CA\$|NZ\$|S\$|HK\$|MX\$|₩|₺|₴|Kč|Ft\b|lei\b|RM\s?\d|Rp\s?\d|₱|₫|฿|AED|SAR)"
    r"\s?\d|\d[\d.,]*\s?(?:€|£|zł|kr|Kč|руб|₽|EUR|GBP|CAD|AUD|INR|JPY|CNY|BRL|MXN|PLN|SEK|NOK|DKK|CHF|NZD|ZAR|TRY)\b",
    re.I,
)
CURRENCY_CODE = re.compile(
    r"[\"'](?:currency|currency_code|currencyCode|priceCurrency|presentmentCurrency|shopCurrency|active|iso_code)[\"']\s*:\s*[\"']([A-Z]{3})[\"']|"
    r"(?:product:price:currency|og:price:currency)[\"'][^>]*content=[\"']([A-Z]{3})|"
    r"data-currency(?:-code)?=[\"']([A-Z]{3})|Shopify\.currency\s*=\s*\{\s*\"active\"\s*:\s*\"([A-Z]{3})",
)
KNOWN_CURRENCIES = {"USD", "CAD", "EUR", "GBP", "AUD", "NZD", "JPY", "CNY", "INR", "BRL", "MXN", "PLN", "SEK", "NOK", "DKK", "CHF",
                    "ZAR", "TRY", "RUB", "UAH", "CZK", "HUF", "RON", "IDR", "MYR", "PHP", "VND", "THB", "KRW", "SGD", "HKD",
                    "AED", "SAR", "ILS", "ARS", "CLP", "COP", "PEN", "TWD", "BGN", "HRK", "ISK", "EGP", "NGN", "KES", "PKR"}

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado", "CT": "Connecticut",
    "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee",
    "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin",
    "WY": "Wyoming", "DC": "District of Columbia", "PR": "Puerto Rico",
}
_ST_ABBR = "|".join(US_STATES)
_ST_FULL = "|".join(sorted(US_STATES.values(), key=len, reverse=True))
US_ADDRESS = re.compile(rf"\b[A-Z][A-Za-z.' -]{{2,28}},\s*(?:{_ST_ABBR}|{_ST_FULL})\.?,?\s+\d{{5}}(?:-\d{{4}})?\b")
CA_ADDRESS = re.compile(r"\b(?:ON|QC|BC|AB|MB|SK|NS|NB|NL|PE|Ontario|Quebec|Québec|British Columbia|Alberta|Manitoba|Saskatchewan|Nova Scotia|New Brunswick)\.?,?\s+[A-Z]\d[A-Z]\s?\d[A-Z]\d\b")

PHONE = re.compile(r"(?:tel:|\+1[\s.\-]?|\b1[\s.\-])?\(?\b([2-9]\d{2})\)?[\s.\-]([2-9]\d{2})[\s.\-](\d{4})\b")
CA_NPA = {204, 226, 236, 249, 250, 257, 263, 289, 306, 343, 354, 365, 367, 368, 382, 387, 403, 416, 418, 428, 431, 437, 438, 450,
          460, 468, 474, 506, 514, 519, 548, 579, 581, 584, 587, 604, 613, 639, 647, 672, 683, 705, 709, 742, 753, 778, 780, 782,
          807, 819, 825, 867, 873, 879, 902, 905}
CARIB_NPA = {242, 246, 264, 268, 284, 345, 441, 473, 649, 658, 664, 721, 758, 767, 784, 809, 829, 849, 868, 869, 876}
TOLLFREE = {800, 833, 844, 855, 866, 877, 888}

US_SHIPPING = re.compile(
    r"free (?:standard |ground |us |u\.s\. )?shipping (?:on |for |to )?(?:all )?(?:orders? )?(?:over \$\d+ )?(?:with)?in (?:the )?(?:continental |contiguous )?(?:US|U\.S\.A?\.?|USA|United States|lower 48)|"
    r"free (?:US|U\.S\.|USA|domestic) shipping|"
    r"(?:ships?|shipping|delivery) (?:to|within|throughout|across) (?:all (?:50 states|of the US)|the (?:continental |contiguous )?(?:US|U\.S\.A?\.?|USA|United States)|(?:the )?lower 48)|"
    r"(?:ships?|shipped|shipping) from (?:our (?:warehouse|facility|shop|studio) in |the )?(?:USA|U\.S\.A?\.?|US|United States|"
    rf"(?:{_ST_FULL}))|"
    r"(?:US|U\.S\.|USA|domestic) orders? (?:ship|over)|contiguous (?:US|U\.S\.|United States)|continental (?:US|U\.S\.|United States)|"
    r"lower 48 states|all 50 states|USPS|UPS Ground|FedEx Ground|"
    r"proudly (?:made|designed|based) in (?:the )?(?:USA|U\.S\.A?\.?|America)|made in (?:the )?(?:USA|U\.S\.A\.)|american[- ]made",
    re.I,
)
US_LOCALE = re.compile(r"hreflang=[\"']en-us[\"']|og:locale[\"'][^>]*content=[\"']en_US|lang=[\"']en-US[\"']", re.I)
CANADA_WORDS = re.compile(r"\bCanada\b|\bCanadian\b|Canada Post|\bGST\b|\bHST\b", re.I)

MARKETPLACE_ROOTS = {
    "amazon.com", "ebay.com", "etsy.com", "temu.com", "aliexpress.com", "aliexpress.us", "poshmark.com", "mercari.com",
    "alibaba.com", "wish.com", "shein.com", "walmart.com", "target.com", "depop.com", "grailed.com", "stockx.com", "goat.com",
    "offerup.com", "craigslist.org", "facebook.com", "reverb.com", "chairish.com", "1stdibs.com", "bonanza.com", "ruby-lane.com",
    "rubylane.com", "tradesy.com", "thredup.com", "therealreal.com", "vinted.com", "ebid.net", "newegg.com", "overstock.com",
    "wayfair.com", "joom.com", "dhgate.com", "banggood.com", "zulily.com", "storenvy.com", "tophatter.com", "kidizen.com",
    "curtsy.com", "vestiairecollective.com", "farfetch.com", "ubuy.com", "desertcart.com", "fruugo.com", "fruugo.us",
}
MARKETPLACE_TEXT = re.compile(r"\bsell(?:ers?)? on (?:our )?marketplace|become a (?:seller|vendor)|start selling|vendor (?:login|registration|dashboard)|multi-?vendor|sold by (?:third[- ]party )?sellers", re.I)

DIGITAL = re.compile(
    r"\b(?:e-?books?|digital (?:downloads?|products?|files?|patterns?|planners?|prints?|art)|instant download|printables?|"
    r"lightroom presets?|presets|fonts?|svg (?:files?|bundles?)|templates?|online courses?|masterclass|courses?|"
    r"gift cards?|software|licen[cs]e keys?|memberships?|sample packs?|plugins?|webinars?|"
    r"coaching|downloadable|mp3|pdf)\b",
    re.I,
)
SERVICE = re.compile(
    r"\b(?:book (?:an |your )?(?:appointment|consultation|session|now)|schedule (?:a |your )?(?:consultation|appointment|service)|"
    r"free (?:quote|estimate|consultation)|get a quote|request a quote|our services|services we offer|"
    r"law firm|attorneys?|dentist(?:ry)?|clinic|chiropract|salon|spa services|plumbing services|hvac|roofing|"
    r"real estate|realtor|insurance (?:agency|quotes?)|mortgage|tax preparation|accounting services|"
    r"web design|marketing agency|seo services|staffing|recruit(?:ing|ment)|church|ministr(?:y|ies)|"
    r"hotel|resort|vacation rentals?|tours?\b|travel agency|wedding venue|photography services)\b",
    re.I,
)
SERVICE_TITLE = re.compile(
    r"\b(?:tours?|travel|vacations?|cruises?|excursions?|hotels?|resorts?|inn|lodge|b&b|bed and breakfast|campground|"
    r"law (?:firm|office)|attorneys?|lawyers?|insurance|mortgage|realty|real estate|dentist|dental (?:care|office)|clinic|"
    r"church|school|academy|university|college|webinars?|conference|summit|events? tickets?|tickets|courses?|training|"
    r"hosting|vpn|software|app\b|saas|agency|consulting|marketing services|news|magazine|podcast|radio)\b",
    re.I,
)
SERVICE_PRODUCT_NAME = re.compile(
    r"\b(?:tours?|tickets?|admission|passes?|excursions?|cruises?|day trip|rental|reservations?|bookings?|appointments?|"
    r"sessions?|lessons?|classes|class|courses?|workshops?|webinars?|registration|membership|subscription|tuition|"
    r"consultation|services?|installation|repair|donations?|sponsorship|e-?gift card|gift card|downloads?|license)\b",
    re.I,
)
RESTAURANT = re.compile(r"\b(?:order online for (?:pickup|delivery)|view (?:our )?menu|our menu|dine[- ]in|takeout|take-out|"
                        r"reservations?|toasttab\.com|chownow|grubhub|doordash|ubereats|slicelife|menufy|restaurant|pizzeria|"
                        r"catering menu|happy hour|brunch)\b", re.I)
SAAS = re.compile(r"\b(?:free trial|start (?:your )?free trial|sign up free|pricing plans?|per (?:user|seat)/(?:mo|month)|"
                  r"request a demo|book a demo|get started for free|api documentation|saas|platform for teams)\b", re.I)
ADULT = re.compile(r"\b(?:porn|xxx|sex ?toys?|adult toys?|escorts?|onlyfans|camgirls?|hentai|nsfw|erotic|fetish|bdsm)\b", re.I)
GAMBLING = re.compile(r"\b(?:casino|sportsbook|betting odds|slots? games?|poker online|online gambling)\b", re.I)

CATEGORIES = [
    ("Perfume & Fragrance", r"eau de parfum|eau de toilette|perfumes?|fragrances?|parfum|cologne|colognes|body mist|attar|oud"),
    ("Beauty & Cosmetics", r"makeup|cosmetics?|skincare|skin care|serums?|moisturi[sz]ers?|cleansers?|lipsticks?|lip gloss|mascara|eyeliner|foundation|concealer|lashes|nail polish|nails?|beauty|face masks?|toners?|sunscreen|spf"),
    ("Personal Care & Grooming", r"shaving|razors?|beard oil|beard|grooming|shampoo|conditioner|hair care|deodorants?|body wash|soaps?|bath bombs?|lotions?|toothpaste|oral care"),
    ("Fashion - Women", r"dresses|dress|women.s (?:clothing|fashion|apparel)|womens|blouses?|skirts?|lingerie|bras?|leggings|swimwear|bikinis?|jumpsuits?|maternity wear"),
    ("Fashion - Men", r"menswear|men.s (?:clothing|fashion|apparel)|mens|suits?|ties|neckties|dress shirts?|blazers?"),
    ("Fashion - Kids", r"kids.? (?:clothing|apparel|fashion)|children.s clothing|toddler clothes|baby clothes|onesies?"),
    ("Fashion - Sportswear & Streetwear", r"sportswear|activewear|athleisure|streetwear|hoodies?|sweatshirts?|joggers|sneakers|graphic tees"),
    ("Fashion & Apparel", r"t-?shirts?|tees|shirts?|pants|jeans|jackets?|coats?|apparel|clothing|clothes|fashion|outerwear|socks|hats?|caps?|beanies?|uniforms?|scrubs|costumes?|tops"),
    ("Shoes", r"shoes|footwear|boots|sandals|heels|loafers|slippers|clogs|insoles"),
    ("Bags & Luggage", r"bags?|handbags?|purses?|totes?|backpacks?|luggage|suitcases?|wallets?|duffels?|crossbody"),
    ("Jewelry & Watches", r"jewelry|jewellery|necklaces?|bracelets?|earrings?|rings?|pendants?|charms?|watches|wristwatch|diamonds?|gold|sterling silver|engagement rings?|wedding bands?"),
    ("Eyewear", r"sunglasses|eyeglasses|eyewear|glasses frames|reading glasses|blue light glasses|contact lenses"),
    ("Mobiles & Accessories", r"phone cases?|iphone|samsung galaxy|phone accessories|chargers?|charging cables?|power banks?|screen protectors?|airpods|earbuds|phone mounts?"),
    ("Computers & Electronics", r"electronics|computers?|laptops?|monitors?|keyboards?|mouse|printers?|cameras?|drones?|headphones|speakers|audio|tvs?|televisions?|smart home|routers?|networking|pc parts|gpus?|hard drives?|ssds?|batteries|cables"),
    ("Gaming", r"gaming|video games?|consoles?|playstation|xbox|nintendo|gamers?|retro games?|controllers?"),
    ("Home Appliances", r"appliances?|refrigerators?|washers?|dryers?|vacuums?|air purifiers?|humidifiers?|blenders?|air fryers?|coffee makers?|espresso machines?|mixers?|grills?|smokers?|water filters?"),
    ("Furniture", r"furniture|sofas?|couches?|sectionals?|chairs?|tables?|desks?|bed frames?|dressers?|cabinets?|bookcases?|recliners?|ottomans?|patio furniture"),
    ("Home Decor", r"home decor|decor|wall art|wall decor|vases?|candles?|rugs?|curtains?|throw pillows?|mirrors?|picture frames?|wreaths?|signs?|tapestr(?:y|ies)|artificial flowers?"),
    ("Kitchenware & Tableware", r"kitchenware|cookware|bakeware|knives|cutlery|kitchen|pots?|pans?|skillets?|dinnerware|plates?|mugs?|tumblers?|water bottles?|drinkware|glassware|tableware|utensils?|cutting boards?"),
    ("Bedding, Mattresses & Textiles", r"bedding|mattress(?:es)?|sheets|duvets?|comforters?|quilts?|blankets?|pillows?|towels?|linens?|fabrics?|textiles?|yarn"),
    ("Home Improvement & Hardware", r"hardware|tools?|power tools|hand tools|plumbing|faucets?|fixtures?|paint|paints|flooring|doors?|windows?|cabinet hardware|fasteners?|screws?|bolts?|home improvement|hvac parts|filters?"),
    ("Lighting & Electrical", r"lighting|lights?|lamps?|chandeliers?|led|bulbs?|light fixtures?|electrical|switches|outlets?|ceiling fans?"),
    ("Industrial & Tools", r"industrial|machinery|equipment|safety equipment|ppe|compressors?|generators?|pumps?|welding|hydraulics?|bearings?|valves?|motors?|janitorial|material handling|lab equipment|sawmills?"),
    ("Electronic Components & Hobby Electronics", r"arduino|raspberry pi|electronic components|sensors?|modules?|resistors?|capacitors?|pcbs?|microcontrollers?|soldering|ham radio|antennas?"),
    ("Toys & Hobbies", r"toys?|dolls?|lego|puzzles?|board games?|card games?|trading cards?|collectibles?|action figures?|plush|model kits?|rc cars?|hobby|hobbies|diecast|figures|miniatures"),
    ("Baby & Maternity", r"baby|babies|infant|newborn|diapers?|strollers?|car seats?|nursery|maternity|breastfeeding|baby bottles|pacifiers?"),
    ("Books & Stationery", r"books?|bookstore|novels?|comics?|stationery|notebooks?|journals?|planners?|pens?|pencils?|greeting cards?|calendars?"),
    ("Office & School Supplies", r"office supplies|school supplies|ink|toner|paper|labels|envelopes|office furniture|binders?|classroom"),
    ("Sports, Fitness & Outdoor", r"sports?|fitness|gym|workout|exercise|yoga|camping|hiking|outdoor|fishing|hunting|archery|golf|tennis|baseball|softball|basketball|football|soccer|hockey|lacrosse|cycling|bikes?|bicycles?|skateboards?|surf|snowboards?|skis?|kayaks?|paddle|climbing|boxing|martial arts|pickleball|disc golf|cheerleading"),
    ("Firearms Accessories & Tactical", r"tactical|holsters?|optics|scopes?|ammo|ammunition|firearms?|guns?|rifles?|pistols?|edc|airsoft|paintball|gun safes?|crossbows?"),
    ("Automotive Parts & Accessories", r"auto parts|car parts|truck parts|automotive|car accessories|truck accessories|jeep|wheels|tires|exhaust|suspension|brakes|headlights?|floor mats|car care|detailing|motorcycle|powersports|atv|utv|off-?road|performance parts|seat covers?"),
    ("Marine & RV", r"marine|boat|boating|rv|camper|trailer parts|outboard|pontoon"),
    ("Grocery & Food", r"grocery|groceries|food|snacks?|spices?|seasonings?|sauces?|hot sauce|bbq sauce|jerky|meat|beef|steaks?|seafood|olive oil|honey|jams?|pantry|gourmet|baking mix|flour|pasta|nuts|popcorn|salsa|maple syrup"),
    ("Coffee & Tea", r"coffee|espresso|coffee beans|roasters?|roastery|tea|teas|matcha|loose leaf"),
    ("Chocolates, Candy & Baked Goods", r"chocolates?|candy|candies|sweets|fudge|cookies|cakes?|brownies|baked goods|bakery|toffee|caramels?|gummies|cupcakes?"),
    ("Wine, Beer & Spirits", r"wines?|winery|vineyard|beer|brewery|spirits|whiskey|whisky|bourbon|vodka|gin|rum|tequila|cider|mead|sake|liquor"),
    ("Flowers, Gifts & Party", r"flowers?|florist|bouquets?|gifts?|gift baskets?|party supplies|balloons?|personalized gifts?|custom gifts?|engraved|keepsakes?"),
    ("Pets", r"pets?|dogs?|cats?|puppy|kitten|dog treats?|cat food|dog food|pet supplies|leashes?|collars?|aquariums?|reptiles?|birds?|horses?|equine|chickens?|poultry"),
    ("Health, Supplements & Wellness", r"supplements?|vitamins?|protein|nutrition|wellness|health|probiotics?|collagen|herbal|herbs|essential oils?|aromatherapy|keto|immune|pre-?workout|sports nutrition|mushrooms?"),
    ("CBD, Vape & Smoke", r"cbd|hemp|delta-?8|thc|kratom|vape|vapes|e-?liquids?|e-?juice|smoke shop|glass pipes?|bongs?|rolling papers?|cigars?|tobacco|hookah"),
    ("Medical Supplies & Equipment", r"medical supplies|medical equipment|mobility|wheelchairs?|walkers?|compression|orthopedic|braces?|cpap|diabetic|first aid|stethoscopes?|hearing aids?|dental supplies"),
    ("Garden & Agriculture", r"garden|gardening|plants?|seeds?|nursery|fertilizers?|soil|hydroponics?|grow lights?|lawn|planters?|greenhouses?|trees|succulents?|farm supplies|irrigation"),
    ("Arts, Crafts & Sewing", r"crafts?|craft supplies|art supplies|brushes|canvas|sewing|quilting|fabric|knitting|crochet|embroidery|beads|beading|scrapbooking|stickers?|vinyl|cricut|resin|pottery|handmade"),
    ("Music & Instruments", r"guitars?|basses|drums?|pianos?|ukuleles?|violins?|instruments?|amps?|amplifiers|pedals?|strings|sheet music|vinyl records|records|dj equipment|microphones?"),
    ("Art, Prints & Collectibles", r"art prints?|prints|posters?|original art|paintings?|photography prints|sculptures?|coins?|stamps?|memorabilia|autographs?|antiques?|vintage"),
    ("Religious & Spiritual", r"christian|bibles?|rosar(?:y|ies)|catholic|crosses|jewish|judaica|islamic|spiritual|crystals?|tarot|metaphysical|sage|incense"),
    ("Cleaning & Household Supplies", r"cleaning|cleaners?|detergents?|laundry|household|paper towels?|trash bags?|disinfectants?|air fresheners?"),
    ("Packaging & Shipping Supplies", r"packaging|boxes|mailers?|shipping supplies|poly bags|bubble wrap|custom packaging"),
    ("Wholesale & B2B Supplies", r"wholesale|bulk|b2b|distributor|restaurant supplies|salon supplies|janitorial supplies|promotional products|custom printing"),
    ("Department Store / General Merchandise", r"department store|general store|variety store|everything store|discount store|general merchandise"),
]
CATEGORY_RES = [(n, re.compile(r"\b(?:" + rx + r")\b", re.I)) for n, rx in CATEGORIES]

TAG_RE = re.compile(r"<[^>]+>")
SCRIPT_RE = re.compile(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", re.I | re.S)


def visible_text(html: str, limit=400_000) -> str:
    t = SCRIPT_RE.sub(" ", html[:limit])
    t = TAG_RE.sub(" ", t)
    t = htmlmod.unescape(t)
    return re.sub(r"\s+", " ", t)


def meta(html: str, name: str):
    m = re.search(r"<meta[^>]+(?:property|name)=[\"']%s[\"'][^>]*content=[\"']([^\"']*)" % re.escape(name), html[:200_000], re.I)
    if not m:
        m = re.search(r"<meta[^>]+content=[\"']([^\"']*)[\"'][^>]*(?:property|name)=[\"']%s[\"']" % re.escape(name), html[:200_000], re.I)
    return htmlmod.unescape(m.group(1)).strip() if m else None


def title_of(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html[:300_000], re.I | re.S)
    return re.sub(r"\s+", " ", htmlmod.unescape(m.group(1))).strip()[:300] if m else ""


GENERIC_TITLE = re.compile(r"^(?:home|home ?page|welcome|official (?:site|store|website|online store)|online (?:store|shop|shopping)|shop|store|index|"
                           r"shop online|default|main|homepage|products|all products|catalog|collections?)$", re.I)
JUNK_NAME = re.compile(r"\.(?:html?|php|aspx?)$|^https?://|^[\W\d_]+$", re.I)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def store_name(html: str, host: str) -> str:
    h = re.sub(r"^www\d?\.", "", host.lower())
    label = _norm(h.split(".")[0])
    for cand in (meta(html, "og:site_name"), meta(html, "application-name")):
        if cand and 1 < len(cand) < 60 and not GENERIC_TITLE.match(cand.strip()) and not JUNK_NAME.search(cand):
            return cand.strip()
    t = title_of(html)
    if t:
        parts = [p.strip() for p in re.split(r"\s[|\-–—:•·]\s|\s?\|\s?", t) if p.strip()]
        parts = [p for p in parts if not GENERIC_TITLE.match(p) and not JUNK_NAME.search(p)]
        if parts:
            if len(label) >= 3:
                for p in parts:
                    pl = _norm(p)
                    if pl and (label in pl or pl in label) and len(p) <= 60:
                        return p
            cands = sorted({parts[0], parts[-1]}, key=len)
            return (cands[0] if len(cands[0]) >= 2 else parts[0])[:80]
    return h.split(".")[0]


def detect_platform(html: str, url: str, low: str | None = None) -> str:
    h = low if low is not None else html[:600_000].lower()
    found = {name for name, subs in PLATFORM_SUBSTR.items() if any(s in h for s in subs)}
    if ".myshopify.com" in url:
        found.add("shopify")
    for p in PLATFORM_ORDER:
        if p in found:
            return p
    return "custom/unknown"


def jsonld(html: str):
    types, cur = set(), set()
    for m in re.finditer(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", html[:1_500_000], re.I | re.S):
        blob = m.group(1)
        types.update(re.findall(r"\"@type\"\s*:\s*\[?\s*\"([A-Za-z]+)\"", blob))
        cur.update(x.upper() for x in re.findall(r"\"priceCurrency\"\s*:\s*\"([A-Za-z]{3})\"", blob))
    return types, cur


def currencies(html: str) -> Counter:
    c = Counter()
    for m in CURRENCY_CODE.finditer(html[:1_500_000]):
        code = next(g for g in m.groups() if g)
        if code in KNOWN_CURRENCIES:
            c[code] += 1
    return c


def phones(text: str):
    us, ca, tf = [], [], []
    for m in PHONE.finditer(text[:1_500_000]):
        npa = int(m.group(1))
        s = f"({m.group(1)}) {m.group(2)}-{m.group(3)}"
        if npa in TOLLFREE:
            tf.append(s)
        elif npa in CA_NPA:
            ca.append(s)
        elif npa in CARIB_NPA or m.group(1)[1:] == "11" or m.group(2) == "555":
            continue
        else:
            us.append(s)
    return us, ca, tf


def us_signals(html_list, text_list, final_url: str, api: dict | None = None):
    """Combine page-level evidence into US relevance.

    Returns (decision, evidence dict, reason). decision: 'us' | 'weak' | 'non_us' | 'canada'.
    """
    api = api or {}
    html = "\n".join(h[:1_500_000] for h in html_list if h)
    text = "\n".join(t for t in text_list if t)
    ev = {}
    cur = currencies(html)
    _, ldcur = jsonld(html)
    for c in ldcur:
        if c in KNOWN_CURRENCIES:
            cur[c] += 2
    if api.get("currency"):
        for c in api["currency"] if isinstance(api["currency"], (list, set, tuple)) else [api["currency"]]:
            if c:
                cur[c.upper()] += 5
    usd_prices = len(PRICE_USD.findall(text))
    other_prices = len(PRICE_OTHER.findall(text))
    country = (api.get("country") or "").upper()
    host = re.sub(r"^https?://", "", final_url).split("/")[0].lower()

    usd_code = cur.get("USD", 0) > 0
    other_codes = {k: v for k, v in cur.items() if k != "USD"}
    if usd_code:
        ev["currency"] = "USD"
    elif other_codes:
        ev["currency"] = max(other_codes, key=other_codes.get)
    if usd_prices:
        ev["usd_prices"] = usd_prices
    if country:
        ev["shop_country"] = country

    tels = " ".join(re.findall(r"href=[\"']tel:([^\"']{7,30})[\"']", html, re.I))
    us_ph, ca_ph, tf_ph = phones(text + " \n " + tels)
    if us_ph:
        ev["us_phone"] = us_ph[0]
    if tf_ph:
        ev["tollfree"] = tf_ph[0]
    addr = US_ADDRESS.search(text)
    if addr:
        ev["us_address"] = addr.group(0)[-60:]
    ship = US_SHIPPING.findall(text)
    if ship:
        ev["us_shipping"] = sorted({s.strip()[:60] for s in ship})[:3]
    if host.endswith(".us"):
        ev["us_tld"] = True
    if US_LOCALE.search(html):
        ev["en_us_locale"] = True
    ca_addr = CA_ADDRESS.search(text)
    ca_words = len(CANADA_WORDS.findall(text))

    usd = usd_code or (usd_prices >= 2 and not other_codes and other_prices <= usd_prices)
    dominant_other = None
    if other_codes and not usd_code:
        dominant_other = max(other_codes, key=other_codes.get)
    elif not usd and other_prices >= 3 and other_prices > usd_prices * 2:
        dominant_other = "non-USD prices"

    us_strong = []
    if country == "US":
        us_strong.append("shop_country=US")
    if us_ph:
        us_strong.append("us_phone")
    if addr:
        us_strong.append("us_address")
    if ship:
        us_strong.append("us_shipping")
    if host.endswith(".us"):
        us_strong.append("us_tld")
    us_medium = []
    if tf_ph:
        us_medium.append("tollfree")
    if ev.get("en_us_locale"):
        us_medium.append("en_us_locale")

    canada = (country == "CA") or (cur.get("CAD", 0) > 0 and not usd_code) or host.endswith(".ca") or bool(ca_addr) or bool(ca_ph and not us_ph)
    if canada:
        ev["canada_signals"] = [x for x, ok in (("shop_country=CA", country == "CA"), ("CAD", cur.get("CAD", 0) > 0),
                                                  (".ca", host.endswith(".ca")), ("ca_address", bool(ca_addr)),
                                                  ("ca_phone", bool(ca_ph)), ("canada_words", ca_words >= 3)) if ok]

    if dominant_other and not usd:
        if dominant_other == "CAD" or (canada and not us_strong):
            return "canada", ev, f"Canadian store ({dominant_other})"
        return "non_us", ev, f"non-US currency ({dominant_other})"
    if country and country != "US" and not usd:
        return ("canada" if country == "CA" else "non_us"), ev, f"store country {country}, no USD"
    if usd:
        if canada and not (country == "US" or addr or us_ph):
            if ship:
                return "weak", ev, "Canadian merchant signals with USD + US shipping (manual review)"
            return "canada", ev, "USD shown but Canadian merchant signals dominate"
        if us_strong:
            if country and country != "US" and not (addr or us_ph or ship):
                return "weak", ev, f"USD but store country {country}"
            return "us", ev, "USD + " + ", ".join(us_strong)
        if us_medium:
            return "weak", ev, "USD + only weak US signal (" + ", ".join(us_medium) + ")"
        return "weak", ev, "USD prices only, no second US signal"
    if us_strong:
        return "weak", ev, "US signals (" + ", ".join(us_strong) + ") but no USD prices seen"
    return "weak", ev, "no currency or US signals"


def classify_category(texts, weights=None):
    weights = weights or [1] * len(texts)
    acc = Counter()
    for t, w in zip(texts, weights):
        if not t:
            continue
        t = t[:40000]
        for name, rx in CATEGORY_RES:
            n = len(rx.findall(t))
            if n:
                acc[name] += w * min(n, 25)
    if not acc:
        return "General / Unclassified"
    return acc.most_common(1)[0][0]
