import json,sqlite3,re,collections,os
from urllib.parse import urlparse
from rules import *
import importlib
c=sqlite3.connect('../uae/data/uae_ecom.sqlite')
db={r[0]:r for r in c.execute("select key,store_name,platform,category,status,final_url,evidence_url,subcategory from verifications")}
ref={r[0]:r for r in c.execute("select best_key,tier,tranco_rank,category,name from reference_stores where best_key is not null")}
base=json.load(open('stores.json'));excl=json.load(open('excluded.json'))
def hostkey(u):
    h=urlparse(u).netloc.lower().split(':')[0]
    p=h.split('.')
    if len(p)>=3 and p[-2] in('co','com','org','net'): p=p[-3:]
    else: p=p[-2:]
    return re.sub(r'[^a-z0-9]','','.'.join(p))
have={hostkey(x['site']) for x in base}
for x in base: x.setdefault('channel','Baseline (first pass)')
def recs(files):
    out=collections.defaultdict(list)
    for f in files:
        if not os.path.exists(f): continue
        for l in open(f):
            r=json.loads(l); out[r['key']].append(r)
    return out
def good(rl):
    g=[r for r in rl if r.get('status')==200]
    return max(g,key=lambda r:(r.get('nlinks',0)+10*r.get('nclo',0))) if g else None
MAJ=re.compile(r"namshi|ounass|centrepoint|maxfashion|splash|h&m|zara|adidas|nike|sssports|sun & sand|carrefour|bloomingdale|american eagle|gap\b|guess|victoria|styli|6th|aivi|brands for less|cotton on|under armour|dkny|michael kors|hugo boss|reebok|puma|matalan|banana republic|diesel|ted baker|karl lagerfeld|superdry|jack & jones|columbia|armani|lacoste|calvin|tommy|mango|uniqlo|marks|primark|cos\b|burberry|valentino|balenciaga|dolce|coach|kate spade|tory burch|max mara|sandro|maje|reiss|gant|muji|giordano|footlocker|foot locker|jd sports|decathlon|gymshark|athleta|champion",re.I)
def tier(key,name,r):
    t=ref.get(key)
    if t and t[1]=='major': return 'Brand-Major'
    if MAJ.search(name or ''): return 'Brand-Major'
    if r and (r.get('nprod',0)>=100 or r.get('ncol',0)>=60 or r.get('ncat',0)>=40): return 'Large'
    if r and (r.get('nprod',0)>=40 or r.get('ncol',0)>=15 or r.get('ncat',0)>=15): return 'Medium'
    return 'Small'
def nm(key,r,d):
    n=(d[1] if d else '') or ''
    if not n and r: n=re.split(r'\s[|–—-]\s',(r.get('title') or '').replace('\n',' '))[0].strip()
    return re.sub(r'^Fashion: ','',n) or key
new=[];dec=collections.Counter()
def add(chan,x):
    k=hostkey(x['site'])
    if k in have: return False
    have.add(k);x['channel']=chan;new.append(x);return True
def ecom(r): return r.get('cart') or r.get('nprod',0)>0 or r.get('ncat',0)>0 or r.get('ncol',0)>0
def uaesig(r,u):
    host=urlparse(r.get('final') or u).netloc.lower(); path=urlparse(r.get('final') or u).path
    return host.endswith('.ae') or re.search(r'(^|/)(ae|en-ae|ar-ae|ae-en|en_ae|uae)(/|$)',path) or host.startswith('ae.') or (r.get('aed') and r.get('p971'))
# A/B/C: master (verified) keys re-scanned
ex_keys={x['key'] for x in excl if x['source'].startswith('Master Directory')}
R=recs(['out_r3.jsonl','out_pw1.jsonl','out_pw3.jsonl'])
for key,rl in R.items():
    if key not in ex_keys: continue
    r=good(rl); d=db[key]; cat=d[3] or ''
    if not r: continue
    name=nm(key,r,d)
    ok,why,ns,nw=classify(r,cat,name)
    if not ok: continue
    ispw=bool(r.get('pw'))
    chan='Playwright render (JS menus)' if ispw else 'Retry of unreachable/blocked directory stores'
    stat={'verified':'Verified','verified_secondary_evidence':'Verified (secondary evidence)','verified_manual_major':'Known major retailer – manually accepted'}.get(d[4],d[4])
    typ='Fashion-only' if (cat.startswith('Fashion') and cat!='Fashion - Kids') else 'Has clothing section'
    add(chan,dict(name=name,site=d[5] or d[6] or r['url'],type=typ,gender=gender(r,cat),platform=d[2] or r.get('plat') or '',tier=tier(key,name,r),status=stat,ev=r.get('ev') or r.get('final') or r['url'],signal=f"{why}; {'rendered' if ispw else 'retry'}; terms={','.join(list(r.get('terms',{}))[:6])}",source='Master Directory (re-scan)',key=key,cat=cat))
