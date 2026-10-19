import asyncio, httpx, sqlite3, re, json, sys, time, html as H, urllib.parse as up, random
from fk import *
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
DB='/tmp/sa/fashion/fashion.sqlite'
A=re.compile(r'<a\s[^>]*?href=["\']([^"\'#][^"\']*)["\'][^>]*>(.*?)</a>',re.I|re.S)
TAG=re.compile(r'<[^>]+>')
TITLE=re.compile(r'<title[^>]*>(.*?)</title>',re.I|re.S)
META=re.compile(r'<meta[^>]+(?:name|property)=["\'](?:description|og:description|og:title|keywords)["\'][^>]*content=["\']([^"\']*)',re.I)
def init():
    c=sqlite3.connect(DB); c.execute("create table if not exists scan(key text primary key,url text,ok int,platform text,strong text,weak text,women int,men int,uni int,kid int,adult int,evidence_url text,signal text,src text,nlinks int,err text,ts text)"); c.commit(); return c
class Host:
    def __init__(s): s.sem={}; s.last={}
    async def wait(s,h):
        sem=s.sem.setdefault(h,asyncio.Semaphore((2 if __import__('os').environ.get('LOW') else 6) if h=='salla.sa' else (1 if __import__('os').environ.get('LOW') else 3)))
        return sem
HS=Host()
async def get(cl,url,host,maxb=1500000):
    sem=await HS.wait(host)
    async with sem:
        gap=HS.last.get(host,0)+0.15-time.time()
        if gap>0: await asyncio.sleep(gap)
        r=None
        for i in range(3):
            try:
                r=await cl.get(url,headers={"User-Agent":UA,"Accept-Language":"ar,en;q=0.8"},timeout=20,follow_redirects=True)
                if r.status_code==429 and i<2:
                    await asyncio.sleep(min(float(r.headers.get('retry-after','5') or 5),20)); continue
                break
            except (httpx.ConnectError,httpx.ConnectTimeout) as e:
                if i==2: raise
                await asyncio.sleep(2+i*3)
            finally: HS.last[host]=time.time()
    return r
def page_text(body,base):
    t=" ".join(TITLE.findall(body)[:1]+META.findall(body)[:4])
    links=[]
    for h,tx in A.findall(body[:1500000]):
        tx=H.unescape(TAG.sub(" ",tx)).strip()[:80]
        try: u=up.urljoin(base,H.unescape(h))
        except Exception: continue
        links.append((u,tx))
    return H.unescape(t),links
def find_evidence(links):
    for u,tx in links:
        path=norm(up.urlparse(u).path)
        for s in (tx,path):
            m=KW.search(s)
            if m and m.group(0).lower() not in WEAK: return u,m.group(0)
    for u,tx in links:
        for s in (tx,norm(up.urlparse(u).path)):
            m=KW.search(s)
            if m: return u,m.group(0)
    return None,None
