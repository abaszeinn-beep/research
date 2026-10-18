import httpx,json,time,re
terms=["abaya","fashion Kuwait","boutique","عبايات","ملابس","فساتين","dishdasha","دشداشة","ازياء","kuwait clothing","women fashion kuwait","men fashion kuwait","modest fashion","sportswear kuwait","lingerie kuwait","hijab","jalabiya","kaftan","fashion store","clothing store"]
res={}
c=httpx.Client(timeout=25)
for t in terms:
  for cc in ("kw",):
    for ent in ("software",):
        for a in range(4):
            try:
                r=c.get("https://itunes.apple.com/search",params={"term":t,"country":cc,"entity":ent,"limit":200}); 
                for x in r.json().get("results",[]): res[x["trackId"]]={"name":x["trackName"],"seller":x.get("sellerName"),"url":x.get("sellerUrl"),"genre":x.get("primaryGenreName"),"term":t}
                break
            except Exception as e: time.sleep(5*(a+1))
    time.sleep(1)
json.dump(res,open("work/apps2.json","w"),ensure_ascii=False); print(len(res))
