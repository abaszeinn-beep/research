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
    ("auto", ["قطع غيار سيارات", "إكسسوارات سيارات", "كفرات", "إطارات", "بطاريات سيارات", "زيوت محركات", "العناية بالسيارات", "تظليل", "قطع غيار دبابات"], ["auto parts", "car accessories", "tires", "car batteries", "motor oil", "car care", "motorcycle parts"]),
    ("grocery", ["مواد غذائية", "بقالة", "سوبرماركت", "عسل", "سمن بري", "بهارات", "زيت زيتون", "لحوم", "خضار وفواكه", "منتجات عضوية", "مكسرات", "أجبان"], ["grocery", "supermarket", "honey", "spices", "olive oil", "meat", "organic food", "nuts", "cheese"]),
    ("coffee", ["قهوة مختصة", "محمصة قهوة", "بن", "قهوة سعودية", "شاي", "تمور", "تمور سكري", "تمور المدينة", "أدوات قهوة"], ["specialty coffee", "coffee roastery", "coffee beans", "saudi coffee", "tea", "dates", "coffee equipment"]),
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

from . import market as MK

CITIES = MK.CITIES

AR_TEMPLATES = [
    "متجر {t} اونلاين الكويت",
    "{t} توصيل الكويت د.ك",
    "{t} متجر كويتي",
    "شراء {t} اون لاين الكويت كي نت",
]
EN_TEMPLATES = [
    "{t} online store Kuwait",
    "buy {t} online Kuwait KWD",
    "{t} shop Kuwait delivery KD",
    "site:com.kw {t}",
]
CITY_TEMPLATES = ["متجر {t} {c}", "{te} shop {ce} Kuwait"]

PLATFORM_QUERIES = [
    "\"powered by shopify\" Kuwait KWD", "myshopify Kuwait KWD", "\"KWD\" \"add to cart\" Kuwait", "\"د.ك\" \"أضف إلى السلة\"",
    "\"دينار كويتي\" متجر", "\"KNET\" online store Kuwait", "\"كي نت\" متجر الكتروني", "site:com.kw shop", "site:com.kw \"add to cart\"",
    "site:kw online store", "site:com.kw متجر", "inurl:en-kw shop", "inurl:ar-kw", "inurl:kw-en products", "inurl:/kw/en/ shop online",
    "ordable store Kuwait", "site:ordable.com", "expandcart Kuwait store", "salla Kuwait KWD متجر", "zid store Kuwait", "woocommerce Kuwait KWD",
    "\"free delivery\" Kuwait online shop", "\"توصيل مجاني\" داخل الكويت متجر", "\"ship to Kuwait\" official store", "official online store Kuwait",
    "\"المتجر الرسمي\" الكويت", "best online stores in Kuwait", "top online shopping sites Kuwait", "Kuwaiti online stores list",
    "أفضل المتاجر الإلكترونية في الكويت", "مواقع تسوق كويتية", "Kuwaiti brands online store", "homegrown Kuwaiti brands",
    "small business Kuwait online shop", "Kuwait instagram shops with website", "best perfume shops Kuwait online", "best abaya brands Kuwait online",
    "best coffee roasters Kuwait online", "Kuwait online grocery delivery stores", "Kuwait electronics online stores", "Kuwait furniture online stores",
    "The Avenues Kuwait store directory", "360 Mall Kuwait stores", "Al Kout Mall stores", "Marina Mall Kuwait stores", "Assima Mall stores",
    "Al Hamra Tower mall stores", "Gate Mall Kuwait stores", "Murouj Kuwait shops", "Souq Sharq stores", "Al Khiran Mall stores list",
    "Alshaya brands Kuwait", "Alghanim Industries retail brands", "Kuwait ecommerce awards", "Kuwait startup ecommerce brands",
]


def norm(q: str) -> str:
    toks = re.sub(r"[\"']", "", q.lower()).split()
    return " ".join(sorted(set(toks)))


def generate(seed=0):
    """Platform/listicle queries first, then niche queries interleaved round-robin across categories and
    languages so a partial run still covers every category; city long tail last."""
    rnd = random.Random(seed)
    out = [("platform", q) for q in PLATFORM_QUERIES]
    per_cat = []
    for cat, ar, en in NICHES:
        items = []
        for i in range(max(len(ar), len(en))):
            for tpl in AR_TEMPLATES:
                if i < len(ar):
                    items.append((cat, tpl.format(t=ar[i])))
            for tpl in EN_TEMPLATES:
                if i < len(en):
                    items.append((cat, tpl.format(t=en[i])))
        per_cat.append(items)
    for i in range(max(len(x) for x in per_cat)):
        for items in per_cat:
            if i < len(items):
                out.append(items[i])
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
