import re,urllib.parse as up
from fk import *
from build import FASH,HEAVY,NEG,NAMEHINT,nm
NEG3=re.compile(r'اسكراب|سكراب|scrub|طبي|medical|uniform|يونيفورم|مغسلة|laundry|فروسية|equestrian|horse|تطريز|embroider',re.I)
def items(cats):
    out=[]
    for it in (cats or '').split(' | '):
        it=it.strip()
        if it.startswith('/') or it.startswith('http'):
            segs=[up.unquote(s) for s in it.split('/') if s and not re.fullmatch(r'c\d+|category|categories|\d+|en|ar|sa|ar-us|en-us|collections?|[A-Za-z0-9]{5,7}',s)]
            it=segs[-1].replace('-',' ') if segs else ''
        if it and len(it.split())<=4 and len(it)<=40: out.append(it)
    return out
BADIT=re.compile(r'العناية بالملابس|غسيل|منظف|مطهر|detergent|للملابس|laundry|ملابس الحيوان|pet|كلاب|قطط|dog|cat',re.I)
GENERIC={'ملابس','clothing','clothes','apparel','garments','أزياء','ازياء'}
def exact(cats):
    hits=[]
    for it in items(cats):
        if BADIT.search(it): continue
        m=KW.search(it)
        if m and m.group(0).lower() not in WEAK and re.fullmatch(r'.{0,25}',it): hits.append(m.group(0))
    return hits
def classify3(r,fast=False):
    """r: dict(category,name,key,cat_tokens,prod_tokens,cats,women,men,uni,kid,adult,ok)"""
    cat=r['category'] or ''; name=r['name'] or ''
    if NEG3.search(nm(name,r['key'])): return None
    ct=[x for x in (r['cat_tokens'] or '').split(',') if x]; pt=[x for x in (r['prod_tokens'] or '').split(',') if x]
    ex=exact(r['cats'])
    if not r['ok']: return None
    kids = (r['kid'] and not (r['women'] or r['men'] or r['uni'] or r['adult'])) or re.search(r'أطفال|اطفال|(?<![a-z])kids?(?![a-z])|مواليد',name,re.I) and not re.search(r'نسائ|رجال|women|men',name,re.I)
    if kids: return None
    sig=None
    if cat in ('Pets',): return None
    spec=[h for h in ex if h.lower() not in GENERIC]
    if cat in HEAVY or cat in ('Home Decor','Pets','Furniture'):
        ok_=len(set(h.lower() for h in ex))>=2 and bool(spec)
    elif FASH(cat) or cat in ('Sports, Fitness & Outdoor','General / Unclassified','Department Store / General',''):
        ok_=bool(ex)
    else:
        ok_=bool(spec)
    if ok_: sig='category: '+ex[0]
    elif len(set(ct))>=3 and cat not in HEAVY: sig='categories: '+",".join(sorted(set(ct))[:3])
    elif len(set(ct))>=1 and FASH(cat): sig='category-link: '+ct[0]
    if not sig: return None
    g=[]
    w=r['women'] or cat in('Fashion - Women','Fashion - Abayas & Modest'); mn=r['men'] or cat=='Fashion - Men'
    if w: g.append('Women')
    if mn: g.append('Men')
    if r['uni'] or not g: g.append('Unisex')
    return dict(type='Fashion-only' if FASH(cat) else 'Has clothing section',gender=", ".join(g),signal=sig,how='category-level')
