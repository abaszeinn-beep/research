"""Apply re-derived gender + sanity-pass removals; emits /tmp/step3_main.pkl, /tmp/step3_removed.pkl, QA sample."""
import pandas as pd, json, re, sys
sys.path.insert(0,'.')
from step2_gender_fetch import flags, toks, W, M, U
d=pd.read_pickle('/tmp/step1.pkl')
res={}
for l in open('/tmp/gender_fetch.jsonl'):
    r=json.loads(l);res[r['key']]=r
def decide(row):
    r=res.get(row['key']);old=row['Gender']
    if r is None or r.get('error'): return old,'fetch_missing'
    w=m=u=n=0;ok=False;cu=0
    for k,nk in (('coll','coll_n'),('prod','prod_n'),('home','home_n')):
        if k in r:
            ok=True;a,b,c=r[k];w+=a;m+=b;u+=c;n+=r[nk]
            if k=='coll':cu=c
    if not ok:
        why='robots' if r.get('robots_blocked') else 'fetch_failed:%s'%(r.get('coll_status') or r.get('home_status'))
        return (name_gender(row) or old),why
    def present(c,o):
        if c>=2: return (c/max(n,1)>=0.03 or c>=5 or o>=2) and (c/(c+o)>=0.08)
        return c==1 and n<=12 and o==0
    st=set()
    if present(w,m):st.add('W')
    if present(m,w):st.add('M')
    expl=cu>=1 or (u>=3 and u/(w+m+u)>=0.15)
    if st=={'W','M'} or expl: return 'Unisex','fetch'
    if st=={'W'}: return 'Women','fetch'
    if st=={'M'}: return 'Men','fetch'
    nm=name_gender(row)
    if nm: return nm,'name'
    if old in('Women','Men'): return old,'kept_old_nosignal'
    return 'Unspecified','no_signal'
def name_gender(row):
    w,m,u=flags(row['Store Name']+' '+row['Website'].split('//')[-1].split('.')[0].replace('-',' '))
    if (w and m) or u:return 'Unisex'
    return 'Women' if w else 'Men' if m else None
KIDS=re.compile(r"\b(kids?|baby|babies|children'?s?|toddlers?|infants?|newborns?)\b",re.I)
ADULT=re.compile(r"\b(women'?s?|men'?s?|adults?|ladies|womenswear|menswear)\b",re.I)
KIDS_OK={'billionaire boys club','baby phat'}
KIDS_EXTRA={'ala california girls state','mia belle girls'}
KEEP_NAMES={'marine layer','run the jewels','stoopher & boots','army navy marine store','couture candy','boot world'}
MKT=re.compile(r"\b(marketplace|flea market|costco|walmart|amazon|etsy|ebay|wholesale|wholesalers|distributors?|in bulk|bulk|tractor supply)\b",re.I)
NONF=re.compile(r"\b(pets?|cbd|vape|vaporizers?|nutrition|supplements?|pharmacy|furniture|medical supply|beauty supply|auto parts|jerky|candy|sweets|mints)\b",re.I)
SPEC=re.compile(r"\b(shoes?|boots?|footwear|sneakers?|kicks|bags?|handbags?|purses?|jewel\w*|jewelers|watch(es)?|eyewear|sunglasses|hats?|caps|socks|printing|embroidery|signs?)\b",re.I)
FASH=re.compile(r"(apparel|clothing|clothes|boutique|fashion|wear|outfitters?|threads|tees?|shirts?|garments?|dress|denim|lingerie|swim|apparels)",re.I)
DOM_RM={'garmentory.com':'Marketplace (multi-vendor)','thredup.com':'Marketplace (resale)','therealreal.com':'Marketplace (resale)','rebelsmarket.com':'Marketplace (multi-vendor)',
 'morphmarket.com':'Non-fashion marketplace','superlinewholesale.com':'B2B wholesale-only','t-shirtwholesaler.com':'B2B wholesale-only','wholesalefashiontrends.com':'B2B wholesale-only',
 'eyemarketme.com':'Custom print/branding shop (B2B)','worldbuildersmarket.com':'Non-fashion','shopgrandcentralmarket.com':'Non-fashion (food hall)','webmediamarketing360.wixsite.com':'Not a store (review/marketing site)'}
GENERIC=re.compile(r"^(my site|home|access .*|just a moment.*|error \d+.*|attention required.*|\d{1,2}|it)$",re.I)
def clean_name(row):
    n=re.sub(r'\s+',' ',row['Store Name'].replace('&amp;','&')).strip()
    n=re.sub(r'^welcome to ','',n,flags=re.I)
    if GENERIC.match(n):
        from urllib.parse import urlparse
        h=urlparse(row['Website']).netloc.lower().removeprefix('www.').split('.')[0]
        return h.title()
    return n
def reason(row):
    if row['key'] in DOM_RM:return DOM_RM[row['key']]
    n=row['Store Name'];nl=n.lower()
    if any(k in nl for k in KIDS_OK) or nl in KEEP_NAMES:return None
    if nl in KIDS_EXTRA:return 'Kids-only by name (no adult signal)'
    if KIDS.search(n) and not ADULT.search(n):return 'Kids-only by name (no adult signal)'
    if MKT.search(n):return 'Marketplace / wholesale-only / big-box by name'
    if NONF.search(n) and not FASH.search(n):return 'Non-fashion by name'
    if SPEC.search(n) and not FASH.search(n):return 'Shoes/bags/accessories/print-shop only by name'
    return None
if __name__=='__main__':
    g=d.apply(decide,axis=1,result_type='expand');d['New Gender']=g[0];d['Gender basis']=g[1]
    d['Store Name']=d.apply(clean_name,axis=1)
    d['rm']=d.apply(reason,axis=1)
    rem=d[d.rm.notna()].copy();main=d[d.rm.isna()].copy()
    print(len(main),len(rem));print(main['Gender basis'].value_counts());print(pd.crosstab(main.Gender,main['New Gender']))
    main.to_pickle('/tmp/step3_main.pkl');rem.to_pickle('/tmp/step3_removed.pkl')
