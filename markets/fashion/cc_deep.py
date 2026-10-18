import httpx,json,time,sys,re
crawls=["CC-MAIN-2026-39","CC-MAIN-2026-34","CC-MAIN-2026-30","CC-MAIN-2026-25"]
terms="abaya|abayas|dress|dresses|dishdasha|kaftan|jalabiya|modest|women|men|clothing|fashion|hoodie|jeans|%D8%B9%D8%A8%D8%A7%D9%8A%D8%A7%D8%AA|%D8%AF%D8%B1%D8%A7%D8%B9%D9%87|%D9%81%D8%B3%D8%A7%D8%AA%D9%8A%D9%86|%D9%85%D9%84%D8%A7%D8%A8%D8%B3|عبايات|دراعة|فساتين|ملابس"
doms=set(); c=httpx.Client(timeout=120,headers={"User-Agent":"kw-fashion-research/1.0 (polite)"})
out=open("work/cc_fashion_hosts.txt","a")
def q(crawl,url,mt,extra):
    for a in range(6):
        try:
            r=c.get(f"https://index.commoncrawl.org/{crawl}-index",params=dict(url=url,matchType=mt,output="json",fl="url",filter=f"~url:(?i).*({terms}).*",limit=extra))
            if r.status_code==200: return r.text.splitlines()
            print(crawl,url,r.status_code,flush=True)
        except Exception as e: print(crawl,url,type(e).__name__,flush=True)
        time.sleep(15*(a+1))
    return []
for crawl in crawls:
    for url,mt in (("com.kw","domain"),("kw","domain"),("*.com.kw","host")):
        ls=q(crawl,url,mt,20000)
        print(crawl,url,len(ls),flush=True)
        for l in ls:
            try: u=json.loads(l)["url"]
            except: continue
            h=re.sub(r"^https?://","",u).split("/")[0]
            if h not in doms: doms.add(h); out.write(h+"|"+u+"\n"); out.flush()
print("done",len(doms))
