import httpx,json,re,time
c=httpx.Client(timeout=170,headers={"User-Agent":"kw-fashion-research/1.0 (polite)"})
F="abaya|abayas|dress|dresses|dishdasha|kaftan|jalabiya|modest|women|clothing|fashion|%D8%B9%D8%A8%D8%A7%D9%8A%D8%A7%D8%AA|%D8%AF%D8%B1%D8%A7%D8%B9%D9%87|%D9%81%D8%B3%D8%A7%D8%AA%D9%8A%D9%86|%D9%85%D9%84%D8%A7%D8%A8%D8%B3"
qs=[("com.kw","domain",F),("kw","domain",F),
    ("*.myshopify.com","prefix","(kuwait|abaya|q8|-kw|kw-)[^/]*\\.myshopify|abaya.*kw"),
    ("*.zid.store","prefix","(kuwait|q8|kw)"),("*.mnasati.com","prefix",""),("*.salla.sa","prefix","(kuwait|q8|kw)")]
out={}
for url,mt,flt in qs:
    for a in range(5):
        try:
            p={"url":url,"matchType":"domain" if mt=="domain" else "host" if url.startswith("*.") else mt,"fl":"original","collapse":"urlkey","limit":8000,"output":"txt"}
            if flt: p["filter"]="original:.*("+flt+").*"
            r=c.get("http://web.archive.org/cdx/search/cdx",params=p)
            print(url,r.status_code,len(r.text.splitlines()),flush=True)
            if r.status_code==200:
                for u in r.text.splitlines():
                    h=re.sub(r"^https?://","",u).split("/")[0].split(":")[0].lower(); out.setdefault(h,u)
                break
        except Exception as e: print(url,type(e).__name__,flush=True)
        time.sleep(20*(a+1))
json.dump(out,open("work/wb_hosts.json","w")); print(len(out))
