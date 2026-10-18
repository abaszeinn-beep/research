import asyncio, httpx, re, json, sys, html as H
from urllib.parse import urljoin, urlparse
UA={"User-Agent":"Mozilla/5.0 (compatible; KuwaitFashionResearch/1.0; research, polite)","Accept-Language":"en,ar;q=0.8"}
CLOTH=r"dress(?:es)?|abaya|abayas|thobe|thawb|dishdash\w*|shirts?|t-?shirts?|jeans|denim|pants|trousers|hoodies?|sweatshirts?|jackets?|coats|blazers?|suits|lingerie|underwear|undergarments?|activewear|sportswear|apparel|clothing|clothes|garments?|fashion|kaftan|caftan|jalabiya|jalabiyah|jilbab|hijab|modest|skirts?|blouses?|knitwear|sweaters?|jumpers?|leggings|shorts|jumpsuits|pyjamas?|pajamas?|loungewear|nightwear|swimwear|polo shirts?|cardigans?|kurtas?|sarees?|ready.?to.?wear|thoub|kandura|bisht|shemagh|ghutra|abayat|عباي\w*|دشداش\w*|ثوب|ثياب|فستان|فساتين|ملابس|أزياء|ازياء|قميص|قمصان|بنطلون|بناطيل|جاكيت|بيجام\w*|جلابي\w*|قفطان|تيشيرت|هودي|بلوزة|تنورة|ملابس داخلية|لانجري|حجاب|إسدال|اسدال|بشت|غترة|شماغ|ملابس رياضية|عبايه|عبايات|طقم|جلابيات|مدرعة|دراعة"
NONF=r"mobiles?|phones?|lapelectronics?|grocer\w*|furniture|appliances?|tv|televisions?|gaming|supermarket|vegetables|fruits|meat|tools|hardware|pharmacy|perfumes?|makeup|cosmetics?|skincare|beauty|jewel\w*|watches|toys?|stationery|books|pets?|car |automotive|tyres|home decor|kitchen|الكترونيات|إلكترونيات|جوال|موبايل|اثاث|أثاث|عطور|مكياج|مجوهرات|ساعات|ألعاب|بقالة|خضار"
WOM=r"women'?s?|woman|ladies|lady|female|girls?|نسائ\w*|نساء|حريمي|بنات|abayas?|عباي\w*|dresses|bridal|maternity|lingerie|فساتين|فستان|للنساء|المرأة"
MEN=r"\bmen'?s?\b|\bman\b|\bgents?\b|male|boys?|رجال\w*|للرجال|شباب|ولادي|dishdash\w*|thobes?|دشداش\w*|ghutra|شماغ|غتر\w*|bisht|بشت"
KIDS=r"kids?|baby|babies|children|child|toddlers?|infants?|newborn|اطفال|أطفال|طفل|مواليد|رضع"
W=lambda p:re.compile(r'(?<!\w)(?:'+p+r')(?!\w)',re.I)
cl=W(CLOTH);nf=W(NONF);wo=W(WOM);me=W(MEN.replace(r'\b',''));kd=W(KIDS)
def strip(h):
    h=re.sub(r"(?is)<(script|style|noscript|svg)\b.*?</\1>"," ",h)
    return h
def nav_text(h):
    h2=strip(h)
    m=re.search(r"(?is)<title[^>]*>(.*?)</title>",h)
    title=H.unescape(m.group(1)).strip() if m else ""
    md=re.search(r'(?is)<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',h)
    desc=H.unescape(md.group(1)) if md else ""
    links=re.findall(r'(?is)<a\b[^>]*href=["\']([^"\']*)["\'][^>]*>(.*?)</a>',h2)
    items=[]
    for href,t in links:
        t=re.sub(r"<[^>]+>"," ",t); t=H.unescape(re.sub(r"\s+"," ",t)).strip()
        if 0<len(t)<45: items.append((href,t))
    return title,desc,items
