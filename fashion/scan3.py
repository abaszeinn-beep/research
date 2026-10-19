import asyncio, httpx, sqlite3, re, json, sys, time, html as H, urllib.parse as up, random, pickle
from fk import *
import scan
from scan import get, page_text, norm, UA
DB='/tmp/sa/fashion/scan3.sqlite'
CATLINK=re.compile(r'/c\d{4,}|/categor|/collections?/|product-category|/category/|/cat/|/shop/|/ar/c|/en/c|/department|/group',re.I)
def init():
    c=sqlite3.connect(DB,timeout=60); c.execute("create table if not exists s3(key text primary key,url text,ok int,platform text,cat_tokens text,prod_tokens text,cats text,women int,men int,uni int,kid int,adult int,evidence_url text,src text,nlinks int,err text)"); c.commit(); return c
def flat(cats,out):
    for c in cats or []:
        out.append(c.get('name') or ''); flat(c.get('sub_categories'),out)
async def get2(cl,url,h):
    sem=scan.HS.sem.setdefault('api.salla.dev',asyncio.Semaphore(3))
    async with sem:
        await asyncio.sleep(0.25)
        for i in range(4):
            try:
                r=await cl.get(url,headers=h,timeout=25)
                if r.status_code==429: await asyncio.sleep(6*(i+1)); continue
                return r
            except Exception: await asyncio.sleep(2)
    return None
async def one(cl,key,url,plat,out,sem):
    async with sem:
        res=dict(key=key,url=url,ok=0,platform=plat,cat_tokens='',prod_tokens='',cats='',women=0,men=0,uni=0,kid=0,adult=0,evidence_url=None,src='',nlinks=0,err=None)
        try:
            pu=up.urlparse(url); host=pu.netloc; base=f"{pu.scheme}://{host}"
            r=await get(cl,url,host)
            body=r.text if r.status_code<400 else ""
            if r.status_code>=400: res['err']=f"http{r.status_code}"
            cat_texts=[]; prod_texts=[]; links=[]
            if body:
                res['ok']=1; t,links=page_text(body,str(r.url)); prod_texts.append(t)
                for u,tx in links:
                    path=norm(up.urlparse(u).path)
                    if CATLINK.search(u): cat_texts+= [tx,path]
                    else: prod_texts+= [tx,path]
                if tx_nav:=re.findall(r'<(?:nav|header)[^>]*>(.*?)</(?:nav|header)>',body[:800000],re.S|re.I):
                    for blk in tx_nav[:3]:
                        for h,tx in A.findall(blk): cat_texts.append(H.unescape(TAG.sub(' ',tx)))
            if plat=='salla' or 'salla' in body[:200000].lower() and '"store":{"id"' in body:
                m=re.search(r'"store":\{"id":(\d+)',body)
                if m:
                    h={"Store-Identifier":m.group(1),"Accept":"application/json","Referer":url,"User-Agent":UA}
                    cr=await get2(cl,"https://api.salla.dev/store/v1/products/categories",h)
                    if cr is not None and cr.status_code==200:
                        cs=[]; flat(cr.json().get('data'),cs); cat_texts+=cs; res['src']+='+salla-cats'
                    pr=await get2(cl,"https://api.salla.dev/store/v1/products?per_page=30",h)
                    if pr is not None and pr.status_code==200:
                        for p in pr.json().get('data',[]): prod_texts.append(p.get('name') or ''); prod_texts.append((p.get('category') or {}).get('name') or '')
                        res['src']+='+salla-prods'
            if re.search(r'cdn\.shopify|myshopify',body or ''):
                try:
                    rr=await get(cl,base+"/collections.json?limit=250",host)
                    if rr.status_code==200:
                        for c in rr.json().get('collections',[]): cat_texts+=[c.get('title') or '',norm(c.get('handle'))]
                        res['src']+='+collections'
                except Exception: pass
            if re.search(r'wp-content|woocommerce',body or '',re.I):
                try:
                    rr=await get(cl,base+"/wp-json/wc/store/v1/products/categories?per_page=100",host)
                    if rr.status_code==200:
                        for c in rr.json(): cat_texts.append(H.unescape(c.get('name',''))+' '+norm(c.get('slug','')))
                        res['src']+='+wc'
                except Exception: pass
            ca=analyze("\n".join(x or '' for x in cat_texts))
            if not ca['strong'] and res['ok'] and not res['src'].count('salla-cats'):
                try:
                    rr=await get(cl,base+"/sitemap.xml",host)
                    if rr.status_code==200 and '<loc' in rr.text:
                        locs=re.findall(r'<loc>\s*([^<]+?)\s*</loc>',rr.text)
                        sub=[l for l in locs if re.search(r'categor|collection|taxonomy|product_cat',l,re.I)][:2]
                        for sm in sub:
                            r2=await get(cl,sm.replace('&amp;','&'),host)
                            if r2.status_code==200: locs+=re.findall(r'<loc>\s*([^<]+?)\s*</loc>',r2.text)
                        cl_=[norm(up.urlparse(l).path) for l in locs[:4000] if CATLINK.search(l)]
                        cat_texts+=cl_; res['src']+='+sitemap-cats'
                        ca=analyze("\n".join(x or '' for x in cat_texts))
                except Exception: pass
            pa=analyze("\n".join(x or '' for x in prod_texts))
            allv=analyze("\n".join(x or '' for x in cat_texts+prod_texts))
            ev=None
            for u,tx in links:
                for s_ in (tx,norm(up.urlparse(u).path)):
                    mm=KW.search(s_ or '')
                    if mm and mm.group(0).lower() not in WEAK: ev=u; break
                if ev: break
            res.update(cat_tokens=",".join(ca['strong']),prod_tokens=",".join(pa['strong']),cats=" | ".join(dict.fromkeys(x for x in cat_texts if x and len(x)<60))[:600],women=int(allv['women']),men=int(allv['men']),uni=int(allv['uni']),kid=int(allv['kid']),adult=int(allv['adult']),evidence_url=ev,nlinks=len(links))
        except Exception as e: res['err']=(res['err'] or '')+type(e).__name__+str(e)[:50]
        out.append(res)
A=scan.A; TAG=scan.TAG
async def main(rows,conc=int(__import__('os').environ.get('CONC','120'))):
    c=init(); done={r[0] for r in c.execute("select key from s3 where ok=1 or err not like 'http429%'")}
    rows=[r for r in rows if r[0] not in done]; random.shuffle(rows); print('todo',len(rows),flush=True)
    sem=asyncio.Semaphore(conc); out=[]
    async with httpx.AsyncClient(verify=False,limits=httpx.Limits(max_connections=conc+20)) as cl:
        tasks=[asyncio.create_task(one(cl,k,u,p,out,sem)) for k,u,p in rows]; n=0
        while tasks:
            await asyncio.sleep(10); tasks=[t for t in tasks if not t.done()]
            b,out[:]=out[:],[]
            for r in b: c.execute("insert or replace into s3 values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",tuple(r[k] for k in ['key','url','ok','platform','cat_tokens','prod_tokens','cats','women','men','uni','kid','adult','evidence_url','src','nlinks','err']))
            c.commit(); n+=len(b); print(n,len(tasks),flush=True)
if __name__=="__main__":
    which=sys.argv[1]
    rows=pickle.load(open('/tmp/sa/fashion/rows3.pkl','rb'))
    rows=[r for r in rows if (r[1].startswith('https://salla.sa/'))==(which=='salla')]
    asyncio.run(main(rows))
