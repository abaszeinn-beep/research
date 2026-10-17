"""Expand the medium/large reference list from public pages fetched in this run.

Sources (each stored on the reference row): Ministry of Commerce e-commerce
evaluation PDFs, Zid's public success-story page, Wikipedia category members,
Wikidata retail chains, the Saudi App Store shopping chart (sellerUrl),
agency portfolios, and any ranking article or mall directory that responds
without a checkpoint. Salla's marketing site is recorded if it is still
behind a bot wall; an archived showcase copy is used when the Wayback CDX
API returns one.

Nothing here is marked verified. Storefront URLs are queued with
db.add_candidates for the existing verifier. A name with no official URL
on the source page is kept only when a Wikipedia/Wikidata site or an App
Store sellerUrl names the same brand.
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import time
import unicodedata
from urllib.parse import urlsplit

import httpx

from . import db, reference
from .common import NON_STORE_ROOTS, clean_host, identity, registrable_domain

UA = {"User-Agent": "saudi-ecom-directory-research/1.0 (public-source harvester)",
      "Accept-Language": "ar-SA,ar;q=0.9,en;q=0.7"}
SKIP_ROOTS = NON_STORE_ROOTS | {
    "youtu.be", "youtu.be", "gstatic.com", "googletagmanager.com", "clarity.ms",
    "hyros.com", "perspectivefunnel.com", "schema.org", "w3.org", "apple.com",
    "itunes.apple.com", "apps.apple.com", "play.google.com", "wa.me", "t.me",
    "mc.gov.sa", "gov.sa", "wikipedia.org", "wikidata.org", "wikimedia.org",
}
SOCIAL = ("facebook.com", "instagram.com", "twitter.com", "x.com", "tiktok.com", "snapchat.com",
          "linkedin.com", "youtube.com", "youtu.be", "pinterest.com", "whatsapp.com")


def get(client, url, timeout=30):
    for i in range(3):
        try:
            r = client.get(url, timeout=timeout)
            return r
        except httpx.HTTPError:
            time.sleep(1.5 * (i + 1))
    return None


def roots_of(url: str):
    host = clean_host(urlsplit(url).hostname or "")
    if not host or "." not in host:
        return None
    root = registrable_domain(host)
    if root in SKIP_ROOTS or root.endswith((".gov.sa", ".edu.sa", ".med.sa", ".sch.sa")):
        return None
    if any(root == s or root.endswith("." + s) for s in SOCIAL):
        return None
    return root


def norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9\u0600-\u06ff]+", "", s)


def existing_index(con):
    idx = {}
    for ref_id, name, tier in con.execute("SELECT ref_id, name, tier FROM reference_stores WHERE kind IN ('brand','mall')"):
        idx.setdefault(norm_name(name), (ref_id, tier, name))
        for part in re.split(r"[:/|]", name):
            idx.setdefault(norm_name(part), (ref_id, tier, name))
    return idx


def attach_source(con, ref_id, source):
    raw = con.execute("SELECT sources FROM reference_stores WHERE ref_id=?", (ref_id,)).fetchone()
    srcs = json.loads(raw[0] or "[]")
    if source not in srcs:
        srcs.append(source)
        con.execute("UPDATE reference_stores SET sources=? WHERE ref_id=?", (json.dumps(srcs, ensure_ascii=False), ref_id))


def add_ref(con, index, name, category, tier, domains, source, url=None, kind="brand"):
    name = re.sub(r"\s+", " ", (name or "").strip())[:140]
    domains = [d.lower().strip() for d in domains if d and roots_of("https://" + d)]
    # de-dup preserving order
    seen = []
    for d in domains:
        root = registrable_domain(d)
        if root not in seen:
            seen.append(root)
    domains = seen
    key = norm_name(name)
    if key and key in index:
        ref_id = index[key][0]
        attach_source(con, ref_id, source)
        if domains:
            old = (con.execute("SELECT domains FROM reference_stores WHERE ref_id=?", (ref_id,)).fetchone() or [""])[0].split()
            merged = old + [d for d in domains if d not in old]
            if merged != old:
                con.execute("UPDATE reference_stores SET domains=? WHERE ref_id=?", (" ".join(merged), ref_id))
        return ref_id, False
    if not domains or not name:
        return None, False
    row = con.execute("SELECT tier FROM reference_stores WHERE name=? AND kind=?", (name, kind)).fetchone()
    if row and row[0] == "major":
        tier = "major"
    ref_id = reference.upsert(con, name, category, tier, " ".join(domains), [source], None, kind)
    index[key] = (ref_id, tier, name)
    target = url or f"https://{domains[0]}/"
    ident = identity(target) or identity(f"https://{domains[0]}/")
    if ident:
        db.add_candidates(con, [(ident["url"], 7)], f"public:{source.split()[0][:40]}", source[:240], 7)
        con.execute(
            "INSERT OR IGNORE INTO reference_urls VALUES (?,?,?,?,?,?,?,?)",
            (ref_id, ident["url"], ident["key"], "public", None, ident["url"], json.dumps({"source": source})[:500], db.now()),
        )
    return ref_id, True


def ministry(client, con):
    """One PDF per evaluated store. The title line is the legal name; URLs are rare."""
    page = get(client, "https://mc.gov.sa/ar/mediacenter/Pages/esv.aspx")
    if page is None or page.status_code != 200:
        print("[public] ministry page unavailable", flush=True)
        return []
    pdfs = sorted(set(re.findall(r"/ar/mediacenter/esv/\d+\.pdf", page.text)), key=lambda p: int(re.search(r"(\d+)", p).group(1)))
    pdfs = [p for p in pdfs if int(re.search(r"(\d+)", p).group(1)) <= 250]
    print(f"[public] ministry pdfs {len(pdfs)}", flush=True)
    try:
        import pymupdf
    except ImportError:
        print("[public] pymupdf missing, skipping pdf text", flush=True)
        return []
    out = []
    for path in pdfs:
        url = "https://mc.gov.sa" + path
        try:
            r = client.get(url, timeout=12)
        except httpx.HTTPError:
            print(f"[public] ministry skip {path}", flush=True)
            continue
        if r.status_code != 200 or not r.content.startswith(b"%PDF"):
            continue
        try:
            doc = pymupdf.open(stream=r.content, filetype="pdf")
            text = unicodedata.normalize("NFKC", "\n".join(p.get_text("text") for p in doc))
        except Exception:
            continue
        urls = re.findall(r"https?://[a-z0-9./_-]{4,80}", text, re.I)
        hosts = []
        for u in urls:
            root = roots_of(u)
            if root:
                hosts.append(root)
        lines = [ln.strip(" -\t") for ln in text.splitlines() if ln.strip()]
        title = ""
        for ln in lines:
            if "متجر" in ln or "شركة" in ln:
                title = ln
                break
        title = re.split(r"\s+جودة الخدمات", title)[0].strip(" -")
        short = title.split("-")[0].strip()
        short = re.sub(r"^(متجر|شركة)\s+", "", short)
        short = re.sub(r"\s+(الإلكتروني|الالكتروني|الإلكترونية|الالكترونية)$", "", short).strip()
        if len(short) < 2:
            continue
        out.append({"name": short[:120], "category": "Department Store / General", "tier": "medium",
                    "domains": hosts, "url": ("https://" + hosts[0] + "/") if hosts else None,
                    "source": f"ministry-of-commerce:esv {url} (fetched {db.now()[:10]})",
                    "legal": title[:180]})
        if len(out) % 10 == 0:
            print(f"[public] ministry parsed {len(out)} {short[:40]}", flush=True)
        time.sleep(0.05)
    return out


def zid_stories(client):
    r = get(client, "https://zid.sa/en/success-stories/")
    if r is None or r.status_code != 200:
        print("[public] zid success page unavailable", flush=True)
        return []
    names = re.findall(r'\\"alt\\":\\"([^\\"]{2,60})\\"', r.text) or re.findall(r'"alt":"([^"]{2,60})"', r.text)
    names = list(dict.fromkeys(names))
    print(f"[public] zid story names {len(names)}: {names[:12]}", flush=True)
    out = []
    for name in names:
        slug = re.sub(r"[^a-z0-9]", "", name.lower())
        if len(slug) < 4:
            continue
        # the story page names the merchant; keep a host only when DNS has an address
        hosts = []
        for host in (f"{slug}.com", f"{slug}.sa", f"{slug}.com.sa"):
            try:
                socket.getaddrinfo(host, 443, socket.AF_INET)
                hosts.append(host)
            except socket.gaierror:
                continue
        if not hosts:
            print(f"[public] zid {name}: no resolving host", flush=True)
            continue
        out.append({"name": name, "category": "Department Store / General", "tier": "medium",
                    "domains": hosts, "url": f"https://{hosts[0]}/",
                    "source": "zid.sa/en/success-stories (fetched " + db.now()[:10] + ")"})
    return out


def wikipedia(client):
    cats = [
        "Category:Retail_companies_of_Saudi_Arabia",
        "Category:Supermarkets_of_Saudi_Arabia",
        "Category:Clothing_companies_of_Saudi_Arabia",
        "Category:Food_and_drink_companies_of_Saudi_Arabia",
        "Category:Pharmacies_of_Saudi_Arabia",
        "Category:Saudi_Arabian_brands",
    ]
    out = []
    for cat in cats:
        cm = None
        while True:
            params = {"action": "query", "list": "categorymembers", "cmtitle": cat, "cmlimit": "50",
                      "cmtype": "page", "format": "json"}
            if cm:
                params["cmcontinue"] = cm
            try:
                r = client.get("https://en.wikipedia.org/w/api.php", params=params, timeout=30)
            except httpx.HTTPError:
                break
            if r.status_code != 200:
                break
            data = r.json()
            titles = [m["title"] for m in data.get("query", {}).get("categorymembers", [])]
            for start in range(0, len(titles), 20):
                try:
                    info = client.get("https://en.wikipedia.org/w/api.php", params={
                        "action": "query", "prop": "extlinks", "titles": "|".join(titles[start:start + 20]),
                        "ellimit": "20", "format": "json", "redirects": "1",
                    }, timeout=30)
                except httpx.HTTPError:
                    continue
                if info.status_code != 200:
                    continue
                for page in info.json().get("query", {}).get("pages", {}).values():
                        links = [l.get("*") or l.get("url") or "" for l in page.get("extlinks") or []]
                        hosts = []
                        for u in links:
                            root = roots_of(u if u.startswith("http") else "https://" + u)
                            if root:
                                hosts.append(root)
                        if hosts:
                            out.append({"name": page.get("title") or titles[0], "category": cat.split(":", 1)[-1].replace("_", " "),
                                        "tier": "medium", "domains": hosts[:4], "url": None,
                                        "source": f"wikipedia:{cat} (API {db.now()[:10]})"})
            cm = (data.get("continue") or {}).get("cmcontinue")
            if not cm:
                break
            time.sleep(0.3)
    print(f"[public] wikipedia rows {len(out)}", flush=True)
    return out


def wikidata(client):
    query = """
    SELECT ?item ?itemLabel ?site WHERE {
      ?item wdt:P17 wd:Q851 .
      ?item wdt:P856 ?site .
      ?item wdt:P31/wdt:P279* ?class .
      VALUES ?class { wd:Q507619 wd:Q180846 wd:Q738958 wd:Q161726 wd:Q2001305 }
      SERVICE wikibase:label { bd:serviceParam wikibase:language "en,ar". }
    } LIMIT 400
    """
    try:
        r = client.get("https://query.wikidata.org/sparql", params={"query": query, "format": "json"},
                       headers={**UA, "Accept": "application/sparql-results+json"}, timeout=50)
    except httpx.HTTPError as e:
        print("[public] wikidata failed", type(e).__name__, flush=True)
        return []
    if r.status_code != 200:
        print("[public] wikidata", r.status_code, flush=True)
        return []
    out = []
    for b in r.json().get("results", {}).get("bindings", []):
        site = b.get("site", {}).get("value") or ""
        root = roots_of(site)
        if not root:
            continue
        qid = (b.get("item", {}).get("value") or "").rsplit("/", 1)[-1]
        out.append({"name": b.get("itemLabel", {}).get("value") or root, "category": "Retail",
                    "tier": "medium", "domains": [root], "url": site,
                    "source": f"wikidata:{qid} retail-chain (SPARQL {db.now()[:10]})"})
    print(f"[public] wikidata rows {len(out)}", flush=True)
    return out


def itunes_seller(client, term):
    """Return (root, sellerUrl, source) when a Saudi shopping app's name matches the term."""
    try:
        r = client.get("https://itunes.apple.com/search", params={"term": term, "country": "sa", "entity": "software", "limit": 5}, timeout=30)
    except httpx.HTTPError:
        return None
    time.sleep(3.1)
    if r.status_code != 200:
        return None
    want = norm_name(term)
    if len(want) < 3:
        return None
    for app in r.json().get("results") or []:
        if app.get("primaryGenreName") not in {"Shopping", "Food & Drink", "Lifestyle"}:
            continue
        if want not in norm_name(app.get("trackName") or "") and want not in norm_name(app.get("sellerName") or ""):
            continue
        root = roots_of(app.get("sellerUrl") or "")
        if root:
            return root, app["sellerUrl"], f"appstore:{app.get('trackId')} sellerUrl for '{term[:40]}'"
    return None


