import httpx,json,time,urllib.parse
terms="abaya,abayas,dishdasha,thobe,fashion,women fashion,men fashion,clothing,clothes,fashion store,modest wear,lingerie,sportswear,activewear,dresses,kuwait fashion,kuwait abaya,hijab,online fashion,streetwear,brand outlet,department store,ملابس,عبايات,أزياء,ازياء,دشداشة,فساتين,ملابس رجالية,ملابس نسائية,بوتيك,متجر ازياء,حريمي,جلابية,قفطان,ملابس رياضية,ملابس داخلية".split(",")
res={}
c=httpx.Client(timeout=20)
for t in terms:
    for ent in ("software",):
        try:
            r=c.get("https://itunes.apple.com/search",params={"term":t,"country":"kw","entity":ent,"limit":200})
            for x in r.json().get("results",[]):
                res[x["trackId"]]={"name":x["trackName"],"seller":x.get("sellerName"),"url":x.get("sellerUrl"),"genre":x.get("primaryGenreName"),"term":t}
        except Exception as e: print(t,e)
    time.sleep(1)
json.dump(res,open("work/apps.json","w"),ensure_ascii=False)
print(len(res))
