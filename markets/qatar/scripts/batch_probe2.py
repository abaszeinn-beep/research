"""Batch Wayback product probe over unresolved/no-storefront reference brands (Qatar path patterns), plus Qatar App Store lookup.
Writes logs/batch_probe.jsonl (one JSON object per brand). Resumable: skips names already in the file."""
import asyncio, json, os, re, sqlite3, sys
import httpx
sys.path.insert(0, os.path.dirname(__file__))
import major_probe as mp
from urllib.parse import quote

OUT = "logs/batch_probe2.jsonl"
PROD = r".*(/p/|/products?/|\.html|-p[0-9]{5,}|/pd/|/buy-|/dp/|/item|[0-9]{6,}).*"
PATHS = ["/qa/", "/en-qa/", "/qa-en/"]

EXTRA = {"Samsung": ["samsung.com/qa/", "samsung.com/qa_ar/"], "LG": ["lg.com/qa/", "lg.com/qa_ar/"], "Mango": ["shop.mango.com/qa/", "shop.mango.com/qa/en/"],
         "Puma": ["me.puma.com/qa/", "me.puma.com/qa/en/"], "Under Armour": ["underarmour.me/en-qa/", "underarmour.me/ar-qa/"], "Skechers": ["skechers-me.com/qa/", "skechers.me/qa/"],
         "Sony": ["electronics.sony.com/", "sony.com.qa/", "store.sony.com.qa/", "sony-mea.com/qa/"], "Uniqlo": ["uniqlo.com/qa/", "uniqlo.com/qa/en/"],
         "Anker": ["anker.com/qa/", "ankerme.com/qa/"], "Canon": ["qa.canon-me.com/", "canon-me.com/qa/"], "Bose": ["bose.com/qa/", "boseqatar.com/"], "Sharaf DG": ["qatar.sharafdg.com/", "sharafdg.com/qa/"],
         "Pottery Barn": ["potterybarn.com.qa/"], "West Elm": ["westelm.com.qa/"], "Crate & Barrel": ["crateandbarrel.com.qa/"], "Pottery Barn Kids": ["potterybarnkids.com.qa/"],
         "Lifestyle": ["lifestyleshops.com/qa/en/"], "Babyshop": ["babyshopstores.com/qa/en/", "babyshopstores.com/qa/ar/"], "Emax": ["emaxme.com/qa/en/"], "Shoe Mart": ["shoemartstores.com/qa/en/"],
         "Iconic": ["iconicstores.com/qa/en/"], "Pan Emirates": ["panemirates.com/qa/en/", "panhome.com/qa/"], "Mango ": [], "Tommy Hilfiger": ["qa.tommy.com/", "tommy.com/qa/"],
         "Rituals": ["rituals.com/en-qa/", "rituals.com/ar-qa/"], "Pandora": ["pandora.net/en-qa/", "pandora.net/ar-qa/"], "MAC Cosmetics": ["maccosmetics.qa/", "maccosmetics.com/qa/"],
         "Kiko Milano": ["kikocosmetics.com/en-qa/", "kikocosmetics.qa/"], "Golden Scent": ["goldenscent.com/en-qa/", "goldenscent.com/qa/"], "Rasasi": ["rasasi.com/qa/", "rasasi.qa/"],
         "Levi's": ["levi.com/QA/", "levi.com/qa/en/", "levi.com.qa/"], "Columbia": ["columbia.com/qa/", "columbiame.com/qa/"], "Hamleys": ["hamleys.qa/", "hamleys.com/qa/"], "Toys R Us": ["toysrusmena.com/qa/", "toysrus.qa/"],
         "DeFacto": ["defacto.com/en-qa/", "defacto.com/ar-qa/"], "Koton": ["koton.com/en-qa/", "koton.com/ar-qa/"], "LC Waikiki": ["lcwaikiki.qa/", "lcw.com/en-qa/"], "Forever 21": ["forever21.com/qa/", "forever21me.com/qa/"],
         "River Island": ["riverisland.com/qa/", "riverisland.ae/"], "New Look": ["newlook.com/qa/"], "Aldo": ["aldoshoes.qa/", "aldoshoes.me/qa/"], "Nine West": ["ninewest.me/qa/"],
         "GNC": ["gnc.qa/", "gnc-me.com/qa/"], "iHerb": ["iherb.com/qa/"], "Yves Rocher": ["yves-rocher.qa/"], "Lindt": ["lindt.com/qa/"], "Godiva": ["godivaarabia.com/qa/"], "Charlotte Tilbury": ["charlottetilbury.com/qa/"]}

def prefixes(doms, name=""):
    out = list(EXTRA.get(name, []))
    for d in doms:
        d = re.sub(r"^www\.", "", d)
        label = d.split(".")[0]
        if d.endswith(".qa"):
            continue
        out += [d + "/qa/en/", d + "/qa/ar/", d + "/en_qa/", d + "/qa_en/", d + "/qatar/", "shop." + d + "/qa/", f"{label}.com.qa/", f"{label}.qa/", f"{label}qatar.com/", f"{label}-qatar.com/"]
    seen = []
    for p in out:
        if p not in seen:
            seen.append(p)
    return seen[:12]

async def one(c, sem, ref_id, name, doms, done):
    if name in done:
        return
    async with sem:
        hit = None
        tried = 0
        for p in prefixes(doms, name):
            tried += 1
            r = await mp.probe(c, name, p, PROD)
            if r.get("ok"):
                hit = r
                break
        app = None
        try:
            q = quote(re.sub(r"[^A-Za-z0-9 ]", " ", name.split("/")[0]).strip())
            j = (await c.get(f"https://itunes.apple.com/search?term={q}&country=qa&entity=software&limit=5", timeout=30)).json()
            toks = [t for t in re.findall(r"[a-z0-9]{3,}", name.lower())]
            for x in j.get("results", []):
                if x.get("primaryGenreName") in ("Shopping", "Food & Drink", "Lifestyle") and toks and toks[0] in x["trackName"].lower() and x["currentVersionReleaseDate"][:4] in ("2026", "2025"):
                    app = {"name": x["trackName"], "seller": x["sellerName"], "date": x["currentVersionReleaseDate"][:10], "url": x["trackViewUrl"].split("?")[0]}
                    break
        except Exception:
            pass
        rec = {"ref_id": ref_id, "name": name, "domains": doms, "tried": tried, "hit": hit, "app": app}
        with open(OUT, "a") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(name, bool(hit), bool(app), flush=True)

async def main():
    con = sqlite3.connect("data/qatar_ecom.sqlite")
    rows = con.execute("""SELECT ref_id,name,domains FROM reference_stores WHERE kind='brand' AND status IN ('unresolved','excluded')
        AND (reason LIKE '%no%storefront found%' OR reason LIKE 'unresolved:%') AND name NOT IN ('Snoonu','Talabat Mart','noon','Amazon')""").fetchall()
    done = set()
    if os.path.exists(OUT):
        done = {json.loads(l)["name"] for l in open(OUT)}
    sem = asyncio.Semaphore(int(sys.argv[1]) if len(sys.argv) > 1 else 5)
    async with httpx.AsyncClient(headers=mp.H) as c:
        await asyncio.gather(*(one(c, sem, r, n, d.split(), done) for r, n, d in rows))
asyncio.run(main())
