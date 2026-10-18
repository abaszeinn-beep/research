import sqlite3, csv, re, collections, urllib.parse as up, random, json, os
from build import *
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
MAN=[("Redtag","https://sa.redtagfashion.com/","Redtag fashion & home retailer (Landmark/Al Hokair); site bot-walled (403)"),
("Lefties","https://www.lefties.com/sa/","Inditex brand; Saudi storefront bot-walled (403)"),
("Asics","https://www.asics.com/sa/","Sportswear/footwear brand; Saudi storefront bot-walled (403)"),
("Calvin Klein","https://www.calvinklein.sa/","Calvin Klein KSA store; bot-walled (403)"),
("Centrepoint (Lifestyle)","https://www.lifestyleshops.com/sa/","Landmark Group fashion department store; bot-walled (403)"),
("DeFacto","https://www.defacto.com/en-sa/","DeFacto Saudi storefront; bot-walled (403)"),
("Diesel","https://diesel.com/sa/","Diesel Saudi storefront; JS-rendered Salesforce store"),
("Fred Perry","https://www.fredperry.com/sa-en/","Fred Perry Saudi storefront; bot-walled (403)"),
("Lacoste","https://www.lacoste.sa/","Lacoste Saudi store; JS cart not detectable statically"),
("Tryano","https://www.tryano.com/sa/","Tryano (Chalhoub/Al Tayer) fashion store; JS-rendered Salesforce store"),
("US Polo Assn","https://uspa.com/sa/","U.S. Polo Assn. Saudi storefront; JS-rendered"),
("Koton","https://www.koton.sa/en","Koton Saudi storefront; thin static HTML"),
("River Island","https://www.riverisland.com/sa/","River Island Saudi storefront; bot-walled"),
("Old Navy","https://www.oldnavy.com.sa/","Old Navy Saudi store; browser check inconclusive"),
("Hollister","https://www.hollisterco.sa/","Hollister Saudi store; browser check inconclusive"),
("Abercrombie & Fitch","https://www.abercrombie.sa/","Abercrombie & Fitch Saudi store; browser check inconclusive"),
("Calzedonia","https://www.calzedonia.com/sa/","Calzedonia Saudi storefront (legwear/swimwear/clothing)"),
("R&B Fashion","https://randbfashion.com/en_sa/explore-products","R&B Fashion Saudi storefront; JS-rendered")]
def master_rows():
    q="""select s.*,v.store_name,v.platform vplat,v.category,v.status vstatus,v.final_key,v.saudi_score,v.evidence_url vev,v.reason,c.first_source from scan s join m.verifications v using(key) join m.candidates c using(key)"""
    cur=s.execute(q); cols=[d[0] for d in cur.description]
    return [dict(zip(cols,r)) for r in cur]
def status_label(vs,reason):
    if vs=='verified': return 'Verified'
    if vs=='verified_secondary_evidence': return 'Verified (secondary evidence)'
    if vs=='verified_manual_major': return 'Known major retailer – manually accepted'
    if vs=='unverified' and reason and 'weak_saudi' in reason: return 'Unverified – weak Saudi signals only'
    return None
BRANDS={'sa.hm.com':('Has clothing section','Women, Men'),'namshi.com|sa':('Fashion-only','Women, Men'),'zara.com|sa':('Fashion-only','Women, Men'),'maxfashion.com|sa':('Fashion-only','Women, Men'),'sa.nayomi.com':('Fashion-only','Women'),'decathlon.sa':('Has clothing section','Women, Men'),'decathlon.com.sa':('Has clothing section','Women, Men'),'reebok.sa':('Fashion-only','Women, Men'),'adidas.sa':('Fashion-only','Women, Men'),'mango.com|sa':('Fashion-only','Women, Men'),'brandsforless.com|sa':('Has clothing section','Women, Men'),'stylishop.com|sa':('Has clothing section','Women'),'newbalance.com.sa':('Has clothing section','Women, Men'),'luluhypermarket.com|sa':('Has clothing section','Women, Men'),'carrefourksa.com':('Has clothing section','Women, Men'),'americaneagle.com.sa':('Fashion-only','Women, Men')}
def run():
    rows=master_rows(); final=[]; excl=[]
    for r in rows:
        lab=status_label(r['vstatus'],r['reason'])
        r['name']=r['store_name'] or r['key']; r['category']=r['category'] or ''
        if lab is None:
            if r['vstatus']=='unverified':
                res,why=classify(r)
                if res: excl.append((r['name'],r['url'],'unverified candidate (not included): '+(r['reason'] or '')[:80]+' — looks like clothing seller ('+res['signal']+')',r['category'],r['key']))
            continue
        res,why=classify(r)
        if res is None and r['key'] in BRANDS:
            t,g=BRANDS[r['key']]; res=dict(type=t,gender=g,signal='known major retailer with clothing (live site bot-walled/throttled; category or brand knowledge)',how='major-brand')
        if res is None:
            if r['category'] in ('Fashion & Apparel','Fashion - Women','Fashion - Men','Fashion - Abayas & Modest','Fashion - Sportswear & Streetwear','Fashion - Kids','Shoes','Bags & Luggage','Jewelry & Watches','Sports, Fitness & Outdoor','Department Store / General','General / Unclassified','Baby & Maternity','Religious Products','Perfumes & Oud','') and True:
                excl.append((r['name'],r['url'],why,r['category'],r['key']))
            continue
        src='New discovery: fashion seed list' if r['first_source']=='seed:fashion_v1' else ('Existing unverified candidates' if lab.startswith('Unverified') else 'Existing master directory')
        final.append(dict(key=r['key'],name=r['name'],site=r['url'],type=res['type'],gender=res['gender'],platform=r['vplat'] or r['platform'],
            tier=size_tier(r['key'],r['url'],r['vplat']),status=lab,ev=r['evidence_url'] or r['vev'] or r['url'],signal=res['signal'],how=res['how'],src=src,cat=r['category'],final_key=r['final_key']))
    have_dom={up.urlparse(f['site']).netloc.replace('www.','') for f in final}
    allmaster={up.urlparse(r['url']).netloc.replace('www.','') for r in rows}
    for n,u,note in MAN:
        d=up.urlparse(u).netloc.replace('www.','')
        if d in allmaster or any(d.split('.')[0]==x.split('.')[0] and 'redtag' not in d for x in have_dom if False): 
            excl.append((n,u,'already in master directory (classified there)','',u)); continue
        g='Women, Men' if n not in ('Calzedonia',) else 'Women'
        t='Fashion-only'
        if n in('Centrepoint (Lifestyle)','Redtag'): t='Has clothing section'; g='Women, Men'
        final.append(dict(key=u,name=n,site=u,type=t,gender=g,platform='custom/unknown',tier='Brand-Major',status='Known major retailer – manually accepted',ev=u,signal='known fashion brand/retailer; '+note,how='manual-major',src='New discovery: GCC/global fashion brand (manual major)',cat='',final_key=u))
    # dedupe on final_key then domain
    seen={};out=[]
    for f in final:
        k=f['final_key'] or f['key']
        if k in seen: continue
        seen[k]=1; out.append(f)
    return out,excl
if __name__=="__main__":
    out,excl=run()
    print(len(out),len(excl))
    import pickle; pickle.dump((out,excl),open('result.pkl','wb'))
    print(collections.Counter(f['type'] for f in out)); print(collections.Counter(f['src'] for f in out)); print(collections.Counter(f['gender'] for f in out))
