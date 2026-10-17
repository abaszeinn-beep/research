"""US-relevance signals, storefront state detection and category classification."""
from __future__ import annotations

import html as htmllib
import re
from collections import Counter

PASSWORD_PAGE = re.compile(r"template-password|action=[\"']/password[\"']|id=[\"']password-page|"
                           r"<title>[^<]{0,80}(?:opening soon|coming soon|password)[^<]{0,40}</title>", re.I)
UNAVAILABLE = re.compile(r"this (?:shop|store) is (?:currently )?unavailable|store unavailable|"
                         r"sorry, this shop is currently unavailable|only one step left|"
                         r"there(?:&#39;|')s no page at this address|create your own online store|"
                         r"this store does not exist", re.I)
CHALLENGE = re.compile(r"just a moment\.\.\.|cf-chl|challenge-platform/h/|attention required! \| cloudflare|"
                       r"pardon our interruption|px-captcha|are you a robot|incapsula|ddos-guard|"
                       r"sucuri website firewall|access denied</title>|verify you are human", re.I)
ADD_TO_CART = re.compile(r"action=[\"'][^\"']*/cart/add|/cart/add\.js|add[ -]to[ -]cart|"
                         r"data-add-to-cart|product-form__submit|shopify-payment-button", re.I)
PRICE_CUR = re.compile(r"[\"']priceCurrency[\"']\s*:\s*[\"']([A-Z]{3})[\"']")
ACTIVE_CUR = re.compile(r"Shopify\.currency\s*=\s*\{\s*\"active\"\s*:\s*\"([A-Z]{3})\"")
OG_SITE = re.compile(r"<meta[^>]+property=[\"']og:site_name[\"'][^>]+content=[\"']([^\"']{1,120})", re.I)
TITLE = re.compile(r"<title[^>]*>\s*([^<]{1,200}?)\s*</title>", re.I | re.S)

STATES = ("AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|"
          "NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC")
STATE_NAMES = ("Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida|Georgia|Hawaii|"
               "Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|"
               "Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|"
               "New York|North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|"
               "South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|"
               "Wisconsin|Wyoming")
US_ADDRESS = re.compile(rf"\b(?:{STATES}|{STATE_NAMES}),?\s+(\d{{5}})(?:-\d{{4}})?\b")
PHONE = re.compile(r"(?:\+?1[\s.-]?)?\(?\b([2-9]\d{2})\)?[\s.-]([2-9]\d{2})[\s.-](\d{4})\b")
TEL_LINK = re.compile(r"href=[\"']tel:\+?1?[\s.()-]*([2-9]\d{2})[\s.()-]*([2-9]\d{2})[\s.-]*(\d{4})", re.I)
CA_AREA = {"204", "226", "236", "249", "250", "263", "289", "306", "343", "354", "365", "367", "368", "382", "403",
           "416", "418", "428", "431", "437", "438", "450", "468", "474", "506", "514", "519", "548", "579", "581",
           "584", "587", "604", "613", "639", "647", "672", "683", "705", "709", "742", "753", "778", "780", "782",
           "807", "819", "825", "867", "873", "879", "902", "905"}
NON_GEO_AREA = {"800", "888", "877", "866", "855", "844", "833", "900", "555", "456", "500", "533", "544", "566",
                "577", "588", "600", "700", "710"}
CARIB_AREA = {"242", "246", "264", "268", "284", "345", "441", "473", "649", "658", "664", "721", "758", "767",
              "784", "809", "829", "849", "868", "869", "876"}
US_SHIP = re.compile(r"free (?:standard |ground )?shipping (?:on |for )?(?:all )?(?:us|u\.s\.|usa|domestic|contiguous)|"
                     r"ships? (?:from|within|in) (?:the )?(?:usa|u\.s\.a?\.?|us\b|united states|america)|"
                     r"shipping (?:within|to) (?:the )?(?:usa|u\.s\.|united states|contiguous|lower 48)|"
                     r"contiguous (?:u\.s\.|us\b|united states)|lower 48|made in (?:the )?usa", re.I)


def visible_text(html: str) -> str:
    t = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", htmllib.unescape(t))