def appstore(client, limit=80):
    feeds = [
        "https://itunes.apple.com/sa/rss/topfreeapplications/limit=100/genre=6024/json",
        "https://itunes.apple.com/sa/rss/toppaidapplications/limit=50/genre=6024/json",
    ]
    ids = []
    for feed in feeds:
        r = get(client, feed)
        if r is None or r.status_code != 200:
            print("[public] app store feed failed", feed, flush=True)
            continue
        try:
            entries = r.json()["feed"].get("entry") or []
        except ValueError:
            continue
        if isinstance(entries, dict):
            entries = [entries]
        for e in entries:
            iid = (e.get("id") or {}).get("attributes", {}).get("im:id")
            name = ((e.get("im:name") or {}).get("label")) or ""
            if iid:
                ids.append((iid, name))
    print(f"[public] app store chart apps {len(ids)}", flush=True)
    out = []
    for iid, chart_name in ids[:limit]:
        try:
            r = client.get("https://itunes.apple.com/lookup", params={"id": iid, "country": "sa"}, timeout=30)
        except httpx.HTTPError:
            time.sleep(4)
            continue
        time.sleep(3.1)
        if r.status_code != 200:
            continue
        results = r.json().get("results") or []
        if not results:
            continue
        app = results[0]
        if app.get("primaryGenreName") not in {"Shopping", "Food & Drink"}:
            continue
        seller = app.get("sellerUrl") or ""
        root = roots_of(seller)
        if not root:
            continue
        out.append({"name": app.get("trackName") or chart_name, "category": "Shopping app",
                    "tier": "medium", "domains": [root], "url": seller,
                    "source": f"appstore-chart:{iid} {app.get('trackName','')[:40]} sellerUrl (country=sa, {db.now()[:10]})"})
    print(f"[public] app store seller urls {len(out)}", flush=True)
    return out


