import json,urllib.request,urllib.parse,time,sys
terms="abaya,fashion,clothing,women fashion,men fashion,modest fashion,sportswear,lingerie,thobe,dresses,apparel,boutique,streetwear,denim,activewear,department store,shopping online qatar,hijab,kaftan,jalabiya,menswear,womenswear,online shopping fashion,clothes shopping,underwear,swimwear,outlet fashion,luxury fashion,brands online shopping,ladies wear".split(',')
res={}
for t in terms:
    for ent in ('software',):
      for off in (0,):
        u="https://itunes.apple.com/search?"+urllib.parse.urlencode({'term':t,'country':'qa','entity':ent,'limit':200})
        try:
            d=json.load(urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'}),timeout=20))
        except Exception as e: print(t,e,file=sys.stderr); continue
        for r in d['results']:
            if r.get('primaryGenreName') in ('Shopping','Lifestyle','Business') or 'Shopping' in r.get('genres',[]):
                res[r['trackId']]={'name':r['trackName'],'seller':r.get('sellerName'),'url':r.get('sellerUrl'),'genre':r.get('primaryGenreName'),'desc':r.get('description','')[:300],'term':t}
        time.sleep(1.5)
json.dump(res,open('appstore_qa.json','w'),ensure_ascii=False,indent=0); print(len(res))
