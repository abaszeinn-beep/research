import asyncio, aiohttp, re, json, sys, sqlite3, time, html as H
from urllib.parse import urlparse, urljoin
UA={'User-Agent':'Mozilla/5.0 (compatible; research-bot; polite)','Accept-Language':'en,ar'}
CLOTH=r"abaya|abayas|kandura|kanduras|thobe|thawb|jalabiya|jalabiyah|kaftan|caftan|dress(?:es)?|gown|skirts?|blouses?|tops?\b|t-?shirts?|tees?\b|shirts?|polos?|jeans|denim|trousers|pants|leggings|joggers|hoodies?|sweatshirts?|sweaters?|knitwear|jackets?|coats?|blazers?|suits?|abayat|lingerie|underwear|bras?\b|panties|innerwear|sleepwear|pyjamas?|pajamas?|loungewear|swimwear|activewear|sportswear|apparel|clothing|clothes|garments?|menswear|womenswear|ready.?to.?wear|modest|hijab|scarves|shawls?|sheila|jumpsuits?|shorts|co-?ords|cardigans?|streetwear|عباي[ةات]|عبايات|فساتين|فستان|ملابس|كندورة|كنادير|ثوب|جلابية|قمصان|تيشيرت|بناطيل|ملابس داخلية|ازياء|أزياء|هوديز|ملابس رياضية|حجاب|اوشحة|بيجاما"
WOM=r"\bwomen|\bwoman|\bladies|\blady|\bgirls?\b|womens|women's|نساء|نسائ|حريمي|بناتي"
MEN=r"\bmen\b|\bmens\b|men's|\bmenswear|\bgents?\b|\bboys?\b|رجال|رجالي"
KID=r"\bkids?\b|\bbaby\b|\bbabies\b|\binfants?\b|\btoddlers?\b|\bboys?\b|\bgirls?\b|\bchildren\b|أطفال|اطفال|اولاد|بنات"
UNI=r"unisex|للجنسين"
cr=re.compile(r'(?<![a-z])(?:'+CLOTH+r')(?![a-z])',re.I);wr=re.compile(WOM,re.I);mr=re.compile(MEN,re.I);kr=re.compile(KID,re.I);ur=re.compile(UNI,re.I)
ANCH=re.compile(r'<a\b[^>]*?href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',re.I|re.S)
TAG=re.compile(r'<[^>]+>')
async def get(s,url,mx=600000):
    try:
        async with s.get(url,timeout=aiohttp.ClientTimeout(total=15),allow_redirects=True) as r:
            if r.status!=200: return r.status,None,str(r.url)
            b=await r.content.read(mx)
            return 200,b.decode(r.get_encoding() if r.charset else 'utf-8','ignore'),str(r.url)
    except Exception as e: return 0,None,url
def terms(texts):
    out={}
    for t in texts:
        for m in cr.findall(t): out[m.lower()]=out.get(m.lower(),0)+1
    return out
async def one(s,sem,hostsem,row):
    key,url,plat,cat=row
    res={'key':key,'url':url}
    async with sem:
        st,h,final=await get(s,url)
        res['status']=st
        if not h: return res
        base=final
        texts=[];links=[]
        title=H.unescape(TAG.sub(' ',(re.search(r'<title[^>]*>(.*?)</title>',h,re.I|re.S) or [0,''])[1]))
        desc=(re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)',h,re.I) or [0,''])[1]
        for href,inner in ANCH.findall(h):
            t=H.unescape(TAG.sub(' ',inner)); t=re.sub(r'\s+',' ',t).strip()
            if 0<len(t)<60: texts.append(t)
            links.append((href,t))
        pathtexts=[urlparse(urljoin(base,hf)).path.replace('-',' ').replace('/',' ').replace('_',' ') for hf,_ in links]
        res['title']=title.strip()[:120]; res['desc']=desc[:200]
        extra=[]
        isshop=plat=='shopify' or 'cdn.shopify.com' in h
        if isshop:
            u=urlparse(final); root=f'{u.scheme}://{u.netloc}'
            st2,j,_=await get(s,root+'/collections.json?limit=250',400000)
            if j:
                try:
                    cols=json.loads(j).get('collections',[]); extra+= [c.get('title','')+' '+c.get('handle','').replace('-',' ') for c in cols]; res['ncol']=len(cols)
                except: pass
            st3,j,_=await get(s,root+'/products.json?limit=100',600000)
            if j:
                try:
                    pr=json.loads(j).get('products',[])
                    pt={}
                    for p in pr:
                        k=(p.get('product_type') or '').strip()
                        if k: pt[k]=pt.get(k,0)+1
                    res['ptypes']=dict(sorted(pt.items(),key=lambda x:-x[1])[:12]); res['nprod']=len(pr)
                    extra+=list(pt.keys())+[' '.join(p.get('tags',[]) if isinstance(p.get('tags'),list) else [p.get('tags','')]) for p in pr[:30]]
                except: pass
        elif plat=='woocommerce' or 'wp-content' in h:
            u=urlparse(final); root=f'{u.scheme}://{u.netloc}'
            st2,j,_=await get(s,root+'/wp-json/wc/store/v1/products/categories?per_page=100',300000)
            if j:
                try:
                    cats=json.loads(j); extra+=[c.get('name','')+' '+c.get('slug','').replace('-',' ') for c in cats]; res['ncat']=len(cats)
                except: pass
        navtxt=texts+pathtexts+extra+[title,desc]
        T=terms(navtxt); res['terms']=dict(sorted(T.items(),key=lambda x:-x[1])[:15])
        res['w']=sum(1 for t in navtxt if wr.search(t)); res['m']=sum(1 for t in navtxt if mr.search(t)); res['k']=sum(1 for t in navtxt if kr.search(t)); res['u']=sum(1 for t in navtxt if ur.search(t))
        res['nclo']=sum(T.values()); res['ntt']=len(T)
        # sample evidence url: first link with clothing term
        for href,t in links:
            if cr.search(t) or cr.search(href):
                res['ev']=urljoin(base,href); break
        res['final']=final
        res['cart']=bool(re.search(r'add.to.cart|add_to_cart|addtocart|/cart\b|/checkout|ajax_add_to_cart|أضف إلى السلة|اضف الى السلة|add to bag|add to basket',h,re.I))
        res['aed']=bool(re.search(r'\bAED\b|د\.إ|\bDhs?\b|درهم',h))
        res['p971']=bool(re.search(r'\+\s?971|00971',h))
        res['plat']='shopify' if isshop else ('woocommerce' if 'wp-content' in h and 'woocommerce' in h.lower() else '')
    return res
async def main(inp,out,conc):
    rows=json.load(open(inp))
    done=set()
    try:
        for l in open(out): done.add(json.loads(l)['key'])
    except FileNotFoundError: pass
    rows=[r for r in rows if r[0] not in done]
    sem=asyncio.Semaphore(conc); conn=aiohttp.TCPConnector(limit=conc,limit_per_host=2,ssl=False)
    f=open(out,'a')
    async with aiohttp.ClientSession(headers=UA,connector=conn) as s:
        tasks=[asyncio.create_task(one(s,sem,None,r)) for r in rows]
        n=0
        for t in asyncio.as_completed(tasks):
            r=await t; f.write(json.dumps(r,ensure_ascii=False)+'\n'); f.flush(); n+=1
            if n%200==0: print(n,len(rows),flush=True)
if __name__=='__main__': asyncio.run(main(sys.argv[1],sys.argv[2],int(sys.argv[3])))
