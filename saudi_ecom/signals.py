"""Page analysis: parked/closed detection, platform, ecommerce, Saudi relevance, category."""
from __future__ import annotations

import html as htmlmod
import json
import re
from collections import Counter

PARKED = re.compile(
    r"domain (?:name )?(?:is|may be) for sale|buy this domain|this domain is for sale|"
    r"parked (?:free|domain)|sedoparking|parkingcrew|bodis\.com|hugedomains|dan\.com/|afternic|"
    r"domain has expired|this domain has expired|renew (?:this|your) domain|"
    r"account (?:has been )?suspended|this account has been suspended|website (?:is )?expired|"
    r"الموقع (?:موقوف|معلق)|انتهت صلاحية|هذا النطاق للبيع|الدومين للبيع|"
    r"welcome to nginx|apache2? (?:ubuntu |debian )?default page|it works!|"
    r"index of /|default web site page|future home of something quite cool|"
    r"web hosting by|under construction|الموقع تحت الإنشاء|تحت الانشاء|"
    r"site not found|no such app|there is nothing here|domain not configured|"
    r"this site can.t be reached",
    re.I,
)
PARKED_TITLE = re.compile(r"coming soon|under construction|404|not found|قريبا|قريباً|parked|for sale|suspended|default page|welcome to nginx|index of", re.I)
CLOSED = re.compile(
    r"المتجر مغلق|المتجر (?:حاليا|حالياً) (?:قيد الصيانة|مغلق)|متجر مغلق|store is (?:currently )?closed|"
    r"store (?:is )?(?:temporarily )?unavailable|this store is unavailable|store unavailable|"
    r"temporarily closed|maintenance mode|we.ll be back soon|"
    r"المتجر غير متاح|المتجر متوقف|تم إيقاف المتجر|المتجر تحت الصيانة|المتجر في وضع الصيانة|"
    r"opening soon|password-page|enter store using password|"
    r"this shop is unavailable|sorry, this shop is currently unavailable",
    re.I,
)

PLATFORM_MARKERS = [
    ("salla", re.compile(r"cdn\.salla\.(?:sa|network)|salla\.network|twilight::init|salla-add-product|assets\.salla", re.I)),
    ("zid", re.compile(r"zid\.store|zidcdn|media\.zid\.store|zid-theme|zidstore|cdn\.zid\.|window\.zid|zid_store", re.I)),
    ("shopify", re.compile(r"cdn\.shopify\.com|Shopify\.theme|shopify-section|myshopify\.com", re.I)),
    ("woocommerce", re.compile(r"woocommerce|wc-ajax|wp-content/plugins/woocommerce|wc-block", re.I)),
    ("magento", re.compile(r"Magento_|mage/cookies|text/x-magento-init|/static/version\d+/frontend/", re.I)),
    ("salesforce-commerce", re.compile(r"demandware|/on/demandware\.store|dwanalytics|sfcc", re.I)),
    ("sap-hybris", re.compile(r"/_ui/responsive|hybris|ACC\.config", re.I)),
    ("opencart", re.compile(r"index\.php\?route=(?:product|common|checkout)|catalog/view/theme", re.I)),
    ("prestashop", re.compile(r"prestashop|/modules/ps_|var prestashop", re.I)),
    ("bigcommerce", re.compile(r"bigcommerce\.com|cdn\d*\.bigcommerce|stencil-utils", re.I)),
    ("expandcart", re.compile(r"expandcart", re.I)),
    ("youcan", re.compile(r"youcan\.shop|cdn\.youcan", re.I)),
    ("wix", re.compile(r"wixstores|static\.wixstatic\.com|wix-ecommerce", re.I)),
    ("ecwid", re.compile(r"ecwid|app\.ecwid\.com", re.I)),
    ("matjrah", re.compile(r"matjrah", re.I)),
    ("vtex", re.compile(r"vtex\.|vteximg", re.I)),
    ("nopcommerce", re.compile(r"nopcommerce|nop\.", re.I)),
    ("odoo", re.compile(r"/web/assets/|odoo|website_sale", re.I)),
    ("wuilt", re.compile(r"wuilt", re.I)),
]

