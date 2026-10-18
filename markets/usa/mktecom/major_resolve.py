"""Resolve unresolved huge/large retailers with the final-merge evidence rule (no bot-wall/CAPTCHA/login bypass, no orders, no paid APIs).

  python3 -m mktecom.major_resolve [--names "Walgreens,Macy's"] [--dry]

Rule
* US-headquartered, single-country retailers (US_SINGLE): `verified_secondary_evidence` with two independent current proofs where at least
  one is US-specific by nature: SEC 10-K (<=550 days) naming the e-commerce site, a US-only App Store / Google Play shopping app from the
  retailer (updated <=450 days, not listed in the GB/CA/AU/DE App Store), or an archived US product page with USD prices and an ordering
  control captured <=365 days ago. A robots-allowed product sitemap or a live storefront with product + purchase markers counts as the
  second proof.
* Global brands: the stricter rule - at least one US-specific storefront proof (archived/live US storefront product page in USD, or product
  sitemap under the US path) plus a second proof of any kind.
Every decision is stored in `major_decisions` (decision, rule, reason, evidence) and shown in the Major Retailer Coverage Audit.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import warnings

import httpx

from . import db, reference, secondary as S

US_SINGLE = {
    "Walgreens", "Ahold Delhaize USA (Stop & Shop)", "H-E-B", "Macy's", "Meijer", "Harris Teeter", "King Soopers", "Fry's Food", "NAPA Auto Parts",
    "Bass Pro Shops", "Cabela's", "JCPenney", "Saks Fifth Avenue", "Neiman Marcus", "Bergdorf Goodman", "Harbor Freight Tools", "RH",
    "Raymour & Flanigan", "Mattress Firm", "Arhaus", "Container Store", "Southeastern Grocers (Winn-Dixie)", "WinCo Foods", "FreshDirect",
    "Gopuff", "1-800 Contacts", "McKesson Medical-Surgical", "B&H Photo Video", "Micro Center", "Crutchfield", "Zoro", "REI",
    "Big 5 Sporting Goods", "Backcountry", "NFL Shop", "MLB Shop", "NBA Store", "Lids", "Finish Line", "Madewell", "Ann Taylor", "Men's Wearhouse",
    "Books-A-Million", "Pep Boys", "RockAuto", "Summit Racing", "US Foods", "The RealReal", "Fanatics", "T-ZONE",
}
EXTRA_EDGAR = {
    "walgreens.com": "WALGREENS BOOTS ALLIANCE|walgreens.com", "macys.com": "MACY'S|macys.com", "grainger.com": "GRAINGER W W|grainger.com",
    "containerstore.com": "CONTAINER STORE GROUP|containerstore.com", "therealreal.com": "REALREAL|therealreal.com",
    "bigfive.com": "BIG 5 SPORTING GOODS|big 5", "big5sportinggoods.com": "BIG 5 SPORTING GOODS|big5sportinggoods.com",
    "cdw.com": "CDW|cdw.com", "usfoods.com": "US FOODS HOLDING|usfoods.com", "napaonline.com": "GENUINE PARTS|napaonline.com",
    "rh.com": "RH|rh.com", "mattressfirm.com": "TEMPUR SEALY INTERNATIONAL|mattress firm", "booksamillion.com": "",
    "bhphotovideo.com": "", "microcenter.com": "", "rei.com": "", "summitracing.com": "", "frysfood.com": "KROGER|fry's", "kingsoopers.com": "KROGER|king soopers",
    "harristeeter.com": "KROGER|harris teeter", "dyson.com": "", "lg.com": "", "zennioptical.com": "", "carhartt.com": "", "patagonia.com": "",
    "madewell.com": "J CREW GROUP|madewell", "menswearhouse.com": "TAILORED BRANDS|men's wearhouse",
    "urbanoutfitters.com": "URBAN OUTFITTERS|urbanoutfitters", "fastenal.com": "FASTENAL|fastenal.com", "arrow.com": "ARROW ELECTRONICS|arrow.com",
    "backcountry.com": "", "finishline.com": "", "nflshop.com": "", "mlbshop.com": "", "store.nba.com": "", "lids.com": "",
}


def _quote(t):
    return t


US_TERMS = re.compile(r"\bZIP\b|U\.S\.|\bUSA\b|United States|all 50 states|nationwide|\bUS stores?\b|\bUSD\b|\bUSPS\b|your local store|store locator|in-store pickup|curbside", re.I)


async def app_store_us(client, name, domain):
    toks = S.name_tokens(name) or [domain.split(".")[0]]
    term = " ".join(toks[:3])
    res = None
    for attempt in range(4):
        async with S.ITUNES_LOCK:
            await asyncio.sleep(3.5)
            try:
                r = await client.get("https://itunes.apple.com/search", params={"term": term, "country": "us", "entity": "software", "limit": "15"}, timeout=30)
                if r.status_code == 200:
                    res = r.json().get("results", [])
            except Exception:
                pass
        if res is not None:
            break
        await asyncio.sleep(4 * 2 ** attempt)
    if res is None:
        return {"type": "app_store_us_only", "ok": False, "detail": "itunes_error"}
    label = domain.split(".")[0]
    generic = {"toys", "fashion", "beauty", "home", "kids", "baby", "market", "shop", "store", "online", "mall", "sport", "sports", "wear", "outlet", "depot"}
    strong = [t for t in toks if t not in generic] or toks
    for a in res:
        title = (a.get("trackName") or "").lower()
        seller = (a.get("sellerName") or "").lower()
        surl = (a.get("sellerUrl") or "").lower()
        match = (len(label) >= 4 and label in surl) or (all(t in title or t in seller for t in strong[:2]) and len("".join(strong[:2])) >= 4)
        if not match or a.get("primaryGenreName") not in ("Shopping", "Food & Drink", "Lifestyle", "Health & Fitness", "Medical", "Sports", "Business", "Utilities"):
            continue
        rel = (a.get("currentVersionReleaseDate") or "")[:10]
        try:
            age = (S.NOW.date() - __import__("datetime").date.fromisoformat(rel)).days
        except ValueError:
            age = 9999
        if age > 450:
            continue
        terms = sorted({m.group(0).lower() for m in US_TERMS.finditer(a.get("description") or "")})[:4]
        if not terms:
            return {"type": "app_store_us_only", "ok": False, "detail": f"app '{a.get('trackName')}' found but listing has no US-specific wording", "url": a.get("trackViewUrl")}
        return {"type": "app_store_us_only", "ok": True, "url": a.get("trackViewUrl"), "date": rel.replace("-", ""),
                "detail": f"US App Store shopping app '{a.get('trackName')}' by {a.get('sellerName')}, updated {rel}; listing is US-specific ({', '.join(terms)})"}
    return {"type": "app_store_us_only", "ok": False, "detail": f"no current US shopping app matching {term!r}"}


def decide(name, evs):
    ok = {e["type"]: e for e in evs if e.get("ok")}
    single = name in US_SINGLE
    arch_ok = [t for t in ("wayback_product", "commoncrawl_product") if t in ok and ok[t].get("age_days", 9999) <= 365]
    us_specific = set()
    if "sec_edgar" in ok:
        us_specific.add("sec_edgar")
    if "app_store_us_only" in ok:
        us_specific.add("app_store_us_only")
    if "google_play" in ok and "app_store_us_only" not in ok and single:
        us_specific.add("google_play")
    if arch_ok:
        us_specific.add(arch_ok[0])
    storefront = {t for t in ("sitemap", "live_storefront") if t in ok} | set(arch_ok)
    other = set(ok) - {"app_store", "google_play", "app_store_us_only"}
    if set(ok) & {"app_store_us_only", "google_play"}:
        other.add("app_store_us_only" if "app_store_us_only" in ok else "google_play")
    if single:
        types = other
        if len(types) >= 2 and (us_specific & types):
            return "verified_secondary_evidence", "US-HQ single-country retailer: two independent current proofs, one US-specific (" + ", ".join(sorted(types)) + ")"
        return "unresolved", "US-HQ single-country retailer: fewer than two independent current proofs (" + ", ".join(sorted(types)) + ")" if types else "US-HQ single-country retailer: no independent proof obtained"
    if storefront and len(set(ok) | storefront) >= 2:
        return "verified_secondary_evidence", "global brand: US-specific storefront proof plus second proof (" + ", ".join(sorted(ok)) + ")"
    return "unresolved", "global brand: no US-specific storefront proof obtained (" + (", ".join(sorted(ok)) or "none") + ")"


PATTERNS = ["shop/product/", "shopping/product/", "product/", "products/", "p/", "ip/", "dp/", "pd/", "prod/", "item/", "pdp/", "store/c/", "catalog/product/",
            "s/", "browse/product/", "us/en/product/", "en-us/product/", "shop/", "c/"]


async def wayback_targeted(client, prefix):
    """Targeted Wayback CDX prefix queries on common product paths (cheap, unlike whole-host prefix scans); validate USD + ordering control."""
    import datetime as dt
    host, _, path = prefix.partition("/")
    hosts = [host] if host.startswith("www.") else ["www." + host, host]
    since = (S.NOW - dt.timedelta(days=365)).strftime("%Y%m%d")
    tried = 0
    with_rows = 0
    for h in hosts:
        for pat in PATTERNS:
            url = f"{h}/{path}{pat}*"
            try:
                r = await client.get("https://web.archive.org/cdx/search/cdx", params={"url": url, "from": since, "filter": ["statuscode:200", "mimetype:text/html"],
                                     "collapse": "urlkey", "limit": "6", "fl": "timestamp,original"}, timeout=70)
            except Exception:
                continue
            rows = sorted([l.split(" ") for l in r.text.splitlines() if len(l.split(" ")) == 2 and not S.NON_PRODUCT.search(l)], reverse=True)
            for ts, orig in rows[:4]:
                tried += 1
                try:
                    pg = await client.get(f"https://web.archive.org/web/{ts}id_/{orig}", timeout=60, follow_redirects=True)
                except Exception:
                    continue
                n_loc, cart, foreign = S.page_ok(pg.text[:2_000_000])
                if n_loc and cart and not foreign:
                    return {"type": "wayback_product", "ok": True, "url": f"https://web.archive.org/web/{ts}/{orig}", "date": ts[:8], "age_days": S.days_ago(ts),
                            "detail": f"archived US product page with {n_loc} USD price strings and ordering control"}
            if rows:
                with_rows += 1
                if with_rows >= 5:
                    break
        if tried:
            break
    return {"type": "wayback_product", "ok": False, "detail": f"no usable archived product page <=365 days ({tried} captures tested)"}


async def gather(arch, live, item, prior, con):
    prefix = re.sub(r"^www\d+\.", "www.", S.storefront_prefix(item["url"]))
    evs = []
    old = {e["type"]: e for e in prior}
    for t in ("sitemap", "commoncrawl_product", "wayback_product", "live_storefront"):
        if t in old and old[t].get("ok"):
            evs.append(old[t])
    if not any(e["type"] == "wayback_product" for e in evs) and not any(e["type"] == "commoncrawl_product" for e in evs):
        w = await wayback_targeted(arch, prefix)
        evs.append(w)
    if not any(e["type"] == "sitemap" for e in evs):
        evs.append(await S.sitemap_ev(live, prefix))
    if not any(e["type"] == "live_storefront" for e in evs):
        evs.append(S.live_storefront(con, item["key"]))
    s = await S.sec_edgar(live, item["name"], item["root"])
    evs.append(s)
    evs.append(await app_store_us(live, item["name"], item["root"]))
    evs.append(await S.google_play(live, item["name"], item["root"]))
    return evs


async def main(names, dry):
    warnings.filterwarnings("ignore")
    S.EDGAR_ALIASES.update(EXTRA_EDGAR)
    con = reference.connect()
    con.execute("""CREATE TABLE IF NOT EXISTS major_decisions(key TEXT PRIMARY KEY, name TEXT, tier TEXT, before_status TEXT, decision TEXT, rule TEXT,
                   reason TEXT, evidence TEXT, decided_at TEXT)""")
    audit = reference.audit(con)
    todo = [r for r in audit if r["tier"] in ("huge", "large") and r["status"].startswith("unresolved") and r["kind"] in ("brand", "wikidata")
            and (not names or r["name"] in names)]
    keys = {}
    for r in todo:
        row = con.execute("SELECT key, url, root_domain FROM reference_stores WHERE ref_id=?", (r["ref_id"],)).fetchone()
        keys[r["ref_id"]] = row
    print(f"[major] {len(todo)} unresolved huge/large", flush=True)
    sem = asyncio.Semaphore(4)
    async with httpx.AsyncClient(headers=S.UA_RESEARCH, follow_redirects=True) as arch, httpx.AsyncClient(headers=S.UA_BROWSER, follow_redirects=True, verify=False) as live:
        async def one(r):
            key, url, root = keys[r["ref_id"]]
            url = S.URL_OVERRIDE.get(root or "", r["url"] or url)
            item = {"key": key, "name": r["name"], "url": url if url.startswith("http") else "https://" + url, "root": root}
            srow = con.execute("SELECT evidence FROM secondary_evidence WHERE key=?", (key,)).fetchone()
            prior = json.loads(srow[0]) if srow else []
            async with sem:
                try:
                    evs = await asyncio.wait_for(gather(arch, live, item, prior, con), 900)
                except Exception as e:
                    print("[major] error", r["name"], type(e).__name__, flush=True)
                    return
            decision, rule = decide(r["name"], evs)
            oks = [e for e in evs if e.get("ok")]
            ev_text = " | ".join(f"{e['type']}: {e['detail'][:160]} ({e.get('url')}, {e.get('date')})" for e in oks) or "no accepted proof; " + "; ".join(f"{e['type']}={e.get('detail','')[:60]}" for e in evs)
            print(f"[major] {r['name']} -> {decision} :: {rule}", flush=True)
            if dry:
                return
            con.execute("INSERT OR REPLACE INTO major_decisions VALUES(?,?,?,?,?,?,?,?,?)", (key, r["name"], r["tier"], r["status"], decision, rule, rule, ev_text[:1500], db.now()))
            con.execute("INSERT OR REPLACE INTO secondary_evidence VALUES(?,?,?,?,?)", (key, S.storefront_prefix(item["url"]), "verified_secondary_evidence" if decision == "verified_secondary_evidence" else "insufficient_secondary_evidence", json.dumps(evs), db.now()))
            if decision == "verified_secondary_evidence":
                first = oks[0]
                prod = next((e.get("url") for e in oks if e["type"] in ("commoncrawl_product", "wayback_product", "live_storefront")), None) or first.get("url")
                sf = "https://" + S.storefront_prefix(item["url"])
                n = con.execute("""UPDATE verifications SET status='verified_secondary_evidence', method='major_rule', reason=?, product_evidence=?, evidence_url=?, verified_at=?,
                                final_url=?, final_key=coalesce(final_key, key) WHERE key=?""", ("verified_secondary_evidence: " + ev_text[:900], prod, prod, db.now(), sf, key)).rowcount
                if n == 0:
                    con.execute("INSERT INTO verifications(key, final_url, final_key, store_name, status, reason, evidence_url, product_evidence, verified_at, method) VALUES(?,?,?,?,?,?,?,?,?,?)",
                                (key, sf, key, r["name"], "verified_secondary_evidence", "verified_secondary_evidence: " + ev_text[:900], prod, prod, db.now(), "major_rule"))
                con.execute("UPDATE candidates SET status='verified' WHERE key=?", (key,))
        await asyncio.gather(*(one(r) for r in todo))


COLS = ["key", "final_url", "final_key", "store_name", "platform", "category", "market_score", "market_evidence", "ecom_evidence", "product_evidence",
        "status", "reason", "evidence_url", "verified_at", "method"]


def dump(path):
    con = reference.connect()
    out = []
    for key, name, tier, before, decision, rule, reason, ev, at in con.execute("SELECT * FROM major_decisions"):
        v = con.execute(f"SELECT {','.join(COLS)} FROM verifications WHERE key=?", (key,)).fetchone()
        sec = con.execute("SELECT prefix, verdict, evidence, ts FROM secondary_evidence WHERE key=?", (key,)).fetchone()
        out.append(dict(key=key, name=name, tier=tier, before=before, decision=decision, rule=rule, reason=reason, evidence=ev, at=at,
                        ver=dict(zip(COLS, v)) if v else None, sec=sec))
    with open(path, "w") as f:
        for o in out:
            f.write(json.dumps(o) + "\n")
    print("dumped", len(out))


def replay(path):
    con = reference.connect()
    con.execute("""CREATE TABLE IF NOT EXISTS major_decisions(key TEXT PRIMARY KEY, name TEXT, tier TEXT, before_status TEXT, decision TEXT, rule TEXT,
                   reason TEXT, evidence TEXT, decided_at TEXT)""")
    n = 0
    for l in open(path):
        o = json.loads(l)
        con.execute("INSERT OR REPLACE INTO major_decisions VALUES(?,?,?,?,?,?,?,?,?)", (o["key"], o["name"], o["tier"], o["before"], o["decision"], o["rule"], o["reason"], o["evidence"], o["at"]))
        if o["sec"]:
            con.execute("INSERT OR REPLACE INTO secondary_evidence VALUES(?,?,?,?,?)", (o["key"], *o["sec"]))
        if o["decision"] == "verified_secondary_evidence" and o["ver"]:
            v = o["ver"]
            con.execute("DELETE FROM verifications WHERE key=?", (o["key"],))
            con.execute(f"INSERT INTO verifications({','.join(COLS)}) VALUES({','.join('?' * len(COLS))})", [v[c] for c in COLS])
            con.execute("INSERT OR IGNORE INTO candidates(key,url,root_domain,first_source,status,priority) VALUES(?,?,?,?,?,0)", (o["key"], v["final_url"], o["key"].split("|")[0], "reference:curated", "verified"))
            con.execute("UPDATE candidates SET status='verified' WHERE key=?", (o["key"],))
        n += 1
    print("replayed", n)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", default="")
    ap.add_argument("--replay", default="")
    ap.add_argument("--names", default="")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    if a.dump:
        dump(a.dump)
        raise SystemExit
    if a.replay:
        replay(a.replay)
        raise SystemExit
    asyncio.run(main({n for n in a.names.split(";") if n}, a.dry))
