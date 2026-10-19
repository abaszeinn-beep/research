import asyncio,aiohttp,json,re
UA={'User-Agent':'Mozilla/5.0 (compatible; research-bot; polite)'}
AE=re.compile(r"(^|[/._-])(ae|uae)([/._-]|$)|en-ae|ar-ae|ae-en|ae_en|en_ae|ar_ae|/ae/",re.I)
async def probe(s,sem,d):
    base=d.replace('www.','')
    cands=[f"https://www.{base}/ae/",f"https://www.{base}/en-ae/",f"https://www.{base}/ae/en/",f"https://www.{base}/en_ae/",f"https://www.{base}/ar-ae/",f"https://ae.{base}/",f"https://www.{base.split('.')[0]}.ae/",f"https://{base.split('.')[0]}.ae/",f"https://www.{base}/uae/"]
    async with sem:
        for u in cands:
            try:
                async with s.get(u,timeout=aiohttp.ClientTimeout(total=15),allow_redirects=True) as r:
                    fin=str(r.url)
                    if r.status==200 and AE.search(re.sub(r'^https?://','',fin)) :
                        t=await r.text(errors='ignore')
                        if len(t)>2000: return d,u,fin
            except Exception: pass
    return d,None,None
async def main():
    ds=open('brand_list.txt').read().split()
    sem=asyncio.Semaphore(8)
    async with aiohttp.ClientSession(headers=UA,connector=aiohttp.TCPConnector(ssl=False)) as s:
        res=await asyncio.gather(*[probe(s,sem,d) for d in ds])
    json.dump(res,open('brand_probe.json','w'))
    print(sum(1 for r in res if r[1]),len(res))
asyncio.run(main())