# unverified-candidate style channels
def promote(chan,files,needuae=True,source='',minns=4):
    R=recs(files)
    for key,rl in R.items():
        r=good(rl)
        if not r: continue
        d=db.get(key); cat=(d[3] if d else '') or ''
        name=nm(key,r,d)
        ok,why,ns,nw=classify(r,cat,name)
        txt=(r.get('title') or '')+' '+(r.get('desc') or '')+' '+name
        if not ok or ns<minns or not re.search(r'abaya|clothing|apparel|fashion|dress|wear|boutique|lingerie|ملابس|عباي|أزياء|ازياء|فساتين|menswear|womenswear',txt,re.I): continue
        if not ecom(r) or (needuae and not uaesig(r,r['url'])): continue
        if cat in ('Perfumes & Oud','Beauty & Cosmetics','Mobiles & Accessories','Pharmacy & Wellness'): continue
        site=r.get('final') or r['url']
        st='Live-checked: clothing + cart + UAE signal (not in verified directory)'
        add(chan,dict(name=name,site=site,type='Has clothing section' if (cat and not cat.startswith('Fashion')) else 'Fashion-only',gender=gender(r,cat),platform=r.get('plat') or (d[2] if d else '') or '',tier=tier(key,name,r),status=st,ev=r.get('ev') or site,signal=f"nav/collections; terms={','.join(list(r.get('terms',{}))[:6])}; cart={r.get('cart')} aed={r.get('aed')}",source=source,key=key,cat=cat))
# unverified retry (exclude keys of master)
class _F: pass
rr=recs(['out_r3.jsonl','out_pw2.jsonl','out_pw3.jsonl'])
rr={k:v for k,v in rr.items() if k not in ex_keys and not k.startswith(('cc|','app|','bl|','rc|'))}
json.dump({k:v for k,v in rr.items()},open('/tmp/_rr.json','w'))
open('/tmp/_rr.jsonl','w').write(''.join(json.dumps(r)+'\n' for v in rr.values() for r in v))
promote('Retry/Playwright of unverified candidates',['/tmp/_rr.jsonl'],source='Unverified candidates (retry)')
promote('Common Crawl .ae fashion-path hosts',['out_cc.jsonl','out_cc_pw.jsonl'],source='New discovery (Common Crawl)')
promote('App Store (UAE fashion apps)',['out_app.jsonl'],needuae=False,source='New discovery (App Store)',minns=3)
# brand locale: accept with UAE locale in final URL
R=recs(['out_bl.jsonl'])
for key,rl in R.items():
    r=good(rl)
    if not r: continue
    name=nm(key,r,None); ok,why,ns,nw=classify(r,'',name)
    if not ok and not (ns>=2 and r.get('aed')): continue
    if not uaesig(r,r['url']): continue
    site=r.get('final') or r['url']
    add('Global fashion brands: UAE-locale probe',dict(name=name,site=site,type='Fashion-only',gender=gender(r,''),platform=r.get('plat') or '',tier=tier(key,name,r),status='Live-checked: UAE-locale storefront',ev=r.get('ev') or site,signal=f"UAE locale URL; terms={','.join(list(r.get('terms',{}))[:6])}; aed={r.get('aed')}",source='New discovery (brand UAE-locale probe)',key=key,cat=''))
MAN=[
('Diesel UAE','https://ae.diesel.com/','Fashion-only','Unisex','Live-checked: UAE storefront (AED, denim/apparel nav)','https://ae.diesel.com/','Brand re-check'),
('La Senza UAE','https://www.lasenza.com/ae/','Fashion-only','Women','Live-checked: AED prices, lingerie nav (lasenza.ae down with 521)','https://www.lasenza.com/ae/','Brand re-check'),
('R&B Fashion UAE','https://randbfashion.com/en_ae/explore-products','Fashion-only','Unisex','Live-checked: UAE locale + AED, clothing nav','https://randbfashion.com/en_ae/explore-products','Brand re-check'),
('Reebok UAE','https://www.reebok.ae/','Fashion-only','Unisex','Live-checked: AED, apparel nav','https://www.reebok.ae/','Brand re-check'),
('Ted Baker UAE','https://tedbaker.ae/','Fashion-only','Unisex','Live-checked: UAE official site (AED, clothing nav)','https://tedbaker.ae/','Brand re-check'),
('Karl Lagerfeld UAE','https://www.karllagerfeld.com/en-ae/','Fashion-only','Unisex','Live-checked: UAE locale + AED, clothing nav','https://www.karllagerfeld.com/en-ae/','Brand re-check'),
('Armani UAE (incl. Armani Exchange)','https://www.armani.com/en-ae/','Fashion-only','Unisex','Live-checked: UAE locale (Armani AE official site)','https://www.armani.com/en-ae/','Brand re-check'),
('Skechers UAE','https://www.skechers.com/en-ae/','Has clothing section','Unisex','Live-checked: UAE locale; clothing nav (footwear-led brand)','https://www.skechers.com/en-ae/','Brand re-check'),
('Sivvi','https://www.sivvi.com/','Fashion-only','Unisex','Known major retailer – manually accepted (UAE App Store shopping app; site unreachable from this environment)','https://apps.apple.com/ae/app/sivvi','Brand re-check'),
('Columbia UAE','https://columbia.ae/','Fashion-only','Unisex','Live-checked: AED, clothing nav','https://columbia.ae/','Brand re-check'),
]
for n,u,t,g,st,ev,src in MAN:
    add('Brand re-check (dropped/requested brands)',dict(name=n,site=u,type=t,gender=g,platform='',tier='Brand-Major',status=st,ev=ev,signal='manual re-check of requested brand',source='New discovery (brand re-check)',key='man|'+u,cat=''))
json.dump(new,open('new_stores.json','w'),ensure_ascii=False)
print(len(new),collections.Counter(x['channel'] for x in new))