ADD_TO_CART = re.compile(
    r"add[ -_]?to[ -_]?(?:cart|bag|basket)|addtocart|add-to-cart|buy now|shop now|"
    r"أضف (?:إلى|الى|ل|لل)?\s?(?:السلة|سلة|العربة)|اضف (?:إلى|الى|ل|لل)?\s?(?:السلة|سلة)|إضافة (?:إلى|الى|ل|لل)?\s?(?:السلة|سلة)|"
    r"اضافة (?:إلى|الى|لل)\s?(?:السلة|سلة)|أضف للسلة|اشتري الآن|اشتر الآن|شراء الآن|اطلب الآن|"
    r"salla-add-product-button|data-product-id|product-form|cart/add|\?add-to-cart=",
    re.I,
)
CART_CHECKOUT = re.compile(r"/cart\b|/checkout\b|/basket\b|سلة التسوق|السلة|عربة التسوق|إتمام الطلب|اتمام الطلب|checkout|mini-cart|cart-count|cart_count", re.I)
PRODUCT_LINK = re.compile(
    r"href=[\"'][^\"']*(?:/products?/[^\"'/?#]+|/p\d{5,}|/p/[^\"'/?#]+|-p-\d+|/item/[^\"'/?#]+|/dp/|"
    r"product_id=\d+|route=product/product|/product-page/|/[a-z0-9-]+-\d{4,}\.html|/buy-[^\"'/?#]+|/pd/)[^\"']*[\"']",
    re.I,
)
PRICE_SAR = re.compile(r"(?:\d[\d,.]*\s*(?:ر\.?\s?س|SAR|ريال|﷼|SR\b))|(?:(?:SAR|ر\.?\s?س|SR|﷼)\s*\d)", re.I)
PRICE_ANY = re.compile(r"(?:\d[\d,.]*\s*(?:AED|د\.إ|KWD|د\.ك|QAR|ر\.ق|BHD|OMR|USD|EGP|ج\.م|JOD|\$|€|£))|(?:(?:AED|KWD|QAR|BHD|OMR|USD|EGP|\$|€|£)\s*\d)", re.I)
SAR_CURRENCY_CODE = re.compile(r"[\"'](?:currency|currency_code|currencyCode|priceCurrency|active)[\"']\s*:\s*[\"']SAR[\"']|data-currency=[\"']SAR|Shopify\.currency\s*=\s*\{[^}]*SAR|currency=SAR|<meta[^>]+(?:product:price:currency|og:price:currency)[^>]+SAR", re.I)
OTHER_CURRENCY_CODE = re.compile(r"[\"'](?:currency|currency_code|currencyCode|priceCurrency|active)[\"']\s*:\s*[\"'](AED|KWD|QAR|BHD|OMR|USD|EGP|JOD|EUR|GBP|MAD|TRY|INR|PKR)[\"']", re.I)

SAUDI_PHONE = re.compile(r"(?:\+|00)\s?966[\s\-]?\(?\d|(?<!\d)05\d[\s\-]?\d{3}[\s\-]?\d{4}(?!\d)|(?<!\d)9200\d{5}(?!\d)|(?<!\d)800\s?\d{3}\s?\d{4}(?!\d)|wa\.me/966|api\.whatsapp\.com/send\?phone=966")
VAT = re.compile(r"(?<!\d)3\d{13}3(?!\d)")
CR = re.compile(r"(?:سجل تجاري|السجل التجاري|رقم السجل|س\.ت|commercial registration|C\.?R\.? ?(?:No|Number|#)|CR ?No)\s*[:.#]?\s*\d{7,10}", re.I)
MAROOF = re.compile(r"maroof\.sa|معروف", re.I)
SAUDI_WORDS = re.compile(
    r"المملكة العربية السعودية|السعودية|Saudi Arabia|\bKSA\b|Kingdom of Saudi|"
    r"الرياض|جدة|جده|مكة|المدينة المنورة|الدمام|الخبر|الظهران|الطائف|أبها|ابها|خميس مشيط|تبوك|حائل|بريدة|عنيزة|الجبيل|الأحساء|الاحساء|جازان|جيزان|نجران|الباحة|القصيم|ينبع|القطيف|الخرج|"
    r"\bRiyadh\b|\bJeddah\b|\bJiddah\b|\bMakkah\b|\bMecca\b|\bMadinah\b|\bMedina\b|\bDammam\b|\bKhobar\b|\bDhahran\b|\bTaif\b|\bAbha\b|Khamis Mushait|\bTabuk\b|\bHail\b|\bBuraydah\b|\bUnaizah\b|\bJubail\b|Al[ -]Ahsa|\bJazan\b|\bJizan\b|\bNajran\b|Al[ -]Baha|\bQassim\b|\bYanbu\b|\bQatif\b",
    re.I,
)
SAUDI_PAY_SHIP = re.compile(r"\bmada\b|مدى|stc ?pay|سمسا|\bSMSA\b|SPL|سبل|البريد السعودي|Saudi Post|ناقل|naqel|\bAJEX\b|أرامكس|aramex|zajil|زاجل|redbox|تمارا|tamara|تابي|tabby|ضريبة القيمة المضافة|VAT", re.I)
SA_LOCALE = re.compile(r"(?:lang|hreflang|content)=[\"'](?:ar|en)[-_]SA[\"']|/(?:en|ar)[-_]sa/|/sa[-_](?:en|ar)/|og:locale[\"'][^>]*(?:ar|en)_SA", re.I)

