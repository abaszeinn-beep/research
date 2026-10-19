import json,re,collections
from urllib.parse import urlparse
base=json.load(open('stores.json'));new=json.load(open('new_stores.json'));excl=json.load(open('excluded.json'))
before=len(base)
for x in base: x.setdefault('channel','Baseline (first pass)')
def hk(u):
    h=urlparse(u).netloc.lower().split(':')[0].split('.')
    return '.'.join(h[-3:] if len(h)>=3 and h[-2] in('co','com','org','net') else h[-2:])
REN={'off---white.com':'Off-White UAE','ryderwear.com':'Ryderwear UAE','primark.ae':'Primark UAE','victoriassecret.com':"Victoria's Secret UAE (global site, UAE locale)",'piazzaitalia.it':'Piazza Italia UAE','manyavar.com':'Manyavar UAE','suitsupply.com':'Suitsupply UAE','bottegaveneta.com':'Bottega Veneta UAE','luxemarca.com':'Luxe Marca','battaofficial.com':'Batta','businessofprelovedfashion.com':'BOPF (Business of Preloved Fashion)','nukhbaa.com':'Nukhbaa','proswimwear.ae':'ProSwimwear UAE','signaturestudio.ae':'Signature Studio','gant.ae':'GANT UAE','base53.ae':'Base53','store.liverpoolfc.ae':'Liverpool FC Store Middle East','maisondefashion.ae':'Maison de Fashion','kofah.com':'Kofah','sported.ae':'Sported','ipekyol.com':'Ipekyol UAE','fashionnova.com':'Fashion Nova UAE'}
for x in new:
    x['name']=REN.get(hk(x['site']),x['name'])
dropped=[]
keep=[]
for x in base:
    if x['key']=='trendyol.ae' or 'trendyol' in x['site']: dropped.append(x);continue
    keep.append(x)
allr=keep+new
inc={hk(x['site']) for x in allr}
excl=[e for e in excl if hk(e['site']) not in inc]
for x in dropped: excl.append(dict(name=x['name'],site=x['site'],reason='Multi-seller marketplace (Trendyol) – excluded',cat=x['cat'],key=x['key'],source='Recall pass decision'))
dec=[("Farfetch","https://www.farfetch.com/ae/","Marketplace (multi-boutique)"),("Mothercare UAE","https://www.mothercare.ae/","Kids/baby-led (maternity minor) – excluded as kids-only"),("Zara Home","https://www.zarahome.com/ae/","Home products, skipped"),("Aldo","https://www.aldoshoes.me/","Shoes/bags only"),("Charles & Keith","https://www.charleskeith.ae/","Shoes/bags only"),("Koton","https://www.koton.com/en-ae/","No UAE evidence found (Turkish site, no AED/UAE signals)"),("Levi's","https://www.levi.com/AE/en_AE/","UAE page not found"),("Hollister","https://www.hollisterco.com/shop/ae","No ordering/storefront reachable"),("Harvey Nichols","https://www.harveynichols.com/en-ae/","No UAE storefront reachable"),("The North Face UAE","https://www.thenorthface.ae/","Unreachable, no evidence"),("Vero Moda","https://www.veromoda.com/ae/","Redirects to global site, no UAE storefront"),("ONLY","https://www.only.com/ae/","Redirects to global site, no UAE storefront"),("& Other Stories","https://www.stories.com/en_ae/","No UAE storefront reachable"),("VogaCloset","https://www.vogacloset.com/","Serves Saudi storefront, not UAE"),("Modanisa","https://www.modanisa.com/ae/","Error page for UAE; global site only"),("New Balance UAE (live)","https://www.newbalance.ae/","Retained from first pass as manually accepted major")]
for n,u,r in dec:
    if n.startswith('New Balance'): continue
    excl.append(dict(name=n,site=u,reason=r,cat='',key='dec|'+n,source='Recall pass decision'))
json.dump(allr,open('stores.json','w'),ensure_ascii=False);json.dump(excl,open('excluded.json','w'),ensure_ascii=False)
ch=collections.Counter(x['channel'] for x in allr)
print(before,len(allr),ch)
json.dump({'before':before,'after':len(allr),'channels':ch},open('recall_summary.json','w'))
