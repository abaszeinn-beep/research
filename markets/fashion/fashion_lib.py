import re, json, asyncio, aiohttp, ssl, time
from urllib.parse import urlparse, urljoin
UA = "Mozilla/5.0 (compatible; QatarFashionResearch/1.0; polite research crawler)"
STRONG = r"""clothing|clothes|apparel|garment|ready[- ]?to[- ]?wear|\babayas?\b|abaya|kaftan|caftan|jalabiy|jalabeya|thobe|thawb|\bthoub|dishdasha|kandura|\bdress(es)?\b|\bgowns?\b|\bskirts?\b|\bblouses?\b|\btops?\b|t-?shirts?|\btees?\b|\bshirts?\b|polos?\b|\bpolo\b|trousers|\bpants\b|jeans|denim|leggings|joggers|sweatpants|hoodies?|sweatshirts?|sweaters?|knitwear|jumpers?|cardigans?|jackets?|\bcoats?\b|blazers?|\bsuits?\b|tracksuits?|activewear|sportswear|athleisure|loungewear|nightwear|sleepwear|pyjamas?|pajamas?|lingerie|underwear|innerwear|\bbras?\b|briefs|boxers|swimwear|swimsuits?|modest ?wear|hijabs?|jilbab|shawls?|scarves|kimono|jumpsuits?|playsuits?|shorts|womenswear|menswear|streetwear|uniform|maternity wear|nursing wear|ملابس|عباي|عبا[ءه]|ثوب|ثياب|فساتين|فستان|أزياء|ازياء|قمصان|قميص|تيشيرت|بنطلون|بناطيل|جاكيت|معاطف|ملابس داخلية|لانجري|حجاب|حجابات|اسدال|إسدال|جلابية|جلابيات|كاجوال|رياضية|بيجامة|بجامات|قفطان|كوفية|شيلة|ترنج|بدل|سترات|جينز|كنزات|هودي|بلوزة|بلوزات|تنانير|ملابس نسائية|ملابس رجالية"""
STRONG_RE = re.compile(STRONG, re.I)
FASHION_ONLY_HINT = re.compile(r"fashion|clothing|apparel|abaya|boutique|wear\b|ready[- ]?to[- ]?wear|lingerie|modest|ملابس|أزياء|ازياء|عباي|بوتيك|موضة", re.I)
WOMEN = re.compile(r"\bwomen'?s?\b|\bwoman\b|\bladies\b|\blady\b|\bgirls?\b|\bfemale\b|\bhers?\b|abaya|عباي|نساء|نسائي|سيدات|بنات|فساتين|dress(es)?\b|lingerie|hijab|حجاب|kaftan|jalabiy|bridal|maxi|blouse|skirt", re.I)
MEN = re.compile(r"\bmen'?s?\b|\bmale\b|\bgents?\b|\bgentlemen\b|\bboys?\b|thobe|thawb|dishdasha|kandura|رجال|رجالي|ثوب|ثياب رجال|شباب|غتر|menswear", re.I)
KIDS = re.compile(r"\bkids?\b|\bbab(y|ies)\b|\bchildren'?s?\b|\binfants?\b|\btoddlers?\b|newborn|أطفال|اطفال|مواليد|رضع|طفل", re.I)
SHOE_BAG = re.compile(r"shoes?|footwear|sneakers?|sandals?|boots?|handbags?|bags?\b|luggage|watches|jewel+ery|perfumes?|fragrances?|eyewear|sunglasses|accessor(y|ies)|أحذية|حذاء|احذية|حقائب|ساعات|مجوهرات|عطور|نظارات|إكسسوارات|اكسسوارات", re.I)
STOP = re.compile(r"^(home|login|sign ?in|register|cart|wishlist|contact|about|blog|faq|help|track|stores?|offers?|sale|new|search|account|my account|language|english|arabic|العربية|الرئيسية|تسجيل.*|اتصل.*|من نحن)\b", re.I)

def sslctx():
    c = ssl.create_default_context(); c.check_hostname=False; c.verify_mode=ssl.CERT_NONE; return c

async def get(sess, url, timeout=30, maxb=600000):
    try:
        async with sess.get(url, timeout=aiohttp.ClientTimeout(total=timeout), allow_redirects=True, max_redirects=6) as r:
            b = await r.content.read(maxb)
            return r.status, str(r.url), b.decode(r.get_encoding() if r.charset else 'utf-8', 'replace'), r.headers.get('content-type','')
    except Exception as e:
        return 0, url, '', type(e).__name__

def nav_items(html):
    html = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html)
    items=[]
    for m in re.finditer(r"(?is)<a\b[^>]*href=[\"']([^\"'#][^\"']*)[\"'][^>]*>(.*?)</a>", html):
        t = re.sub(r"<[^>]+>"," ",m.group(2)); t=re.sub(r"\s+"," ",re.sub(r"&amp;","&",t)).strip()
        h = m.group(1)
        if 2<=len(t)<=60: items.append((t,h))
    return items

def meta(html):
    t = re.search(r"(?is)<title[^>]*>(.*?)</title>", html); d = re.search(r'(?is)<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', html)
    og = re.search(r'(?is)<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\'](.*?)["\']', html)
    return (re.sub(r"\s+"," ",t.group(1)).strip() if t else ''), (d.group(1).strip() if d else ''), (og.group(1).strip() if og else '')

