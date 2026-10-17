"""Diversified Arabic + English query generation (categories x niches x cities x platforms)."""
from __future__ import annotations

import itertools
import random
import re

# (category, [arabic terms], [english terms])
NICHES = [
    ("fashion", ["عبايات", "عبايات سوداء", "جلابيات", "ملابس نسائية", "فساتين سهرة", "ملابس محتشمة", "طرح وشيلات", "ملابس رجالية", "ثياب رجالية", "شماغ وغتر", "بشوت", "ملابس أطفال", "ملابس مواليد", "ملابس رياضية", "ملابس داخلية", "بيجامات", "مقاسات كبيرة", "زي موحد", "يونيفورم طبي", "تيشيرتات", "جينز", "ستريت وير"],
     ["abaya", "modest fashion", "women clothing", "evening dresses", "men thobes", "kids clothing", "sportswear", "lingerie", "pajamas", "plus size clothing", "uniforms", "streetwear", "hoodies", "scrubs medical uniforms"]),
    ("shoes", ["أحذية", "أحذية نسائية", "أحذية رجالية", "أحذية رياضية", "نعال", "صنادل شرقية", "أحذية أطفال"], ["shoes", "sneakers", "sandals", "kids shoes", "footwear"]),
    ("bags", ["حقائب نسائية", "شنط", "حقائب سفر", "شنط مدرسية", "محافظ رجالية"], ["handbags", "luggage", "backpacks", "wallets", "travel bags"]),
    ("jewelry", ["مجوهرات", "ذهب", "فضة", "إكسسوارات نسائية", "ساعات", "ساعات رجالية", "خواتم", "مسابح", "ألماس"], ["jewelry", "gold jewelry", "silver jewelry", "watches", "accessories", "diamonds", "prayer beads"]),
    ("beauty", ["مكياج", "مستحضرات تجميل", "العناية بالبشرة", "منتجات كورية", "رموش", "أظافر", "العناية بالشعر", "صبغات شعر", "منتجات طبيعية"], ["makeup", "cosmetics", "skincare", "korean skincare", "lashes", "nail polish", "hair care", "organic beauty"]),
    ("perfume", ["عطور", "عطور نسائية", "عطور رجالية", "عود", "بخور", "دهن عود", "مباخر", "مسك", "عطور فرنسية", "معطرات مفارش"], ["perfume", "oud", "bakhoor", "incense", "niche perfume", "attar", "musk", "home fragrance"]),
    ("grooming", ["عناية رجالية", "منتجات اللحية", "أدوات حلاقة", "مزيل عرق", "عناية شخصية"], ["men grooming", "beard care", "shaving", "personal care"]),
    ("electronics", ["إلكترونيات", "جوالات", "إكسسوارات جوال", "كفرات جوال", "شواحن", "سماعات", "لابتوبات", "قطع كمبيوتر", "شاشات", "كاميرات مراقبة", "أجهزة ذكية", "طابعات", "راوترات"], ["electronics", "mobile phones", "phone accessories", "phone cases", "chargers", "headphones", "laptops", "pc parts", "monitors", "cctv cameras", "smart home", "printers", "networking"]),
    ("gaming", ["ألعاب فيديو", "بلايستيشن", "إكسسوارات قيمنق", "كراسي قيمنق", "أجهزة ألعاب"], ["gaming", "playstation", "gaming accessories", "gaming chairs", "video games"]),
    ("appliances", ["أجهزة منزلية", "أجهزة مطبخ", "مكيفات", "غسالات", "ثلاجات", "مكانس كهربائية", "قلايات هوائية", "مكائن قهوة", "فلاتر مياه"], ["home appliances", "kitchen appliances", "air conditioners", "vacuum cleaners", "coffee machines", "water filters"]),
    ("furniture", ["أثاث", "أثاث منزلي", "كنب", "غرف نوم", "أثاث مكتبي", "أثاث خارجي", "جلسات خارجية", "طاولات", "مجالس عربية"], ["furniture", "sofas", "bedroom furniture", "office furniture", "outdoor furniture", "majlis"]),
    ("decor", ["ديكور", "ديكورات منزلية", "لوحات جدارية", "سجاد", "ستائر", "شموع", "تحف", "إضاءة"], ["home decor", "wall art", "rugs", "curtains", "candles", "lighting", "chandeliers"]),
    ("kitchen", ["أواني منزلية", "أواني طبخ", "أدوات مطبخ", "ترامس", "دلال قهوة", "أطقم ضيافة", "فناجين"], ["kitchenware", "cookware", "tableware", "thermos", "arabic coffee pots", "serveware"]),
    ("bedding", ["مفارش", "مراتب", "مخدات", "بطانيات", "مناشف", "أقمشة", "أقمشة رجالية"], ["bedding", "mattresses", "pillows", "blankets", "towels", "fabrics"]),
    ("hardware", ["عدد وأدوات", "أدوات كهربائية", "أدوات سباكة", "دهانات", "أدوات صحية", "معدات بناء", "مواد بناء", "سيراميك", "بلاط", "أبواب", "عوازل"], ["hardware tools", "power tools", "plumbing supplies", "paints", "sanitary ware", "building materials", "ceramic tiles", "doors"]),
    ("electrical", ["أدوات كهربائية", "إنارة", "ليد", "كيابل", "طاقة شمسية", "مولدات كهرباء"], ["electrical supplies", "led lighting", "cables", "solar panels", "generators"]),
    ("toys", ["ألعاب أطفال", "ألعاب تعليمية", "ليغو", "دمى", "ألعاب خارجية", "هوايات", "مجسمات", "طائرات درون"], ["toys", "educational toys", "lego", "dolls", "hobbies", "collectibles", "drones"]),
    ("baby", ["مستلزمات أطفال", "مستلزمات مواليد", "عربيات أطفال", "حفاضات", "مستلزمات الأمومة", "ملابس حوامل"], ["baby products", "baby gear", "strollers", "diapers", "maternity"]),
    ("books", ["كتب", "مكتبة", "روايات", "قرطاسية", "أدوات مدرسية", "أدوات مكتبية", "دفاتر", "أقلام"], ["books", "bookstore", "stationery", "school supplies", "office supplies", "notebooks", "pens"]),
    ("sports", ["أدوات رياضية", "معدات رياضية", "أجهزة رياضية", "مستلزمات تخييم", "رحلات برية", "صيد", "دراجات هوائية", "سكوترات", "معدات غوص", "مكملات رياضية"], ["sports equipment", "fitness equipment", "gym equipment", "camping gear", "fishing gear", "bicycles", "scooters", "diving gear", "outdoor gear"]),
    ("auto", ["قطع غيار سيارات", "إكسسوارات سيارات", "كفرات", "إطارات", "بطاريات سيارات", "زيوت محركات", "العناية بالسيارات", "تظليل", "قطع غيار دراجات نارية"], ["auto parts", "car accessories", "tires", "car batteries", "motor oil", "car care", "motorcycle parts"]),
    ("grocery", ["مواد غذائية", "بقالة", "سوبرماركت", "عسل", "سمن بري", "بهارات", "زيت زيتون", "لحوم", "خضار وفواكه", "منتجات عضوية", "مكسرات", "أجبان"], ["grocery", "supermarket", "honey", "spices", "olive oil", "meat", "organic food", "nuts", "cheese"]),
    ("coffee", ["قهوة مختصة", "محمصة قهوة", "بن", "قهوة عربية", "شاي", "تمور", "تمور سكري", "تمور خلاص", "أدوات قهوة"], ["specialty coffee", "coffee roastery", "coffee beans", "arabic coffee", "tea", "dates", "coffee equipment"]),
    ("sweets", ["شوكولاتة", "حلويات", "معمول", "كيك", "حلويات شرقية", "توزيعات"], ["chocolate", "sweets", "maamoul", "cakes", "candy"]),
    ("gifts", ["ورود", "هدايا", "تنسيق ورد", "توزيعات مناسبات", "مستلزمات حفلات", "بالونات", "تغليف هدايا", "هدايا رجالية"], ["flowers", "gifts", "florist", "party supplies", "balloons", "gift boxes"]),
    ("pets", ["مستلزمات حيوانات أليفة", "أكل قطط", "مستلزمات قطط", "مستلزمات طيور", "أحواض أسماك", "مستلزمات خيل"], ["pet supplies", "cat food", "dog food", "bird supplies", "aquarium", "equestrian"]),
    ("health", ["أجهزة طبية", "مستلزمات طبية", "صيدلية", "فيتامينات", "مكملات غذائية", "عدسات لاصقة", "نظارات", "مستلزمات أسنان", "كراسي متحركة"], ["medical equipment", "medical supplies", "pharmacy", "vitamins", "supplements", "contact lenses", "eyewear", "dental supplies", "wheelchairs"]),
    ("industrial", ["معدات صناعية", "معدات سلامة", "مضخات", "معدات لحام", "معدات مطاعم", "معدات مخابز", "معدات تبريد", "مستلزمات مصانع"], ["industrial equipment", "safety equipment", "pumps", "welding equipment", "restaurant equipment", "refrigeration equipment"]),
    ("agri", ["مستلزمات زراعية", "بذور", "أسمدة", "نباتات", "شتلات", "أدوات حدائق", "ري بالتنقيط"], ["agriculture supplies", "seeds", "fertilizers", "plants", "garden tools", "irrigation"]),
    ("components", ["قطع إلكترونية", "أردوينو", "حساسات", "روبوتات تعليمية"], ["electronic components", "arduino", "sensors", "robotics kits"]),
    ("religious", ["سجاد صلاة", "مصاحف", "مستلزمات العمرة", "ملابس إحرام", "هدايا إسلامية"], ["prayer mats", "quran", "umrah supplies", "ihram", "islamic gifts"]),
    ("crafts", ["أدوات رسم", "أدوات خياطة", "منتجات يدوية", "خرز", "ريزن", "كروشيه", "أدوات فنية"], ["art supplies", "sewing supplies", "handmade", "beads", "resin art", "craft supplies"]),
    ("b2b", ["بيع بالجملة", "مورد", "موزع معتمد", "توريدات", "تغليف", "مستلزمات مطاعم", "مستلزمات تنظيف", "منظفات"], ["wholesale", "supplier", "distributor", "packaging", "cleaning supplies", "b2b"]),
    ("department", ["متجر شامل", "هايبر ماركت", "منوعات", "أدوات منزلية"], ["department store", "hypermarket", "household items"]),
]