async def one(cl,key,url,plat,cat,out,sem):
    async with sem:
        res=dict(key=key,url=url,ok=0,platform=plat,strong="",weak="",women=0,men=0,uni=0,kid=0,adult=0,evidence_url=None,signal=None,src="",nlinks=0,err=None)
        try:
            pu=up.urlparse(url); host=pu.netloc
            base=f"{pu.scheme}://{host}"
            r=await get(cl,url,host)
            if r.status_code>=400 and r.status_code!=404: res['err']=f"http{r.status_code}"
            body=r.text if r.status_code<400 else ""
            final=str(r.url)
            texts=[]; links=[]
            if body:
                res['ok']=1
                t,links=page_text(body,final); texts.append(t); res['src']="home"
                for u,tx in links:
                    texts.append(tx); texts.append(norm(up.urlparse(u).path))
            # platform probes
            extra=[]
            if re.search(r'cdn\.shopify|Shopify\.theme|myshopify',body or ''):
                try:
                    rr=await get(cl,base+"/collections.json?limit=250",host)
                    if rr.status_code==200:
                        j=rr.json().get('collections',[])
                        for c in j: extra.append((f"{base}/collections/{c['handle']}",c.get('title','')))
                        res['src']+="+collections.json"
                    rr=await get(cl,base+"/products.json?limit=100",host)
                    if rr.status_code==200:
                        for p in rr.json().get('products',[])[:100]:
                            extra.append((f"{base}/products/{p['handle']}",(p.get('product_type') or '')+' '+' '.join(p.get('tags') if isinstance(p.get('tags'),list) else str(p.get('tags','')).split(','))))
                        res['src']+="+products.json"
                except Exception: pass
            if re.search(r'wp-content|woocommerce',body or '',re.I):
                try:
                    rr=await get(cl,base+"/wp-json/wc/store/v1/products/categories?per_page=100",host)
                    if rr.status_code==200:
                        for c in rr.json(): extra.append((c.get('permalink') or base,H.unescape(c.get('name',''))+' '+c.get('slug','')))
                        res['src']+="+wc-categories"
                except Exception: pass
            for u,tx in extra: texts.append(tx); texts.append(norm(u.split('/')[-1] if 'collections' in u else '')); 
            links=links+extra
            full=" \n".join(texts)
            a=analyze(full)
            if not a['strong'] and len(a['weak'])<2 and (res['ok'] and cat not in SKIPMAP):
                # sitemap fallback
                try:
                    rr=await get(cl,base+"/sitemap.xml",host)
                    if rr.status_code==200 and '<loc' in rr.text:
                        locs=re.findall(r'<loc>\s*([^<]+?)\s*</loc>',rr.text)
                        sub=[l for l in locs if re.search(r'categor|collection|taxonomy|product_cat',l,re.I)][:1]
                        for sm in sub:
                            r2=await get(cl,sm.replace('&amp;','&'),host)
                            if r2.status_code==200: locs+=re.findall(r'<loc>\s*([^<]+?)\s*</loc>',r2.text)
                        locs=locs[:3000]
                        sl=[(l,norm(up.urlparse(l).path)) for l in locs]
                        full2=" \n".join(x for _,x in sl)
                        a2=analyze(full2)
                        if a2['strong'] or len(a2['weak'])>=2:
                            a=a2; links=sl+links; res['src']+="+sitemap"
                except Exception: pass
            ev,sig=find_evidence(links)
            res.update(strong=",".join(a['strong']),weak=",".join(a['weak']),women=int(a['women']),men=int(a['men']),uni=int(a['uni']),kid=int(a['kid']),adult=int(a['adult']),evidence_url=ev,signal=sig,nlinks=len(links))
        except Exception as e:
            res['err']=(res['err'] or '')+type(e).__name__+str(e)[:60]
        out.append(res)
SKIPMAP={'Grocery & Food','Coffee, Tea & Dates','Chocolates & Sweets','Pharmacy & Wellness','Automotive Parts & Accessories','Building Materials','Industrial & Tools','Agriculture & Gardening','Electronic Components','Cleaning & Household Supplies','Packaging & Supplies','Wholesale & B2B','Healthcare & Medical Equipment','Furniture','Lighting & Electrical','Pets','Office Supplies','Books & Stationery','Gaming','Computers & Electronics','Mobiles & Accessories','Home Appliances','Kitchenware & Tableware','Flowers, Gifts & Party','Perfumes & Oud'}
async def main(rows,conc=150):
    c=init(); done={r[0] for r in c.execute("select key from scan")}
    rows=[r for r in rows if r[0] not in done]
    random.shuffle(rows)
    print("todo",len(rows),flush=True)
    sem=asyncio.Semaphore(conc); out=[]
    async with httpx.AsyncClient(verify=False,limits=httpx.Limits(max_connections=conc+20)) as cl:
        tasks=[asyncio.create_task(one(cl,k,u,p,cat,out,sem)) for k,u,p,cat in rows]
        n=0
        while tasks:
            await asyncio.sleep(10)
            tasks=[t for t in tasks if not t.done()]
            batch,out[:]=out[:],[]
            for r in batch:
                c.execute("insert or replace into scan values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))",(r['key'],r['url'],r['ok'],r['platform'],r['strong'],r['weak'],r['women'],r['men'],r['uni'],r['kid'],r['adult'],r['evidence_url'],r['signal'],r['src'],r['nlinks'],r['err']))
            c.commit(); n+=len(batch); print(n,len(tasks),flush=True)
if __name__=="__main__":
    src=sqlite3.connect('/tmp/sa/data/saudi_ecom.sqlite')
    which=sys.argv[1]
    if which=="master":
        rows=src.execute("select key,final_url,platform,category from verifications where status like 'verified%' and final_url is not null").fetchall()
        lim=None
    elif which in("salla","other"):
        rows=src.execute("select key,final_url,platform,category from verifications where status like 'verified%' and final_url is not null").fetchall()
        rows=[r for r in rows if (r[1].startswith('https://salla.sa/'))==(which=="salla")]
        lim=None
        
    else:
        rows=json.load(open(which))
    asyncio.run(main(rows))
