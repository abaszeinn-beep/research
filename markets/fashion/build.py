import json,re,sqlite3,csv,collections
from fashion_lib import *
db=sqlite3.connect('../qatar/data/qatar_ecom.sqlite'); db.row_factory=sqlite3.Row
P=[json.loads(l) for l in open('probe_main.jsonl')]
NEW=[json.loads(l) for l in open('probe_new.jsonl')]
EX=[json.loads(l) for l in open('probe_extra.jsonl')]
# manual include decisions: host-substring -> (display name, Type, Gender)
FO,HC='Fashion-only','Has clothing section'
INC={
'nike.qa':('Nike Qatar',HC,'Unisex'),'muji.qa':('Muji Qatar',HC,'Unisex'),'victoriassecret.com.qa':("Victoria's Secret Qatar",FO,'Women'),
'aivi.com':('6thStreet / AIVI Qatar',FO,'Unisex'),'lichi.com':('Lichi',FO,'Women'),'almotahajiba.com':('Almotahajiba',FO,'Women'),
'gymshark.qa':('Gymshark Qatar',FO,'Unisex'),'brandsco.qa':('Brands Qatar',FO,'Men'),'swish.qa':('Swish.qa',HC,'Unisex'),
'dokofashionwear.qa':('Doko Fashion Wear',FO,'Women'),'daralqaftan.qa':('Dar Al Qaftan',FO,'Women'),'fazi.qa':('FAZI',FO,'Women'),
'nymphaea.qa':('Nymphaea Abayas',FO,'Women'),'myabaya.qa':('My Abaya',FO,'Women'),'mijade.qa':('Mijade QA',FO,'Women'),'sadil.qa':('Sadil',FO,'Women'),
'phati.qa':('Phati',FO,'Women'),'azul.qa':('Azul',FO,'Women'),'hermosa.qa':('Hermosa QA',HC,'Women'),'fetch.qa':('Fetch',FO,'Unisex'),
'eupathy.qa':('Eupathy',HC,'Unisex'),'romano.qa':('Romano',FO,'Unisex'),'roumastyle.qa':('Roma Style',FO,'Women'),'peak.qa':('Peak Qatar',HC,'Unisex'),
'desigual.com':('Desigual Qatar',FO,'Unisex'),'squatwolf.com':('Squatwolf Qatar',FO,'Unisex'),
'replayjeans.qa':('Replay Qatar',FO,'Unisex'),'offpitch.qa':('Off Pitch',FO,'Unisex'),'mandala.qa':('Mandala Qatar',FO,'Women'),
'shoptriumph.qa':('Triumph & Sloggi Qatar',FO,'Women'),'decathlon.qa':('Decathlon Qatar',HC,'Unisex'),'footlocker.qa':('Foot Locker Qatar',HC,'Unisex'),
'tafaul.com.qa':('Tafaul Hub',FO,'Unisex'),'rumi.qa':('Rumi Earth',FO,'Women'),'qfit.qa':('Qfit',FO,'Unisex'),'tedbaker.qa':('Ted Baker Qatar',FO,'Unisex'),
'suitsupply.com':('Suitsupply',FO,'Men'),'chantelle.com':('Chantelle',FO,'Women'),'luisaspagnoli.com':('Luisa Spagnoli',FO,'Women'),
'balmain.com':('Balmain',FO,'Unisex'),'dolcegabbana.com':('Dolce & Gabbana',HC,'Unisex'),'amiparis.com':('Ami Paris',FO,'Unisex'),
'valentino.com':('Valentino',FO,'Unisex'),'qa.macduggal.com':('Mac Duggal Qatar',FO,'Women'),'giordano.qa':('Giordano Qatar',FO,'Unisex'),
'en-qa.sssports.com':('Sun & Sand Sports Qatar',HC,'Unisex'),'marksandspencer.qa':('Marks & Spencer Qatar',HC,'Unisex'),'vanillawear-qa.com':('Vanilla Wear',FO,'Women'),
'salams.com':('Salam Stores',HC,'Unisex'),'malikaclothing.qa':('Malika Clothing',FO,'Women'),'adidas.qa':('Adidas Qatar',HC,'Unisex'),
'afraaboutique.com':('Afraa Boutique',FO,'Unisex'),'samastore.qa':('Sama Store',HC,'Unisex'),'fitwell.qa':('Fitwell',HC,'Women'),
'trendycorner.qa':('Trendy Corner',FO,'Women'),'lunacouture.qa':('Luna Couture',FO,'Women'),
'coudre.qa':('Coudre',FO,'Women'),'dartline.qa':('Dart',FO,'Women'),
'grizzly.qa':('Grizzly',FO,'Unisex'),'thejacketmaker.qa':('The Jacket Maker',FO,'Unisex'),
'skylink.qa':('Skylink',FO,'Women'),'digitaldepot.qa':('Digital Depot (Akasya)',FO,'Women'),
'emvano.qa':('Emvano',FO,'Unisex'),'nimbus.com.qa':('Nimbus',FO,'Unisex'),'dary.com.qa':('Dary',FO,'Women'),
'dreams.com.qa':('Dreams',FO,'Women'),'jaya-qa.com':('Jaya',FO,'Women'),'maxfashion.com':('Max Fashion Qatar',HC,'Unisex'),'matalanme.com':('Matalan Qatar',FO,'Unisex'),
'qa.alnasser.net':('Al Nasser Qatar',HC,'Unisex'),'shop5.qa':('Shop Five',FO,'Men'),'rivafashion.com':('Riva Fashion',FO,'Women'),
'maje.qa':('Maje Qatar',FO,'Women'),'sandro.qa':('Sandro Qatar',FO,'Unisex'),'undiz.com':('Undiz',FO,'Women'),'wearfigs.com':('FIGS',FO,'Unisex'),
'shein.com':('SHEIN',FO,'Unisex'),'zara.com':('Zara Qatar',FO,'Unisex'),'pullandbear.com':('Pull&Bear Qatar',FO,'Unisex'),'stradivarius.com':('Stradivarius Qatar',FO,'Women'),
'oysho.com':('Oysho Qatar',FO,'Women'),'bershka.com':('Bershka Qatar',FO,'Unisex'),'massimodutti.com':('Massimo Dutti Qatar',FO,'Unisex'),'vogacloset.com':('VogaCloset',HC,'Unisex'),
'shop.mango.com':('Mango Qatar',FO,'Unisex'),'outoftheblue.qa':('Out of the Blue',HC,'Unisex'),'instaura.qa':('Instaura Lingerie',FO,'Women'),
'next.qa':('Next Qatar',HC,'Unisex'),
'qatarfactories':None,
'aceandzianwomenclothing.qa':('Ace & Zian Women Clothing',FO,'Women'),
}
# mirror/duplicate keys collapsed by display name
EXCL_REASON={
'getit.qa':'general store; clothing not confirmed','js.qa':'general store; clothing not confirmed','jumbosouq':'general store; clothing not confirmed','newyorker':'German site; no Qatar storefront evidence','the-fashion-square':'US storefront; no Qatar evidence','basicabaya':'UAE store; no Qatar storefront','mytheresa':'no Qatar storefront evidence','luluhypermarket':'bot-walled (HTTP 403); clothing section not verifiable live - manual check needed','carrefourqatar':'site did not return catalog to a plain fetch; clothing section not verifiable - manual check needed','homecentre':'furniture/home only',
'storey.shop':'multi-brand marketplace','iqalattar':'headwear accessory only (igal)','verno.qa':'no clothing evidence','toda.qa':'no clothing evidence',
'junior couture':'kids-only','scarletkids':'kids-only','scarlet kids':'kids-only','mumzworld':'baby/kids marketplace','babyology':'baby-only','mamasandpapas':'baby/kids-focused brand',
'mothercare':'kids/baby-only','kiddo':'kids-only','kidzy':'kids-only','kendamil':'baby-only','tinyworld':'baby/kids-only','shamiya':'kids-only (no adult signal)',
'colehaan':'shoes/bags/accessories-focused','culture-circle':'sneakers/accessories resale; not a Qatar storefront','souqly':'multi-vendor marketplace','localbazar':'multi-vendor marketplace',
'dohalist':'classifieds','tawarmall':'mall directory / aggregator','storecensus':'directory (not a store)','smartuniforms':'B2B uniform supplier','globeuniforms':'B2B uniform supplier','royaluniformhub':'B2B uniform supplier',
'safetywares':'PPE / B2B workwear','sskqatar':'PPE / B2B workwear','customon':'non-Qatar print-on-demand site','hoodiego':'non-Qatar print-on-demand site','fog.qa':'printing services','nitted':'custom T-shirt printing service',
'qmax':'home goods (clothes racks only)','factory.qa':'textile industry directory','signinn':'waterproofing/HVAC firm','qarmainspect':'B2B software','fashionrevolution':'NGO site',
'qkicks':'sneakers-focused','boohooman':'non-Qatar storefront (no Qatar signal)','dresslily':'non-Qatar storefront','theiconic':'Australian site; no Qatar storefront','mayfair.qa':'perfume store',
'byfatma':'gift shop (apparel is minor accessories)','benrahim':'unclear (trading company)','kasimy':'home goods','vibram':'footwear only','dokan':'unverified general store, fashion not confirmed',
'jawdatop':'general store, fashion not confirmed','noa.com.qa':'general store, fashion not confirmed','binsufi':'trading company','bellecurve':'unclear',
'modanisa':'no Qatar storefront signal','prettylittlething':'no Qatar storefront signal','boohoo.com':'no Qatar storefront signal','jarir':'electronics/books only',
}
db_ver={r['key']:dict(r) for r in db.execute("select key,final_url,store_name,platform,category,status,reason,evidence_url,market_score,product_evidence from verifications")}
rank={}
for r in csv.DictReader(open('../qatar/data/reference_universe.csv')):
    for d in r['domains'].split(): rank[d]=(r['tier'],r['tranco_rank'])
