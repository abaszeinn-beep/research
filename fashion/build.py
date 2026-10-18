import sqlite3, re, json, csv, os, urllib.parse as up
from fk import *
s=sqlite3.connect('fashion.sqlite'); s.execute("attach '/tmp/sa/data/saudi_ecom.sqlite' as m")
FASH=lambda c:(c or '').startswith('Fashion') and c!='Fashion - Kids'
HEAVY={'Furniture','Home Decor','Bedding, Mattresses & Textiles','Kitchenware & Tableware','Cleaning & Household Supplies','Pets','Agriculture & Gardening','Automotive Parts & Accessories','Healthcare & Medical Equipment','Industrial & Tools','Building Materials','Lighting & Electrical','Home Appliances','Packaging & Supplies','Wholesale & B2B','Computers & Electronics','Mobiles & Accessories','Grocery & Food','Coffee, Tea & Dates','Chocolates & Sweets','Books & Stationery','Gaming','Pharmacy & Wellness','Office Supplies','Electronic Components','Home Improvement & Hardware','Beauty & Cosmetics','Personal Care & Grooming'}
CLEAR={'عبايات','عباية','عبايه','abaya','abayas','thobe','thobes','ثوب','ثياب','فساتين','dress','dresses','lingerie','لانجري','clothing','apparel','ملابس','jalabiya','جلابية','garments','t-shirt','t-shirts','قمصان','hoodies','menswear','womenswear','ملابس داخلية','ready-to-wear','activewear','sportswear','kaftan','بشوت','سراويل','بناطيل'}
NAMEHINT=re.compile(r'abaya|abaia|thobe|thawb|jalab|lingerie|fashion|wear\b|dress|cloth|apparel|boutique|outfit|عباي|ثوب|ثياب|أزياء|ازياء|فساتين|ملابس|موضة|لانجري|بوتيك|جلاب',re.I)
NEG=re.compile(r'مغسلة|مغاسل|laundry|تنظيف|dry ?clean|تعليمي|educational|car ?care|driving|(?<![a-z])trips(?![a-z])|(?<![a-z])diver|(?<![a-z])rent(?![a-z])|تأجير|مقاول|clinic|عيادة|مدرسة|academy|فروسية|equestrian|horse|uniform|يونيفورم|ملابس طبية|تطريز بالكمبيوتر|embroider',re.I)
def nm(*a): return " ".join(x or '' for x in a)
def tier_map():
    t={}
    for k,tier,rank,status,name in s.execute("select best_key,tier,tranco_rank,status,name from m.reference_stores where best_key is not null and best_key!=''"):
        t[k]=(tier,rank,name)
    return t
TM=tier_map()
def size_tier(key,url,plat,manual=False):
    if manual: return 'Brand-Major'
    if re.search(r'zara|hm\.com|h&m|maxfashion|namshi|nike|adidas|puma|reebok|newbalance|decathlon|nayomi|oysho|stylishop|brandsforless|sivvi|mango|bershka|stradivarius|massimodutti|pullandbear|americaneagle|ounass|aivi|6thstreet|styli\.com|splash|centrepoint|rivafashion|lulu|carrefour|next\.|underarmour|sssports|victoria|guess\.|levi\.|giordano|skechers|lacoste|gap\.|shein|redtag',key+' '+url,re.I) and not key.startswith('salla.sa/') and '.zid.store' not in url: return 'Brand-Major'
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
    if r.get('vstatus') in ('verified_secondary_evidence','verified_manual_major') and (FASH(cat) or cat in ('Sports, Fitness & Outdoor','Department Store / General')) and not r['ok'] or (r.get('vstatus') in ('verified_secondary_evidence','verified_manual_major') and not r['strong'] and (FASH(cat) or cat in ('Sports, Fitness & Outdoor','Department Store / General'))):
        ev=('known major retailer; category '+cat+' (storefront bot-walled)','major-category')
    if r['ok'] and nstrong and not NEG.search(nm(r['name'],r['key'])):
        if FASH(cat) or cat=='Fashion - Kids':
            need=1
        elif cat in ('Department Store / General','General / Unclassified','Sports, Fitness & Outdoor','Baby & Maternity','Religious Products','Shoes','') or cat is None:
            need=2
        elif cat in HEAVY:
            need=4
        else:
            need=3
        if nstrong>=need and (clear or nstrong>=3): ev=(r['signal'] or strong[0],'live')
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
    namekid=bool(re.search(r'أطفال|اطفال|(?<![a-z])kids?(?![a-z])|children|(?<![a-z])baby(?![a-z])|مواليد',r['name'] or '',re.I)) and not re.search(r'نسائ|رجال|women|men|ladies',r['name'] or '',re.I)
    kids_only = (r['kid'] or namekid) and not (r['women'] or r['men'] or r['uni'] or r['adult'])
    if kids_only or cat=='Fashion - Kids' and not (r['women'] or r['men'] or r['uni'] or r['adult']): return None,'kids-only clothing'
    g=[]
    w=r['women'] or cat in('Fashion - Women','Fashion - Abayas & Modest'); mn=r['men'] or cat=='Fashion - Men'
    if w: g.append('Women')
    if mn: g.append('Men')
    if r['uni'] or not g: g.append('Unisex')
    typ='Fashion-only' if (FASH(cat) and ev[1]!='x') else 'Has clothing section'
    if not FASH(cat) and nstrong>=5 and cat in ('General / Unclassified',''): typ='Fashion-only'
    return dict(type=typ,gender=", ".join(g),signal=ev[0],how=ev[1]),None
