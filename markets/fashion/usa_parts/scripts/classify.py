import re,json,collections
CLOTH=re.compile(r"\b(t-?shirts?|tees?|shirts?|hoodies?|sweatshirts?|crewnecks?|pullovers?|jackets?|coats?|parkas?|dress(es)?|gowns?|pants|trousers|jeans|denim|leggings?|joggers?|sweatpants|shorts|skirts?|skorts?|sweaters?|cardigans?|knitwear|blouses?|tank tops?|tanks? (top|dress)|camis?|bras?|bralettes?|underwear|briefs|boxers?|panties|thongs?|lingerie|bodysuits?|jumpsuits?|rompers?|swimsuits?|swimwear|bikinis?|trunks|board ?shorts|polos?|henleys?|jerseys?|vests?|blazers?|suit jackets?|suit sets?|tuxedos?|robes?|pajamas?|pyjamas?|loungewear|sleepwear|activewear|sports bras?|abayas?|hijabs?|kaftans?|tunics?|crop tops?|apparel|clothing|flannels?|outerwear|windbreakers?|overalls?|chinos|sweatshirt|long ?sleeves?|short ?sleeves?|singlets?|unitards?|onesies?|scrubs|socks)\b",re.I)
NOSOCK=re.compile(r"\bsocks?\b",re.I)
KIDS=re.compile(r"\b(kids?|child(ren)?'?s?|boys?|girls?|baby|babies|toddlers?|infants?|youth|newborns?|juniors?|tween|little|mini me)\b",re.I)
NONCLOTH=re.compile(r"\b(gift ?cards?|e-?gift|shoes?|sneakers?|boots?|sandals?|handbags?|bags?|totes?|wallets?|jewel+ery|necklaces?|earrings?|rings?|bracelets?|watch(es)?|sunglasses|candles?|mugs?|stickers?|posters?|prints?|phone cases?|pillows?|blankets?|towels?|dog|cat|pet|collars?|leashes?)\b",re.I)
WOM=re.compile(r"\b(bras?|bralettes?|bikinis?|panties|thongs?|skirts?|dress(es)?|blouses?|leggings?|lingerie|camis?|rompers?|gowns?|women'?s?|woman|ladies|lady|female|womens|her|maternity|bridal|bride)\b",re.I)
MEN=re.compile(r"\b(boxers?|briefs|trunks|tuxedos?|men'?s?|man|male|mens|guys?|him|gentlemen)\b",re.I)
UNI=re.compile(r"\b(unisex|gender[- ]neutral|all[- ]gender)\b",re.I)
AUTO=re.compile(r"\b(assy|gasket|engine|transmission|chevrolet|chevy|gmc|ford|dodge|toyota|honda|oem|fitting|golf tee|tee ball|tee fitting|fuel|radiator|bolt|valve|trans cooler|puppy|cvr|comics?|vinyl|ebook|funko)\b|tuxedo cat",re.I)
SOFT=re.compile(r"\b(ornaments?|stickers?|pins?|patch(es)?|posters?|figures?|dolls?|plush|candles?|mugs?|pattern|knitting|crochet|yarn|kits?|loafers?|boots?|shoes?|sneakers?|belts?|bags?|download|digital|collectible|dog|cat|pet|bottles?|tumblers?|cups?|gift cards?|stands?|hangers?)\b",re.I)
STRONG=re.compile(r"\b(t-?shirts?|tees?|shirts?|hoodies?|sweatshirts?|jackets?|dress(es)?|leggings?|pants|shorts|sweaters?|tank tops?|jeans|joggers?|crewnecks?|pullovers?|bras?|bikinis?|apparel)\b",re.I)
BADTYPE=re.compile(r"fabric|yarn|pattern|album|vinyl|fragrance|perfume|nail|gel|cake|pie\b|book|toy|figure|ornament|doll|sticker|necklace|earring|ring\b|bracelet|dildo|case|pod\b|supplement|protein",re.I)
BADTITLE=re.compile(r"(top|base|gel|clear|nail) coat|dress-?up|dress form|compare to|eau de|cologne|fragrance|\bpolo (red|black|blue|sport|ralph)|pattern\b|knit kit|dress[- ]up|\b\d+[- ]?(pack|pk)\b.*\btee\b|\btee\b.*\d+ ?mm|golf tees?",re.I)
def prod_flags(p):
    title,ptype,tags,vendor=p
    t=title+' | '+ptype+' | '+' '.join(tags)
    ct=title+' | '+ptype
    cl=bool(CLOTH.search(ct)) and not BADTITLE.search(ct) and not (BADTYPE.search(ptype) and not re.search(r'cloth|apparel|shirt|tee|hood|jacket|dress|top|bottom',ptype,re.I)) and not AUTO.search(ct) and not (SOFT.search(ct) and not STRONG.search(ct))
    if cl and NOSOCK.search(ct) and not CLOTH.search(NOSOCK.sub('',ct)): cl=False
    if cl and NONCLOTH.search(ptype) and not CLOTH.search(ptype): cl=False
    if cl and re.search(r"\b(shirt|tee|hoodie|dress|jacket|shorts|pants)\b",ct,re.I)==None: pass
    if not cl and re.search(r"clothing|apparel|^tops?$|^bottoms?$|outerwear",ptype,re.I): cl=True
    kid=bool(KIDS.search(t))
    adult_tag=bool(WOM.search(t) or MEN.search(t) or UNI.search(t))
    return cl,kid,bool(WOM.search(t)),bool(MEN.search(t)),bool(UNI.search(t))
def analyze(prods):
    n=len(prods);cl=ad=w=m=u=0;st=0
    ex=[]
    for p in prods:
        c,k,W,M,U=prod_flags(p)
        if not c: continue
        # kids-only product: kid and no adult signal
        if k and not(W or M or U) : continue
        if k and (W or M) and re.search(r"\b(boys?|girls?|kids?|toddler|baby|youth)\b",p[0]+p[1],re.I): continue
        cl+=1; st+=bool(STRONG.search(p[0]+' '+p[1]))
        w+=W and not M; m+=M and not W; u+=U or (W and M)
        if len(ex)<3: ex.append(p[0])
    return n,cl,w,m,u,ex,st
def gender(cl,w,m,u,namecat=''):
    if cl==0: return None
    sw,sm,su=w/cl,m/cl,u/cl
    if su>=0.3 or (sw>=0.25 and sm>=0.25): return 'Unisex'
    if w>m and w>=1 and sw>=0.2 : return 'Women'
    if m>w and m>=1 and sm>=0.2: return 'Men'
    return 'Unisex'
def decide(n,cl,fashion_cat,st=None):
    if n==0: return None
    if st is None: st=cl
    share=cl/n
    if share>=0.6 or (fashion_cat and share>=0.35): return 'Fashion-only'
    if st>=3 and cl>=3 and share>=0.025 or (fashion_cat and cl>=2 and share>=0.05): return 'Has clothing section'
    return 'no'
