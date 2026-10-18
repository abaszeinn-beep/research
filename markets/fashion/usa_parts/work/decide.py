import pandas as pd, re, json
from urllib.parse import urlparse
src=open('/tmp/w/markets/fashion/usa_parts/work/classify.py').read()
for nm in ['WOM','MEN','UNI','KID','NONCLO','NAMEBAD','NAMENONCLO']:
    exec(re.search(r'^'+nm+r'=.*$',src,re.M).group(0))
df=pd.read_pickle('/tmp/res.pkl')
FC={'Apparel & Fashion','Fashion & Apparel','Fashion - Women'}
df['fc']=df.cat.isin(FC)|df.refcat.fillna('').str.startswith('Fashion')
WEAK={'tops','jackets','bras','shorts','coats','jerseys','jersey'}
BADCATS=re.compile(r'Jewel|Shoes|Footwear|Bags|Eyewear|Electr|Computer|Book|Food|Grocery|Furniture|Home|Auto|Tools|Industrial|Pets|Religious|Music|Party|Gifts|Arts|Toys|Beauty|Mobile|Lighting|Health|Packaging|Firearms|Baby',re.I)
MANUAL=json.load(open('/tmp/w/markets/fashion/usa_parts/work/manual.json')) if __import__('os').path.exists('/tmp/w/markets/fashion/usa_parts/work/manual.json') else {}
APP=re.compile(r"cloth|apparel|fashion|wear|boutique|tee|shirt|thread|style|dress|closet|outfit|wardrobe|denim|jean|lingerie|swim|bikini|couture|garment|attire|hoodie|merch|gown|gear|collection|studio|label|atelier|vintage|mode|chic|glam|lux|trend|co\\.?$|supply|goods|shop|store|outfitters|market",re.I)
NOTAPP=re.compile(r"restaurant|\bcandy\b|bullets|glassblow|railway|railroad|\bcafe\b|bakery|\bgrill\b|tavern|pizza|brewing|winery|distill|\bammo\b|bbq|steakhouse",re.I)
def dom(u): return re.sub(r'^www\.','',urlparse(u).netloc.lower())
def tier(r):
    if r.vstatus.startswith('Known') or r.reftier=='huge': return 'Brand-Major'
    if r.reftier=='large': return 'Large'
    if r.reftier in('medium','recognized'): return 'Medium'
    return 'Small'
out=[];exc=[]
for r in df.itertuples():
    rec=dict(**{'Store Name':r.name,'Website':r.url,'Platform':r.platform or 'unknown','Size Tier':tier(r),'Source':'USA master directory ('+r.vstatus+')','cat':r.cat})
    d=dom(r.url); name=r.name or ''
    def inc(typ,gender,status,ev,sig):
        rec.update({'Type':typ,'Gender':gender,'Verification Status':status,'Evidence URL':ev,'Matched Signal':sig});out.append(rec)
    def ex(reason): rec['Exclusion Reason']=reason; rec['live']=r.live; exc.append(rec)
    if d in MANUAL:
        m=MANUAL[d]
        if m[0]=='x': ex('manual: '+m[1]);continue
        inc(m[0],m[1],'Known major – stored/known category (bot-walled or JS site; no bypass)',r.url,m[2]);continue
    if r.live=='ok':
        clo=r.clo if isinstance(r.clo,set) else set()
        core=clo-WEAK; nclo=len(clo)
        wom,men,kid,uni=r.wom,r.men,r.kid,r.uni
        gen=wom+men>0
        kidonly=(wom+men+uni==0 and kid>=3 and kid>=2*max(nclo,1)) or (bool(NAMEBAD.search(name)) and wom+men==0)
        if r.fc: kidonly=(wom+men==0 and kid>=3 and kid>=2*nclo)
        nonclo_name=bool(NAMENONCLO.search(name)) and wom+men==0 and not (core)
        ok=False;status=None;ev=r.ev if isinstance(r.ev,str) else r.url;sig=r.sig if isinstance(r.sig,str) else ''
        if r.fc:
            if kidonly: ex('kids-only signals');continue
            if nonclo_name: ex('name indicates non-clothing (shoes/jewelry/bags/B2B)');continue
            if NOTAPP.search(name) and len(core)<3: ex('non-fashion business (restaurant/food/etc.) with incidental merch');continue
            if len(core)>=2 or (len(core)>=1 and gen): ok=True;status='Verified live (nav/sitemap clothing links)'
            elif nclo>=1 or gen: ok=True;status='Verified live (weak nav signal; stored fashion category)'
            elif isinstance(r.tmatch,str) and r.tmatch: ok=True;status='Verified live (page title/meta)';ev=r.url;sig='title:'+r.tmatch
            else:
                txt=name+' '+str(getattr(r,'title','') or '')+' '+d
                if not NOTAPP.search(name): ok=True;status='Stored category only (live page has no parseable nav)'; ev=r.url;sig='stored category '+r.cat
                else: ex('stored fashion category but no live/nav/name evidence');continue
        else:
            if kidonly: ex('kids-only signals');continue
            both=wom>0 and men>0
            bad=bool(BADCATS.search(r.cat)) or nonclo_name
            nameapp=bool(re.search(r'cloth|apparel|boutique|fashion|western wear|denim|lingerie|swimwear|\bwear\b|outfitters',name,re.I)) and not re.search(r'book|home|jewel|sweet|food|pool|hardware|furniture|baby|children|kids',name,re.I)
            if nameapp and nclo>=1: good=True
            elif bad: good=len(core)>=3 and both
            else: good=len(core)>=3 or (len(core)>=2 and gen) or (bool(clo&{'clothing','apparel'}) and both and len(core)>=1)
            if good:
                ok=True;status='Verified live (nav/sitemap clothing links)'
            else: ex('no adult clothing signal in live nav/sitemap');continue
        wg='Women' if wom>0 else None; mg='Men' if men>0 else None
        if r.cat=='Fashion - Women' or (r.refcat=='Fashion - Women'): wg='Women'
        if r.refcat=='Fashion - Men': mg='Men'
        if wg and mg: g='Unisex'
        elif wg: g='Women'
        elif mg: g='Men'
        else:
            if re.search(r"\b(women|womens|ladies|woman|girl|lady|she)\b|boutique|dress",name,re.I): g='Women'
            elif re.search(r"\b(men|mens|man|guys)\b",name,re.I): g='Men'
            else: g='Unisex'
        inc('Fashion-only' if r.fc else 'Has clothing section',g,status,ev,sig)
    else:
        if r.fc and not NAMENONCLO.search(name) and not NAMEBAD.search(name) and r.live.startswith('fail') and not NOTAPP.search(name):
            g='Women' if (r.cat=='Fashion - Women' or re.search(r"\b(women|womens|ladies|boutique|dress)\b",name,re.I)) else ('Men' if re.search(r"\b(men|mens)\b",name,re.I) else 'Unisex')
            inc('Fashion-only',g,'Stored category only (live check failed: %s)'%r.live,r.url,'stored category '+r.cat)
        else: ex('not fashion by stored category' if r.live=='notchecked' else 'live check failed/blocked; no fashion evidence')
O=pd.DataFrame(out);E=pd.DataFrame(exc)
O.to_pickle('/tmp/O.pkl');E.to_pickle('/tmp/E.pkl')
print(len(O),len(E));print(O.Type.value_counts());print(O.Gender.value_counts());print(O['Verification Status'].value_counts())
