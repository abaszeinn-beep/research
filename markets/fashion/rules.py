import re,json
STRONG=re.compile(r"^(abayas?|abayat|kandura|kanduras|thobe|thawb|jalabiyah?|kaftan|caftan|dress(es)?|gowns?|skirts?|blouses?|t-?shirts?|tshirts?|tees?|shirts?|polos?|jeans|denim|trousers|pants|leggings|joggers|hoodies?|sweatshirts?|sweaters?|knitwear|blazers?|lingerie|underwear|bras?|panties|innerwear|sleepwear|pyjamas?|pajamas?|loungewear|swimwear|activewear|sportswear|apparel|clothing|clothes|menswear|womenswear|ready.?to.?wear|hijab|jumpsuits?|cardigans?|streetwear|co-?ords|عباي[ةات]|عبايات|فساتين|فستان|ملابس|كندورة|كنادير|ثوب|جلابية|قمصان|تيشيرت|بناطيل|ازياء|أزياء|هوديز|حجاب|بيجاما|ملابس رياضية|ملابس داخلية)$",re.I)
NONFASH=('Pets','Industrial & Tools','Wholesale & B2B','Automotive Parts & Accessories','Building Materials','Packaging & Supplies','Healthcare & Medical Equipment','Furniture','Home Improvement & Hardware','Computers & Electronics','Agriculture & Gardening','Electronic Components','Lighting & Electrical','Cleaning & Household Supplies','Office Supplies','Books & Stationery','Religious Products','Flowers, Gifts & Party','Grocery & Food','Coffee, Tea & Dates','Chocolates & Sweets','Home Decor','Kitchenware & Tableware','Home Appliances')
B2B=re.compile(r"uniforms?|workwear|corporate|wholesale|\bb2b\b|safety|scrubs|promotional|custom\s?(t-?shirt|print)|printing|laundry|dry.?clean",re.I)
KIDT=re.compile(r"\bkids?\b|\bbaby\b|children|toddler|infant|أطفال|اطفال|newborn|\bboys?\b|\bgirls?\b",re.I)
def classify(r,cat,name):
    T=r.get('terms',{})
    full=r.get('terms',{})
    ns=sum(1 for t in T if STRONG.match(t)); nw=len(T)-ns
    ttl=r.get('title','')+' '+r.get('desc','')
    thit=bool(re.search(r"abayas?|kandura|clothing|apparel|ready.?to.?wear|menswear|womenswear|dresses|lingerie|sportswear|activewear|streetwear|\bfashion\b|ملابس|عباي|أزياء|ازياء|فساتين",ttl,re.I))
    ns_raw=ns
    if thit: ns+=1
    pt=r.get('ptypes',{})
    ptc=sum(v for k,v in pt.items() if re.search(r"shirt|dress|abaya|jean|hood|jacket|coat|trouser|pant|legging|lingerie|underwear|bra\b|apparel|cloth|kandura|thobe|top|wear|skirt|suit|sweat|polo|short|robe|pyjama|swim|set|knit",k,re.I))
    fashcat=cat.startswith('Fashion') or cat.startswith('Department')
    title=(r.get('title','')+' '+r.get('desc',''))
    ok=False;why=''
    fw=re.search(r"fashion|clothing|clothes|wear\b|abaya|boutique|apparel|dress|style|kandura|thobe|garment|ملابس|أزياء|ازياء|عباي|فساتين|كندور",title,re.I)
    if cat in ('Fashion - Women','Fashion - Abayas & Modest','Fashion - Men','Fashion - Sportswear & Streetwear'): ok=True;why='directory category (specific fashion)'
    elif fashcat and (ns_raw>=1 or nw>=2 or (fw and nw>=1)) and cat!='Fashion - Kids': ok=True;why='category+nav'
    elif ns>=2 and cat not in NONFASH: ok=True;why='nav/collections'
    elif ns>=1 and ptc>=3 and cat not in NONFASH: ok=True;why='product_types'
    elif ptc>=5 and cat not in NONFASH: ok=True;why='product_types'
    elif fashcat and cat=='Fashion - Kids' and ns>=1 and (r.get('w',0)+r.get('m',0))>=1: ok=True;why='kids+adult'
    if cat in ('Jewelry & Watches','Bags & Luggage','Shoes','Perfumes & Oud','Beauty & Cosmetics','Mobiles & Accessories','Baby & Maternity','Toys & Hobbies','Gaming','Personal Care & Grooming','Pharmacy & Wellness','Arts, Crafts & Handmade','Bedding, Mattresses & Textiles') and ns<2 and ptc<3: ok=False
    if cat in ('Perfumes & Oud','Beauty & Cosmetics','Mobiles & Accessories','Toys & Hobbies','Gaming','Personal Care & Grooming','Pharmacy & Wellness','Arts, Crafts & Handmade','Bedding, Mattresses & Textiles') and ns_raw<4 and ptc<5 and not re.search(r'abaya|kandura|lingerie|activewear|sportswear|streetwear|ready.?to.?wear|clothing|apparel',ttl,re.I): ok=False
    if cat in ('Baby & Maternity','Fashion - Kids') and (KIDT.search(ttl) or not re.search(r'abaya|women|\bmen\b|lingerie|modest|maternity|ladies',ttl,re.I)): ok=False
    if cat in ('Baby & Maternity','Fashion - Kids') and ok: why='kids+adult'
    if ok and cat in NONFASH and ns<4: ok=False
    if not ok and cat.startswith('Sports') and ns_raw>=1 and thit and not B2B.search(r.get('title','')): ok=True;why='sports apparel'
    if ok and B2B.search(r.get('title','')+' '+name) and ns<6: ok=False
    if ok and re.search(r'marketplace|tailor shop|tailoring (&|and) alteration|marine\b',title,re.I): ok=False
    NEG=re.compile(r"\bbooks?\b|salon|skin.?care|make.?up|perfumes?|fragrances?|advertising|embroider|personalized|gifts?\b|general trading|production|equestrian|horse|\bbike|bicycle|foods?\b|\btrading\b|rackets?|flip.?flops?|sandals|footwear|orthotics|\bmall\b|marketplace|laundry|packaging|\bprinting|stationery|supplies|photos|royalty|hostel|restaurant|domain|hosting|slot",re.I)
    if ok and NEG.search(title+' '+name) and not re.search(r"abaya|kandura|ready.?to.?wear|menswear|womenswear|lingerie|streetwear|activewear|sportswear|clothing|apparel|dresses",title,re.I): ok=False
    if ok and NEG.search(r.get('title','')+' '+name) and ns_raw<4 and cat not in('Fashion - Abayas & Modest','Fashion - Women','Fashion - Men'): ok=False
    if ok and KIDT.search(r.get('title','')+' '+name) and not re.search(r"abaya|women|\bmen\b|\bmens\b|ladies|lingerie|modest|maternity|adult",title,re.I): ok=False
    HARD=re.compile(r"travel|concierge|fishing|motorcycle|motorbike|\bmoto\b|rental|rent your|pacifier|teether|feeding|\bbooks?\b|كتب|مكتبة|hair (drama|extension|salon)|group\b|uniforms?\b|workwear|printing|stock photo|laptop|interlining|\bchef|custom clothing|bragard|everything|touratech|adventure gear|yoga mat|trading llc|equestrian|horse|jewelry & watches|fashion jewelry",re.I)
    if ok and HARD.search(r.get('title','')+' '+name) and ns_raw<10: ok=False
    SVC=re.compile(r"alteration|stitching|tailor shop|tailors? in|tailoring (service|&)|uniform|workwear|scrubs|school",re.I)
    if ok and SVC.search(r.get('title','')+' '+name) and ns_raw<8: ok=False
    if ok and not fashcat and not thit and ns_raw<4 and cat not in ('Sports, Fitness & Outdoor',): ok=False
    if ok and cat=='Fashion & Apparel' and not fw and ns_raw<2 and nw<2 and (r.get('w',0)+r.get('m',0))<1 and ptc<3: ok=False
    if ok and cat=='Fashion & Apparel' and not fw and ns_raw==0 and nw==0 and (r.get('w',0)+r.get('m',0))<1: ok=False
    return ok,why,ns,nw
def gender(r,cat):
    T=r.get('terms',{}); w=r.get('w',0); m=r.get('m',0)
    tl=' '.join(T)
    fem=len(re.findall(r"abaya|bra\b|bras|lingerie|panties|dress|gown|skirt|blouse|kaftan|caftan|jalabiya|hijab|عباي|فساتين|فستان|جلابية|حجاب",tl,re.I))
    mal=len(re.findall(r"kandura|thobe|thawb|كندورة|ثوب|كنادير",tl,re.I))
    if cat in('Fashion - Women','Fashion - Abayas & Modest'): w+=3
    if cat=='Fashion - Men': m+=3
    w+=fem*2; m+=mal*2
    if w>=3*max(m,1) and w>=2 and m<=1 or (w>0 and m==0): return 'Women'
    if m>=3*max(w,1) and m>=2 or (m>0 and w==0): return 'Men'
    return 'Unisex'