# Exclusions
DIGITAL = re.compile(
    r"بطاقات? (?:رقمية|شحن|سوا|ايتونز|قوقل|بلايستيشن|ستيم)|بطاقات الألعاب|شحن (?:ألعاب|العاب|شدات|جواهر)|شدات|ببجي|pubg|free ?fire|فري فاير|"
    r"gift ?cards?|digital (?:cards?|codes?|products?)|اشتراك(?:ات)? (?:نتفلكس|شاهد|سناب|بلس)|netflix|shahid|spotify|"
    r"itunes|playstation (?:plus|network) card|steam (?:wallet|card)|razer gold|"
    r"دورات? (?:تدريبية|اونلاين|أونلاين)|كورس(?:ات)?|online courses?|ebooks?|كتب إلكترونية|ملفات (?:رقمية|pdf)|قوالب|templates|"
    r"تصاميم جاهزة|متابعين|followers|likes|خدمات (?:رقمية|التسويق|السوشيال)|استضافة|hosting|vpn|software licen[cs]e|مفاتيح تفعيل|license keys?",
    re.I,
)
SERVICE = re.compile(
    r"حجز (?:موعد|مواعيد)|احجز (?:موعدك|الآن)|book (?:an )?appointment|booking|عيادة|clinic|صالون|salon|spa\b|"
    r"خدمات (?:تنظيف|نقل|صيانة|التصميم|الشحن|قانونية|محاسبية)|cleaning services|moving services|استشارات|consulting|"
    r"تأجير|rent(?:al)?s?\b|عقارات|real estate|تأشيرات|visa services|travel agency|حجوزات الطيران|توظيف|recruitment|"
    r"تصميم (?:مواقع|شعارات|جرافيك)|web design|marketing agency|وكالة تسويق|برمجة تطبيقات",
    re.I,
)
CHARITY = re.compile(r"جمعية|خيري|خيرية|تبرع|تبرعات|كفالة يتيم|كفالة|صدقة|زكاة|وقف خيري|أوقاف|donat(?:e|ion)|charity|sadaqah|zakat|non-?profit|غير ربحية", re.I)
ORG = re.compile(r"نادي|جمعية|مستشفى|hospital|جامعة|university|مدرسة|مدارس|school|academy|أكاديمية|معهد|institute|كلية|college|وزارة|ministry|هيئة|authority|بلدية|municipality|غرفة تجارية|chamber of commerce|مجمع طبي|مجمع [^ ]+ الطبي|مجمع [^ ]+ [^ ]+ الطبي|مركز طبي|educational|تعليمي|تعليمية|medical (?:complex|center)|عيادات|clinics|منصة|platform|مكتب محاماة|law firm|مكتب هندسي|consultants?|استشارات|شركة مقاولات|contracting|نقابة|federation|اتحاد", re.I)
RESTAURANT = re.compile(r"food menu|restaurant menu|قائمة الطعام|المنيو|مطعم|restaurant|order food|اطلب وجبتك|وجبات|meals?\b|burger|برجر|pizza|بيتزا|شاورما|shawarma|كافيه|cafe\b|توصيل الطعام|food delivery", re.I)