async def get(c,url,**k):
    try:
        r=await c.get(url,**k); return r
    except Exception: return None
async def probe(c,sem,key,url,name):
    out={"key":key,"url":url,"name":name,"ok":False}
    async with sem:
        r=await get(c,url)
        if r is None: out["err"]="fetch"; return out
        out["http"]=r.status_code; out["final"]=str(r.url)
        if r.status_code>=400: out["err"]=f"http{r.status_code}"; return out
        h=r.text[:600000]; base=str(r.url).split("?")[0]
        root=f"{r.url.scheme}://{r.url.host}"
        title,desc,items=nav_text(h)
        out["title"]=title[:120]
        out["kwsig"]=len(re.findall(r"kuwait|الكويت|\bKWD\b|\bKD\b|د\.ك|en-kw|ar-kw",h[:400000],re.I))
        cats=[];sig=[];ev=base
        shop="cdn.shopify.com" in h or "Shopify.theme" in h
        woo="wp-content/plugins/woocommerce" in h or "woocommerce" in h[:200000].lower()
        if shop:
            out["platform"]="Shopify"
            rr=await get(c,root+"/collections.json?limit=250")
            if rr is not None and rr.status_code==200:
                try:
                    cs=rr.json().get("collections",[]); cats+= [x.get("title","")+" "+x.get("handle","") for x in cs]; sig.append("shopify_collections"); ev=root+"/collections.json"
                except Exception: pass
            rr=await get(c,root+"/products.json?limit=60")
            if rr is not None and rr.status_code==200:
                try:
                    ps=rr.json().get("products",[])
                    out["nprod"]=len(ps)
                    cats+=[ (p.get("product_type","")+" "+p.get("title","")+" "+" ".join(p.get("tags",[]) if isinstance(p.get("tags"),list) else [p.get("tags","")])) for p in ps]
                    if ps: sig.append("shopify_products"); 
                    pr=[v.get("price") for p in ps[:5] for v in p.get("variants",[])[:1]]
                    out["prices"]=pr
                except Exception: pass
        elif woo:
            out["platform"]="WooCommerce"
            rr=await get(c,root+"/wp-json/wc/store/v1/products/categories?per_page=100")
            if rr is not None and rr.status_code==200:
                try:
                    cats+=[H.unescape(x.get("name","")) for x in rr.json()]; sig.append("woo_store_api_categories"); ev=root+"/wp-json/wc/store/v1/products/categories"
                except Exception: pass
        else:
            low=h.lower()
            out["platform"]=("Zid" if "zid.store" in low or "zid.sa" in low else "Salla" if "salla" in low and "cdn.salla" in low else "Magento" if "mage-" in low or "magento" in low else "SFCC" if "demandware" in low else "MNASATI" if "mnasati" in low else "Custom/Other")
        navs=[t for _,t in items]
        if navs: sig.append("homepage_nav")
        out["sig"]=sig; out["ev"]=ev
        out["cats"]=cats[:400]; out["nav"]=navs[:150]
        out["ok"]=True
    return out
async def main(inp,outp,conc):
    rows=[l.rstrip("\n").split("|") for l in open(inp)]
    sem=asyncio.Semaphore(conc)
    lim=httpx.Limits(max_connections=conc*2)
    async with httpx.AsyncClient(headers=UA,follow_redirects=True,timeout=httpx.Timeout(12),limits=lim,verify=False) as c:
        tasks=[probe(c,sem,r[0],r[1],r[2] if len(r)>2 else "") for r in rows]
        with open(outp,"w") as f:
            n=0
            for fut in asyncio.as_completed(tasks):
                o=await fut; f.write(json.dumps(o,ensure_ascii=False)+"\n"); n+=1
                if n%200==0: print(n,flush=True)
if __name__=="__main__": asyncio.run(main(sys.argv[1],sys.argv[2],int(sys.argv[3])))