def html_portfolio(client, url, source, category="Agency portfolio"):
    r = get(client, url)
    if r is None or r.status_code != 200 or "just a moment" in r.text[:300].lower() or "vercel" in r.text[:1500].lower() and "checkpoint" in r.text[:1500].lower():
        print(f"[public] blocked or down {url} {None if r is None else r.status_code}", flush=True)
        return []
    domains = []
    for host in set(re.findall(r"\b(?:[a-z0-9-]+\.)+(?:sa|com\.sa|com|store|net)\b", r.text, re.I)):
        root = roots_of("https://" + host)
        if root and root != roots_of(url):
            domains.append(root)
    # also real hrefs
    for href in re.findall(r'href=["\'](https?://[^"\']+)', r.text, re.I):
        root = roots_of(href)
        if root and root != roots_of(url):
            domains.append(root)
    domains = list(dict.fromkeys(domains))
    print(f"[public] {url} domains {len(domains)}", flush=True)
    return [{"name": d, "category": category, "tier": "medium", "domains": [d], "url": f"https://{d}/",
             "source": f"{source} {url} (fetched {db.now()[:10]})"} for d in domains]


def salla_archive(client):
    try:
        r = client.get("https://web.archive.org/cdx/search/cdx", params={
            "url": "salla.com/en-sa/showcase", "output": "json", "fl": "timestamp,original,statuscode",
            "filter": "statuscode:200", "limit": "5",
        }, timeout=40)
    except httpx.HTTPError as e:
        print("[public] salla wayback cdx failed", type(e).__name__, flush=True)
        return []
    if r.status_code != 200 or not r.text.strip().startswith("["):
        print("[public] salla showcase not in wayback", r.status_code, flush=True)
        return []
    rows = r.json()[1:]
    if not rows:
        return []
    ts, original, _ = rows[-1]
    archived = f"https://web.archive.org/web/{ts}id_/{original}"
    page = get(client, archived, timeout=40)
    if page is None or page.status_code != 200:
        return []
    hrefs = re.findall(r'href=["\'](https?://[^"\']+)', page.text, re.I)
    out = []
    for href in hrefs:
        if "web.archive.org" in href or "salla.com" in href:
            # archived external links are rewritten; unwrap
            m = re.search(r"https?://web\.archive\.org/web/\d+(?:id_)?/(https?://.+)", href)
            if m:
                href = m.group(1)
        root = roots_of(href)
        if not root or "salla.com" in root:
            continue
        out.append({"name": root, "category": "Salla showcase", "tier": "medium", "domains": [root],
                    "url": f"https://{root}/", "source": f"salla-showcase-wayback:{ts} {archived}"})
    # unique
    uniq = {}
    for row in out:
        uniq[row["domains"][0]] = row
    print(f"[public] salla archive domains {len(uniq)}", flush=True)
    return list(uniq.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-appstore", action="store_true")
    ap.add_argument("--appstore-limit", type=int, default=60)
    a = ap.parse_args()
    con = reference.connect()
    db.register_source(con, "public_refs", "directory", "Public rankings, ministry evaluations, platform showcases, app charts, agency portfolios")
    index = existing_index(con)
    added = 0
    touched = 0
    with httpx.Client(headers=UA, follow_redirects=True, verify=False, timeout=30) as client:
        batches = [
            ("ministry", ministry(client, con)),
            ("zid", zid_stories(client)),
            ("wikipedia", wikipedia(client)),
            ("wikidata", wikidata(client)),
        ]
        pages = [
            ("https://skylightad.com/en/work/", "agency:skylight"),
            ("https://www.zalal.sa/en/zalal-work-examples", "agency:zalal"),
            ("https://toteel.com/blog/%d9%85%d8%aa%d8%a7%d8%ac%d8%b1-%d8%a5%d9%84%d9%83%d8%aa%d8%b1%d9%88%d9%86%d9%8a%d8%a9-%d8%b3%d8%b9%d9%88%d8%af%d9%8a%d8%a9/", "article:toteel"),
            ("https://www.ijjad.com/best-ecommerce-retail-brands-saudi-arabia-2026", "article:ijjad"),
            ("https://centers.cenomi.com/sa-en/malls/", "mall:cenomi"),
            ("https://play.google.com/store/apps/category/SHOPPING?hl=en&gl=SA", "google-play:shopping-sa"),
        ]
        for url, tag in pages:
            batches.append((tag, html_portfolio(client, url, tag)))
        batches.append(("salla-archive", salla_archive(client)))
        if not a.skip_appstore:
            batches.append(("appstore", appstore(client, a.appstore_limit)))
        for tag, rows in batches:
            n = 0
            for row in rows:
                # ministry rows may have no domain yet; try the app store only later. Skip domain-less here.
                if tag == "ministry" and not row["domains"]:
                    touched += 1
                    key = norm_name(row["name"])
                    if key in index:
                        attach_source(con, index[key][0], row["source"])
                        n += 1
                        continue
                    found = itunes_seller(client, row["name"])
                    if not found and row.get("legal") and row["legal"] != row["name"]:
                        found = itunes_seller(client, row["legal"].split("-")[0])
                    if found:
                        row["domains"] = [found[0]]
                        row["url"] = found[1]
                        row["source"] = row["source"] + " | " + found[2]
                    else:
                        con.execute(
                            "INSERT INTO sources VALUES (?,?,?,?,?,?) ON CONFLICT(source) DO UPDATE SET notes=excluded.notes, ts=excluded.ts",
                            (f"ministry-name:{key[:48]}", "name-only", row["name"][:80], "no-url", (row.get("legal") or "")[:180], db.now()),
                        )
                        print(f"[public] ministry no url: {row['name']}", flush=True)
                        continue
                ref_id, is_new = add_ref(con, index, row["name"], row["category"], row["tier"], row["domains"], row["source"], row.get("url"))
                if ref_id:
                    n += 1
                    added += int(is_new)
            con.commit()
            print(f"[public] {tag} applied {n} new_total={added}", flush=True)
    print(f"[public] done new_refs={added}", flush=True)


if __name__ == "__main__":
    main()
