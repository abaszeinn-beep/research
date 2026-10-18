import pandas as pd,re,json,sqlite3,collections,csv
from final import *
import io,contextlib
with contextlib.redirect_stdout(io.StringIO()):
    import export
df=pd.read_pickle('work/final.pkl')
df=df.sort_values(["name"],key=lambda s:s.str.lower()).reset_index(drop=True)
inc=set(df.key)
main=df.rename(columns={"name":"Store Name","site":"Website","type":"Type","gender":"Gender","platform":"Platform","tier":"Size Tier (best-effort)","status":"Verification Status","evidence":"Evidence URL","signal":"Classification Signal","source":"Discovery Source"})
cols=["Store Name","Website","Type","Gender","Platform","Size Tier (best-effort)","Verification Status","Evidence URL","Classification Signal","Discovery Source"]
main=main[cols]
ex=[]
def catreason(cat):
    for a,b in CATREASON:
        if a.lower() in (cat or "").lower(): return b
    return None
seen=set()
def add(k,name,reason,src):
    if k in seen or k in inc: return
    seen.add(k); v=V.get(k)
    ex.append(dict(name=name or k,site=(v[7] if v and v[7] else "https://"+k.split("|")[0]+"/"),reason=reason,src=src))
for k,r in EXR.items():
    if not r: continue
    v=V.get(k); add(k,(v[1] if v and v[1] else k),r,"Reviewed - fashion-like but excluded")
n_live_nonf=0
for k,v in V.items():
    st=v[2] or ""
    cat=v[3] or ""
    if st.startswith("verified"):
        r=catreason(cat)
        o=D.get(k)
        if r: reason=f"{r} (directory category: {cat})"
        else: reason=f"Not a clothing retailer (directory category: {cat or 'n/a'}); " + ("live homepage/collections nav shows no adult clothing section" if o and o.get("ok") else "no adult clothing evidence")
        add(k,v[1],reason,"Master Directory (verified)")
    else:
        cat_l=cat.lower()
        if any(x in cat_l for x in("ashion","sport","department")) or re.search(r"abaya|fashion|boutique|wear|dress|style|thob|dishdash|moda|couture|apparel|cloth|lingerie|jeans|outfit|عباي|ازياء|أزياء|ملابس",k+" "+(v[1] or ""),re.I):
            add(k,v[1],f"Not accepted: {(v[5] or st)[:70]} (fashion-like name/category but no Kuwait storefront / not live-verifiable)","Unverified/rejected candidate")
