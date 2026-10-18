import json, re, glob, pandas as pd, sys
from urllib.parse import urlparse
W='/tmp/w/markets/fashion/usa_parts/work/'
ns=pd.read_pickle('/tmp/ns2.pkl')
live={}
for f in ['live.jsonl','live_retry.jsonl','live_sm.jsonl']:
    try:
        for l in open(W+f):
            x=json.loads(l)
            if x['ok'] or x['url'] not in live: live[x['url']]=x
    except FileNotFoundError: pass
CLO=re.compile(r"\b(clothing|clothes|apparel|dresses|shirts?|t-?shirts?|tees?|hoodies?|sweatshirts?|jackets?|coats?|jeans|denim|pants|trousers|shorts|leggings|sweaters?|knitwear|tops|bottoms|outerwear|lingerie|bras?|underwear|swimwear|swimsuits?|bikinis?|activewear|sportswear|loungewear|pajamas|pyjamas|sleepwear|skirts?|blouses?|tanks?|joggers|polos?|suits?|jerseys?|cardigans?|jumpsuits?|rompers?|abayas?|modest|gowns?|kaftans?|flannels?|vests?|workwear|hosiery|tights|chinos|sweatpants|hats?|beanies)\b",re.I)
STRONG=re.compile(r"\b(clothing|clothes|apparel|dresses|shirts?|t-?shirts?|tees?|hoodies?|sweatshirts?|jackets?|jeans|denim|pants|trousers|leggings|sweaters?|tops|bottoms|outerwear|lingerie|bras|underwear|swimwear|swimsuits?|bikinis?|activewear|loungewear|pajamas|sleepwear|skirts?|blouses?|joggers|polos?|jerseys?|cardigans?|jumpsuits?|abayas?|gowns?|sweatpants|chinos)\b",re.I)
WOM=re.compile(r"\b(women'?s?|womens|womenswear|ladies)\b|/wom[ae]n",re.I)
MEN=re.compile(r"(?<![a-z])(men'?s?|mens|menswear|guys)\b|/mens?(?:[-/_?]|$)",re.I)
UNI=re.compile(r"unisex|all[- ]gender|gender[- ]neutral",re.I)
KID=re.compile(r"\b(kids?|boys?|girls?|baby|babies|toddlers?|infants?|children'?s?|youth|juniors?|newborn|tweens?)\b",re.I)
NONCLO=re.compile(r"shoes?|sneakers?|boots?|footwear|sandals|jewel|watch|handbag|bags?\b|purse|accessor|wallet|eyewear|sunglasses",re.I)
NAMEBAD=re.compile(r"\b(kids?|baby|babies|toddler|children|infant|newborn)\b",re.I)
NAMENONCLO=re.compile(r"jewel|shoe|footwear|sneaker|boot|handbag|bag\b|watch|diamond|ring\b|gems?\b|wholesale|blanks?\b|uniforms?\b",re.I)
def analyze(x):
    L=x.get('links',[]); cats=x.get('woocats') or []
    items=[(t,h) for h,t in L]
    # anchor text or url path
    def path(h): return urlparse(h).path.lower().replace('-',' ').replace('_',' ').replace('/',' / ')
    pieces=[(t+' '+path(h)) for t,h in items]+[c for c in cats]
    clo=set();wom=0;men=0;kid=0;nonclo=0;ev=None;sig=None;uni=0
    for (t,h),p in zip(items,pieces[:len(items)]):
        m=STRONG.search(t) or STRONG.search(path(h))
        if m:
            clo.add(m.group(1).lower())
            if not ev: ev,sig=h,m.group(1).lower()
        if WOM.search(t) or WOM.search(h): wom+=1
        if MEN.search(t) or MEN.search(h): men+=1
        if UNI.search(t) or UNI.search(h): uni+=1
        if KID.search(t) or KID.search(urlparse(h).path): kid+=1
    for c in cats:
        m=STRONG.search(c)
        if m: clo.add(m.group(1).lower()); ev=ev or x['final']; sig=sig or 'woocat:'+c
        if WOM.search(c): wom+=1
        if MEN.search(c): men+=1
    td=(x.get('title','')+' '+x.get('desc',''))
    tm=STRONG.search(td)
    return dict(viasm=bool(x.get('via_sm')),clo=clo,wom=wom,men=men,uni=uni,kid=kid,ev=ev,sig=sig,tmatch=tm.group(1).lower() if tm else None,tkid=bool(KID.search(td)),nlinks=len(L))
sm={}
try:
    for l in open(W+'sm.jsonl'):
        y=json.loads(l)
        if y['sm']: sm[y['url']]=y['sm']
except FileNotFoundError: pass
res=[]
for r in ns.itertuples():
    x=live.get(r.url); cat=r.category or ''
    if r.url in sm:
        x=dict(x) if x else {'url':r.url,'ok':True,'final':r.url,'title':'','links':[]}
        x['ok']=True; x['links']=list(x.get('links',[]))+[(u,'') for u in sm[r.url]]; x['via_sm']=True
    rec=dict(name=r.name,url=r.url,platform=r.platform or '',cat=cat,vstatus=r.vstatus,reftier=r.reftier,refcat=r.refcat)
    rec['live']='ok' if x and x['ok'] else ('fail:'+str((x or {}).get('err') or (x or {}).get('status'))) if x else 'notchecked'
    if x and x['ok']:
        rec.update(analyze(x)); rec['title']=x.get('title','')
    res.append(rec)
df=pd.DataFrame(res); df.to_pickle('/tmp/res.pkl'); print(df.live.str[:9].value_counts())
