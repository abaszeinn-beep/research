# UAE Ecommerce Directory: pipeline, state and resume guide

Work directory: `markets/uae/`. Code: `markets/uae/mkt_ecom/` (market-parameterized copy of `saudi_ecom/`; the Saudi
package is unchanged). Market config: `mkt_ecom/market.py`, selected with `MARKET=uae` (default). Live DB:
`markets/uae/data/uae_ecom.sqlite` (WAL; several worker processes write concurrently). Committed snapshot:
`data/uae_ecom.sqlite.gz` (cached page text dropped).

## Deliverables (in `markets/uae/`)

| File | Contents |
|---|---|
| `UAE_Ecommerce_Master_Directory.xlsx` | Master Directory (Store Name, Root Domain / Storefront URL; verified only), Verification Evidence, Unverified Candidates, Research Coverage, Major Retailer Coverage Audit |
| `UAE_Ecommerce_Master_Directory.csv` | CSV of the Master Directory sheet |
| `data/uae_ecom.sqlite.gz` | compressed DB snapshot |
| `data/reference_universe.csv` | reference universe with coverage status per row |
| `logs/progress_metrics.jsonl` | metrics every 10 minutes |

## Generalization (what changed vs `saudi_ecom`)

* `market.py`: currency + price regexes (AED, د.إ, Dhs, درهم), phone (+971 strong; 05x/0x/600/800 local formats weak),
  TRN (15 digits starting with 1, keyword-bound), trade licence / DED / free zone, emirates + districts + malls,
  payment/shipping (Emirates Post, Aramex, tabby, tamara, Quiqup, …), `.ae` ccTLD and excluded suffixes
  (`.gov.ae`, `.ac.ae`, `.sch.ae`, `.mil.ae`), locale paths and subdomains, foreign-geo regex (Saudi and other GCC
  storefronts count as foreign), URL variants for reference resolution, marketplaces/aggregators, App Store country,
  Shopify country AE.
* `common.identity()`: dedicated UAE storefronts of multi-country domains keep a market key (`brand.com|ae` for
  `/en-ae/`, `/ae-en/`, `/ae/en/`, `/uae/` paths; host for `ae.`/`uae.` subdomains). Platform-hosted stores keep the
  merchant URL (`salla.sa/<slug>`, `<x>.myshopify.com`, `<x>.zid.store`, …).
* DB columns `market_score` / `market_evidence` (renamed from `saudi_*`).

## Scope decisions

* Excluded aggregators: noon, Amazon.ae (multi-seller marketplaces), Dubizzle (classifieds), InstaShop / Talabat / Careem /
  Deliveroo / El Grocer-style multi-store delivery apps, Desertcart / Ubuy (cross-border marketplaces), Farfetch
  (multi-boutique), car/property classifieds. Namshi is a single retailer and is included. Full list:
  `market.UAE["marketplaces"]`.
* Same verification rules as the Saudi run: product evidence + purchase evidence + market relevance score ≥ 4 with at
  least one strong signal (`.ae`, UAE locale, AED in store config, AED prices, +971 phone, TRN, Shopify country AE).
* Bot-walled/JS-only sites: headless browser (no challenge solving), then `secondary.py` (≥2 independent current
  evidence types incl. ≥1 storefront-level: Wayback/Common Crawl product page with AED price + ordering control,
  robots-allowed sitemap with UAE product URLs, UAE App Store shopping app) → `verified_secondary_evidence`.

## How to resume