def platform(html, hdr=''):
    h = html[:400000].lower()
    if 'cdn.shopify.com' in h or 'shopify.theme' in h: return 'Shopify'
    if 'wp-content' in h and ('woocommerce' in h): return 'WooCommerce'
    if 'salla' in h and ('cdn.salla' in h or 'salla.sa' in h or 'salla.network' in h): return 'Salla'
    if 'zid.store' in h or 'cdn.zid' in h or 'zid.sa' in h: return 'Zid'
    if 'mage-init' in h or 'magento' in h or 'requirejs/require.js' in h: return 'Magento'
    if 'demandware' in h or 'dwstatic' in h or '/on/demandware' in h: return 'Salesforce Commerce Cloud'
    if 'cdn11.bigcommerce' in h or 'bigcommerce' in h: return 'BigCommerce'
    if 'wixstatic' in h: return 'Wix'
    if 'squarespace' in h: return 'Squarespace'
    if 'prestashop' in h: return 'PrestaShop'
    if 'opencart' in h or 'catalog/view/theme' in h: return 'OpenCart'
    if '_next/static' in h or '__next' in h: return 'Custom (Next.js)'
    if 'wp-content' in h: return 'WordPress'
    return 'Custom/Other'

async def probe(sess, url):
    """returns dict of evidence"""
    out = {'url':url,'ok':False}
    st, fu, html, ct = await get(sess, url)
    out.update(status=st, final=fu)
    if st==0 or st>=400 or not html:
        out['err']= f'http_{st}' if st else ct; return out
    out['ok']=True
    plat = platform(html); out['platform']=plat
    out['qar']=bool(re.search(r'\bQAR\b|\bQR\s?\d|ر\.ق|ريال قطري|Qatar|قطر',html[:600000]))
    title, desc, og = meta(html); out.update(title=title, desc=desc, og=og)
    items = nav_items(html); out['nav']=[t for t,_ in items][:400]
    base = '{0.scheme}://{0.netloc}'.format(urlparse(fu))
    cols=[]; ptypes=[]; ev=None
    if plat=='Shopify':
        st2,_,j,_ = await get(sess, base+'/collections.json?limit=250', 10, 400000)
        if st2==200:
            try:
                cols=[c['title'] for c in json.loads(j).get('collections',[])]; ev=base+'/collections.json'
            except Exception: pass
        st3,_,j,_ = await get(sess, base+'/products.json?limit=250', 10, 1500000)
        if st3==200:
            try:
                ps=json.loads(j).get('products',[]); ptypes=[(p.get('product_type') or '')+'|'+p.get('title','') for p in ps]; out['n_products']=len(ps)
                ev = ev or base+'/products.json'
            except Exception: pass
    elif plat=='WooCommerce':
        st2,_,j,_ = await get(sess, base+'/wp-json/wc/store/v1/products/categories?per_page=100', 10, 400000)
        if st2==200:
            try: cols=[re.sub('&amp;','&',c['name']) for c in json.loads(j)]; ev=base+'/wp-json/wc/store/v1/products/categories'
            except Exception: pass
    out.update(cols=cols, ptypes=ptypes[:250], ev=ev or fu)
    return out

def classify(p, dbcat=''):
    """returns (label, type, gender, signal, evidence_n)"""
    if not p.get('ok'): return None
    navt=[t for t in p['nav'] if not STOP.match(t)]
    cols=p.get('cols',[])
    ptypes=p.get('ptypes',[])
    head=' '.join([p.get('title',''),p.get('desc',''),p.get('og','')])
    items = list(dict.fromkeys(navt+cols))
    strong_items=[t for t in items if STRONG_RE.search(t)]
    ptype_hits=[x for x in ptypes if STRONG_RE.search(x.split('|')[0])]
    ptitle_hits=[x for x in ptypes if STRONG_RE.search(x)]
    head_hit = bool(STRONG_RE.search(head))
    nclo=len(strong_items)
    score = nclo + (3 if ptype_hits else 0) + (len(ptitle_hits)//15) + (2 if head_hit else 0)
    # fashion-only?
    fo = bool(FASHION_ONLY_HINT.search(head)) or dbcat.startswith('Fashion') or dbcat.startswith('Fashion & ')
    # share of items that are clothing among short nav/collections
    share = nclo/max(1,len(set(cols)) if cols else min(len(items),60))
    # gender
    txt=' '.join(strong_items+cols+navt[:120]+[head]+[x for x in ptypes[:80]])
    w=bool(WOMEN.search(txt)); m=bool(MEN.search(txt))
    kids=bool(KIDS.search(' '.join(strong_items+[head]))) 
    adult_txt=' '.join(strong_items+[head])
    gender = 'Unisex' if (w and m) else 'Women' if w else 'Men' if m else 'Unisex'
    sig = '; '.join((strong_items[:6])) or ('product_type:'+ptype_hits[0] if ptype_hits else ('meta:'+head[:80] if head_hit else ''))
    if score>=3 or (nclo>=1 and head_hit):
        typ = 'Fashion-only' if (fo and (share>=0.25 or head_hit)) or share>=0.5 else 'Has clothing section'
        return ('fashion',typ,gender,sig,score,kids)
    if score>=1 or head_hit:
        return ('maybe','Has clothing section',gender,sig,score,kids)
    return ('not','','',sig,score,kids)
