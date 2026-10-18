import httpx,json,re,time
c=httpx.Client(timeout=150,headers={"User-Agent":"kw-fashion-research/1.0 (polite)"})
qs=[("mnasati.com","domain",None),
("*.myshopify.com","host","(?i).*(abaya|dishdasha|kuwait|q8|[-.]kw[-./]|kwt).*"),
("*.zid.store","host","(?i).*(abaya|kuwait|q8|kw).*"),
("*.salla.sa","host","(?i).*(kuwait|q8|abaya).*"),
("*.mnasati.com","host",None)]
out={}
for url,mt,flt in qs:
  for crawl in ("CC-MAIN-2026-39","CC-MAIN-2026-34","CC-MAIN-2026-30"):
    ok=False
    for a in range(4):
        try:
            p=dict(url=url,output="json",fl="url",limit=3000)
            if mt=="domain": p["matchType"]="domain"
            if flt: p["filter"]="~url:"+flt
            r=c.get(f"https://index.commoncrawl.org/{crawl}-index",params=p)
            print(url,crawl,r.status_code,len(r.text.splitlines()),flush=True)
            if r.status_code==200:
                for l in r.text.splitlines():
                    try:u=json.loads(l)["url"]
                    except: continue
                    h=re.sub(r"^https?://","",u).split("/")[0]; out.setdefault(h,u)
                ok=True;break
            if r.status_code==404: ok=True;break
        except Exception as e: print(url,crawl,type(e).__name__,flush=True)
        time.sleep(10*(a+1))
    if ok and out: pass
json.dump(out,open("work/cc2_hosts.json","w")); print(len(out))
