# Saudi Arabia Ecommerce Directory — pipeline, state and resume guide

All code is in `saudi_ecom/`. All shared state is in the SQLite DB `data/saudi_ecom.sqlite`
(WAL mode; several processes write to it concurrently). Every discovery/verification step is
resumable: completed Common Crawl index pages, search queries and harvested directory pages are
recorded in the `jobs` / `queries` tables and skipped on restart; candidates carry a status.

## Deliverables

| File | Contents |
|---|---|
| `Saudi_Arabia_Ecommerce_Master_Directory.xlsx` | Sheet1 *Master Directory* (Store Name, Root Domain / Storefront URL — verified, deduplicated), Sheet2 *Verification Evidence*, Sheet3 *Unverified Candidates* (unverified + rejected + still-pending, with reasons), Sheet4 *Research Coverage* |
| `Saudi_Arabia_Ecommerce_Master_Directory.csv` | CSV of the Master Directory sheet |
| `data/saudi_ecom.sqlite.gz` | gzip snapshot of the working DB (the live DB is `data/saudi_ecom.sqlite`) |
| `logs/progress_metrics.jsonl` | metrics snapshot every 10 min (discovery rate over time) |
| `PROGRESS_LOG.md` | narrative progress log + final report |

## Pipeline components

| Module | Role | Concurrency |
|---|---|---|
| `common.py` | URL normalization and store identity (`identity()`), platform/marketplace lists | – |
| `db.py` | schema: `candidates`, `candidate_sources`, `verifications`, `queries`, `jobs`, `sources`, `metrics`, `workers` | – |
| `discover_cc.py` | Common Crawl CDX index harvesting (`salla.sa/*`, `*.zid.store`, `*.sa`, `*.myshopify.com`, …) across many crawls | asyncio, 2–3 concurrent requests per process |
| `discover_search.py` + `queries.py` | ~5.9k generated Arabic/English queries (niches × templates × cities × platform operators), near-duplicate filtered; Bing (cc=SA) primary, DuckDuckGo html slow secondary | 1 request at a time per engine with throttling/backoff |
| `discover_pages.py` | outbound-link harvesting from showcase/directory sitemaps (e.g. zid.sa) and from listicle pages found via Bing | asyncio, 4–6 |
| `seeds.py` | ~330 known Saudi retailers / international brands' Saudi storefronts — **seeds only, all live-verified** | – |
| `verify.py` | async HTTP verifier (robots.txt respected, global semaphore + per-host semaphore and adaptive per-host gap, 429 Retry-After, bounded exponential backoff, 45 s per-request and 240 s per-candidate caps) | asyncio, 48–64 per process |
| `verify_browser.py` | Playwright (headless Chromium) second pass for JS-rendered / thin pages | 4 browser contexts |
| `signals.py` | parked/closed/demo detection, platform fingerprints, ecommerce + Saudi-relevance signals, category classifier | – |
| `export.py` | dedup pass + Excel/CSV export | – |
| `status.py`, `monitor.py` | metrics | – |

### Store identity / dedup rules
* Shared-platform storefronts keep the merchant-specific identity: `salla.sa/<slug>`, `<slug>.zid.store`, `<x>.myshopify.com`, etc. They are never collapsed into `salla.sa`.
* Independent sites collapse to the registrable domain (tldextract / PSL), e.g. `shop.brand.com.sa` → `brand.com.sa`.
* Dedicated Saudi storefronts of multi-country domains keep a Saudi-specific identity: `brand.com|sa` for `/en-sa/`, `/sa/en/`, `/ar_sa/`, `/saudi-en/` paths (all locale variants map to one key), and the host for `sa.` / `ksa.` subdomains.
* After verification each record stores `final_key` (identity of the URL after redirects). Export groups verified records by Salla store id / Shopify myshopify domain / final key, so a `salla.sa/<slug>` that redirects to a custom domain is merged with that domain (custom domain kept). Different stores with similar names are not merged.

