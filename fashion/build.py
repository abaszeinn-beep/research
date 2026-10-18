import sqlite3, re, json, csv, os, urllib.parse as up
from fk import *
s=sqlite3.connect('fashion.sqlite'); s.execute("attach '/tmp/sa/data/saudi_ecom.sqlite' as m")
FASH=lambda c:(c or '').startswith('Fashion') and c!='Fashion - Kids'
HEAVY={'Furniture','Home Decor','Bedding, Mattresses & Textiles','Kitchenware & Tableware','Cleaning & Household Supplies','Pets','Agriculture & Gardening','Automotive Parts & Accessories','Healthcare & Medical Equipment','Industrial & Tools','Building Materials','Lighting & Electrical','Home Appliances','Packaging & Supplies','Wholesale & B2B','Computers & Electronics','Mobiles & Accessories','Grocery & Food','Coffee, Tea & Dates','Chocolates & Sweets','Books & Stationery','Gaming','Pharmacy & Wellness','Office Supplies','Electronic Components','Home Improvement & Hardware','Beauty & Cosmetics','Personal Care & Grooming'}
CLEAR={'عبايات','عباية','عبايه','abaya','abayas','thobe','thobes','ثوب','ثياب','فساتين','dress','dresses','lingerie','لانجري','clothing','apparel','ملابس','jalabiya','جلابية','garments','t-shirt','t-shirts','قمصان','hoodies','menswear','womenswear','ملابس داخلية','ready-to-wear','activewear','sportswear','kaftan','بشوت','سراويل','بناطيل'}
NAMEHINT=re.compile(r'abaya|abaia|thobe|thawb|jalab|lingerie|fashion|wear\b|dress|cloth|apparel|boutique|outfit|عباي|ثوب|ثياب|أزياء|ازياء|فساتين|ملابس|موضة|لانجري|بوتيك|جلاب',re.I)
def nm(*a): return " ".join(x or '' for x in a)
def tier_map():
    t={}
    for k,tier,rank,status,name in s.execute("select best_key,tier,tranco_rank,status,name from m.reference_stores where best_key is not null and best_key!=''"):
        t[k]=(tier,rank,name)
    return t
TM=tier_map()
def size_tier(key,url,plat,manual=False):
    if manual: return 'Brand-Major'
    t=TM.get(key)
    if t and t[0]=='major': return 'Brand-Major'
    if t and t[0]=='medium': return 'Large'
    host=up.urlparse(url).netloc
    if key.startswith('salla.sa/') or host.endswith('.zid.store') or host.endswith('myshopify.com') or host=='salla.sa': return 'Small'
    return 'Medium'
def classify(r):
    cat=r['category']; strong=[x for x in r['strong'].split(',') if x]; weak=[x for x in r['weak'].split(',') if x]
    nstrong=len(set(strong)); clear=any(x in CLEAR for x in strong)
    nameh=bool(NAMEHINT.search(nm(r['name'],r['key'])))
    ev=None; reason=None
    if r['ok'] and nstrong:
        need=3 if cat in HEAVY else 2
        if nstrong>=need or (clear and (FASH(cat) or cat in ('Sports, Fitness & Outdoor','Department Store / General','General / Unclassified','Shoes','Bags & Luggage','Religious Products','Jewelry & Watches','Baby & Maternity','Fashion - Kids','Arts, Crafts & Handmade','Flowers, Gifts & Party','Perfumes & Oud','') or cat is None) and (nstrong>=2 or FASH(cat) or cat in('Department Store / General','General / Unclassified','Sports, Fitness & Outdoor'))):
            ev=(r['signal'] or strong[0],'live')
    if not ev and r['ok'] and len(set(weak))>=2 and (FASH(cat) or cat in('Department Store / General','Sports, Fitness & Outdoor')):
        ev=(",".join(weak),'live-weak')
    if not ev and FASH(cat) and nameh and cat!='Fashion - Kids':
        ev=('store name/domain hint + category '+cat,'name+category')
    if not ev and cat in ('Fashion & Apparel','Fashion - Women','Fashion - Men','Fashion - Abayas & Modest','Fashion - Sportswear & Streetwear') and not r['ok']:
        return None,'unclassifiable: storefront not fetchable (%s)'%(r['err'] or 'no content')
    if not ev:
        if cat in ('Bags & Luggage','Jewelry & Watches','Shoes','Perfumes & Oud'): return None,'accessories/shoes/bags/jewelry/perfume only - no clothing signal'
        if cat=='Fashion - Kids' : return None,'kids-only clothing'
        if FASH(cat): return None,'stored fashion category but no clothing signal in nav/categories'
        return None,'no clothing signal'
    kids_only = r['kid'] and not (r['women'] or r['men'] or r['uni'] or r['adult'])
    if kids_only or cat=='Fashion - Kids' and not (r['women'] or r['men'] or r['uni'] or r['adult']): return None,'kids-only clothing'
    g=[]
    w=r['women'] or cat in('Fashion - Women','Fashion - Abayas & Modest'); mn=r['men'] or cat=='Fashion - Men'
    if w: g.append('Women')
    if mn: g.append('Men')
    if r['uni'] or not g: g.append('Unisex')
    typ='Fashion-only' if (FASH(cat) and ev[1]!='x') else 'Has clothing section'
    if not FASH(cat) and nstrong>=5 and cat in ('General / Unclassified',''): typ='Fashion-only'
    return dict(type=typ,gender=", ".join(g),signal=ev[0],how=ev[1]),None
