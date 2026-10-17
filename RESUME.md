# Saudi Arabia Ecommerce Directory — pipeline, state and resume guide

All code is in `saudi_ecom/`. All shared state is in the SQLite DB `data/saudi_ecom.sqlite`
(WAL mode; several processes write to it concurrently). Every discovery/verification step is
resumable: completed Common Crawl index pages, search queries and harvested directory pages are
recorded in the `jobs` / `queries` tables and skipped on restart; candidates carry a status.

## Deliverables

| File | Contents |
|---|---|
| `Saudi_Arabia_Ecommerce_Master_Directory.xlsx` | *Master Directory* (verified, deduplicated), *Verification Evidence*, *Unverified Candidates*, *Major Retailer Coverage Audit*, *Research Coverage* |
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
| `reference.py` | reference universe of big/medium Saudi online stores (`reference_stores`, `reference_urls`): `load` (brand TSV + Tranco `.sa` + Wikidata), `load-malls`, `resolve` (Saudi URL variants live, Wayback CDX for blocked), `retry-none`, `appstore` (Saudi App Store `sellerUrl` domains), `link` (queue as candidates), `audit` (coverage status per reference store) | resolve: 32 refs in parallel |
| `secondary.py` | evidence for bot-walled / JS-only storefronts without bypassing anything: Wayback + Common Crawl product captures with SAR prices and ordering control (≤180 days), robots-allowed sitemaps, Saudi App Store shopping app (≤365 days). ≥2 independent evidence types incl. ≥1 storefront-level → `verified_secondary_evidence` | 10 targets in parallel |
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
7. Later rules from QA rounds: `*.myshopify.com` candidates are pre-checked with `/meta.json` (country ≠ SA and currency ≠ SAR → rejected in one request; otherwise the store's own domain is fetched instead of the throttled myshopify host); a redirect to a non-Saudi geo storefront (`us.`, `/en-ae/`, …) without SAR/`.sa`/VAT evidence → rejected; WooCommerce catalogs whose permalinks are mostly `/service/`, `/الخدمة/`, booking or course paths → rejected as services; agencies, clinics, consultancies, software developers, schools and similar organisation names → unverified (manual review); Zid stores with ≤3 products whose names look like services/digital goods → unverified (manual review); generic platforms (custom, Wix, Odoo, WooCommerce without Store API products) need add-to-cart markers plus strong product evidence.

### Scope decisions
* **noon.com and amazon.sa are excluded** as multi-seller marketplaces (aggregators), per the brief. Other excluded aggregators are listed in `common.MARKETPLACE_ROOTS`.
* Retailers that run their own store but also host third-party sellers (e.g. Namshi, Jarir, Extra) are included as retailers.
* Stores selling both physical and some digital goods are included (note added); digital-only are rejected.
* Also excluded as marketplaces: Farfetch (multi-boutique), Trendyol, Temu, AliExpress, Ubuy/Desertcart (cross-border), Haraj/OpenSooq (classifieds), used-car marketplaces.
* `verified_secondary_evidence` (Status column) = live site behind a bot wall / JS-only, accepted on ≥2 independent evidence types, at least one storefront-level (archived product pages with SAR prices + ordering control, sitemap, indexed pages). Wayback lookups use the newest captures within 640 days (widened from 180; the capture date is stored). A Saudi App Store shopping app counts when it was updated within 450 days (widened from 365; the listing date is stored). Evidence URLs + dates are in the Verification Evidence sheet. No CAPTCHA or bot wall was bypassed. Sitemap indexes are followed (including `.xml.gz`); a child sitemap counts when its name says "product" (the substring "item" inside "sitemaps" does not). Inditex product URLs ending in `-l` plus digits count as product pages.
* 6th Street's Saudi storefront now redirects to AIVI (`en-sa.aivi.com`). Danube grocery is `danube.sa` (BinDawood); Danube Home's country sites are UAE/Qatar/Oman/Bahrain and `/sa` redirects to the UAE store, so it is excluded. STC's public site had no device shop (excluded as no online ordering). ACE's resolving storefront is the UAE site; `ace-ksa.com` does not resolve. Ibrahim AlQurashi's Saudi shop is the Salla store IBRAQ (`saudi.ibraqperfumes.com`).
* A brand's Saudi storefront on a global domain (`brand.com/sa-en/`, `sa.brand.com`) counts as that brand's Saudi store; root-domain geo-redirects seen from this US-based VM are not treated as proof of absence.
* H&M's Saudi shop is `sa.hm.com` (Alshaya), not `www2.hm.com/en_sa`. Sharaf DG Saudi is `saudi.sharafdg.com`.  Brands For Less is `brandsforless.com/en-sa`. Pull&Bear is `pullandbear.com/sa`. Sivvi is `sivvi.com/saudi-en`. Toys R Us (`toysrus.com.sa`) no longer resolves. LC Waikiki's site states it is non-transactional. Obeikan's public site is corporate and `obeikan.store` does not connect. Jack & Jones Saudi is `jackjones.com/ar-sa` (verified live).
* No AI subagents were used: the Task tool was not available in this environment, so parallelism came from separate tmux worker processes sharing the SQLite DB.

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
| Wayback CDX | works but slow (24 s/request); prefix queries used for Saudi-path resolution and secondary evidence; domain-wide filtered queries time out |
| Bing HTML (re-tested 2026-10-16) | **degraded**: returns unrelated results (calculator sites) to this IP — no longer used |
| DuckDuckGo html (re-tested 2026-10-16) | HTTP 202 anomaly page on the first query |
| iTunes Search API (country=sa) | works (~20 req/min); used for App Store evidence and `sellerUrl` domain discovery |
| Search API keys in env | none present |

## Coverage round (2026-10-17)

Continued on the live DB. Did not rebuild the pipeline and did not finish a local Tranco top-200k screen (four shard agents own that merge).

| Channel | This round |
|---|---|
| Tranco list 64VVX (`data/raw/tranco_latest.csv`, not the older `data/raw/tranco.csv`) | Partial. `jobs.kind=tranco_screen`: 6,330 done, 2,285 transient retry. Five Saudi-storefront hits, all already verified (mi.com/sa, nike.sa, lg.com/sa, marksandspencer.sa, nespresso.com/sa). Local screener is stopped. |
| Ministry of Commerce e-commerce PDFs (`mc.gov.sa/.../esv/N.pdf`, 97 files) | Works (pymupdf + NFKC). 13 storefronts became reference rows; 82 scorecards had a legal name and no URL (`sources` `ministry-name:*`, status `no-url`). |
| Zid success stories | Works. Merchant names are the alt/children intersection. Official host only via App Store `sellerUrl` or a homepage that contains the brand. 7 rows. |
| Wikipedia category API / Wikidata SPARQL | APIs work. Extlinks and the broad class filter also return news, banks, and non-retailers. Kept rows are Saudi hosts only; a re-run now inserts `.sa` / `.com.sa` hosts only. |
| SkyLight portfolio `skylightad.com/en/work/` | Works. 16 client homepages. |
| Saudi App Store shopping chart `sellerUrl` | Works. 7 new seller sites. |
| Salla showcase, Zalal portfolio, Cenomi malls, Google Play category HTML | Salla is Cloudflare "Just a moment"; Zalal did not load; Cenomi returned page chrome, not tenants; Play HTML has no seller URLs. Not bypassed. |
| Bing / DuckDuckGo / Mojeek / Brave | Bing answers with unrelated hosts (those pending rows were deleted). DDG anomaly block, Mojeek 403, Brave 429. |
| Common Crawl CDX | `collinfo.json` listed 128 crawls (latest `CC-MAIN-2026-39`) once, then the index TLS connection failed (`SSL_ERROR_SYSCALL`) and one query returned HTTP 504. `data.commoncrawl.org` still serves the path lists (900 columnar parts for that crawl). No new CC candidates this round. `CC-MAIN-2026-39` `.sa` harvest was already done in session 4. |

New modules: `saudi_ecom/discover_tranco.py`, `discover_public.py`, `discover_cc_markers.py`, `discover_search_retry.py`. Portfolio scraping reads homepage links only, so a re-run does not ingest CDN and news hosts from article HTML.

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

# verification: one process per platform queue, because each platform has its own rate-limit bucket and a
# shared queue lets a throttled platform hold every concurrency slot.
scripts/start_worker.sh verifier-1 saudi_ecom.verify --concurrency 24 --per-host 2 --worker v1 --where "\"AND platform_hint IN ('salla','shopify') AND priority>=0\""
scripts/start_worker.sh verifier-2 saudi_ecom.verify --concurrency 48 --per-host 2 --worker v2 --where "\"AND coalesce(platform_hint,'') NOT IN ('salla','zid','shopify') AND priority>=0\""
scripts/start_worker.sh verifier-3 saudi_ecom.verify --concurrency 12 --per-host 2 --worker v3 --where "\"AND platform_hint='zid' AND priority>=0\""
# slow retry queue (priority<0): rate-limited / timed-out candidates (e.g. Hostinger CDN throttles per client IP)
scripts/start_worker.sh verifier-5 saudi_ecom.verify --concurrency 4 --per-host 1 --worker v5 --where "\"AND priority<0\""
# watchdog restarts any verifier whose log is stale >6 min (same filters as above)
tmux new-session -d -s watchdog "bash scripts/watchdog.sh 2>&1 | tee -a logs/watchdog.log"
# browser pass for JS-rendered pages
scripts/start_worker.sh browser saudi_ecom.verify_browser --concurrency 4 --limit 1500

# re-check rate-limited ones later (non-Salla go to the slow queue; Salla back to verifier-1)
python3 -c "import sqlite3;c=sqlite3.connect('data/saudi_ecom.sqlite');c.execute(\"UPDATE candidates SET status='pending', priority=CASE WHEN platform_hint IN ('salla','shopify') THEN 5 ELSE -1 END WHERE status='unverified' AND key IN (SELECT key FROM verifications WHERE reason LIKE 'rate_limited%')\");c.commit()"

# reference universe + major/medium coverage audit (order matters; every step is resumable)
python3 -m saudi_ecom.reference load            # reference_brands.tsv + franchise_groups.tsv + data/raw/tranco.csv + data/raw/wikidata_*.json
python3 -m saudi_ecom.reference load-malls      # saudi_ecom/data/mall_tenants.tsv (Kingdom Centre, Red Sea Mall)
scripts/start_worker.sh reference saudi_ecom.reference resolve --kinds brand,mall --no-bing
python3 -m saudi_ecom.reference retry-none      # Wayback CDX under Saudi paths for refs where nothing was found live
python3 -m saudi_ecom.reference link            # queue resolved URLs (priority 10) -> verifiers
python3 -m saudi_ecom.reference audit           # sets reference_stores.status
python3 -m saudi_ecom.reference appstore        # extra official domains for excluded/unresolved refs, then resolve + link again
scripts/start_worker.sh secondary saudi_ecom.secondary --limit 1000 --concurrency 10   # unresolved refs (bot walls / JS)
python3 -m saudi_ecom.reference audit
# the export writes data/reference_universe.csv and the "Major Retailer Coverage Audit" sheet

# metrics / export
python3 -m saudi_ecom.status
python3 -m saudi_ecom.export
python3 -m saudi_ecom.snapshot   # consistent compressed snapshot for git (drops cached page text)

# coverage-round modules (resumable via jobs / reference_stores). Do not restart a full local
# Tranco top-200k screen while the shard agents are merging that list.
python3 -m saudi_ecom.discover_public --skip-appstore
python3 -m saudi_ecom.discover_cc_markers --rank-limit 2500 --concurrency 4 --platform-crawls 2
python3 -m saudi_ecom.verify --concurrency 12 --per-host 2 --worker cov --idle-exit 90 --where "AND (first_source LIKE 'public:%')"
python3 -m saudi_ecom.secondary --keys blackbox.com.sa,boutiqaat.com|sa   # explicit keys only; the default sweep takes every unresolved ref
```

Ad-hoc check of URLs without touching the DB: `python3 -m saudi_ecom.check_urls https://example.sa ...`