### Verification decision (per candidate, evidence URL + UTC timestamp stored)
1. Fetch storefront (follow redirects). DNS failure → rejected; 404/410 → rejected; 403/429/503 or bot challenge → **unverified** (no bypass attempted).
2. Parked/placeholder, platform "store closed / maintenance" (`المتجر مغلق`), "coming soon" (`ترقَّب إطلاق المتجر`), demo/test stores → rejected.
3. Platform probes (the same public endpoints the storefront's own JS uses): Salla storefront API product list (gives product `type`: physical `product` vs `digital`/`codes`/`service`/`booking`/`food`/`donating`), Shopify `/meta.json` (shop country, base currency) + `/products.json` (`requires_shipping`), WooCommerce Store API; otherwise product links, schema.org Product/Offer, listing page, sitemap product URLs.
4. Requires product evidence **and** purchase evidence (add-to-cart / cart / checkout markers or a commerce platform with built-in cart).
5. Exclusions: marketplaces/aggregators (noon, amazon.sa, haraj, opensooq, …), digital-only, services-only, restaurants/food-service (Salla product types are authoritative where available; text heuristics otherwise, applied only when product evidence is weak).
6. Saudi relevance score from combined signals: `.sa` TLD (not counting `salla.sa` itself), Saudi locale path/hreflang, SAR currency in store config, SAR/ر.س prices, +966/05x/9200 phones, Saudi VAT (15 digits 3…3), CR number, Maroof, Saudi city names, mada/SPL/SMSA/etc., Salla/Zid platform, Shopify shop country = SA. Verified needs score ≥ 4 **and** at least one strong signal; score 2–4 → unverified (weak); other currency only / non-SA Shopify country → rejected.

### Scope decisions
* **noon.com and amazon.sa are excluded** as multi-seller marketplaces (aggregators), per the brief. Other excluded aggregators are listed in `common.MARKETPLACE_ROOTS`.
* Retailers that run their own store but also host third-party sellers (e.g. Namshi, Jarir, Extra) are included as retailers.
* Stores selling both physical and some digital goods are included (note added); digital-only are rejected.

## Search channel test results (Phase 1, from this VM)
| Channel | Result |
|---|---|
| Bing HTML (`cc=SA&setlang=ar`) | **works**, ~10 results/page, used as primary engine |
| DuckDuckGo html/lite | works for ~2 queries then HTTP 202 "anomaly" block; used as slow secondary with long backoff |
| Google | blocked (JS-only "enablejs" interstitial) |
| Brave Search | HTTP 429 |
| Mojeek | HTTP 403 |
| Yandex, Startpage | CAPTCHA |
| searx.be | 200 but JSON API disabled |
| Common Crawl CDX (index.commoncrawl.org) | **works** (intermittent 502s, retried) — highest yield |
| crt.sh JSON | works, but Salla/Zid use wildcard certificates → very low yield |
| Wayback CDX | works but slow (24 s/request); not used |
| Search API keys in env | none present |

## How to resume

```bash
cd /workspace
pip install httpx selectolax beautifulsoup4 lxml tldextract pandas openpyxl playwright && python3 -m playwright install --with-deps chromium
# if starting from the compressed snapshot:
[ -f data/saudi_ecom.sqlite ] || gunzip -k data/saudi_ecom.sqlite.gz

# reset candidates stuck "in_progress" by a killed run (only when no verifier is running)
python3 -c "import sqlite3;c=sqlite3.connect('data/saudi_ecom.sqlite');c.execute(\"UPDATE candidates SET status='pending' WHERE status='in_progress'\");c.commit()"

# discovery (all resumable; completed jobs/queries are skipped)
scripts/start_worker.sh cc-discovery saudi_ecom.discover_cc --patterns salla.sa,zid.store,salla.store,sa,myshopify.com --concurrency 3
scripts/start_worker.sh search-discovery saudi_ecom.discover_search --engines bing,ddg
scripts/start_worker.sh listicles saudi_ecom.discover_pages --expand-queries saudi_ecom/data/listicle_queries.txt
python3 -m saudi_ecom.seeds

# verification (two processes: one includes Salla, one excludes Salla so the throttled salla.sa host doesn't starve others)
scripts/start_worker.sh verifier-1 saudi_ecom.verify --concurrency 48 --worker v1
scripts/start_worker.sh verifier-2 saudi_ecom.verify --concurrency 64 --worker v2 --where "\"AND coalesce(platform_hint,'')!='salla'\""
# browser pass for JS-rendered pages
scripts/start_worker.sh browser saudi_ecom.verify_browser --concurrency 4

# re-check rate-limited ones later
python3 -c "import sqlite3;c=sqlite3.connect('data/saudi_ecom.sqlite');c.execute(\"UPDATE candidates SET status='pending' WHERE key IN (SELECT key FROM verifications WHERE reason LIKE 'rate_limited%' OR reason LIKE '%http_429%')\");c.commit()"

# metrics / export
python3 -m saudi_ecom.status
python3 -m saudi_ecom.export
gzip -kf data/saudi_ecom.sqlite   # compressed snapshot for git
```

Ad-hoc check of URLs without touching the DB: `python3 -m saudi_ecom.check_urls https://example.sa ...`