CATEGORIES = [
    ("Perfumes & Oud", r"عطر|عطور|perfume|fragrance|parfum|oud|عود|بخور|bakhoor|bukhoor|مسك|musk|دهن|عنبر|المباخر|مبخرة"),
    ("Beauty & Cosmetics", r"مكياج|makeup|cosmetic|تجميل|skincare|skin care|العناية بالبشرة|بشرة|سيروم|serum|lipstick|أظافر|nail|رموش|lashes|beauty"),
    ("Personal Care & Grooming", r"عناية شخصية|personal care|حلاقة|shaving|beard|لحية|grooming|شامبو|shampoo|العناية بالشعر|hair care|deodorant|مزيل"),
    ("Fashion - Abayas & Modest", r"عباي|abaya|جلابي|jalabiya|طرح|hijab|حجاب|modest|نقاب|شيلة|كاب|جلابية|دراعة|بشت|bisht"),
    ("Fashion - Men", r"ثوب|ثياب|أثواب|thobe|شماغ|shemagh|غتر|غترة|menswear|رجالي|men.s clothing|ملابس رجالية|بدل رجالية"),
    ("Fashion - Women", r"فساتين|فستان|dress(?:es)?|نسائي|women.s (?:clothing|fashion)|ملابس نسائية|بلايز|تنانير|lingerie|لانجري|ملابس داخلية"),
    ("Fashion - Kids", r"ملابس اطفال|ملابس أطفال|kids.? (?:wear|clothing|fashion)|children.s clothing|ملابس مواليد"),
    ("Fashion - Sportswear & Streetwear", r"sportswear|activewear|ملابس رياضية|streetwear|hoodies?|هوديز|sneakers|سنيكرز"),
    ("Fashion & Apparel", r"ملابس|أزياء|ازياء|fashion|apparel|clothing|clothes|t-?shirts?|تيشيرت|قمصان|بناطيل|jeans|جينز|uniforms?|يونيفورم|زي موحد"),
    ("Shoes", r"أحذية|احذية|حذاء|shoes|footwear|نعال|صنادل|sandals|boots|كعب"),
    ("Bags & Luggage", r"حقائب|شنط|شنطة|bags?\b|handbags?|luggage|backpacks?|wallets?|محافظ|حقيبة"),
    ("Jewelry & Watches", r"مجوهرات|jewel|ذهب|فضة|خواتم|earrings?|اساور|أساور|bracelets?|قلادة|قلائد|necklaces?|ساعات يد|ساعات رجالية|ساعات نسائية|ساعة يد|wrist ?watch(?:es)?|watches|ألماس|diamonds?|مسابح"),
    ("Mobiles & Accessories", r"جوال|جوالات|mobiles?|phones?|iphone|ايفون|سامسونج|samsung|كفرات|cases?\b|شواحن|chargers?|سماعات|earbuds|airpods|power ?bank"),
    ("Computers & Electronics", r"كمبيوتر|computers?|laptops?|لابتوب|حاسب|electronics|إلكترونيات|الكترونيات|شاشات|monitors?|printers?|طابعات|كاميرات|cameras?|تلفزيون|tv\b|smart home|راوتر|networking|قطع كمبيوتر|pc parts"),
    ("Gaming", r"gaming|ألعاب الفيديو|العاب فيديو|بلايستيشن|playstation|xbox|nintendo|اكس بوكس|قيمنق|قيمينق|gamers?"),
    ("Home Appliances", r"أجهزة منزلية|اجهزة منزلية|appliances?|غسالات|washing machines?|ثلاجات|refrigerators?|مكيفات|air conditioners?|مكانس|vacuum|خلاطات|blenders?|قلاية|air fryer"),
    ("Furniture", r"أثاث|اثاث|furniture|كنب|sofas?|كراسي|chairs?|طاولات|tables?|غرف نوم|bedroom|مجالس|خزائن|wardrobes?"),
    ("Home Decor", r"ديكور|decor|تحف|لوحات|wall art|مزهريات|vases?|شموع|candles?|سجاد|rugs?|carpets?|ستائر|curtains?|إضاءة ديكورية|home accessories"),
    ("Kitchenware & Tableware", r"أواني|اواني|kitchenware|cookware|مطبخ|kitchen|قدور|pots?\b|صحون|plates?|أكواب|cups?|mugs?|ترامس|ثيرموس|thermos|دلال|فناجين|tableware|ضيافة"),
    ("Bedding, Mattresses & Textiles", r"مفارش|bedding|مراتب|مرتبة|mattress|بطانيات|blankets?|وسائد|pillows?|شراشف|sheets|مناشف|towels?|textiles?|أقمشة|اقمشة|fabrics?"),
    ("Home Improvement & Hardware", r"عدد يدوية|العدد والأدوات|أدوات صحية|سباكة|plumbing|hardware|أدوات يدوية|hand tools|power tools|دهانات|paints?|بويات|home improvement|tools?\b"),
    ("Lighting & Electrical", r"إضاءة|اضاءة|lighting|lamps?|ثريات|chandeliers?|led\b|كهربائية|electrical|أفياش|كيابل|cables?|switches"),
    ("Building Materials", r"مواد بناء|building materials|سيراميك|ceramic|بلاط|tiles?|رخام|marble|حديد|steel|اسمنت|cement|أخشاب|wood panels|عوازل|insulation|بورسلان|porcelain"),
    ("Industrial & Tools", r"معدات صناعية|industrial|مصانع|machinery|مكائن|معدات|equipment|safety equipment|معدات السلامة|compressors?|generators?|مولدات|pumps?|مضخات|لحام|welding"),
    ("Electronic Components", r"arduino|raspberry|قطع إلكترونية|electronic components|sensors?|حساسات|موديولات|modules|resistors?|مقاومات|pcb|microcontroller"),
    ("Toys & Hobbies", r"ألعاب أطفال|العاب اطفال|toys?|دمى|dolls?|lego|ليغو|puzzles?|بازل|hobby|hobbies|ألعاب تعليمية|educational toys|rc cars?"),
    ("Baby & Maternity", r"مواليد|رضع|baby|babies|حفاضات|diapers?|maternity|أمومة|امومة|عربات أطفال|strollers?|car seats?|رضاعات|bottles"),
    ("Books & Stationery", r"كتب|books?|مكتبة|library|bookstore|قرطاسية|stationery|أدوات مدرسية|school supplies|دفاتر|notebooks?|أقلام|pens?\b|روايات|novels?"),
    ("Office Supplies", r"مستلزمات مكتبية|office supplies|أدوات مكتبية|ورق تصوير|copy paper|حبر|ink|toner|أحبار|office furniture"),
    ("Sports, Fitness & Outdoor", r"رياضة|رياضي|sports?\b|fitness|لياقة|gym|جيم|camping|تخييم|رحلات|outdoor|صيد|fishing|hunting|مقناص|bicycles?|دراجات|bikes?\b|scooters?|سكوتر|يوغا|yoga|كرة|ball"),
    ("Automotive Parts & Accessories", r"قطع غيار|spare parts|auto parts|سيارات|cars?\b|automotive|إكسسوارات سيارات|car accessories|زيوت|motor oil|كفرات|إطارات|اطارات|tires?|tyres?|بطاريات|batteries|car care|تلميع|عناية بالسيارة"),
    ("Grocery & Food", r"بقالة|grocery|groceries|سوبر ?ماركت|supermarket|مواد غذائية|food products|أغذية|اغذية|معلبات|بهارات|spices|توابل|أرز|rice|زيت زيتون|olive oil|عسل|honey|سمن|ghee|لحوم|meat|دواجن|poultry|خضار|vegetables|فواكه|fruits?|مخبوزات|bakery|ألبان|dairy"),
    ("Coffee, Tea & Dates", r"قهوة|coffee|البن|محمصة|roastery|roasters?|شاي|tea\b|تمور|تمر|dates\b|espresso|اسبريسو|مختص|specialty coffee|هيل|cardamom"),
    ("Chocolates & Sweets", r"شوكولات|chocolate|حلويات|sweets|حلا|كيك|cakes?|معمول|maamoul|حلقوم|candy|حلاوة|بسكويت|cookies|كوكيز|desserts?"),
    ("Flowers, Gifts & Party", r"ورد|زهور|flowers?|florist|هدايا|gifts?|توزيعات|party|حفلات|بالونات|balloons?|تغليف|wrapping|مناسبات|events supplies|بوكيه|bouquet"),
    ("Pets", r"حيوانات أليفة|pets?\b|قطط|cats?\b|كلاب|dogs?\b|طيور|birds?|أسماك الزينة|aquarium|أكل قطط|cat food|dog food|بيطري|veterinary"),
    ("Pharmacy & Wellness", r"صيدلية|pharmacy|أدوية|medicines?|فيتامينات|vitamins?|مكملات غذائية|supplements?|بروتين|protein|wellness|صحة|health|أعشاب|herbs|طب بديل|عسل علاجي"),
    ("Healthcare & Medical Equipment", r"أجهزة طبية|medical (?:devices|equipment|supplies)|مستلزمات طبية|طبي|surgical|جراحية|dental|أسنان|كراسي متحركة|wheelchairs?|مختبر|laboratory|عدسات لاصقة|contact lenses|نظارات|eyewear|optical|بصريات"),
    ("Agriculture & Gardening", r"زراعة|زراعية|agricultur|garden|حدائق|نباتات|plants?|بذور|seeds|أسمدة|fertilizers?|شتلات|ري بالتنقيط|irrigation|مشاتل|nursery"),
    ("Religious Products", r"سجاد صلاة|prayer mats?|مصاحف|quran|مصحف|إسلامي|islamic|سبح|tasbih|إحرام|ihram|حج|عمرة|umrah|hajj"),
    ("Arts, Crafts & Handmade", r"يدوي|handmade|حرف|crafts?|رسم|art supplies|أدوات رسم|خياطة|sewing|تطريز|embroidery|خرز|beads|كروشيه|crochet|resin|ريزن"),
    ("Wholesale & B2B", r"جملة|wholesale|بالجملة|b2b|موزع|distributor|توريد|supplier|مورد|تجار الجملة|bulk"),
    ("Department Store / General", r"department store|hypermarket|هايبر|متجر شامل|كل ما تحتاجه|everything you need|منوعات|متنوعة|general store|variety"),
    ("Packaging & Supplies", r"تغليف|packaging|علب تغليف|أكياس ورقية|طباعة الكرتون|printing services|ملصقات|stickers?"),
    ("Cleaning & Household Supplies", r"منظفات|cleaning|detergents?|household|مناديل|tissues?|معطرات|air fresheners?|تنظيف"),
]
AR = "\u0600-\u06FF"