CITIES = [("الدوحة", "Doha"), ("الريان", "Al Rayyan"), ("الوكرة", "Al Wakrah"), ("لوسيل", "Lusail"), ("الخور", "Al Khor"),
          ("أم صلال", "Umm Salal"), ("الضعاين", "Al Daayen"), ("مسيعيد", "Mesaieed"), ("دخان", "Dukhan"), ("الشمال", "Al Shamal"),
          ("اللؤلؤة", "The Pearl"), ("الغرافة", "Al Gharrafa")]

AR_TEMPLATES = [
    "متجر {t} اونلاين قطر",
    "{t} الدوحة توصيل متجر",
    "شراء {t} اون لاين قطر ر.ق",
]
EN_TEMPLATES = [
    "{t} online store Qatar",
    "buy {t} online Doha QAR",
    "{t} shop Qatar delivery",
    "{t} online shopping qatar site:qa",
    "inurl:en-qa {t}",
]
CITY_TEMPLATES = ["متجر {t} {c}", "{te} store {ce} Qatar online"]

PLATFORM_QUERIES = [
    "myshopify qatar QAR", "\"QAR\" \"add to cart\" qatar", "\"ر.ق\" \"أضف إلى السلة\"", "\"ريال قطري\" متجر",
    "\"Qatari Riyal\" online store", "\"delivery all over Qatar\" shop", "\"free delivery in Doha\" shop",
    "\"cash on delivery\" Qatar online shop", "\"+974\" \"add to cart\"", "site:qa \"add to cart\"", "site:com.qa shop online",
    "site:qa woocommerce shop", "site:qa \"my cart\"", "inurl:en-qa shop", "inurl:qa-en products", "inurl:/qa/en/ shop online",
    "inurl:ar-qa shop", "inurl:qatar-en shop", "\"ship to Qatar\" official store", "\"official online store\" Qatar",
    "\"المتجر الرسمي\" قطر", "best online stores in Qatar", "top qatar ecommerce websites", "qatar online shopping sites list",
    "أفضل مواقع التسوق في قطر", "متاجر الكترونية قطرية", "homegrown qatari brands online store", "qatari brands online shop",
    "qatar made products online store", "منتجات قطرية متجر الكتروني", "best qatari perfume brands online", "qatari abaya brands online",
    "best coffee roasters in qatar online", "qatar small business online shop instagram website", "doha boutique online store",
    "villaggio mall stores list", "mall of qatar stores directory", "place vendome mall stores", "doha festival city stores list",
    "city center doha shops list", "lagoona mall stores", "tawar mall shops", "hyatt plaza doha shops", "gulf mall doha stores",
    "landmark mall doha shops", "the pearl qatar porto arabia shops", "qatar ecommerce awards winners", "qatar startup ecommerce brands",
    "shopify stores qatar", "woocommerce stores qatar", "magento qatar ecommerce website", "salla qatar store", "zid qatar store",
    "expandcart qatar store", "wix online store qatar", "opencart qatar shop", "bigcommerce qatar store",
    "qatar web design company ecommerce portfolio", "ecommerce development qatar our clients", "شركة تصميم متاجر الكترونية قطر اعمالنا",
]


