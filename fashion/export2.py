import sqlite3,pickle,collections,re,urllib.parse as up,random
from build3 import classify3
from build import size_tier
base,excl=pickle.load(open('result.pkl','rb'))
have={f['key'] for f in base}|{f['final_key'] for f in base if f['final_key']}
s=sqlite3.connect('scan3.sqlite'); s.execute("attach '/tmp/sa/data/saudi_ecom.sqlite' as m")
q="""select s3.key,s3.url,s3.ok,s3.platform,s3.cat_tokens,s3.prod_tokens,s3.cats,s3.women,s3.men,s3.uni,s3.kid,s3.adult,s3.nlinks,s3.evidence_url,s3.err,
 v.store_name,v.category,v.status,v.final_key,v.evidence_url,c.first_source,c.priority,
 pw.ok,pw.cat_tokens,pw.all_tokens,pw.women,pw.men,pw.uni,pw.kid,pw.adult
 from s3 join m.verifications v using(key) join m.candidates c using(key) left join pw using(key)"""
cur=s.execute(q); cols=[d[0] for d in cur.description]
add=[]; stat=collections.Counter()
for t in cur:
    d={}
    for c_,v_ in zip(cols,t): d.setdefault(c_,v_)
    r=dict(key=d['key'],name=d['store_name'] or d['key'],category=d['category'] or '',cat_tokens=d['cat_tokens'],prod_tokens=d['prod_tokens'],cats=d['cats'],women=d['women'],men=d['men'],uni=d['uni'],kid=d['kid'],adult=d['adult'],ok=d['ok'])
    fk=d['final_key']
    if d['key'] in have or (fk and fk in have): continue
    if not d['status'].startswith('verified'): continue
    via='scan3'
    res=classify3(r)
    if not res and d['ok:1'] if False else (not res and t[cols.index('ok')] is not None and False): pass
    if not res:
        # playwright result
        pk=[c for c in cols]
        pwok=t[22]
        if pwok:
            ct=[x for x in (t[23] or '').split(',') if x]
            r2=dict(r,ok=1,cat_tokens=t[23] or '',prod_tokens=t[24] or '',cats='',women=t[25] or 0,men=t[26] or 0,uni=t[27] or 0,kid=t[28] or 0,adult=t[29] or 0)
            res=classify3(r2)
            if not res and len(set(ct))>=2 and r['category'] not in ('Pets',):
                res=dict(type='Fashion-only' if r['category'].startswith('Fashion') else 'Has clothing section',gender='Women' if r2['women'] else ('Men' if r2['men'] else 'Unisex'),signal='categories (rendered): '+",".join(sorted(set(ct))[:3]),how='category-level')
            if res: via='playwright'
    if not res: continue
    fs=d['first_source']
    if fs=='appstore:sa_fashion': src='New discovery: Saudi App Store sellerUrl'
    elif fs=='commoncrawl:fashion_paths': src='New discovery: Common Crawl cluster index'
    elif fs=='seed:fashion_v1': src='New discovery: fashion seed list'
    elif d['priority']==78: src='New discovery: transient-failure unverified candidates'
    else: src='Recall re-scan: category-level (Salla/Zid/sitemaps)' if via=='scan3' else 'Recall re-scan: Playwright rendered menus'
    lab={'verified':'Verified','verified_secondary_evidence':'Verified (secondary evidence)','verified_manual_major':'Known major retailer – manually accepted'}[d['status']]
    add.append(dict(key=d['key'],name=r['name'],site=d['url'],type=res['type'],gender=res['gender'],platform=d['platform'] or '',tier=size_tier(d['key'],d['url'],d['platform']),status=lab,ev=d['evidence_url'] or d['url'],signal=res['signal'],how=res['how'],src=src,cat=r['category'],final_key=fk))
seen=set(); out2=[]
for f in add:
    k=f['final_key'] or f['key']
    if k in seen: continue
    seen.add(k); out2.append(f)
print(len(base),len(out2),collections.Counter(f['src'] for f in out2))
pickle.dump((base+out2,excl),open('result2.pkl','wb')); pickle.dump(out2,open('added.pkl','wb'))
