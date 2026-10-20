"""Re-screen verified rows of a shard against the main pipeline's homepage gates (SaaS/service/org/closed/adult) using one live homepage GET
(one GET of the same storefront URL the verifier already fetched). JS-only pages (little text) are never rejected on text evidence.

  python3 -m mktecom.rescreen --sources all-nonshopify --out qa/rescreen_v2_nonshopify.jsonl [--concurrency 20]
  python3 -m mktecom.rescreen --apply qa/rescreen_tranco.jsonl
"""
import argparse, asyncio, json, re, sys, warnings
import httpx
from . import db, export, signals as S

ADULT = re.compile(r"\b(porn|xxx|sex toys?|adult toys?|erotic|vibrators?|dildos?)\b", re.I)
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36", "Accept-Language": "en-US,en;q=0.9"}
PARKED_STRICT = re.compile(r"coming soon|under construction|parked|domain.*for sale|this domain|suspended|default page|welcome to nginx|index of|opening soon", re.I)
TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


GAMBLING = re.compile(r"togel|slot(?:s|gacor|88|online)?\b|\bgacor\b|\bbandar\b|\bjudi\b|casino|sportsbook|\bpoker\b|\btoto\b|\d{3}(?:so|toto|slot|bet)\b|situs|paling hoki|terpercaya|link alternatif", re.I)
NEWS_TITLE = re.compile(r"\b(news|blog|journal|magazine|gazette|times|daily|weekly|digest|podcast|newsletter|stocks?|forum|community)\b", re.I)
SVC_TITLE = re.compile(r"\b(software|platform|saas|real estate|wordpress|plugins?|domain registrat\w*|web hosting|hosting|proxies|proxy|templates?|courses?|training|education|association|society|institute|academy|church|ministr\w+|stock market|continuing education|printing services|gymnastics|pottery|paint(?:ing)? studio|wine bar|dispensary delivery|weed delivery|marketing|agency|consulting|translation|study guides?|curricul\w+)\b", re.I)
EDU_DIGITAL = re.compile(r"powerpoint|proxies|proxy plans?|residential proxy|domain search|register a domain|whois|nameservers?|store builder|real estate (?:agents?|professionals)|idx\b|crm\b|templates?\b|\bcourses?\b|continuing education|\bCEUs?\b|online learning|e-?learning|web-based|\bplugins?\b|\bSaaS\b|domain (?:name )?registration|web hosting|email (?:list|database)|mailing list database|download(?:able)?|instant access|memberships?\b|subscribe to (?:our|the) (?:newsletter|magazine)", re.I)
SERVICE_BUSINESS = re.compile(r"\b(book (?:a|your|an) (?:class|lesson|session|appointment|party|visit)|birthday parties|our classes|class schedule|open gym|walk-?ins? welcome|private lessons?|paint(?:ing)? (?:party|studio)|wine bar|tasting room hours|join our team|same[- ]day (?:weed|cannabis) delivery)\b", re.I)


MARKETPLACE_TXT = re.compile(r"\b(marketplace|buy and sell|buy &amp; sell|buy & sell|sell your|consign(?:ment)?|auction|classifieds)\b", re.I)
NEWS_STRONG = re.compile(r"news,? weather|breaking news|local news|news & weather|\bnewspaper\b", re.I)
CANADA_TXT = re.compile(r"\bcanad(?:a|ian)\b", re.I)
ORG_TXT = re.compile(r"\b(museum|non-?profit|our mission is|organization with a mission|a mission to|membership organization|association of)\b", re.I)
GUIDE_TITLE = re.compile(r"\b(guide to|your guide|recipes?|all about|how[- ]to|reviews? and|politics|culture & |podcast|essays?|musings|sharing ideas)\b", re.I)
HEALTH_SVC = re.compile(r"\b(laser|acupuncture|botox|facials?|med ?spa|massage|chiropractic|healing arts|aesthetics clinic|physical therapy|bar & bottle|coffee bar|acai bowls?|smoothies)\b", re.I)
AU_TXT = re.compile(r"\b(australia(?:'s|n)?|new zealand|united kingdom|\buk\b)\b", re.I)
SVC_NAME_THIN = re.compile(r"\b(academy|school|salon|spa\b|studios?\b|venue|events?\b|coach(?:ing)?|ministr\w+|church|rentals?|parks?\b|recreation|restaurant|cafe|caf\u00e9|bar & grill|catering|dance|gymnastics|fitness center|clinic|dental|counseling|therapy|tutoring|realty|insurance|law (?:office|firm)|consulting|marketing|design agency)\b", re.I)