def _wrap(alt: str) -> str:
    if re.search(f"[{AR}]", alt):
        return f"(?<![{AR}])(?:و|ب|ل|ف)?(?:ال|لل)?(?:{alt})(?:ات|ة|ي|ية|ين|ون|ها|ه)?(?![{AR}])"
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
    m = re.search(r"<meta[^>]+(?:property|name)=[\"']%s[\"'][^>]*content=[\"']([^\"']*)" % re.escape(name), html, re.I)
    if not m:
        m = re.search(r"<meta[^>]+content=[\"']([^\"']*)[\"'][^>]*(?:property|name)=[\"']%s[\"']" % re.escape(name), html, re.I)
    return htmlmod.unescape(m.group(1)).strip() if m else None


def title_of(html: str):
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    return re.sub(r"\s+", " ", htmlmod.unescape(m.group(1))).strip() if m else ""


GENERIC_TITLE_PARTS = re.compile(
    r"^(?:home|home ?page|الرئيسية|الصفحة الرئيسية|welcome|official (?:site|store|website|online store)|online (?:store|shop|shopping)|"
    r"متجر إلكتروني|المتجر الإلكتروني|shop|store|index|saudi arabia|ksa|saudi arabia ksa|المملكة العربية السعودية|السعودية|"
    r"shop online|تسوق اونلاين|تسوق أونلاين|default|main|homepage)$", re.I)


