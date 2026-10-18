import json,sqlite3,re,collections,csv,sys
from urllib.parse import urlparse
from rules import *
from majors import M
c=sqlite3.connect('../uae/data/uae_ecom.sqlite')
db={r[0]:r for r in c.execute("select key,store_name,platform,category,status,final_url,evidence_url,subcategory from verifications")}
cand={r[0]:r for r in c.execute("select key,url,first_source from candidates")}
ref={}
for r in c.execute("select best_key,tier,tranco_rank,category,name from reference_stores where best_key is not null"): ref[r[0]]=r
def load(files):
    rs={}
    for f in files:
        try:
            for l in open(f):
                r=json.loads(l)
                if r['status']==200 or r['key'] not in rs: rs[r['key']]=r
        except FileNotFoundError: pass
    return rs
V=load(['out_verified.jsonl','out_retry.jsonl','out_retry2.jsonl'])
U=load(['out_unver.jsonl'])
MAJOR_HINT=re.compile(r"namshi|ounass|centrepoint|maxfashion|splash|h&m|hm\.com|zara|adidas|nike|sssports|sun & sand|carrefour|bloomingdale|american eagle|gap\b|guess|victoria|styli|6th|aivi|brands for less|cottonon|cotton on|under armour|dkny|michael kors|hugo boss|reebok|puma|skechers|matalan|banana republic|mothercare",re.I)
def tier(key,name,r):
    t=ref.get(key)
    if t and t[1]=='major': return 'Brand-Major'
    if MAJOR_HINT.search(name or ''): return 'Brand-Major'
    nprod=r.get('nprod',0) if r else 0
    ncol=r.get('ncol',0) if r else 0
    ncat=r.get('ncat',0) if r else 0
    if r and (nprod>=100 or ncol>=60 or ncat>=40): return 'Large'
    if r and (nprod>=40 or ncol>=15 or ncat>=15): return 'Medium'
    return 'Small'
def nm(key,r,d):
    n=(d[1] if d else '') or ''
    if not n and r: n=re.split(r'\s[|–—-]\s',r.get('title',''))[0].strip()
    return n or key
rows=[];excl=[]
def add(**k): rows.append(k)
for key,r in V.items():
    d=db[key]; cat=d[3] or ''; name=nm(key,r,d); site=d[5] or d[6] or r['url']
    stat={'verified':'Verified','verified_secondary_evidence':'Verified (secondary evidence)','verified_manual_major':'Known major retailer – manually accepted'}.get(d[4],d[4])
    if r['status']==200:
        ok,why,ns,nw=classify(r,cat,name)
        if ok:
            fo=cat.startswith('Fashion') and cat!='Fashion - Kids' or ns>=6 and cat in('Shoes','Sports, Fitness & Outdoor','Department Store / General') and False
            typ='Fashion-only' if (cat.startswith('Fashion') and cat!='Fashion - Kids') else 'Has clothing section'
            add(name=name,site=site,type=typ,gender=gender(r,cat),platform=d[2] or r.get('plat') or '',tier=tier(key,name,r),status=stat,ev=r.get('ev') or r.get('final') or site,signal=f"{why}; terms={','.join(list(r.get('terms',{}))[:6])}",source='Master Directory (live)',key=key,cat=cat)
        else:
            excl.append(dict(name=name,site=site,reason=('No adult-clothing signal in live nav/collections' if cat not in ('Fashion - Kids',) else 'Kids-only clothing'),cat=cat,key=key,source='Master Directory (live)'))
    else:
        rc=(ref.get(key) or [0]*5)[3] or ''
        if not (cat.startswith('Fashion') or cat.startswith('Department')) and (rc.startswith('Fashion') or rc.startswith('Department')) and d[4]!='verified' : cat=rc
        junk=re.search(r'garment|medical|duty free|water|kids|babies|baby|selfridges|fordeal|sparkling|industries',name,re.I)
        if not junk and (cat.startswith('Fashion') and cat!='Fashion - Kids' or (cat.startswith('Department') and ref.get(key))):
            typ='Fashion-only' if cat.startswith('Fashion') else 'Has clothing section'
            g='Women' if cat in('Fashion - Women','Fashion - Abayas & Modest') else 'Men' if cat=='Fashion - Men' else 'Unisex'
            add(name=name,site=site,type=typ,gender=g,platform=d[2] or '',tier=tier(key,name,None),status=stat,ev=d[6] or site,signal='directory category (site unreachable for live nav check)',source='Master Directory (category only)',key=key,cat=cat)
        else:
            excl.append(dict(name=name,site=site,reason='Not fashion by directory category; live check failed',cat=cat,key=key,source='Master Directory (unreachable)'))
