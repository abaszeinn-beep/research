"""QA sampler: live-fetch a stratified sample of verified rows and print title/description plus automatic checks.

  python3 -m mktecom.qa_sample --n 150 --seed 7 --out qa/qa_sample_1.jsonl
"""
import argparse, asyncio, json, random, re, warnings
from collections import defaultdict
import httpx
from . import db

CART = re.compile(r"add[\s_-]?to[\s_-]?(?:cart|bag|basket)|addtocart|/cart|checkout|buy now|shopping[\s_-]?cart|\"@type\"\s*:\s*\"(?:Product|Offer)\"", re.I)
USD = re.compile(r"\$\s?\d|USD|\"priceCurrency\"\s*:\s*\"USD\"", re.I)
FOREIGN = re.compile(r"(?:€|£|₹|CA\$|C\$|A\$|AU\$|R\$|zł|kr\b|\b(?:EUR|GBP|INR|CAD|AUD|PLN|BRL)\b)\s?\d|\d\s?(?:€|£|zł)")
SVC = re.compile(r"\b(saas|software|hosting|agency|consulting|our services|book (?:a|your) (?:call|demo|appointment)|free trial|request a (?:quote|demo)|schedule a|webinar|api|subscription plans?|pricing plans?)\b", re.I)
CLOSED = re.compile(r"(?:permanently closed|store (?:is )?closed|going out of business|coming soon|under construction|domain (?:is )?for sale|this domain|parked|website is no longer|account suspended|opening soon)", re.I)
ADULT = re.compile(r"\b(porn|xxx|sex toys?|adult toys?|erotic|vibrators?|dildo|18\+|must be 18)\b", re.I)
MARKET = re.compile(r"\b(sell (?:your|on)|marketplace|become a seller|vendors? (?:sign|register)|third[- ]party sellers)\b", re.I)
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36", "Accept-Language": "en-US,en;q=0.9"}

def pick(con, n, seed, exclude=(), skip_shopify=False):
    rows = con.execute("""SELECT v.key, v.store_name, v.platform, v.category, v.final_url, v.status, v.reason, c.first_source,
        (SELECT group_concat(source) FROM group_sources g WHERE g.grp=v.key AND g.status LIKE 'verified%')
        FROM verifications v JOIN candidates c USING(key) WHERE v.status LIKE 'verified%' AND v.duplicate_of IS NULL""").fetchall()
    strata = defaultdict(list)
    for r in rows:
        if r[0] in exclude or (skip_shopify and r[2] == 'shopify'):
            continue
        src = (r[7] or "").split(",")[0].strip()
        src = src if src.startswith("shard_") else "main"
        if src == "main" and r[8] and r[8].startswith("shard_"):
            src = r[8].split(",")[0]
        plat = r[2] or "unknown"
        if plat not in ("shopify", "woocommerce", "custom/unknown", "bigcommerce", "magento", "square", "wix", "shift4shop", "bigcartel", "squarespace", "ecwid", "salesforce-commerce"):
            plat = "other"
        strata[(src, plat)].append(r)
    rnd = random.Random(seed)
    total = sum(len(v) for v in strata.values())
    out = []
    for k, v in sorted(strata.items()):
        take = max(1, round(n * len(v) / total)) if len(v) >= 15 else 0
        out += rnd.sample(v, min(take, len(v)))
    rnd.shuffle(out)
    return out[:n + 15]

async def fetch(client, row):
    key, name, plat, cat, url, status, reason, fs, vs = row
    res = dict(key=key, name=name, platform=plat, category=cat, url=url, status=status, src=(fs or ""), flags=[])
    try:
        r = await client.get(url, timeout=25)
    except Exception as e:
        res.update(http=0, err=type(e).__name__); res["flags"].append("unreachable"); return res
    t = r.text[:400000]
    res["http"] = r.status_code
    res["final"] = str(r.url)
    m = re.search(r"<title[^>]*>(.*?)</title>", t, re.I | re.S)
    res["title"] = re.sub(r"\s+", " ", m.group(1)).strip()[:110] if m else ""
    m = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)', t, re.I)
    res["desc"] = (m.group(1) if m else "")[:140]
    if r.status_code in (401, 403, 429, 503):
        res["flags"].append(f"blocked_{r.status_code}")
    elif r.status_code >= 400:
        res["flags"].append(f"http_{r.status_code}")
    res["cart"] = bool(CART.search(t)); res["usd"] = bool(USD.search(t)); res["foreign"] = len(FOREIGN.findall(t))
    if not res["cart"] and r.status_code < 400: res["flags"].append("no_cart_markers")
    if res["foreign"] > 3 and not res["usd"]: res["flags"].append("foreign_only")
    if len(SVC.findall(t)) >= 4: res["flags"].append("svc_vocab")
    if CLOSED.search(t[:60000]): res["flags"].append("closed_or_placeholder")
    if ADULT.search(t[:60000]): res["flags"].append("adult")
    if MARKET.search(t[:200000]): res["flags"].append("marketplace_vocab")
    return res

async def main(n, seed, out, excl, skip_shopify=False):
    warnings.filterwarnings("ignore")
    con = db.connect()
    ex = set(json.loads(l)["key"] for l in open(excl)) if excl else set()
    rows = pick(con, n, seed, ex, skip_shopify)
    sem = asyncio.Semaphore(15)
    async with httpx.AsyncClient(headers=UA, follow_redirects=True, verify=False) as c:
        async def one(r):
            async with sem:
                return await fetch(c, r)
        res = await asyncio.gather(*(one(r) for r in rows))
    with open(out, "w") as f:
        for r in res: f.write(json.dumps(r) + "\n")
    print(len(res))

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=150); ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="qa/qa_sample_1.jsonl"); ap.add_argument("--exclude", default=""); ap.add_argument("--skip-shopify", action="store_true")
    a = ap.parse_args(); asyncio.run(main(a.n, a.seed, a.out, a.exclude, a.skip_shopify))