```bash
cd /workspace/markets/uae
bash scripts/setup_env.sh                       # deps, Playwright, local dnsmasq cache (needed: VPC DNS rate-limits)
[ -f data/uae_ecom.sqlite ] || gunzip -k data/uae_ecom.sqlite.gz
mkdir -p data/raw logs && curl -sL https://tranco-list.eu/download/64VVX/1000000 | tr -d '\r' > data/raw/tranco.csv
# Wikidata (query in mkt_ecom/data/wikidata_uae.rq) -> data/raw/wikidata_uae_companies.json
curl -s -G https://query.wikidata.org/sparql --data-urlencode query@mkt_ecom/data/wikidata_uae.rq -H "Accept: application/sparql-results+json" \
  | python3 -c "import json,sys;json.dump(json.load(sys.stdin)['results']['bindings'],open('data/raw/wikidata_uae_companies.json','w'))"
# reset rows stuck in_progress (only when no verifier is running)
python3 -c "import sqlite3;c=sqlite3.connect('data/uae_ecom.sqlite');c.execute(\"UPDATE candidates SET status='pending' WHERE status='in_progress'\");c.commit()"

# discovery (resumable; finished jobs are skipped)
python3 -m mkt_ecom.discover_tranco local
scripts/start_worker.sh tranco-probe mkt_ecom.discover_tranco probe --top 200000 --concurrency 80
scripts/start_worker.sh tranco-dns   mkt_ecom.discover_tranco dns --top 200000 --concurrency 15 --chunk 5000   # keep low: DNS rate limit
scripts/start_worker.sh cc-ae        mkt_ecom.discover_cc --patterns ae --concurrency 3 --max-crawls 8
scripts/start_worker.sh wayback-ae   mkt_ecom.discover_wayback --patterns ae --since 2025 --page-lines 50000
scripts/start_worker.sh appstore     mkt_ecom.discover_appstore
python3 -m mkt_ecom.mall_tenants                # Dubai Mall, Mall of the Emirates, Wafi, Dubai Outlet Mall tenant lists

# reference universe + resolution
python3 -m mkt_ecom.reference load && python3 -m mkt_ecom.reference load-malls
scripts/start_worker.sh reference mkt_ecom.reference resolve --kinds brand,mall --no-bing
python3 -m mkt_ecom.reference retry-none && python3 -m mkt_ecom.reference link

# verification (one process per platform bucket) + watchdog + browser + secondary
scripts/start_worker.sh verifier-2 mkt_ecom.verify --concurrency 48 --per-host 2 --worker v2 --where "\"AND coalesce(platform_hint,'') NOT IN ('salla','zid','shopify') AND priority>=0\""
scripts/start_worker.sh verifier-1 mkt_ecom.verify --concurrency 12 --per-host 2 --worker v1 --where "\"AND coalesce(platform_hint,'') IN ('salla','zid','shopify') AND priority>=0\""
tmux new-session -d -s watchdog "bash scripts/watchdog.sh 2>&1 | tee -a logs/watchdog.log"
scripts/start_worker.sh browser   mkt_ecom.verify_browser --concurrency 4 --limit 3000
python3 -m mkt_ecom.reference audit && python3 -m mkt_ecom.reference appstore
scripts/start_worker.sh secondary mkt_ecom.secondary --limit 1500 --concurrency 6
python3 -m mkt_ecom.reference audit

# export + snapshot + commit/push
bash scripts/checkpoint.sh "UAE checkpoint"
```

Ad-hoc check without touching the DB: `python3 -m mkt_ecom.check_urls https://www.example.ae/`.

## State at end of follow-up (2026-10-17 ~23:00Z)

Pending queue drained (1 left). Majors: 45 in directory (22 primary, 23 secondary), 3 unresolved (Lulu Hypermarket, Dubai Duty Free, Joyalukkas), plus Emax, Lifestyle, Ajmal, Toys R Us UAE unresolved (bot-walled/JS) and 7 excluded with reason. New helper modules: `deep_check`, `wb_probe`, `wb_batch*.py`, `majors_resolve`, `secondary2` (see PROGRESS_LOG). Next: more secondary passes for medium/GCC refs (58 medium + 42 GCC unresolved), retry Wayback when archive.org is back, retry unverified (bot-walled) hosts later. `reference retry-none` is very slow; wrap in `timeout`.
