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

CITIES = [("الرياض", "Riyadh"), ("جدة", "Jeddah"), ("مكة", "Makkah"), ("المدينة المنورة", "Madinah"), ("الدمام", "Dammam"),
          ("الخبر", "Khobar"), ("الظهران", "Dhahran"), ("الطائف", "Taif"), ("أبها", "Abha"), ("خميس مشيط", "Khamis Mushait"),
          ("تبوك", "Tabuk"), ("حائل", "Hail"), ("بريدة", "Buraydah"), ("عنيزة", "Unaizah"), ("الجبيل", "Jubail"),
          ("الأحساء", "Al Ahsa"), ("جازان", "Jazan"), ("نجران", "Najran"), ("الباحة", "Al Bahah"), ("القصيم", "Qassim"),
          ("ينبع", "Yanbu"), ("القطيف", "Qatif"), ("الخرج", "Al Kharj"), ("سكاكا", "Sakaka"), ("عرعر", "Arar")]

AR_TEMPLATES = [
    "site:salla.sa {t}",
    "site:zid.store {t}",
    "متجر {t} اونلاين السعودية",
    "{t} متجر الكتروني شحن لجميع مناطق المملكة",
    "\"ر.س\" {t} أضف للسلة",
    "شراء {t} اون لاين توصيل الرياض",
    "{t} متجر سعودي",
]
EN_TEMPLATES = [
    "{t} online store Saudi Arabia",
    "buy {t} online KSA SAR",
    "{t} shop Riyadh delivery",
    "inurl:en-sa {t}",
    "site:com.sa {t} shop",
    "{t} myshopify Saudi Arabia SAR",
]
CITY_TEMPLATES = ["متجر {t} {c}", "site:salla.sa {t} {c}", "{te} store {ce} online"]

PLATFORM_QUERIES = [
    "\"تم التطوير بواسطة سلة\"", "\"مدعوم من سلة\"", "\"powered by salla\"", "\"powered by zid\"", "\"تشغيل زد\"",
    "\"متجر إلكتروني على منصة سلة\"", "\"cdn.salla.sa\"", "\"media.zid.store\"", "\"ريال سعودي\" \"أضف إلى السلة\"",
    "\"Saudi Riyal\" \"add to cart\"", "\"سجل تجاري\" \"أضف للسلة\"", "\"الرقم الضريبي\" متجر", "\"معروف\" متجر الكتروني",
    "site:*.com.sa \"أضف إلى السلة\"", "site:*.sa \"add to cart\"", "inurl:ar-sa shop", "inurl:sa-en products",
    "inurl:/sa/en/ shop online", "\"Free shipping\" \"Saudi Arabia\" \"SAR\"", "\"شحن مجاني\" \"داخل المملكة\" متجر",
    "\"ship to Saudi Arabia\" brand official store", "\"official online store\" KSA", "\"المتجر الرسمي\" السعودية",
    "قائمة أفضل المتاجر الإلكترونية السعودية", "best online stores in Saudi Arabia", "top saudi ecommerce websites",
    "متاجر سلة المميزة", "أشهر متاجر زد", "قائمة متاجر سلة", "دليل المتاجر الإلكترونية السعودية",
    "Saudi DTC brands online", "homegrown saudi brands online store", "علامات تجارية سعودية متجر الكتروني",
    "best saudi perfume brands online", "best saudi abaya brands online", "best saudi coffee roasters online",
    "mall of arabia jeddah stores list", "riyadh park mall stores", "red sea mall stores list", "kingdom centre mall stores",
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