def us_contact_signals(html: str) -> dict:
    out = {}
    text = visible_text(html)
    m = US_ADDRESS.search(text)
    if m:
        out["us_address"] = text[max(0, m.start() - 40): m.end()].strip()[-80:].replace(";", ",")
    phones = []
    for a, b, c in TEL_LINK.findall(html) + PHONE.findall(text):
        if a in CA_AREA or a in CARIB_AREA:
            out.setdefault("ca_phone", f"({a}) {b}-{c}")
        elif a in NON_GEO_AREA:
            out.setdefault("tollfree_phone", f"({a}) {b}-{c}")
        else:
            phones.append(f"({a}) {b}-{c}")
    if phones:
        out["us_phone"] = phones[0]
    m = US_SHIP.search(text)
    if m:
        out["us_shipping_text"] = m.group(0)[:80]
    return out


def store_name_from_html(html: str) -> str:
    m = OG_SITE.search(html)
    if m:
        return htmllib.unescape(m.group(1)).strip()
    m = TITLE.search(html)
    if m:
        return htmllib.unescape(m.group(1)).strip()[:100]
    return ""


CATS = [
    ("Jewelry & Watches", r"jewel|necklace|bracelet|earring|\brings?\b|pendant|\bwatch(?:es)?\b|anklet|diamond|sterling silver|14k|gemstone|engagement"),
    ("Apparel & Fashion", r"shirt|\btee\b|tees\b|dress|hoodie|sweatshirt|\bpants\b|jeans|legging|jacket|coat\b|apparel|clothing|\btops?\b|skirt|shorts|swim|bikini|lingerie|\bbra\b|socks?\b|\bhats?\b|\bcaps?\b|beanie|scarf|tank|romper|jumpsuit|sweater|cardigan|blouse|outfit|uniform|pajama|joggers|polo|vest\b|kimono|boutique"),
    ("Footwear", r"shoes?\b|sneaker|\bboots?\b|sandal|slipper|\bheels?\b|loafer|footwear|clogs?\b|insoles?"),
    ("Bags & Accessories", r"\bbags?\b|handbag|purse|wallet|backpack|\btote|sunglass|eyewear|\bbelts?\b|keychain|accessor|luggage"),
    ("Beauty & Personal Care", r"skin ?care|serum|moisturi|cleanser|lotion|makeup|cosmetic|lipstick|lip gloss|mascara|\bnails?\b|hair ?care|shampoo|conditioner|fragrance|perfume|cologne|\bsoaps?\b|body wash|beard|\blash|\bwigs?\b|hair extension|deodorant|bath bomb|beauty|body butter|sunscreen"),
    ("Health & Wellness", r"supplement|vitamin|protein|capsule|probiotic|collagen|wellness|\bcbd\b|hemp|kratom|tincture|gumm(?:y|ies)|\bhealth|medical|first aid|\bbrace\b|massage|nutrition|electrolyte|pre-?workout"),
    ("Food & Beverage", r"coffee|\bteas?\b|snack|candy|chocolate|sauce|spice|seasoning|jerky|\bhoney\b|cookie|baked|\bfood|gourmet|\bwine|\bbeer\b|spirits|whiskey|bourbon|beverage|\bdrinks?\b|syrup|\bjam\b|popcorn|\bnuts\b|olive oil|\bbbq\b|\bmeat|seafood|cheese|pantry|bakery"),
    ("Home & Kitchen", r"candle|\bdecor|pillow|blanket|\bthrow\b|\brugs?\b|curtain|bedding|\bsheets?\b|towel|kitchen|cookware|\bmugs?\b|tumbler|drinkware|\bvases?\b|wall art|\bframes?\b|ornament|\bhome\b|lighting|\blamps?\b|planter|glassware|dinnerware|cutting board|wax melt|diffuser|housewares|cleaning"),
    ("Furniture", r"furniture|\bsofa|couch|\bchairs?\b|\btables?\b|\bdesks?\b|dresser|bed frame|mattress|cabinet|bookshelf|stool|ottoman|sectional"),
    ("Garden & Outdoor Living", r"garden|\bseeds?\b|\bplants?\b|\bgrills?\b|smoker|patio|\blawn|\bhose\b|fertiliz|greenhouse|hydroponic|bird feeder|succulent"),
    ("Pet Supplies", r"\bdogs?\b|\bcats?\b|\bpets?\b|leash|collar|harness|treats|aquarium|\bbirds?\b|\bhorses?\b|equine|litter|kibble|\bpuppy|\bkitten|reptile"),
    ("Baby & Kids", r"\bbaby|infant|toddler|\bkids\b|children|nursery|diaper|onesie|bodysuit|pacifier|stroller|teether|newborn"),
    ("Toys, Games & Hobbies", r"\btoys?\b|puzzle|board game|\bgames?\b|lego|plush|\bfigures?\b|collectible|trading card|\btcg\b|pokemon|funko|model kit|\bdice\b|hobby|anime|sports cards|booster"),
    ("Sports & Outdoors", r"fishing|hunting|camping|hiking|\bgolf|fitness|\bgym\b|\byoga|\bbikes?\b|cycling|\bski\b|snowboard|\bsurf|skate|outdoor|archery|kayak|paddle|tennis|pickleball|baseball|softball|football|basketball|soccer|hockey|lacrosse|boxing|martial|disc golf|climbing|running|workout|exercise|dumbbell|kettlebell|lure|\bbait\b|\breel\b|\brods?\b"),
    ("Firearms Accessories & Tactical", r"holster|\bammo\b|ammunition|\boptics?\b|\bscopes?\b|rifle|pistol|firearm|\bguns?\b|ar-?15|airsoft|tactical|\bmagazines?\b"),
    ("Automotive & Powersports", r"\bauto\b|automotive|\bcars?\b|\btrucks?\b|\bjeep|\bwheels?\b|\btires?\b|exhaust|brake|motorcycle|\batv\b|\butv\b|powersport|off-?road|light bar|bumper|suspension|turbo|intake|detailing|vehicle|\bbmw\b|\bford\b|chevy|toyota|honda|subaru|harley|\bjdm\b|car parts|\bsxs\b"),
    ("Electronics & Accessories", r"phone case|iphone|samsung|charger|\bcables?\b|headphone|earbud|speaker|electronic|\bcamera|\bdrones?\b|laptop|computer|keyboard|\bmouse\b|gaming|console|\bbattery|power bank|\baudio\b|\bpc\b|\busb\b|smart home|\bled\b"),
    ("Tools, Hardware & Industrial", r"\btools?\b|hardware|\bdrills?\b|\bsaws?\b|wrench|fastener|\bbolts?\b|\bscrews?\b|industrial|welding|plumbing|electrical|\bhvac\b|machine|equipment|\bsafety\b|janitorial|\bvalves?\b|fitting|generator|\bparts\b"),
    ("Arts, Crafts & Sewing", r"\byarn|fabric|sewing|quilt|\bcraft|\bbeads?\b|\bpaints?\b|canvas|brushes|embroider|\bknit|crochet|cricut|\bvinyl\b|\bstamps?\b|scrapbook|\bresin|art supplies|ribbon|\bdtf\b|transfers?\b|sublimation|blanks\b"),
    ("Books, Media & Stationery", r"\bbooks?\b|journal|notebook|planner|stationery|\bpens?\b|greeting card|\bprints?\b|poster|vinyl record|\blp\b|\bdvd\b|\bcomics?\b|calendar|sticker|paperback|hardcover|\balbum\b"),
    ("Gifts, Party & Seasonal", r"\bgifts?\b|party|balloon|personalized|christmas|halloween|wedding|\bfavors?\b|celebrat|engrav|gift basket|flowers?\b|florist|bouquet"),
    ("Vape, Smoke & Tobacco", r"\bvapes?\b|e-liquid|e-juice|cigars?\b|tobacco|hookah|shisha|glass pipe|\bbongs?\b|rolling paper|grinder|smoke shop|delta-?8|delta-?9|thca|disposable"),
    ("Religious & Spiritual", r"\bbible|christian|rosary|catholic|\bchurch|islamic|jewish|judaica|crystals?\b|tarot|spiritual|metaphysical"),
    ("Office & School Supplies", r"\boffice\b|school supplies|printer|toner|ink cartridge|\blabels?\b|packaging|shipping supplies"),
    ("Musical Instruments & Gear", r"guitar|\bbass\b|\bdrums?\b|piano|ukulele|violin|\bpedals?\b|\bamps?\b|amplifier|strings\b|synth|microphone|instrument"),
]
_CATS = [(n, re.compile(p, re.I)) for n, p in CATS]


def categorize(product_types, titles, tags, name="", description="") -> str:
    sc = Counter()
    for weight, texts in ((3, product_types), (1, titles), (1, tags), (2, [name, description])):
        for t in texts:
            if not t:
                continue
            for n, rx in _CATS:
                if rx.search(t):
                    sc[n] += weight
    if not sc:
        return "General Merchandise"
    return sc.most_common(1)[0][0]