# unverified promotion
new=[]
for key,r in U.items():
    if r['status']!=200: continue
    host=urlparse(r.get('final') or r['url']).netloc.lower()
    d=db.get(key); cat=(d[3] if d else '') or ''
    name=nm(key,r,d)
    ok,why,ns,nw=classify(r,cat,name)
    ok2=ok and cat not in ('Perfumes & Oud','Beauty & Cosmetics','Mobiles & Accessories','Pharmacy & Wellness') and ns>=3
    ecom=r.get('cart') or r.get('nprod',0)>0 or r.get('ncat',0)>0
    uae=host.endswith('.ae') or r.get('aed') or r.get('p971')
    strong=host.endswith('.ae') or (r.get('aed') and r.get('p971'))
    if ok2 and ecom and strong and ns>=2 and not KIDT.search(r.get('title','')) :
        site=r.get('final') or r['url']
        add(name=name,site=site,type='Has clothing section' if cat and not cat.startswith('Fashion') else 'Fashion-only',gender=gender(r,cat),platform=r.get('plat') or (d[2] if d else '') or '',tier=tier(key,name,r),status='Live-checked: clothing + cart + UAE signal (not in verified directory)',ev=r.get('ev') or site,signal=f"nav/collections; terms={','.join(list(r.get('terms',{}))[:6])}; cart={r.get('cart')} aed={r.get('aed')} p971={r.get('p971')}",source='Unverified candidates (promoted)',key=key,cat=cat)
    elif ok2:
        excl.append(dict(name=name,site=r.get('final') or r['url'],reason='Clothing signals but insufficient e-commerce/UAE evidence',cat=cat,key=key,source='Unverified candidates'))
# majors
have={urlparse(x['site']).netloc.replace('www.','') for x in rows}
bases={re.sub(r'[^a-z]','',x['name'].lower().split(' uae')[0]) for x in rows}
for n,u,t,g,p in M:
    if not u or n.split(' UAE')[0] in ('Hollister','Harvey Nichols','La Senza',"Levi's",'Diesel'): continue
    h=urlparse(u).netloc.replace('www.','')
    b=re.sub(r'[^a-z]','',n.lower().split(' uae')[0])
    if h in have or any(b in z for z in bases if len(b)>3): continue
    add(name=n,site=u,type=t,gender=g,platform=p,tier='Brand-Major',status='Known major retailer – manually accepted',ev=u,signal='Brand operates UAE storefront; site bot-walled / not live-verifiable from this environment',source='New discovery (franchise/brand lists)',key='major|'+h,cat='')
# dedupe by site host+name
seen=set();out=[]
for x in rows:
    k=re.sub(r'[^a-z0-9]','',urlparse(x['site']).netloc.lower().replace('www.','')) 
    if k in seen: continue
    seen.add(k); out.append(x)
json.dump(out,open('stores.json','w'),ensure_ascii=False)
json.dump(excl,open('excluded.json','w'),ensure_ascii=False)
print(len(out),len(excl))
print(collections.Counter(x['source'] for x in out));print(collections.Counter(x['type'] for x in out));print(collections.Counter(x['gender'] for x in out))