exdf=pd.DataFrame(ex).rename(columns={"name":"Store Name","site":"Website","reason":"Reason","src":"Source"})
exdf=exdf[["Store Name","Website","Reason","Source"]]
n=len(df)
tc=df.Type.value_counts() if False else df.type.value_counts()
gc=df.gender.value_counts()
nd=(df.source=="New discovery").sum()
stc=df.status.value_counts()
cov=[
("Deliverable","Online stores in Kuwait selling adult clothing (women's, men's or unisex), built from the Kuwait ecommerce directory (branch cursor/kuwait-ecommerce-directory-f1cc) plus new fashion-focused discovery."),
("Total fashion stores",str(n)),
("By type"," | ".join(f"{k}: {v}" for k,v in tc.items())),
("By gender"," | ".join(f"{k}: {v}" for k,v in gc.items())),
("By size tier"," | ".join(f"{k}: {v}" for k,v in df.tier.value_counts().items())),
("By verification status"," | ".join(f"{k}: {v}" for k,v in stc.items())),
("From existing research / new discovery",f"{n-nd} / {nd}"),
("Source universe","Master Directory (448 verified-class rows incl. manual majors/secondary evidence), 912 unverified + 853 rejected candidates, 783 reference-brand rows (mall tenants, franchise brands). 2,059 candidate hosts (all verified + unverified + rejected minus DNS-dead/404/parked/non-Kuwait-currency) were live-probed."),
("Step 1 - pre-classification","Directory category, store name/domain keywords (EN+AR) and verifier category text flagged fashion / maybe / not. Unverified/rejected candidates that failed only on weak Kuwait/e-commerce signals (insufficient_market_signals, weak_market_signals, js/thin page, rate-limit) with .kw domain or market score>=2 were re-checked live; those with fashion evidence are listed with status 'Unverified - fashion-confirmed; weak Kuwait/e-commerce signal'."),
("Step 2 - live classification","Per host (polite, <=24 concurrent, single GET per page, no login/CAPTCHA/bot-wall bypass, no orders): homepage nav + title; Shopify /collections.json and /products.json; WooCommerce /wp-json/wc/store/v1/products/categories; platform sniffing (Salla/Zid/Magento/SFCC/MNASATI). Arabic+English clothing keyword sets (dress, abaya, dishdasha/thobe, shirts, jeans, hoodie, lingerie, activewear, modest/hijab, ملابس, فساتين, عبايات, دشداشة, ...). Gender from women/men/boys-girls/ladies/نسائي/رجالي/abaya/thobe nav terms (ولادي=boys counted as kids, not men). Type = Fashion-only if non-fashion category terms (electronics, grocery, beauty, home...) are negligible, else Has clothing section. Hosts that were bot-walled/rate-limited (HTTP 403/429) were classified from the verifier's directory category + brand knowledge, evidence URL = verifier evidence (CC/Wayback KWD product page or storefront)."),
("Step 3 - new discovery",f"(a) Kuwait App Store (itunes search API, country=kw, 38 fashion terms EN/AR) -> 2.7k apps, 835 new seller domains + 70 hand-curated Kuwait fashion storefront guesses added as candidates and run through the existing verifier (905 candidates -> 7 verified Kuwait stores; rest non-Kuwait or unverifiable). (b) Brand-name x 15 domain patterns (kw.<brand>.com, <brand>kw.com, <brand>.shop, ...) for 352 fashion/department/sport reference names (5,163 probes) -> 63 live Kuwait-signal hosts verified with the existing verifier. (c) Kuwait-locale path probing (/kw, /en-kw, /kw/en, /kuwait-en) of 51 global fashion domains (459 probes) -> Alo Yoga, Bottega Veneta. {nd} stores in the final list come from this discovery (source 'New discovery')."),
("Discovery limits","Common Crawl CDX API, Wayback CDX and search engines were unreachable/bot-walled from this VM; the earlier run already scanned the Common Crawl index files for every .kw host and Tranco top ranks, so .kw coverage rests on that. Instagram-only brands without a web store, and Kuwait-locale stores on global domains that block automated requests, are the main under-coverage risk. Mall tenant lists (The Avenues, 360, Assima) were used only via the reference list from the earlier run."),
("Major retailers","Bot-walled majors (Zara/Massimo Dutti/Pull&Bear/Bershka/Oysho, Mango, H&M, Max, Splash, Centrepoint, Namshi, Hugo Boss, American Eagle, Banana Republic, Kiabi, Ted Baker, Gant, Giordano etc.) are included on the verifier's secondary evidence (Common Crawl/Wayback captures of Kuwait product pages with KWD prices and order controls) or manual acceptance; see Evidence URL."),
("Inclusion rules applied","Included: fashion-only and multi-category stores with a men's/women's/unisex clothing section (department stores, hypermarkets with fashion, sports stores selling apparel, brand stores), incl. abaya, dishdasha/thobe, modest wear, lingerie/underwear, sportswear; all sizes. Excluded: kids/baby-only, shoes/bags/accessories/jewelry/watches/perfume-only, B2B uniform suppliers, tailoring/laundry services, closed stores, marketplaces/aggregators, non-Kuwait storefronts, duplicate locale/alias domains."),
("QA","Random sample of 50 of the "+str(n)+" listed stores re-checked against live navigation / directory evidence for fashion-ness, Type and Gender: see QA result in the run summary (error rate stored below)."),
("QA error rate","Pre-fix ~4% (2 of 50 sampled rows had a wrong Gender/Type before rule fixes); post-fix 0 hard errors in the 50-row sample, 1 low-confidence row (LAB: homepage rate-limited during probe, confirmed manually afterwards). Threshold 8% not exceeded."),
("QA findings","Rule fixes applied after sampling/gender cross-check: 'ولادي' (boys) was counted as 'men' -> Women-only stores with boys/kids sections corrected; stores whose nav shows both men and women corrected to Unisex (Souq Sara, The One KD Shop, Kuwait Boutique); Blink Trends reclassified from Fashion-only to Has clothing section (beauty+fashion). A false-positive audit of keyword hits removed non-fashion stores whose pages mention 'clothes/top/dress' incidentally (grocery, pets, kitchen, electronics, gifts)."),
("Unverified rows","Status 'Unverified - fashion-confirmed; weak Kuwait/e-commerce signal' means the fashion classification is confirmed from the live site but the earlier verifier did not accept Kuwait delivery/e-commerce evidence (e.g. JS-rendered carts, low market score). Review before outreach."),
("Notable big brands in list","Zara, H&M, Mango, Bershka, Pull&Bear, Massimo Dutti, Max Fashion, Splash, Centrepoint, Marks & Spencer, Next, Namshi, SHEIN, Nike, Sun & Sand Sports, Decathlon, Foot Locker, GAP, American Eagle, Banana Republic, Victoria's Secret, Hugo Boss, Burberry, Prada, Miu Miu, Valentino, Michael Kors, Tory Burch, Ounass, Bloomingdale's, Harvey Nichols, Lacoste, Guess, U.S. Polo Assn., Diesel, Giordano, Kiabi, Lulu Hypermarket, Al Nasser."),
]
import os
out="../fashion/Kuwait_Fashion_Stores.xlsx"
with pd.ExcelWriter(out,engine="openpyxl") as w:
    main.to_excel(w,sheet_name="Fashion Stores",index=False)
    exdf.to_excel(w,sheet_name="Excluded",index=False)
    pd.DataFrame(cov,columns=["Item","Detail"]).to_excel(w,sheet_name="Coverage & Method",index=False)
    for sh,wd in (("Fashion Stores",[34,42,22,10,28,26,48,70,60,16]),("Excluded",[34,42,90,30]),("Coverage & Method",[34,160])):
        ws=w.sheets[sh]
        for i,x in enumerate(wd): ws.column_dimensions[chr(65+i)].width=x
        ws.freeze_panes="A2"
        from openpyxl.styles import Font,Alignment
        for c in ws[1]: c.font=Font(bold=True)
        if sh=="Coverage & Method":
            for r in ws.iter_rows(min_row=2):
                for c in r: c.alignment=Alignment(wrap_text=True,vertical="top")
main.to_csv("Kuwait_Fashion_Stores.csv",index=False,encoding="utf-8-sig")
print(n,len(exdf))
