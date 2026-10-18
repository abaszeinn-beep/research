import sys,json,gzip,urllib.request,bisect,re,time
def load(idx):
    L=[l.rstrip('\n').split('\t') for l in open(idx,encoding='utf-8',errors='replace')]
    keys=[x[0].split(' ')[0] for x in L]; return L,keys
def fetch(crawl,L,keys,prefix,maxblocks=6):
    i=bisect.bisect_left(keys,prefix)-1; i=max(0,i); out=[]
    n=0
    while i<len(L) and n<maxblocks:
        if keys[i]>prefix and not keys[i].startswith(prefix): break
        f,off,ln=L[i][1],int(L[i][2]),int(L[i][3])
        for att in range(3):
            try:
                req=urllib.request.Request(f'https://data.commoncrawl.org/cc-index/collections/{crawl}/indexes/{f}',headers={'Range':f'bytes={off}-{off+ln-1}'})
                data=gzip.decompress(urllib.request.urlopen(req,timeout=60).read()).decode('utf-8','replace'); break
            except Exception: data=''; time.sleep(2)
        for l in data.split('\n'):
            if l.startswith(prefix):
                try: j=json.loads(l.split(' ',2)[2]); out.append((j['url'],j.get('status')))
                except Exception: pass
        i+=1; n+=1
    return out
if __name__=='__main__':
    P={'lulu':'com,luluhypermarket,gcc)/en-qa/','carrefour':'com,carrefourqatar)/mafqat/en/','splash':'com,splashfashions)/qa/','ck':'qa,calvinklein)/','tommy1':'qa,tommy)/','tommy2':'com,tommy,qa)/','centrepoint':'com,centrepointstores)/qa/','lifestyle':'com,lifestylestores)/qa/','defacto':'com,defacto)/en-qa/','lcw':'com,lcw)/en-qa','lcw2':'com,lcw)/ar-qa','koton':'com,koton)/en-qa/','ae':'qa,com,americaneagle)/','gap':'me,gap)/qa','levis':'qa,levi)/','levis2':'com,levi)/en-qa','puma':'com,puma)/qa/','puma2':'qa,puma)/','ua':'qa,underarmour)/','ua2':'ae,underarmour)/','nb':'qa,newbalance)/','nb2':'com,newbalance,qa)/','sk':'qa,skechers)/','uniqlo':'com,uniqlo)/qa/','namshi':'com,namshi)/qatar-en/','ounass':'qa,ounass)/','farfetch':'com,farfetch)/qa/','sivvi':'com,sivvi)/','br':'me,bananarepublic)/','rnb':'com,rnbfashion)/','styli':'com,stylishop)/qa/','ar-qa-styli':'com,stylishop)/qa/ar','prettylittlething':'qa,prettylittlething)/','brandsoutlet':'qa,brandsoutlet)/','proswim':'qa,proswimwear)/','aboutyou':'qa,aboutyou)/','printemps':'qa,printemps)/'}
    res={}
    for crawl,idx in (('CC-MAIN-2026-17','idx_a.idx'),('CC-MAIN-2025-51','idx_b.idx')):
        L,keys=load(idx)
        for k,p in P.items():
            r=fetch(crawl,L,keys,p); res.setdefault(k,[]).extend(r)
    json.dump(res,open('brand_cc.json','w'))
    FA=re.compile(r"women|womens|ladies|men\b|mens|/men|clothing|apparel|fashion|dress|shirt|abaya|jeans|hoodie|jacket|t-shirt|lingerie|/w/|/m/",re.I)
    for k,v in res.items():
        f=[u for u,s in v if FA.search(u) and s=='200']
        print(k,len(v),len(f),f[:2])
