import httpx,json,re,time,collections
terms="abaya|fashion|women clothing|men clothing|clothing store|kandura|dresses|modest fashion|lingerie|activewear|sportswear|shoes and clothes|online fashion shopping|luxury fashion|streetwear|denim|hijab|thobe|boutique|outfits|wardrobe|designer clothes|mens fashion|womens fashion|swimwear|underwear|plus size|maternity|jalabiya|kaftan|sneakers apparel|shop clothes|fashion sale|brands for less|department store|hypermarket|mall shopping|sports store|gym wear|pakistani clothes|indian ethnic wear|turkish fashion|korean fashion|vintage clothing|thrift fashion|resale fashion|luxury resale|rent dress".split('|')
out={}
c=httpx.Client(timeout=30)
for t in terms:
    for ent in ('software',):
        for off in (0,):
            try:
                r=c.get("https://itunes.apple.com/search",params={'term':t,'country':'ae','entity':ent,'limit':200})
                for a in r.json().get('results',[]):
                    out[a['trackId']]={k:a.get(k) for k in ('trackName','sellerName','sellerUrl','artistViewUrl','primaryGenreName','description')}
                    out[a['trackId']]['description']=(a.get('description') or '')[:300]
            except Exception as e: print(t,e)
            time.sleep(2)
json.dump(out,open('appstore_raw.json','w'),ensure_ascii=False)
print(len(out),sum(1 for v in out.values() if v['sellerUrl']))
