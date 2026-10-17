# United States Ecommerce Directory — pipeline, state and resume guide

Market-parameterized copy of the Saudi pipeline. Code: `markets/usa/mktecom/` (package `mktecom`; the market is
selected by `MKT_MARKET`, default `usa`; all US-specific rules live in `mktecom/market.py`). The Saudi code
(`saudi_ecom/`) and Saudi deliverables at the repo root are untouched. Run every command from `markets/usa/`.

Shared state: SQLite DB `data/usa_ecom.sqlite` (WAL; several worker processes write concurrently; override with
`MKT_ECOM_DB`). The committed snapshot is `data/usa_ecom.sqlite.gz` (backup → drop `cat_text` → VACUUM → gzip).
Every stage is resumable: screened Tranco domains are in `screen`, Common Crawl pages in `jobs`, candidates carry a
status (`pending` / `in_progress` / `verified` / `unverified` / `rejected` / `duplicate`).

## Resume from a fresh VM

```bash
cd markets/usa
gunzip -c data/usa_ecom.sqlite.gz > data/usa_ecom.sqlite          # restore the DB snapshot
pip install httpx tldextract openpyxl                              # same deps as saudi_ecom
mkdir -p data/raw && curl -L -o data/raw/tranco.zip https://tranco-list.eu/top-1m.csv.zip && (cd data/raw && unzip -o tranco.zip)
sqlite3 data/usa_ecom.sqlite "UPDATE candidates SET status='pending' WHERE status='in_progress'"

# workers (each in its own tmux session, log in logs/<name>.log)
scripts/start_worker.sh screen-0   mktecom.screen --start 1 --end 200000 --concurrency 25
scripts/start_worker.sh verifier-1 mktecom.verify --concurrency 24 --per-host 2 --worker v1 --where "AND priority>=0 AND key NOT LIKE '%.myshopify.com'"
scripts/start_worker.sh secondary  mktecom.secondary --limit 1500 --concurrency 3
scripts/start_worker.sh cc-discovery mktecom.discover_cc --concurrency 2
tmux new-session -d -s checkpoint "scripts/checkpoint.sh 1800"     # snapshot + commit + push every 30 min

# deliverables
python3 -m mktecom.reference audit      # tier summary + unresolved huge/large names
python3 -m mktecom.export               # xlsx + csv + evidence/unverified/reference CSVs
python3 -m mktecom.snapshot             # data/usa_ecom.sqlite.gz
```

Next ranges once 1–200k is screened: `mktecom.screen --start 200001 --end 1000000 --concurrency 25` (foreign
ccTLDs are skipped beyond rank 200k unless `--no-skip-foreign`).

Deferred lanes (start when Shopify stops answering HTTP 429, see "Rate limits"):
`mktecom.verify --concurrency 3 --per-host 1 --worker vslow --where "AND priority<0"` (rate-limited retries and
`*.myshopify.com` candidates, priority -1 / -5) and `scripts/requeue_slow.sh` (moves rate-limited/timeouts back to
the slow lane every 20 min, at most 4 attempts).

## Network budget (measured on this VM)

* The egress path tolerates bursts of ~3,000 new connections/min but degrades after sustained load above roughly
  400–500 new hosts/min: DNS lookups (resolver 10.0.0.2) and TCP connects start failing, which looks like dead
  sites. The safe combined setting is screener concurrency 25 (~430 domains/min, one GET each) + verifier
  concurrency 24 (~100 stores/min, 2–5 requests each) + secondary 3.
* The asyncio default executor (8 threads) serialized `getaddrinfo`; `verify.py` and `screen.py` install a
  64-thread executor.
* Health check: share of `screen` rows with `dns_not_resolved` / `fetch_failed:Connect*` per 5 minutes. When it
  jumps (e.g. 30% → 70%), stop workers, delete those rows from `screen` and requeue candidates whose last reason is
  `dns…` / `fetch_failed…` (commands in PROGRESS_LOG.md), then restart with lower concurrency.

## Rate limits and bot walls (nothing is bypassed)

* robots.txt is honoured (screen and verifier). 403/503/challenge pages → `unverified` with reason; no CAPTCHA,
  login, paywall or bot wall is circumvented; no orders are placed; no paid APIs are used.
* Shopify (and Cloudflare-fronted DTC sites) answer HTTP 429 to this Python client for most stores after sustained
  volume, while plain curl still gets 200. That is client-fingerprint filtering, so the pipeline does **not** switch
  clients to get around it: such stores stay `unverified (rate_limited_http_429)` and are retried later at low
  rate, or verified through secondary evidence.
* Bot-walled stores can become `verified_secondary_evidence` through `mktecom.secondary`: ≥2 independent evidence
  types, at least one storefront-level — Common Crawl product-page capture (WARC byte range) with USD prices and an
  ordering control and no foreign currency; robots-allowed live sitemap with product URLs; US App Store shopping app
  updated within 450 days (iTunes Search API, paced at ~17 calls/min); Wayback product capture as fallback.

## Components

