import json,re,csv,sqlite3,random,collections,datetime
from final import *
import pandas as pd
def origin(u):
    p=urlparse(u); return f"{p.scheme}://{p.netloc}"
def website(key,v):
    u=(v[7] if v and v[7] else "https://"+key.split("|")[0]+"/")
    if "|" in key: return u
    p=urlparse(u)
    return u if len(p.path)<=10 and not p.query else origin(u)+"/"
rows=[]
for k,(name,typ,gen,tier,st) in S.items():
    v=V.get(k); o=D.get(k); web=SITE.get(k) or website(k,v)
    if k in SITE: o={"ok":False}
    plat=(o or {}).get("platform") if o and o.get("ok") else None
    if plat=="Magento": plat="Magento / custom (not confirmed)"
    if not plat: plat="Not detected (bot-walled/rate-limited)"
    if o and o.get("ok"):
        f=feats(o); sig=[]
        if "shopify_collections" in o["sig"]: sig.append("Shopify /collections.json")
        if "woo_store_api_categories" in o["sig"]: sig.append("WooCommerce store API categories")
        if not sig: sig.append("homepage nav")
        signal=" + ".join(sig)+": "+", ".join(f["ch"][:6]); ev=o["ev"]
        if ev.rstrip("/")==origin(o["final"]) or ev==o["final"]: ev=o["final"]
    else:
        ev=(v[6] if v and v[6] else web)
        if k in SITE: ev=web
        signal=("Kuwait-locale storefront (/en-kw, KWD) with clothing nav; homepage nav fetched during locale probe" if k in SITE else "directory category '%s' + brand/brand-page knowledge (homepage not fetchable)"%((v[3] if v else "") or "n/a"))
        if st==KNOWN: signal="known major fashion retailer; Kuwait storefront evidence from verifier (%s)"%("CC/Wayback KWD product page")
    vs=(v[2] if v else "") or ""
    if vs=="verified": st=VER
    elif vs=="verified_secondary_evidence": st="Verified (secondary evidence: Common Crawl/Wayback KWD product page)"
    elif vs=="verified_manual_major": st=KNOWN
    new= (FS.get(k,"") or "").startswith("fashion_") or k in NEWKEYS
    rows.append(dict(name=name,site=web,type=typ,gender=gen,platform=plat,tier=tier,status=st,evidence=ev,signal=signal,source="New discovery" if new else "Existing research",key=k))
df=pd.DataFrame(rows)
df=df.sort_values(["type","name"],ascending=[True,True]).reset_index(drop=True)
df.to_pickle("work/final.pkl")
print(len(df)); print(df.type.value_counts()); print(df.gender.value_counts()); print(df.source.value_counts()); print(df.status.value_counts()); print(df.tier.value_counts())
print(df[df.source=="New discovery"][["name","key"]])
