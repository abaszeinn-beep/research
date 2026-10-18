import re, urllib.parse as up
STRONG_AR = "عبايات|عباية|عبايه|فساتين|فستان|ملابس|ثوب|ثياب|أثواب|اثواب|جلابية|جلابيات|جلابيه|بيجامات|بيجاما|لانجري|قمصان|بناطيل|بنطلون|تيشيرت|تيشرتات|هوديز|هودي|جاكيتات|بلوزات|بلوزة|تنانير|جينز|قفطان|كفتان|إسدال|اسدال|بشوت|مشلح|دشداشة|سراويل|أزياء|ازياء|موضة|تفصيل|ملابس داخلية|ثوب رجالي|سويتشيرت|كارديجان|معاطف"
STRONG_EN = r"abayas?|dress(?:es)?|kaftans?|caftans?|jalabiy(?:a|at)|jalabiya|thobes?|thawbs?|thobs|t-?shirts?|tees|hoodies?|sweatshirts?|jeans|trousers|skirts?|blouses?|lingerie|underwear|activewear|sportswear|apparel|clothing|clothes|garments|ready[- ]to[- ]wear|loungewear|pajamas?|pyjamas?|jumpsuits?|leggings|swimwear|bishts?|menswear|womenswear|knitwear|cardigans?|jackets?|shirts?|polo|pants|shorts|sweaters?|fashion|modest|dishdasha|shemagh|sleepwear|nightwear|streetwear|outerwear|coats?"
WEAK = set("تفصيل أزياء ازياء موضة fashion modest موضة أزياء ازياء jackets jacket coat coats shorts shemagh polo pants shirts shirt sweaters sweater".split())
KW = re.compile(r"(?<![a-z])(?:%s)(?![a-z])|%s" % (STRONG_EN, STRONG_AR), re.I)
WOMEN = re.compile(r"(?<![a-z])(?:women'?s?|womens|ladies|lady|female|abayas?|dress(?:es)?|lingerie|blouses?|skirts?|womenswear|kaftans?|maxi|jalabiy(?:a|at)|modest)(?![a-z])|نسائي|نسائية|نساء|حريمي|حريمية|عبايات|عباية|عبايه|فساتين|فستان|لانجري|بلوزة|بلوزات|تنانير|إسدال|اسدال|قفطان|كفتان|جلابية|للمرأة|المرأة", re.I)
MEN = re.compile(r"(?<![a-z])(?:men'?s?|mens|gents?|male|thobes?|thawbs?|thobs|menswear|bishts?|shemagh|ghutra|dishdasha)(?![a-z])|رجالي|رجالية|رجال|للرجال|ثوب|ثياب|أثواب|اثواب|شماغ|غترة|بشت|بشوت|مشلح|دشداشة", re.I)
UNI = re.compile(r"unisex|للجنسين|للجميع|يونيسكس", re.I)
KID = re.compile(r"(?<![a-z])(?:kids?|baby|babies|boys?|girls?|toddlers?|infants?|children|newborn|junior|teens?)(?![a-z])|أطفال|اطفال|طفل|مواليد|اولاد|أولاد|بنات|رضع|صغار", re.I)
ADULTCLOTH = re.compile(r"(?<![a-z])(?:women'?s?|womens|ladies|men'?s?|mens|unisex|adults?|abayas?|thobes?|lingerie|menswear|womenswear)(?![a-z])|رجالي|رجالية|نسائي|نسائية|نساء|رجال|حريمي|للجنسين|عبايات|عباية|عبايه|ثوب رجالي|لانجري", re.I)
def norm(s):
    return up.unquote(s or "").replace("-", " ").replace("_"," ").replace("+"," ")
def analyze(text):
    toks=[m.group(0).lower() for m in KW.finditer(text)]
    # 'fashion','modest','jacket..' alone are weak
    strong=[t for t in toks if t not in WEAK]
    d=dict(strong=sorted(set(strong))[:8], weak=sorted(set(t for t in toks if t in WEAK))[:5],
      women=bool(WOMEN.search(text)), men=bool(MEN.search(text)), uni=bool(UNI.search(text)),
      kid=bool(KID.search(text)), adult=bool(ADULTCLOTH.search(text)))
    return d
