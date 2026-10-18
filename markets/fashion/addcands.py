import json,re,sys
sys.path.insert(0,'../kuwait')
from market_ecom import db
a=json.load(open('../fashion/work/apps.json'))
urls=set()
bad=("instagram.com","github.io","netlify.app","web.app","apple.com","facebook.com","google.com","linktr.ee","wixsite.com")
for x in a.values():
    if x['genre'] not in('Shopping','Lifestyle'): continue
    u=(x['url'] or '').strip()
    if not u.startswith('http'): continue
    h=re.sub(r'^www\.','',u.split('//')[1].split('/')[0].lower())
    if any(b in h for b in bad): continue
    urls.add('https://'+h+'/')
B="""zara.com/kw/en hm.com/en_kw bershka.com/kw/en pullandbear.com/kw/en massimodutti.com/kw/en stradivarius.com/kw/en shop.mango.com/kw/en oysho.com/kw/en uterque.com/kw next.com.kw nextdirect.com/kw lcw.com/en-KW defacto.com/en-kw koton.com/en-kw maxfashion.com/kw/en splashfashions.com/kw lifestylestores.com/kw 6thstreet.com/kuwait-en namshi.com/kuwait-en ounass.com.kw sssports.com/kw-en adidas.com.kw nike.com/kw puma.com/kw newbalance.com.kw skechers.com.kw underarmour.com.kw reebok.com.kw gap.com.kw levi.com.kw hollister.com.kw aeo.com.kw victoriassecret.com.kw lacoste.com.kw guess.com.kw benetton.com.kw hunkemoller.com.kw intimissimi.com tezenis.com lasenza.com.kw dorothyperkins.com.kw burton.co.uk topman.com riverisland.com jdsports.com.kw footlocker.com.kw dressforless.com mrmr.com.kw rivafashion.com molk.com.kw lineskw.com babyfoxkw.com iconic.com.kw tommy.com.kw calvinklein.com.kw ck.com.kw ralphlauren.com.kw boss.com.kw hugoboss.com.kw armani.com.kw michaelkors.com.kw diesel.com.kw replay.com.kw jackjones.com.kw veromoda.com.kw only.com.kw pepejeans.com.kw superdry.com.kw tedbaker.com.kw reiss.com.kw karenmillen.com.kw coast.com.kw oasis-stores.com.kw warehouse.com.kw monsoon.com.kw accessorize.com.kw bluevelvet.com.kw ginger.com.kw splash.com.kw redtagfashion.com brandsforless.com.kw styli.com stylishop.com sivvi.com.kw nisnass.com.kw abayati.com.kw alabaya.com.kw bait-alabaya.com deepinabayas.com sasaabaya.com alhajarabaya.com ahmadalmaghribi.com.kw thegulfwear.com al-dar.com alqabas.com.kw lamar.com.kw zaaheb.com ghayaa.com ana-w-hiya.com elhanabaya.com yalla-shop.com.kw q8dishdasha.com dishdasha.com.kw alhazeemfashion.com.kw aljazeera-fashion.com.kw kuwaitabaya.com abayashop.com.kw boutiqueq8.com q8boutique.com kw-fashion.com fashionq8.com q8fashion.com bnk.com.kw shopq8.com q8store.com kwfashion.com hamdan-fashion.com alsalam.com.kw alsayer.com.kw al-hilal.com.kw salamfashion.com kuwaitfashion.com 360mall.com.kw theavenueskuwait.com assimamall.com.kw 6thstreet.com ounass.ae farfetch.com boohoo.com boohooman.com prettylittlething.com asos.com nelly.com hm.com shein.com ssense.com mytheresa.com net-a-porter.com mrporter.com""".split()
for b in B:
    b=b if b.startswith('http') else 'https://'+b
    urls.add(b if '/' in b[8:] else b+'/')
con=db.connect()
n=db.add_candidates(con,sorted(urls),'fashion_disc','app_store+brand_list',priority=5)
print(len(urls),n)
con.commit() if hasattr(con,'commit') else None