| Module | Role |
|---|---|
| `market.py` | `Market` dataclass + USA config: states/metros, Canadian area codes vs US, toll-free codes, USD price/code regexes, US address (`ST 12345`), US shipping/legal terms (USPS, contiguous US, lower 48, sales tax, CCPA, Prop 65, Made in USA…), foreign geo/ccTLD/place patterns, marketplace exclusions and scope decisions |
| `common.py` | URL normalization, identity: shared-platform subdomains (`x.myshopify.com`, `x.mybigcommerce.com`, `x.square.site`, `x.company.site`, `x.bigcartel.com`, …) keep merchant identity; global domains' US storefront → `root|usa` (en-us / us paths) or `us.` host; else registrable domain |
| `db.py` | schema: candidates, candidate_sources, verifications (`market_score`, `market_evidence`), queries, jobs, sources, metrics, workers |
| `screen.py` | Tranco top-1M homepage screen (robots check + one GET); table `screen`; `store_like` rows queued (priority by rank, +1 with USD) |
| `reference.py` | reference universe: `load` (curated `mktecom/data/reference_brands.tsv` ~1.2k rows: NRF Top 100, Fortune 500 retailers, major DTC brands, global brands' US storefronts, B2B, controls; plus Wikidata retail companies/chains/brands with official websites, tiered by Tranco rank), `link` (queue as candidates, priority by tier), `audit` |
| `verify.py` | async verifier: myshopify `/meta.json` precheck, homepage, Shopify/Woo probes, listing page, sitemap probe, service/demo/charity/restaurant gates, physical-vs-SaaS gate, US relevance score; near-miss stores get one legal/contact page (privacy, terms, shipping, contact) fetched and rescored |
| `signals.py` | platform fingerprints, ecommerce markers, PHYSICAL/SAAS/DIGITAL/SERVICE vocab, US market signals, English category classifier |
| `secondary.py` | secondary evidence (above) |
| `discover_cc.py` | Common Crawl index harvesting of shared-platform hosts (`*.myshopify.com`, `*.mybigcommerce.com`, `*.square.site`, `*.company.site`, `*.bigcartel.com`, `*.shoplightspeed.com`; `.us` domains with `--patterns us`) |
| `export.py` | dedup (Shopify id / final key) + Excel/CSV export |
| `snapshot.py` | compressed DB snapshot |
| `check_urls.py` | ad-hoc QA: verify URLs without touching the DB |

Unadapted copies (still Saudi-oriented, not used for the USA run): `discover_search.py`, `discover_pages.py`,
`discover_wayback.py`, `queries.py`, `seeds.py`, `verify_browser.py`, `status.py`, `monitor.py`.

## Verification decision (USA)

1. Fetch storefront (2 tries, no http fallback). DNS failure → rejected; 404/410 → rejected; 403/429/503/challenge →
   unverified. Parked/closed/coming-soon/demo → rejected.
2. Product evidence (storefront API products, product links, schema.org Product/Offer, price strings, product
   sitemap) **and** purchase evidence (add-to-cart / cart / checkout, or a commerce platform with built-in cart;
   WooCommerce only counts as a commerce platform when its Store API returns products).
3. Physical goods: Shopify `requires_shipping`; otherwise physical-goods vocabulary vs SaaS/digital vocabulary; or
   strong retail markup (≥20 add-to-cart markers, or ≥5 with ≥5 prices, or ≥50 sitemap product URLs). SaaS/media
   sites, digital-only, services, restaurants/meal delivery, charities and organisation sites are rejected or held
   for manual review.
4. US relevance: verified needs a strong signal — `.us`, US phone (area code not Canadian/toll-free), US street
   address / schema.org `addressCountry=US`, Shopify shop country US, en-US locale on a US path/subdomain, US-specific
   shipping/legal terms, USD code + en-US locale with no foreign indicator, or toll-free phone + US place + ≥3 USD
   prices with no foreign indicator — **and** score ≥4 (or ≥3.5 with a US address/phone and ≥2 USD prices).
   International stores (non-US Shopify country, foreign ccTLD) need USD plus US presence or US shipping terms.
   Redirect to a non-US storefront without US evidence → rejected.

## Scope decisions

* Excluded as marketplaces/aggregators (`market.py: marketplaces`): Amazon, eBay, Etsy, Temu, AliExpress, Wish,
  Poshmark, Mercari, OfferUp, craigslist, Facebook Marketplace, Depop, Grailed, StockX, GOAT, Reverb, Chairish,
  1stDibs, Faire (wholesale marketplace), Houzz, Groupon, Instacart/Shipt/DoorDash/Uber Eats (delivery aggregators),
  Farfetch, print-on-demand marketplaces (Zazzle, Redbubble, Society6, TeePublic, Spreadshirt…), Back Market,
  Discogs, AbeBooks, TCGplayer, auction sites, Rakuten (cashback), ticket/service marketplaces; Carvana/CarMax
  (vehicles) are excluded.
* Kept as retailers (first-party retail with own inventory even if they also host third-party sellers):
  Walmart.com, Target, Best Buy, Wayfair, Newegg, Overstock, Shein (own-brand cross-border retailer; its US
  storefront is `us.shein.com`), ThredUp and The RealReal (consignment retailers that own the listing and
  fulfilment), Big Cartel stores (each store is its own merchant).
* Canadian stores without US pricing/presence are excluded (Canadian area codes, CAD, provinces, postal codes count
  against US relevance).
* A global brand's dedicated US storefront (`brand.com/en-us/`, `us.brand.com`) counts as that brand's US store.
* LLM-known brands are seeds only (`reference_brands.tsv`); every directory row is live-verified or
  secondary-evidence verified.
* No AI subagents were used; parallelism came from separate tmux worker processes sharing the SQLite DB.
