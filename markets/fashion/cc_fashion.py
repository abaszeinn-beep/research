import sys,re,json,collections,time,httpx
sys.path.insert(0,'/tmp/uae-fashion/markets/uae')
from mkt_ecom.discover_cc_raw import get,crawl_ids,index_lines,plan_chunks,decode_members,surt_host,BASE,UA
FP=re.compile(r"abaya|abaia|dress|women|womens|woman|ladies|\bmen\b|mens|menswear|clothing|clothes|apparel|kandura|thobe|thawb|modest|lingerie|activewear|sportswear|hoodie|t-?shirt|jeans|jalabiya|kaftan|hijab|fashion|%D8%B9%D8%A8%D8%A7%D9%8A|%D9%81%D8%B3%D8%A7%D8%AA|%D9%85%D9%84%D8%A7%D8%A8%D8%B3|عباي|فساتين|ملابس",re.I)
HN=re.compile(r"abaya|abaia|kandura|thobe|fashion|wear|cloth|apparel|boutique|couture|moda|lingerie|modest|hijab|jalabi|kaftan|dress|outfit|attire|closet|wardrobe|atelier|style|label|denim|tshirt|hoodie|sportswear|activewear|streetwear",re.I)
tld='ae'
out=collections.defaultdict(lambda:[0,0,''])
def harvest(client,crawl,chunk):
    f,off=chunk[0][0],chunk[0][1];end=chunk[-1][1]+chunk[-1][2]-1
    r=get(client,f"{BASE}cc-index/collections/{crawl}/indexes/{f}",{"Range":f"bytes={off}-{end}"})
    if r is None: return False
    for text in decode_members(r.content):
        for line in text.split(b"\n"):
            if not line.startswith(b"ae,"): continue
            surt=line.split(b" ",1)[0].decode('utf-8','replace')
            host=surt_host(surt); path=surt.split(")",1)[1] if ")" in surt else "/"
            o=out[host]; o[1]+=1
            if FP.search(path):
                o[0]+=1
                if not o[2]: o[2]=path[:100]
    return True
client=httpx.Client(headers=UA,follow_redirects=True)
ncr=int(sys.argv[1])
for crawl in crawl_ids(client,ncr):
    lines=index_lines(client,crawl,tld)
    singles,chunks=plan_chunks(lines,tld)
    for h in singles: out[h][1]+=0
    print(crawl,len(lines),len(singles),len(chunks),flush=True)
    for i,ch in enumerate(chunks):
        harvest(client,crawl,ch)
        if i%20==0:
            print(crawl,i,len(chunks),len(out),flush=True)
            json.dump(out,open('cc_fashion.json','w'))
    json.dump(out,open('cc_fashion.json','w'))
print('done',len(out))
