import pandas as pd,json,re,sys,collections
sys.path.insert(0,'/tmp/w')
from classify import *
s=pd.read_pickle('/tmp/w/scoped.pkl')
FASH={'Apparel & Fashion','Fashion & Apparel','Fashion - Women','Fashion - Sportswear & Streetwear','Fashion - Men','Fashion - Activewear & Streetwear'}
F={}
for l in open('/tmp/w/fetch.jsonl'):
    d=json.loads(l)
    if d['u'] not in F or d.get('p'): F[d['u']]=d
NW=re.compile(r"\b(women'?s?|ladies|girl|her|she|femme|mama|bridal|lingerie|bra|bikini|dress(es)?|boutique|maternity|queen|goddess|belle)\b",re.I)
NM=re.compile(r"\b(men'?s?|man|guys?|gents?|him|king|mens)\b",re.I)
def name_gender(n,cat):
    if cat=='Fashion - Women': return 'Women'
    if cat=='Fashion - Men': return 'Men'
    w,m=bool(NW.search(n)),bool(NM.search(n))
    return 'Women' if w and not m else 'Men' if m and not w else 'Unisex'
def tier(r):
    t=r['tier'];rk=r['rank']
    if t=='huge' or (rk==rk and rk<=1500): return 'Brand-Major'
    if t=='large' or (rk==rk and rk<=20000): return 'Large'
    if t in('medium','recognized') or (rk==rk and rk<=200000): return 'Medium'
    return 'Small'
inc=[];exc=[];stats=collections.Counter()
for _,r in s.iterrows():
    u=r['Root Domain / Storefront URL'];nm=r['Store Name'];cat=r['cat'];fc=cat in FASH
    base=dict(**{'Store Name':nm,'Website':u,'Platform':'Shopify','Size Tier':tier(r),'Stored Category':cat})
    def ex(reason): exc.append({**base,'Reason':reason})
    if r['pre']=='not': ex('Non-fashion stored category (not live-checked)'); continue
    d=F.get(u)
    if d and d.get('p'):
        n,cl,w,m,uu,exs,st=analyze(d['p']); ty=decide(n,cl,fc,st)
        if ty and ty!='no':
            g=gender(cl,w,m,uu)
            if g=='Unisex' and uu==0 or (w==m==uu==0):
                aw=sum(1 for q in d['p'] if WOM.search(' '.join([q[0],q[1]]+q[2]))); am=sum(1 for q in d['p'] if MEN.search(' '.join([q[0],q[1]]+q[2])))
                ng=name_gender(nm,cat)
                if ng!='Unisex' and aw+am==0: g=ng
                elif aw>=3*am and aw>=max(3,0.1*n): g='Women'
                elif am>=3*aw and am>=max(3,0.1*n): g='Men'
                elif w==m==uu==0: g=ng
            inc.append({**base,'Type':ty,'Gender':g,'Verification Status':'Verified live (products.json)','Evidence URL':d['src'],'Source':'USA master directory (Shopify) + live Shopify products.json','Matched Signal':f'{cl}/{n} products adult clothing; e.g. '+' ; '.join(exs[:2])})
        else: ex(f'Live products.json: {cl}/{n} clothing products - not an adult clothing store')
        continue
    if fc:
        ty='Fashion-only' if cat!='x' else ''
        inc.append({**base,'Type':ty,'Gender':name_gender(nm,cat),'Verification Status':'Classified from stored evidence (live data unavailable)','Evidence URL':u,'Source':'USA master directory (Shopify) stored category','Matched Signal':f'stored category: {cat}'})
    else: ex('Live data unavailable and stored category not fashion')
I=pd.DataFrame(inc);E=pd.DataFrame(exc)
cols=['Store Name','Website','Type','Gender','Platform','Size Tier','Verification Status','Evidence URL','Source','Matched Signal']
I[cols].to_csv('/tmp/w/inc.csv',index=False);E.to_csv('/tmp/w/exc.csv',index=False)
print(len(s),len(I),len(E));print(I.Type.value_counts(),I.Gender.value_counts(),I['Verification Status'].value_counts(),I['Size Tier'].value_counts(),sep='\n')
print(E.Reason.str[:40].value_counts().head(8))
