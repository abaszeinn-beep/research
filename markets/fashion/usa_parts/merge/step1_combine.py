"""Combine the three USA fashion parts and dedupe by registrable domain (PSL private domains kept, so merchant subdomains stay distinct)."""
import pandas as pd, tldextract, re, os
from urllib.parse import urlparse
P=os.path.dirname(os.path.abspath(__file__))+'/..'
ext=tldextract.TLDExtract(suffix_list_urls=(),include_psl_private_domains=True)
def key(u):
    e=ext(u); return (e.domain+'.'+e.suffix).lower() if e.suffix else e.domain.lower()
def vrank(v):
    v=v.lower()
    if v.startswith('verified live (products') or v.startswith('verified live (nav') or v=='verified' or v.startswith('verified ('): return 5
    if v.startswith('verified live (page'): return 4
    if v.startswith('verified live'): return 3
    if v.startswith('known major'): return 2
    return 1
def norm_vs(v):
    return v
fr=[]
for n in ['shopify','other','discovery']:
    d=pd.read_csv(f'{P}/usa_fashion_{n}.csv').fillna('');d['Source part']=n;d['Matched Signal']=d.get('Matched Signal','');fr.append(d)
d=pd.concat(fr,ignore_index=True)
d['key']=d.Website.map(key)
cnt=d.key.value_counts(); shared=set(cnt[cnt>=5].index)
d['host']=d.Website.map(lambda u:urlparse(u if '://' in u else 'http://'+u).netloc.lower().removeprefix('www.'))
d['key']=d.apply(lambda r:r.host if r.key in shared else r.key,axis=1)
print('shared-host domains:',sorted(shared))
d['vr']=d['Verification Status'].map(vrank)
d['rich']=d.apply(lambda r:sum(bool(str(x)) for x in r[:9])+len(str(r['Matched Signal']))/1000,axis=1)
d['Platform']=d.Platform.str.lower().replace({'custom':'custom/unknown','unknown':'custom/unknown'})
d=d.sort_values(['key','vr','rich'],ascending=[True,False,False])
dup=d[d.duplicated('key',keep='first')].copy()
keep=d.drop_duplicates('key',keep='first').copy()
# record all parts a surviving row appeared in
parts=d.groupby('key')['Source part'].agg(lambda s:'+'.join(sorted(set(s))))
keep['Source part']=keep.key.map(parts)
keep=keep.sort_values('Store Name',key=lambda s:s.str.lower())
dup['Reason']='Duplicate registrable domain (kept stronger/richer row from '+dup.key.map(parts)+')'
keep.to_pickle('/tmp/step1.pkl');dup.to_pickle('/tmp/step1_dup.pkl')
print(len(d),len(keep),len(dup));print(dup[['Website','Source part']].head(10))