def norm(q: str) -> str:
    toks = re.sub(r"[\"']", "", q.lower()).split()
    return " ".join(sorted(set(toks)))


def generate(seed=0):
    rnd = random.Random(seed)
    out = []
    for q in PLATFORM_QUERIES:
        out.append(("platform", q))
    for cat, ar, en in NICHES:
        for t in ar:
            for tpl in AR_TEMPLATES:
                out.append((cat, tpl.format(t=t)))
        for t in en:
            for tpl in EN_TEMPLATES:
                out.append((cat, tpl.format(t=t)))
    head, rest = out[:len(PLATFORM_QUERIES)], out[len(PLATFORM_QUERIES):]
    rnd.shuffle(rest)
    out = head + rest
    # city long tail: sample niche x city combos
    combos = []
    for cat, ar, en in NICHES:
        for (c_ar, c_en) in CITIES:
            t = rnd.choice(ar)
            te = rnd.choice(en)
            for tpl in CITY_TEMPLATES:
                combos.append((f"{cat}|city", tpl.format(t=t, c=c_ar, te=te, ce=c_en)))
    rnd.shuffle(combos)
    out.extend(combos)
    seen, uniq = set(), []
    for ws, q in out:
        n = norm(q)
        if n in seen:
            continue
        seen.add(n)
        uniq.append((ws, q))
    return uniq


if __name__ == "__main__":
    qs = generate()
    print(len(qs))
    for x in qs[:20]:
        print(x)
