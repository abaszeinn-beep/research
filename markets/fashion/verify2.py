import json,re,asyncio,aiohttp,sys
from fashion_lib import *
from urllib.parse import urlparse
main={}
for l in open('probe_main.jsonl'):
    p=json.loads(l); main[p['key']]=p
C=[]
for f,src in (('probe_retry.jsonl','retry'),('probe_cc.jsonl','cc'),('probe_app.jsonl','app')):
    for l in open(f):
        p=json.loads(l)
        if not p['ok']: continue
        c=classify(p,(main.get(p['key'],{}).get('dbcat') or ''))
        if c[0]=='fashion' or (c[0]=='maybe' and (re.search(r'\.qa$|qatar',urlparse(p['final']).netloc,re.I) or re.search('abaya|عباي|lingerie|kaftan|clothing|fashion|apparel|dress|thob|ثوب|ملابس',c[3]+p['title'],re.I))):
            h=urlparse(p['final']).netloc.lower().replace('www.','')
            C.append((src,p,c,h))
seen=set(); C2=[]
for s,p,c,h in C:
    if h in seen: continue
    seen.add(h); C2.append((s,p,c,h))
print(len(C2),file=sys.stderr)
CART=re.compile(r"add[- _]to[- _]cart|addtocart|add-to-bag|ajax-cart|/cart\b|checkout|woocommerce|إضافة (إلى|الى) السلة|أضف للسلة|اضف الى السلة|السلة|shopify|salla|zid\.|data-product|product-form|btn-cart",re.I)
SHIP=['/policies/shipping-policy','/pages/shipping','/pages/shipping-policy','/shipping-policy','/pages/shipping-delivery','/shipping','/pages/delivery','/policies/refund-policy','/shipping-and-delivery','/delivery']
out=open('verify2.jsonl','w')
async def main_():
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=40,limit_per_host=2,ssl=sslctx()),headers={'User-Agent':UA,'Accept-Language':'en'}) as s:
        sem=asyncio.Semaphore(25)
        async def one(src,p,c,h):
            async with sem:
                base='{0.scheme}://{0.netloc}'.format(urlparse(p['final']))
                r={'src':src,'host':h,'url':p['final'],'name':p.get('name'),'title':p['title'],'platform':p['platform'],'type':c[1],'gender':c[2],'sig':c[3],'n_products':p.get('n_products'),'qa_tld':h.endswith('.qa')}
                st,fu,html,_=await get(s,p['final'],25)
                r['cart']=bool(CART.search(html)); r['qar']=bool(re.search(r'\bQAR\b|ر\.ق|ريال قطري|\bQR\s?\d',html)); r['qatar_home']=bool(re.search(r'Qatar|قطر',html)); r['qatar_name']=bool(re.search(r'qatar|قطر',h+' '+p['title'],re.I))
                r['ship_qatar']=False; r['ship_url']=None
                if p['platform']=='Shopify':
                    st2,_,j,_=await get(s,base+'/meta.json',15,50000)
                    if st2==200:
                        try:
                            m=json.loads(j); r['meta_currency']=m.get('currency'); r['meta_country']=m.get('country')
                        except Exception: pass
                if not r['qa_tld'] and not r['qar'] and not r['qatar_name']:
                    for sp in SHIP[:6]:
                        st3,_,h3,_=await get(s,base+sp,15,300000)
                        if st3==200 and re.search(r'Qatar|قطر',h3):
                            r['ship_qatar']=True; r['ship_url']=base+sp; break
            out.write(json.dumps(r,ensure_ascii=False)+'\n'); out.flush()
        await asyncio.gather(*[one(*x) for x in C2])
asyncio.run(main_())
