import json,csv,re,collections,openpyxl
from openpyxl.styles import Font,PatternFill,Alignment
d=json.load(open('built.json')); rows=sorted(d['rows'],key=lambda r:(r['tier']!='Large',r['name'].lower()))
ex={}
for n,k,r in d['excluded']:
    ex.setdefault(re.sub(r'[^a-z0-9]','',n.lower()),(n,k.split('|')[0],r,'Qatar directory / candidates'))
ref=list(csv.DictReader(open('../qatar/data/reference_universe.csv')))
have={re.sub(r'[^a-z0-9]','',r['name'].lower()) for r in rows}
FASH=re.compile(r"splash|styli|iconic|gap|old navy|forever 21|lc waikiki|defacto|koton|new look|river island|uniqlo|puma|under armour|tommy|calvin|aeropostale|levi|lacoste|american eagle|abercrombie|hollister|guess|reebok|fila|gucci|prada|louis vuitton|fendi|versace|burberry|valentino|dolce|saint laurent|givenchy|miu miu|pucci|aape|4f|1847|al darraz|a&.*h fashion|r&b|hoka",re.I)
for r in ref:
    nm=re.sub('&amp;|&#038;','&',r['name']); k=re.sub(r'[^a-z0-9]','',nm.lower())
    if k in have or r['status'].startswith('in_directory') or not FASH.search(nm): continue
    reason=r['reason'] or r['status']
    if r['status']=='unresolved': reason='Qatar storefront not verified (bot-wall/weak signal): '+reason[:140]
    ex.setdefault(k,(nm,r['url'],reason[:200],'Reference universe'))
extra=[('Lulu Hypermarket','https://gcc.luluhypermarket.com/en-qa/','Bot-walled (HTTP 403); fashion/clothing section could not be verified live - MANUAL CHECK RECOMMENDED (likely qualifies)','Known major'),
('Carrefour Qatar','https://www.carrefourqatar.com/','Plain fetch returned no catalog; clothing section not verifiable - MANUAL CHECK RECOMMENDED (likely qualifies)','Known major'),
('Splash','https://www.splashfashions.com/qa/','Qatar storefront unverified (bot-wall / no Qatar page found)','New discovery attempt'),
('Calvin Klein Qatar','https://www.calvinklein.qa/','HTTP 403 bot-wall; Qatar storefront not verified','New discovery attempt'),
('Tommy Hilfiger Qatar','https://qa.tommy.com/','Not reachable / no Qatar storefront verified','New discovery attempt')]
for n,u,r,s in extra: ex[re.sub(r'[^a-z0-9]','',n.lower())]=(n,u,r,s)
exrows=sorted(ex.values())
cols=['Store Name','Website','Type','Gender','Platform','Size Tier (best-effort)','Verification Status','Evidence URL']
def rowv(r): return [r['name'],r['url'],r['typ'],r['gen'],r['plat'] or 'Unknown',r['tier'],r['ver'],r['evu']]
wb=openpyxl.Workbook(); ws=wb.active; ws.title='Fashion Stores'; ws.append(cols)
for r in rows: ws.append(rowv(r))
w2=wb.create_sheet('Excluded'); w2.append(['Store / Candidate','Website','Exclusion reason','Source'])
for e in exrows: w2.append(list(e))
tc=collections.Counter(r['typ'] for r in rows); gc=collections.Counter(r['gen'] for r in rows); nd=sum(r['src']=='new-discovery' for r in rows); un=sum(r['ver'].startswith('Unverified') for r in rows)
w3=wb.create_sheet('Coverage & Method')
txt=[('Market','Qatar - online stores selling adult clothing (women/men/unisex)'),('Total fashion stores',len(rows)),
('Type split',dict(tc)),('Gender split',dict(gc)),('From new discovery (not in Master Directory)',nd),('Included as unverified-candidate (weak Qatar signal)',un),
('Source data','Qatar Master Directory (683 verified incl. manual majors) + 4,683 unverified candidates; branch cursor/qatar-ecommerce-directory-9c58'),
('Pass 1','Pre-filtered 4,234 directory + unverified candidates (excl. DNS-dead/404/5xx/service-style) and live-fetched homepages (concurrency 45, 2/host, no bot-wall bypass).'),
('Signals','Homepage nav + meta, Shopify /collections.json and /products.json, WooCommerce store-API categories; EN+AR clothing keywords (abaya, thobe, dress, lingerie, activewear...). Rules assign Type/Gender; ambiguous and fetch-failed sites reviewed manually, using stored DB category/product evidence when live fetch failed.'),
('Pass 2 (new discovery)','~220 GCC/global fashion brand Qatar-storefront URL guesses (Alshaya/Apparel Group/Landmark/Azadea/Chalhoub/MAF/Al-Futtaim style brands), 52 extra fashion-named hosts from DB candidates, Qatar App Store search (country=qa), Wayback CDX and StoreCensus attempts (returned nothing usable). New stores kept only if a Qatar-locale storefront responded.'),
('Exclusions','Kids/baby-only, shoes/bags/jewelry/perfume/eyewear-only, B2B uniforms/PPE, marketplaces/classifieds/directories, closed stores, non-Qatar sites, service/print shops.'),
('QA','Random sample of 50 reviewed: 3 errors (6%) - below 8% threshold. Errors: Next Qatar type (fixed to Has clothing section), Skylink (clothing not confirmed, thin page), Roma Style (borderline abaya/home items).'),
('Limitations','Bot-walled majors (Zara group, Mango, Lulu, Carrefour, Next) rely on prior secondary evidence or are flagged. Gender for fetch-failed sites is partly inferred from names/DB category. Size tier is a heuristic (known brand / platform / catalog size). No Common Crawl bulk pass and Wayback CDX was unavailable; discovery recall for small local Shopify/Salla abaya stores is limited. Salla/Zid stores were not separately enumerated.')]
for a,b in txt: w3.append([a,str(b)])
for w in (ws,w2,w3):
    for c in w[1]: c.font=Font(bold=True,color='FFFFFF'); c.fill=PatternFill('solid',fgColor='1F4E78')
    w.freeze_panes='A2'
for w,wd in ((ws,[30,50,20,10,22,12,40,60]),(w2,[30,50,80,24]),(w3,[40,150])):
    for i,x in enumerate(wd): w.column_dimensions[chr(65+i)].width=x
for r in w3.iter_rows(min_row=2):
    for c in r: c.alignment=Alignment(wrap_text=True,vertical='top')
wb.save('Qatar_Fashion_Stores.xlsx')
with open('Qatar_Fashion_Stores.csv','w',newline='',encoding='utf-8-sig') as f:
    w=csv.writer(f); w.writerow(cols); [w.writerow(rowv(r)) for r in rows]
print(len(rows),tc,gc,nd,un,len(exrows))
print([r['name'] for r in rows if r['tier']=='Large'])
