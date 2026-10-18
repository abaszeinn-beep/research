"""Sitemap fallback for JS-rendered/unparseable homepages. Collect URL paths (robots Disallow for sitemap not applicable; sitemap.xml is public)."""
import asyncio, httpx, json, re, sys, os, pandas as pd, time
from urllib.parse import urlparse
from collections import defaultdict
IN,OUT=sys.argv[1],sys.argv[2]
done=set(json.loads(l)['url'] for l in open(OUT)) if os.path.exists(OUT) else set()
rows=[r for r in pd.read_pickle(IN).to_dict('records') if r['url'] not in done]
LOC=re.compile(r'<loc>\s*([^<\s]+)\s*</loc>',re.I)
hl=defaultdict(asyncio.Lock)
async def g(c,u,h):
    async with hl[h]:
        await asyncio.sleep(0.3)
        return await c.get(u)
async def work(c,r,sem,fo):
    async with sem:
        u=r['url'];p=urlparse(u);base=f"{p.scheme}://{p.netloc}";h=p.netloc
        out={'url':u,'sm':[]}
        try:
            urls=[];resp=await g(c,base+'/sitemap.xml',h)
            if resp.status_code==200:
                locs=LOC.findall(resp.text)
                subs=[x for x in locs if x.endswith('.xml') or 'sitemap' in x.lower()]
                if subs:
                    pri=[x for x in subs if re.search(r'categor|collection|product_cat|page|product',x,re.I)]
                    for s in (pri or subs)[:3]:
                        try:
                            r2=await g(c,s,h)
                            if r2.status_code==200: urls+=LOC.findall(r2.text)[:400]
                        except Exception: pass
                else: urls=locs[:600]
            out['sm']=urls[:600]; out['status']=resp.status_code
        except Exception as e: out['err']=type(e).__name__
        fo.write(json.dumps(out)+'\n');fo.flush()
async def main():
    sem=asyncio.Semaphore(40)
    async with httpx.AsyncClient(headers={'User-Agent':'Mozilla/5.0 (compatible; research-directory-bot/1.0)'},timeout=15,follow_redirects=True,verify=False) as c:
        with open(OUT,'a') as fo: await asyncio.gather(*(work(c,r,sem,fo) for r in rows))
asyncio.run(main())