def judge(name, html, status=200, key=""):
    if status in (404, 410):
        return "gone_http_%d" % status, ""
    text = S.visible_text(html)
    m = TITLE.search(html)
    title = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    md = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)', html, re.I)
    desc = md.group(1) if md else ""
    atc = len(S.ADD_TO_CART.findall(html))
    prices = len(S.PRICE_ANY.findall(text))
    head = f"{title} {desc[:200]} {name}"
    if GAMBLING.search(head) or GAMBLING.search(text[:1500]) and len(GAMBLING.findall(text[:6000])) >= 3:
        return "gambling_or_spam", title[:80]
    if len(text) < 1200:
        if SVC_NAME_THIN.search(f"{title} {name}") and atc < 5:
            return "service_name_thin_page", name[:60]
        return None, "js_or_thin"
    cjk = len(re.findall(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\u0400-\u04ff\u0600-\u06ff]", text[:3000]))
    if cjk > 300:
        return "non_english_non_us_site", title[:60]
    if key.endswith(".org") and not (atc >= 15 and prices >= 8):
        return "org_domain_site", title[:80]
    if ORG_TXT.search(f"{title} {desc[:240]}") and atc < 12:
        return "org_site", title[:80]
    if GUIDE_TITLE.search(f"{title} {desc[:200]}") and atc < 5 and prices < 8:
        return "guide_blog_media", title[:80]
    if HEALTH_SVC.search(f"{title} {desc[:200]}") and prices < 12:
        return "local_service_or_foodservice", title[:80]
    if AU_TXT.search(f"{title} {desc[:200]}") and not re.search(r"\b(usa|u\.s\.|united states|us store)\b", f"{title} {desc}", re.I) and prices < 12:
        return "non_us_store", title[:80]
    if MARKETPLACE_TXT.search(f"{title} {desc[:200]}"):
        return "marketplace_or_aggregator", title[:80]
    if NEWS_STRONG.search(title):
        return "news_media_site", title[:80]
    if CANADA_TXT.search(f"{title} {desc[:200]}") and not re.search(r"\b(usa|u\.s\.|united states|us store)\b", f"{title} {desc}", re.I):
        return "canadian_store", title[:80]
    if PARKED_STRICT.search(title) and atc < 3:
        return "parked_or_placeholder", title[:80]
    if ADULT.search(text[:20000]) and len(ADULT.findall(text[:60000])) >= 3:
        return "adult", ""
    if (S.ORG.search(head) or S.SERVICE_ORG.search(head) or S.CHARITY.search(head)) and atc < 3 and prices < 6:
        return "service_org_site", title[:80]
    if NEWS_TITLE.search(f"{title} {name}") and atc < 5:
        return "news_media_site", title[:80]
    n_edu = len(EDU_DIGITAL.findall(text))
    if SVC_TITLE.search(title) and prices < 12:
        return "service_or_digital_title", title[:80]
    if n_edu >= 12:
        return "digital_or_education_site", ",".join(sorted({x.lower() for x in EDU_DIGITAL.findall(text)})[:4])
    if n_edu >= 5 and atc < 8:
        return "digital_or_education_site", ",".join(sorted({x.lower() for x in EDU_DIGITAL.findall(text)})[:4])
    if len(SERVICE_BUSINESS.findall(text)) >= 2 and atc < 8:
        return "service_business", ""
    phys = {x.lower() for x in S.PHYSICAL.findall(text)}
    saas = {x.lower() for x in S.SAAS.findall(text)}
    if len(saas) >= 3 and len(saas) > len(phys) and atc < 3:
        return "saas_digital_or_media_site", ",".join(sorted(saas)[:4])
    if S.RESTAURANT.search(text) and len(S.RESTAURANT.findall(text)) >= 6 and atc < 3:
        return "restaurant_or_food_service", ""
    low = html.lower()
    if atc == 0 and prices < 2 and not S.PRODUCT_LINK.search(html):
        return "no_commerce_markers", title[:80]
    return None, ""


async def run(rows, conc, out):
    sem = asyncio.Semaphore(conc)
    async with httpx.AsyncClient(headers=UA, follow_redirects=True, verify=False, timeout=15) as c:
        async def one(r):
            key, name, url = r
            async with sem:
                try:
                    resp = await c.get(url)
                    html = resp.text[:600000]
                    if resp.status_code in (401, 403, 429, 503) or resp.status_code >= 500:
                        return dict(key=key, verdict=None, note=f"http_{resp.status_code}")
                except Exception as e:
                    note = type(e).__name__
                    if note == "ConnectError":
                        import socket
                        try:
                            host = httpx.URL(url).host
                            await asyncio.get_running_loop().run_in_executor(None, socket.getaddrinfo, host, 443)
                        except socket.gaierror:
                            return dict(key=key, verdict="dns_not_resolved", note=note)
                        except Exception:
                            pass
                    return dict(key=key, verdict=None, note=note)
            v, note = judge(name or "", html, resp.status_code, key)
            return dict(key=key, verdict=v, note=note)
        done = 0
        with open(out, "w") as f:
            for fut in asyncio.as_completed([one(r) for r in rows]):
                res = await fut
                f.write(json.dumps(res) + "\n")
                done += 1
                if done % 500 == 0:
                    print(done, flush=True)


def main():
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--concurrency", type=int, default=20)
    ap.add_argument("--apply", default="")
    ap.add_argument("--retry-from", default="")
    a = ap.parse_args()
    con = db.connect()
    if a.apply:
        n = 0
        protected = {r[0] for r in con.execute("SELECT key FROM reference_stores WHERE kind='brand'")}
        protected |= {r[0] for r in con.execute("SELECT final_key FROM verifications v JOIN reference_stores r USING(key) WHERE r.kind='brand' AND final_key IS NOT NULL")}
        con.execute("BEGIN")
        for l in open(a.apply):
            j = json.loads(l)
            if j["key"] in protected and j["verdict"] != "gambling_or_spam":
                continue

            if j["verdict"] == "parked_or_placeholder" and not PARKED_STRICT.search(j["note"]):
                continue
            if j["verdict"]:
                con.execute("UPDATE verifications SET status='rejected', reason=? WHERE key=? AND status LIKE 'verified%'", (f"rescreen: {j['verdict']} ({j['note']})", j["key"]))
                con.execute("UPDATE candidates SET status='rejected' WHERE key=?", (j["key"],))
                n += 1
        con.execute("COMMIT")
        print("rejected", n)
        return
    export.dedup(con)
    if a.sources == "all-nonshopify":
        rows = con.execute("""SELECT v.key, v.store_name, v.final_url FROM verifications v WHERE v.status='verified' AND v.duplicate_of IS NULL
            AND coalesce(v.platform,'') != 'shopify' AND v.key NOT LIKE '%.myshopify.com'""").fetchall()
    else:
        srcs = [s for s in a.sources.split(",") if s]
        q = ",".join("?" * len(srcs))
        rows = con.execute(f"""SELECT v.key, v.store_name, v.final_url FROM verifications v JOIN candidates c USING(key)
            WHERE v.status='verified' AND v.method='shard' AND c.first_source IN ({q})""", srcs).fetchall()
    if a.retry_from:
        redo = {json.loads(l)["key"] for l in open(a.retry_from) if json.loads(l)["note"] in ("ConnectError", "ReadTimeout")}
        rows = [r for r in rows if r[0] in redo]
    print(len(rows), "rows", flush=True)
    asyncio.run(run(rows, a.concurrency, a.out))


if __name__ == "__main__":
    main()