LARGE=re.compile(r"zara|pull|stradi|oysho|bershka|massimo|mango|nike|adidas|h&m|hm\.com|marks|next|shein|sun & sand|sssports|decathlon|foot ?locker|6thstreet|aivi|max fashion|matalan|victoria|muji|gymshark|giordano|ted baker|vogacloset|lacoste|burberry|balenciaga|styli|tommy|calvin|gucci|salam stores|replay|desigual|suitsupply|valentino|mytheresa|triumph|al nasser|riva|splash|lifestyle|centrepoint|brands for less|ounass|namshi|american eagle|ralph|guess|puma|reebok|fila",re.I)
def hostof(p):
    from urllib.parse import urlparse
    return urlparse(p.get('final') or p['url']).netloc.lower().replace('www.','')
def match(p):
    k=p['key'].lower(); h=hostof(p)
    for s in INC:
        if s in k or s in h: return s
rows={}; excluded=[]
def add(name,url,typ,gen,plat,tier,ver,evu,sig,src):
    k=re.sub(r'[^a-z0-9]','',name.lower())
    if k in rows:
        if rows[k]['ver'].startswith('Unverified') and not ver.startswith('Unverified'): pass
        else: return
    rows[k]=dict(name=name,url=url,typ=typ,gen=gen,plat=plat,tier=tier,ver=ver,evu=evu,sig=sig,src=src)
