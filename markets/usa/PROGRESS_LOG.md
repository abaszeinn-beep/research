# USA Ecommerce Directory — progress log

Times are UTC (2026-10-17). Resume instructions are in `RESUME.md`.

## Session 1

* Generalized the Saudi pipeline into `markets/usa/mktecom` with a `Market` config (`market.py`); Saudi code and
  deliverables untouched. Rewrote identity rules, signals (USD, US vs Canadian area codes, US addresses, US
  shipping/legal terms, en-US locale), verifier decision, secondary evidence and exporter for the US.
* Channel tests from this VM: Tranco list download works; Common Crawl index works (CC-MAIN-2026-39 latest, frequent
  504s that need retries); Wayback CDX prefix queries time out (~120 s) so Wayback is only a short-timeout fallback;
  Wikidata SPARQL works; iTunes Search API works (~20 calls/min); Bing returns 200 but was not used; DuckDuckGo
  202, Mojeek 403, Brave 429; no search API keys are available (no paid services used).
* Reference universe: curated `reference_brands.tsv` (~1.2k: 69 huge, 239 large, 905 medium; NRF Top 100, Fortune
  500 retailers, DTC brands, global brands' US storefronts, B2B, plus Canadian/marketplace/defunct controls) +
  Wikidata retail companies/chains/brands (~2.6k with official websites) → ~3.8k reference rows, all queued for
  live verification.
* Tranco homepage screener started on ranks 1–200k.
* The VM reset once around 12:19 and lost the local DB; resumed from the pushed branch and added
  `scripts/checkpoint.sh` (snapshot + commit + push every 30 min).

## Session 2 (resumed after coordinator status check)

* 12:56 Exporter tested: 239 verified at that point. Committed reference/secondary/exporter code.
* 13:00 QA of non-verified reasons found false negatives among well-known US retailers whose homepages carry only
  `$` prices (Walgreens, Purple, Ethan Allen, Foot Locker, Rite Aid, SharkNinja). Fixes: near-miss stores get one
  legal/contact page (privacy/terms/shipping/contact link from the homepage) fetched and rescored; toll-free phone +
  US place + ≥3 USD prices with no foreign indicator counts as a strong US signal; score ≥3.5 is enough when a US
  street address/phone and ≥2 USD prices are present; ≥20 add-to-cart markers counts as retail markup. One new false
  positive found in testing (Kochava, ad-tech on WordPress) → WooCommerce counts as a commerce platform only when
  its Store API returns products. Canadian postal-code regex required a space (it matched hex colours like
  `C7C7C7`). Regression sample of 60 previous decisions: no logic regressions. 478 near-miss candidates requeued.
* 13:05 Shopify (and some Cloudflare-fronted DTC sites) answer HTTP 429 to the Python client for nearly every store,
  including `*.myshopify.com`, while plain curl gets 200. Treated as bot filtering: no client switching. Shopify
  candidates (incl. 12k `*.myshopify.com` from Common Crawl) deferred to priority -5; slow lane paused.
* 13:10 Network saturation diagnosed: with screener 60 + verifier 40, 60–75% of Tranco domains failed DNS/connect
  (live sites like langchain.com marked dead). Measured: bursts of ~3k connections/min are fine but sustained load
  above ~400–500 new hosts/min breaks DNS/TCP. Deleted 6,687 suspect `dead` screen rows for re-screening, requeued
  326 candidates with DNS/connect failures, restarted at screener 25 + verifier 24 (failures back to normal).
* 13:20 Secondary evidence: Common Crawl lookup now asks the index for product-like paths when the first page is
  only category/brand pages (Nordstrom case); iTunes calls paced (3.5 s) with retries (previous run hit
  `itunes_error`). Verified so far by secondary evidence: Home Depot, Lowe's, Chewy, Dollar General,
  Williams-Sonoma.

### Maintenance commands

```bash
# requeue verifier DNS/connect failures after a saturation episode
sqlite3 data/usa_ecom.sqlite "UPDATE candidates SET status='pending', priority=max(priority,4) WHERE status IN ('rejected','unverified') AND key IN (SELECT key FROM verifications WHERE reason LIKE 'dns%' OR reason LIKE 'fetch_failed%')"
# re-screen Tranco rows that failed on DNS/connect
sqlite3 data/usa_ecom.sqlite "DELETE FROM screen WHERE status='dead' AND (reason LIKE 'fetch_failed:Connect%' OR reason='dns_not_resolved' OR reason LIKE 'fetch_failed:ReadTimeout%')"
# retry secondary evidence for stores whose App Store lookup errored
sqlite3 data/usa_ecom.sqlite "DELETE FROM secondary_evidence WHERE verdict='insufficient_secondary_evidence' AND evidence LIKE '%itunes_error%'"
```

## Session 3 (takeover after billing interruption; 13:36-15:50Z)

* Restored the 13:01Z snapshot, restarted screener (1-200k), verifier, secondary, checkpoint. Screening reached ~rank 42k
  (~270 domains/min after the first hour); the remaining 42k-200k is NOT screened (resume with the commands in RESUME.md).
* Common Crawl index (index.commoncrawl.org) became unreachable from this VM (connection refused; data.commoncrawl.org
  still answers), so `discover_cc` crashed and CC product evidence returned nothing. Treated as a blocked channel.
* Secondary evidence: Wayback CDX prefix query for whole hosts times out, so `wayback_product` now tolerates a timeout and
  runs a second, product-path-filtered CDX query (120 s). Added e.g. LEGO, Tractor Supply, Camping World. Many big
  bot-walled retailers (Best Buy, Macy's, Kroger, Walgreens, Petco, ...) still have only the App Store proof (one type), so
  they stay unverified instead of being guessed.
* Export at 15:50Z: 703 verified (635 primary, 68 secondary), 5,848 unverified rows. Audit: huge 24 in directory / 13
  excluded / 32 unresolved; large 71 / 38 / 130.

## Session 4 (coordinator follow-up: huge/large coverage first; 15:51-18:46Z)

* VM was reset at the start (packages and DB lost): restored from snapshot, reinstalled deps, restarted workers.
* Live verifier: when a strong-retail homepage lacks US markers, up to 4 fixed pages (/store-locator, /stores, /privacy ...)
  are fetched and rescored. This did not change Costco/Albertsons/Safeway/Ulta (their pages are JS-heavy), so those were
  fixed through secondary evidence instead (see below). Sherwin-Williams was already verified after the legal-page fix.
* Secondary evidence now also uses: SEC EDGAR (latest 10-K <= 550 days old must mention the store domain next to
  e-commerce/website language and the United States; subsidiary aliases such as Marshalls/HomeGoods -> TJX, Ralphs/Fred
  Meyer -> Kroger), Google Play listing (US) linking to the store domain, and `live_storefront` (the live homepage showed
  products and purchase controls but lacked US signals). Verdict rule: >=2 independent proofs and (a storefront-level
  proof, or an SEC 10-K proof, or both Apple and Google app listings). Limitation: for global brands (Adidas, Zara, H&M)
  the app listings are not US-specific. `recompute_secondary.py` re-applies the rule to stored evidence.
* Reference-audit exclusions documented in code: Ross (stores only, rossstores.com is corporate), Trader Joe's (no online
  ordering), airline lounges, hotels, Audible, FedEx Office, World Bank. TJX reference now points at tjmaxx.com.
* Mall REIT directories: Simon's robots/terms prohibit scraping (not used); Macerich/Westfield/Brookfield expose no
  accessible tenant directory; Shopify Plus case studies give 48 names without domains, BigCommerce showcase 404 (not
  ingested). Common Crawl index still unreachable.
* Tranco screen reached rank ~78.7k of 200k (about 240 domains/min). Export 18:46Z: 1,235 verified (911 primary,
  324 secondary); 7,543 unverified rows.

## Session 5 (tightened verdict, Playwright retry, full Tranco 1-200k; 18:47Z-~04:00Z)

* VM reset again at start; restored snapshot and reinstalled deps (httpx, tldextract, openpyxl, pandas, playwright+chromium).
* Verdict rule tightened: `verified_secondary_evidence` needs >=2 proofs AND at least one US-specific proof (US storefront
  product page via Common Crawl/Wayback with USD + ordering control, robots-allowed product sitemap, SEC 10-K, or a live
  storefront with US market score >= 2). Apple+Google app listings alone no longer count; they are only added as the second
  proof after a US-specific one. `recompute_secondary.py` re-applied the rule: 82 stores downgraded (incl. Adidas, Zara,
  Fanatics, H&M, Macy's, Bass Pro...).
* Playwright retry (`verify_browser.py`, en-US, 75 s timeouts, honours robots, waits out but never solves challenges) over
  716 unverified reference rows: 153 verified, 48 rejected, 515 still unverified (bot walls persist).
* Secondary evidence: Wayback retries with backoff plus generic-URL fallback; EDGAR aliases for public parents (Tapestry, VF,
  PVH, Nordstrom, Urban Outfitters, Deckers, Under Armour, Signet, Kroger banners, ...); URL overrides for Tesla/Sony/TI/Ford/
  Nintendo shop hosts; secondary run over all ~490 remaining reference targets.
* Exclusions added with reasons: GM, Toyota Motor NA, Honeywell (corporate sites, no store found).
* Tranco 1-200k screened. Diagnosed false `dead` rows (ConnectError under load: 27/40 sample alive): deleted ~66k connect/DNS
  failures and re-screened them with two screeners at concurrency 22 each; this recovered several thousand store-like domains.
* Export: 2,667 verified (2,256 primary, 411 secondary), 18,271 unverified rows. Audit (huge in/excl/unres 48/8/13; large
  146/30/63; medium 590/101/214).

## Final merge (USA master)

- Imported four shard CSVs (Shopify, Other platforms, Tranco 200k-500k, Tranco 500k-1M) via `git show origin/<branch>:<path>` into `shards/`; branches were not merged.
- `mktecom/merge_shards.py`: identity normalization, dedup, conflict resolution (hard rejection beats weak verify; otherwise strongest verified row). 99 hard-reject-over-weak-verify groups.
- `mktecom/rescreen.py` (homepage rules v2-v5 in `qa/rescreen_*.jsonl`), `mktecom/nonstore_filter.py` (adult, hosting/SaaS, nonprofit .org, attraction/media, foreign ccTLD), `mktecom/major_resolve.py` (major retailer decisions, `qa/major_decisions.jsonl`).
- Reproduce: `scripts/final_merge.sh <premerge.sqlite.gz>`, then `python3 -m mktecom.export` and `python3 -m mktecom.snapshot`.
- Final: 28,409 unique verified (27,878 primary, 531 secondary evidence); 48 export-level duplicates merged.
- Per-source final verified: main 2,364; Shopify 13,894; Other platforms 7,314; Tranco 200k-500k 1,001; Tranco 500k-1M 6,384 (overlaps counted in each).
- QA: rounds of ~150 stratified rows; non-Shopify error rate fell from ~24% to ~12.6% (round 4) to ~8% in the final round (110 live rows, 9 non-stores removed; other-platforms ~10%). Shopify QA was by name/evidence because live fetches are rate-limited (429).
- Major retailers: huge unresolved 13 -> 8 (Stop & Shop, Bass Pro, Fanatics, H&M US, Meijer, Zara US, JCPenney, REI); large unresolved ~63 -> 47. Remaining are bot-walled with no archived US USD page and only an app listing.
- Caveats: Common Crawl index unreachable; app listing cannot prove "US-only" so US-listing wording is used; .org/ccTLD rules are conservative; Square/Wix JS pages unjudgeable live; cannabis is a gray area.
