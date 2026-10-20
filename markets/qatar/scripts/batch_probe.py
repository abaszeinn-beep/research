"""Batch Wayback product probe over unresolved/no-storefront reference brands (Qatar path patterns), plus Qatar App Store lookup.
Writes logs/batch_probe.jsonl (one JSON object per brand). Resumable: skips names already in the file."""
import asyncio, json, os, re, sqlite3, sys
import httpx
sys.path.insert(0, os.path.dirname(__file__))
import major_probe as mp
from urllib.parse import quote

OUT = "logs/batch_probe.jsonl"
PROD = r".*(/p/|/products?/|\.html|-p[0-9]{5,}|/pd/|/buy-|/dp/|/item|[0-9]{6,}).*"
PATHS = ["/qa/", "/en-qa/", "/qa-en/"]

def prefixes(doms):
    out = []
    for d in doms:
        d = re.sub(r"^www\.", "", d)
        if d.endswith(".qa"):
            out += [d + "/", "www." + d + "/"]
        else:
            out += [d + p for p in PATHS] + [f"qa.{d}/"]
    seen = []
    for p in out:
        if p not in seen:
            seen.append(p)
    return seen[:8]

async def one(c, sem, ref_id, name, doms, done):
    if name in done:
        return
    async with sem:
        hit = None
        tried = 0
        for p in prefixes(doms):
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
