import json,urllib.request,urllib.parse,time,sys
terms="abaya,fashion,clothing,women fashion,men fashion,modest fashion,sportswear,lingerie,thobe,dresses,apparel,boutique,streetwear,denim,activewear,department store,shopping online saudi,hijab,kaftan,jalabiya,menswear,womenswear,online shopping fashion,clothes,underwear,swimwear,outlet,luxury fashion,brands online shopping,ladies wear,عبايات,عباية,ملابس,أزياء,فساتين,ثياب,ثوب,موضة,تسوق,بوتيك,جلابيات,ملابس رياضية,ملابس نسائية,ملابس رجالية,لانجري,تسوق اون لاين,متجر ملابس,ازياء نسائية".split(',')
res={}
for t in terms:
    u="https://itunes.apple.com/search?"+urllib.parse.urlencode({'term':t,'country':'sa','entity':'software','limit':200})
    for att in range(3):
        try:
            d=json.load(urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'}),timeout=25)); break
        except Exception as e: d=None; time.sleep(5)
    if not d: print('fail',t,file=sys.stderr); continue
    for r in d['results']:
        if r.get('primaryGenreName') in ('Shopping','Lifestyle','Business') or 'Shopping' in r.get('genres',[]):
            res[r['trackId']]={'name':r['trackName'],'seller':r.get('sellerName'),'url':r.get('sellerUrl'),'genre':r.get('primaryGenreName'),'desc':r.get('description','')[:300],'term':t}
    time.sleep(3.2)
json.dump(res,open('appstore_sa.json','w'),ensure_ascii=False,indent=0); print(len(res))