def _norm_letters(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def store_name(html: str, fallback: str, host: str = "") -> str:
    label = ""
    if host:
        h = host.lower().split(":")[0]
        h = re.sub(r"^www\d?\.", "", h)
        label = h.split(".")[0] if not h.endswith(("zid.store", "myshopify.com")) else h.split(".")[0]
        label = _norm_letters(label)
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


def detect_platform(html: str, url: str):
    found = []
    for name, rx in PLATFORM_MARKERS:
        if rx.search(html[:400000]):
            found.append(name)
    if "salla.sa/" in url:
        found.insert(0, "salla")
    if ".zid.store" in url:
        found.insert(0, "zid")
    if ".myshopify.com" in url:
        found.insert(0, "shopify")
    # precedence: specific SaaS before generic
    for p in ["salla", "zid", "shopify", "magento", "salesforce-commerce", "sap-hybris", "woocommerce", "opencart",
              "prestashop", "bigcommerce", "expandcart", "youcan", "matjrah", "wuilt", "ecwid", "wix", "vtex", "nopcommerce", "odoo"]:
        if p in found:
            return p
    return "custom/unknown"


def jsonld_types(html: str):
    types = set()
    offers_currency = set()
    for m in re.finditer(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", html, re.I | re.S):
        blob = m.group(1)
        types.update(re.findall(r"\"@type\"\s*:\s*\"([A-Za-z]+)\"", blob))
        offers_currency.update(x.upper() for x in re.findall(r"\"priceCurrency\"\s*:\s*\"([A-Za-z]{3})\"", blob))
    return types, offers_currency


def saudi_signals(html: str, text: str, url: str, final_url: str, platform: str, api_currency: set | None = None):
    ev = {}
    score = 0.0
    host = re.sub(r"^https?://", "", final_url).split("/")[0].lower()
    if (host.endswith(".sa") or host.endswith(".sa.")) and host not in ("salla.sa", "www.salla.sa", "s.salla.sa"):
        ev["sa_tld"] = host
        score += 2.5
    if SA_LOCALE.search(html[:300000]) or re.search(r"/(?:en|ar)[-_]sa\b|/sa[-_](?:en|ar)\b|/sa/|/saudi", final_url, re.I) or host.split(".")[0] in {"sa", "ksa", "saudi"}:
        ev["sa_locale"] = True
        score += 2.5
    sar_prices = len(PRICE_SAR.findall(text))
    sar_code = bool(SAR_CURRENCY_CODE.search(html[:600000]))
    if api_currency and "SAR" in api_currency:
        sar_code = True
    if sar_code:
        ev["currency_SAR_code"] = True
        score += 2.5
    if sar_prices:
        ev["sar_prices"] = sar_prices
        score += 2.0 if sar_prices >= 2 else 1.0
    oc = set(x.upper() for x in OTHER_CURRENCY_CODE.findall(html[:600000]))
    if oc and not sar_code and not sar_prices:
        ev["other_currency"] = sorted(oc)
        score -= 2
    ph = SAUDI_PHONE.findall(html[:600000])
    if ph:
        ev["saudi_phone"] = ph[0].strip()[:20]
        score += 2.0
    v = VAT.findall(text)
    if v:
        ev["vat_number"] = v[0]
        score += 2.0
    if CR.search(text):
        ev["commercial_registration"] = True
        score += 1.5
    if MAROOF.search(html[:600000]):
        ev["maroof"] = True
        score += 1.0
    words = SAUDI_WORDS.findall(text)
    if words:
        ev["saudi_places"] = sorted(set(w for w in words))[:5]
        score += 1.5 if len(words) >= 2 else 1.0
    pay = SAUDI_PAY_SHIP.findall(text)
    if pay:
        ev["saudi_payment_shipping"] = sorted(set(p.lower() for p in pay))[:5]
        score += 0.5 if len(set(pay)) < 2 else 1.0
    if platform in ("salla", "zid"):
        ev["saudi_platform"] = platform
        score += 1.5
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
    scores.sort(reverse=True)
    if not scores:
        return "General / Unclassified", ""
    top = scores[0][1]
    second = scores[1][1] if len(scores) > 1 and scores[1][0] >= max(2, scores[0][0] * 0.5) else ""
    return top, second