def tier_of(name,p):
    if LARGE.search(name) or LARGE.search(p.get('key','')): return 'Large'
    n=p.get('n_products') or 0
    if p.get('platform') in ('Magento','Salesforce Commerce Cloud','Custom (Next.js)') : return 'Medium'
    if n>=200: return 'Medium'
    return 'Small'
def verlabel(p):
    s=p['dbstatus']; r=p.get('dbreason') or ''
    if s=='verified': return 'Verified'
    if s=='verified_manual_major': return 'Known major retailer – manually accepted'
    if s=='verified_secondary_evidence': return 'Verified (secondary evidence)'
    return 'Unverified candidate – weak Qatar signal (fashion-classified)'
for p in P:
    m=match(p)
    if m is None:
        low=(p['key']+' '+(p.get('name') or '')).lower()
        for s,r in EXCL_REASON.items():
            if s in low and (p['dbstatus'].startswith('verified') or 'fashion' in (p.get('dbcat') or '').lower() or classify(p) and classify(p)[0]!='not' if p.get('ok') else False):
                excluded.append((p.get('name') or p['key'],p['key'],r)); break
        continue
    v=INC[m]
    if v is None: continue
    name,typ,gen=v
    # prefer live classification detail when available
    c=classify(p,p.get('dbcat') or '') if p.get('ok') else None
    sig=(c[3] if c and c[3] else '') or ('DB category: '+(p.get('dbcat') or '')+'; live fetch %s'%(p.get('err') or 'thin page'))
    ev=p.get('ev') or p.get('final') or p['url']
    dbr=db_ver.get(p['key'],{})
    if not p.get('ok') and dbr.get('evidence_url'): ev=dbr['evidence_url']
    plat=p.get('platform') or p.get('dbplat') or ''
    if p['dbstatus'].startswith('verified') is False and ('|qa' in p['key']):
        pass
    url=(dbr.get('final_url') or p['url']) if (re.search(r'\|qa$',p['key']) or not p.get('ok')) else p.get('final')
    add(name,url,typ,gen,plat,tier_of(name,p),verlabel(p),ev,sig,'directory' if p['dbstatus'].startswith('verified') else 'unverified-candidates')
# extra from fashion-named candidates
for p in EX:
    m=match(p)
    if m and INC[m]:
        name,typ,gen=INC[m]; c=classify(p)
        add(name,p['final'],typ,gen,p.get('platform',''),'Small','Unverified candidate – weak Qatar signal (fashion-classified)',p.get('ev') or p['final'],c[3] if c else '', 'new-discovery')
# new discovery from brand list
NEWINC={
 'lacoste.qa':('Lacoste Qatar',FO,'Unisex','Known major retailer – Qatar storefront (lacoste.qa, QAR)'),
 'qa.burberry.com':('Burberry Qatar',FO,'Unisex','Qatar-locale storefront (qa.burberry.com); no QAR on homepage'),
 'balenciaga.com':('Balenciaga Qatar',HC,'Unisex','Qatar-locale storefront (en-qa, QAR)'),
 'stylishop.com':('Styli Qatar',FO,'Unisex','Qatar-locale storefront (/qa/en); bot-light page, no QAR on homepage'),
}
for p in NEW:
    if not p['ok']: continue
    k=hostof(p)+p['final']
    for s,(name,typ,gen,ver) in NEWINC.items():
        if s in k:
            c=classify(p); add(name,p['final'],typ,gen,p.get('platform',''),'Large',ver,p['final'],(c[3] if c and c[3] else p.get('title','')),'new-discovery')
json.dump({'rows':list(rows.values()),'excluded':excluded},open('built.json','w'),ensure_ascii=False,indent=1)
print(len(rows),collections.Counter(r['typ'] for r in rows.values()),collections.Counter(r['gen'] for r in rows.values()),collections.Counter(r['src'] for r in rows.values()))
