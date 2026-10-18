"""Multi-method Qatar storefront discovery for global brands: hreflang alternates, robots.txt sitemaps (qa/qatar locale entries),
Shopify Markets (/meta.json, /en-qa), host variants, Qatar App Store. Output logs/multi_probe.jsonl (resumable).
Only robots-allowed public pages are fetched; 403/challenge responses are recorded, never bypassed."""
import asyncio, json, os, re, sqlite3, sys
from urllib.parse import urljoin, urlsplit
import httpx

OUT = "logs/multi_probe.jsonl"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36", "Accept-Language": "en-QA,en;q=0.8"}
QA_HREF = re.compile(r'hreflang="(?:[a-z]{2}-qa|ar-qa|en-qa|qa)"[^>]*href="([^"]+)"|href="([^"]+)"[^>]*hreflang="(?:[a-z]{2}-qa|qa)"', re.I)
QA_LOC = re.compile(r"(?:/|[-_.])(?:qa|qatar)(?:[-_/.]|$)|[a-z]{2}[-_]QA", re.I)
LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)

async def get(c, u, **kw):
    try:
        return await c.get(u, timeout=25, follow_redirects=True, **kw)
    except Exception:
        return None

async def probe(c, sem, ref_id, name, doms, done):
    if name in done:
        return
    async with sem:
        rec = {"ref_id": ref_id, "name": name, "domains": doms, "found": [], "notes": []}
        for d in doms:
            d = re.sub(r"^www\.", "", d)
            label = d.split(".")[0]
            for host in (f"https://www.{d}/", f"https://{d}/"):
                r = await get(c, host)
                if r is None:
                    continue
                if r.status_code in (403, 429, 503):
                    rec["notes"].append(f"{host} http {r.status_code}")
                    continue
                if r.status_code == 200:
                    t = r.text[:400000]
                    for m in QA_HREF.finditer(t):
                        u = urljoin(str(r.url), m.group(1) or m.group(2))
                        rec["found"].append(["hreflang", u])
                    for m in re.finditer(r'(?:href|data-url|"url")\s*[=:]\s*"([^"]*(?:/qa/|/en-qa|/qa-en|/ar-qa|/qatar)[^"]*)"', t, re.I):
                        u = urljoin(str(r.url), m.group(1))
                        if urlsplit(u).hostname and registrable(urlsplit(u).hostname) in (registrable(d),):
                            rec["found"].append(["selector_link", u])
                    break
            rr = await get(c, f"https://www.{d}/robots.txt")
            if rr is not None and rr.status_code == 200 and "<html" not in rr.text[:200].lower():
                sms = re.findall(r"(?im)^sitemap:\s*(\S+)", rr.text)[:6]
                for sm in sms:
                    s = await get(c, sm)
                    if s is None or s.status_code != 200:
                        continue
                    locs = LOC.findall(s.text[:3_000_000])
                    qa = [u for u in locs if QA_LOC.search(u)][:5]
                    if qa:
                        rec["found"].append(["sitemap", qa[0]])
                        rec["notes"].append(f"sitemap {sm}: {len(qa)}+ qatar entries")
            mj = await get(c, f"https://{d}/meta.json")
            if mj is not None and mj.status_code == 200 and mj.text.startswith("{"):
                rec["notes"].append("shopify meta.json: " + mj.text[:120])
                for p in ("/en-qa", "/ar-qa", "/qa"):
                    lr = await get(c, f"https://{d}{p}")
                    if lr is not None and lr.status_code == 200 and "shopify" in lr.text[:200000].lower():
                        rec["found"].append(["shopify_market", f"https://{d}{p}/"])
                        break
            for h in (f"https://{label}.com.qa/", f"https://www.{label}.qa/", f"https://{label}.qa/", f"https://qa.{d}/", f"https://www.{label}qatar.com/", f"https://www.{label}-qatar.com/"):
                v = await get(c, h)
                if v is not None and v.status_code == 200 and len(v.text) > 3000 and label in str(v.url).lower():
                    rec["found"].append(["host_variant", str(v.url)])
                    break
        from urllib.parse import quote
        try:
            q = quote(re.sub(r"[^A-Za-z0-9 ]", " ", name.split("/")[0]).strip())
            j = (await c.get(f"https://itunes.apple.com/search?term={q}&country=qa&entity=software&limit=5", timeout=30)).json()
            tok = re.findall(r"[a-z0-9]{3,}", name.lower())
            for x in j.get("results", []):
                if tok and tok[0] in x["trackName"].lower() and x.get("primaryGenreName") in ("Shopping", "Lifestyle", "Food & Drink") and x["currentVersionReleaseDate"][:4] in ("2025", "2026"):
                    rec["app"] = {"name": x["trackName"], "seller": x["sellerName"], "date": x["currentVersionReleaseDate"][:10], "url": x["trackViewUrl"].split("?")[0]}
                    break
        except Exception:
            pass
        seen, uniq = set(), []
        for k, u in rec["found"]:
            if u not in seen:
                seen.add(u); uniq.append([k, u])
        rec["found"] = uniq[:6]
        with open(OUT, "a") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(name, [k for k, _ in uniq], bool(rec.get("app")), flush=True)

def registrable(h):
    p = h.lower().split(".")
    return ".".join(p[-3:]) if len(p) >= 3 and p[-2] in ("co", "com") else ".".join(p[-2:])

async def main():
    con = sqlite3.connect("data/qatar_ecom.sqlite")
    names = sys.argv[2:]
    ph = ",".join("?" * len(names)) if names else "''"
    q = "SELECT ref_id,name,domains FROM reference_stores WHERE kind='brand' AND ((status='excluded' AND reason LIKE '%no%storefront found%') OR name IN (" + ph + "))"
    rows = con.execute(q, names).fetchall()
    done = {json.loads(l)["name"] for l in open(OUT)} if os.path.exists(OUT) else set()
    sem = asyncio.Semaphore(int(sys.argv[1]))
    async with httpx.AsyncClient(headers=UA) as c:
        await asyncio.gather(*(probe(c, sem, r, n, d.split(), done) for r, n, d in rows))
asyncio.run(main())
