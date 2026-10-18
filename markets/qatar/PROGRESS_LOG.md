# Qatar ecommerce directory — progress log (UTC)

## 2026-10-17

- **~11:00** Read `saudi_ecom/RESUME.md` and `PROGRESS_LOG.md`; copied the pipeline to `markets/qatar/market_ecom/` and
  parameterized it by `MarketConfig` (`market.py`): QAR regexes (QAR, ر.ق, ريال قطري, QR next to digits), +974, .qa /
  .com.qa, Qatar paths and subdomains (/en-qa, /ar-qa, /qa-en, /qa, qa., qatar.), cities, malls, local payment and
  delivery words, marketplaces to exclude (Snoonu, Talabat, noon, Amazon, Qatar Living, Q-Sale, ...).
- New discovery modules: `discover_tranco` (ccTLD list, top-N homepage probe for Qatar hreflang/paths/subdomains and
  outbound .qa links), `discover_crtsh` (certificate transparency), `discover_malls` (mall tenant directories).
- Verifier changes: Shopify edge throttling bucket (all Shopify-hosted shops share one rate limit) with
  `meta.json`/`products.json` fallback on HTTP 429; market-relevance score with strong keys (ccTLD, Qatar locale,
  QAR store currency, QAR prices, +974 phone, Shopify shop country QA).
- **~12:00** Fixed a catastrophic-backtracking price regex (Tranco probe pinned at 100% CPU) and added a
  non-physical business rule (hosting/registrars, e-wallets, banks, insurance, IT services, travel, car rental...).
- **~12:20** VM re-provisioned: `/workspace` moved to the Saudi branch and the uncommitted Qatar DB was lost.
  Work continues in a git worktree at `/home/ubuntu/qatar`; lost edits re-applied and pushed. Discovery re-run from the
  committed code (Tranco ccTLD, crt.sh, mall tenants, DDG search, CC index).
- **~12:40** DNS outage under load: installed dnsmasq as a local cache; requeued candidates that failed with DNS,
  connect or timeout errors. The forward limit was raised to 600 after the cache itself started dropping queries.
- **~12:55** Wayback CDX came back online. TLD-wide and paged domain queries are refused, but a crafted resume key with
  `url=zzzzzzzz.qa` walks the whole `qa,` SURT keyspace; new `discover_wayback` enumerates registrable .qa domains
  with captures since 2025 (36 + 36 resumable slices).
- **~13:05** QA of the first 116 verified rows: added rules for parked registrar pages (Nameshield), theme demo
  content (lorem ipsum / Wix "I'm a product"), service businesses (fitness studios, business centres, surveying,
  engineering consultancies); classifieds Bab Qatar and Doha Ads and the global YesStyle site added to exclusions.
  `market_ecom/data/manual_review.tsv` records manual decisions and is applied on every export.
- **~13:15** First checkpoint with DB snapshot pushed. `secondary.py` generalized to QAR / Qatar App Store / Qatar
  storefront paths. Listicle harvesting switched from Bing (no results from this VM) to DuckDuckGo.
- **~13:20** Reference audit: 213 brand refs + 124 mall tenant refs + Tranco .qa + Wikidata. Corrected seed domains
  for brands whose real storefront differs (e.g. Al Fardan → alfardanfinejewellery.com, Fifty One East →
  51east.com.qa) — still verified live before inclusion. Started the secondary-evidence and headless-browser passes.

## Channel status from this VM

| Channel | Status |
|---|---|
| Tranco top-1M (list 64VVX) | works; only 170 .qa domains in the top 1M |
| Common Crawl CDX index | works but slow; frequent 504s and sizing failures |
| Wayback CDX | works intermittently (503 "Temporarily Offline" bursts); host walk via resume keys |
| crt.sh | `%.com.qa` and `%.net.qa` worked; `%.qa` times out / 502 |
| DuckDuckGo Lite | works with long block/back-off cycles |
| Bing | no organic results returned |
| Mojeek, Ecosia, Qwant | 403 |
| Brave | 429 |
| Startpage | unusable results |
| Apple iTunes Search (country=qa) | works |
| Wikidata SPARQL | companies query works; retail query times out |
| Paid search APIs | none configured; none purchased |

No AI subagents were used; parallelism comes from asyncio workers in separate tmux sessions sharing one SQLite (WAL) DB.

## 2026-10-17 (resumed after billing interruption)

- **13:38** Took over: restored env (dnsmasq, Tranco, DB snapshot), requeued in-progress/transient failures, restarted verifier, Tranco probe, Wayback host walk, DDG search.
- **14:00-14:30** Reference load/resolve, secondary-evidence pass, headless-browser pass (installed Chromium for Playwright).
- **14:50** Checkpoint pushed (452 verified). Wayback walk then added ~6.1k new .qa hosts; verifier drained them.
- **16:10** Wayback host walk finished; final secondary pass, reference link + audit. 16 major refs remain unresolved (below). Search engines: DDG mostly blocked (back-off cycles).
- Unresolved majors: Lulu Hypermarket, Carrefour Qatar, Al Meera, Monoprix Qatar, Jumbo Electronics Qatar, Max Fashion, Home Centre, Baladna, Salam Stores, Apple, IKEA Qatar, Zara, Bath & Body Works, Shein, Sephora, Al Fardan Jewellery (bot-walled/geo-redirected or lacking two independent current proofs).

## 2026-10-17 session 3 (coordinator follow-up: resolve unresolved majors first)

- **16:39** Fresh VM; restored DB from snapshot (queue was already drained: 1 pending), restarted verifier and the Tranco probe from its saved job state.
- **~17:00-17:50** Probed each unresolved major: live fetches, robots-allowed sitemaps, headless-browser renders, Wayback product-path CDX
  (`scripts/major_probe.py`), Qatar App Store. Added `manual_resolve.py` + `manual_resolutions.json`; audit now honours `ref_overrides`.
  Majors: 16 unresolved -> 3 unresolved (+1 new, Malabar), 13 resolved (IKEA, Al Meera, Salam Stores live-verified; Jumbo mapped to its
  online store JS.QA; Lulu, Home Centre, Zara, Sephora, Carrefour, Bath & Body Works secondary; Apple, Baladna, Al Fardan excluded with reasons).
- **~17:10-17:50** `scripts/batch_probe.py` over the medium/no-storefront brand refs: +2 live-verified (ACE Hardware Qatar, Huda Beauty),
  +8 secondary (Ourshopee, Pull&Bear, Bershka, Oysho, Massimo Dutti, Stradivarius, VogaCloset, Junaid Perfumes); 5 single-proof brands left unresolved with reasons.

## 2026-10-17 session 4 (big-brand re-check + Tranco top-200k completion)

- **18:30** Fresh VM again; restored from snapshot. Added `scripts/multi_probe.py` (hreflang alternates, selector links, robots.txt sitemaps with qa/qatar locale entries,
  Shopify /meta.json markets, host variants, Qatar App Store) and `scripts/batch_probe2.py` (Wayback product-path probes with extended Qatar patterns and GCC-operator host variants)
  over all brands marked "no Qatar storefront found" plus Monoprix, Max Fashion, Shein, Malabar. Results: Mango verified (secondary, shop.mango.com/qa), Al Majed Oud (qa.almajed4oud.com, hreflang) verified live;
  Samsung (qa path 404), Uniqlo (404), LG/Sony/H&M (403) show no Qatar store; Puma redirects to the US site. Exclusion reasons now list the methods used.
- Monoprix Qatar: `monoprix-qatar.com` found by host variant but the page is JS/captcha-gated; no second proof. Max Fashion: no current product captures or sitemap (403); app only. Shein: no Qatar-path storefront. Malabar: no Qatar product captures.
- **19:40-00:00** Tranco top-200k probe completed (ranks 1-200,000) in three CPU-bound shards (DNS-limited at ~11 domains/s); ~14.7k DNS/timeout failures from overloaded windows were requeued and re-probed (16 extra hits).
  Tranco hits verified under strict rules; 8 verified rows demoted by manual review (foreign-only locale/currency-selector-only, classifieds, resale marketplace, missing QAR pricing); one store name fixed.
- Browser pass on 261 Tranco Qatar-path candidates: 2 verified. Secondary (Wayback) pass on the same set was stopped after 16 targets (about 1.6 min each); remaining Tranco unverified Qatar-path candidates are listed in Unverified Candidates.

## Manual major acceptance (2026-10-18)

* Approved by the user: well-known major retailers left unresolved only because bot walls, captchas or geo-redirects stopped the two-proof rule are added with status `verified_manual_major` (sheet label: "Known major retailer – manually accepted"). Code: `market_ecom/manual_major.py`; the export adds a `Verification Status` column to the Master Directory and a count line in Research Coverage; the audit status is `in_directory_manual_major`.
* **Accepted (3):** Monoprix Qatar `https://www.monoprix.qa/` (Qatar App Store loyalty app 2026-03-31, Wayback 2026-02-14; captcha not bypassed), Max Fashion `https://www.maxfashion.com/qa/en/` (Qatar App Store app 2026-10-05, Wayback captures 2025; live 403), SHEIN `https://ar.shein.com/` (Middle East storefront serving GCC countries with QAR among its currencies, Qatar App Store app 2026-10-17; `shein.com` itself geo-redirects, `shein.qa` is an unrelated travel site).
* **Rejected (1):** Malabar Gold & Diamonds - the site has country storefronts for in, ae, uk and us only; Qatar pages are a physical store locator, `/qa/` returns HTTP 400, and the Qatar App Store listing (genre Lifestyle) does not prove a Qatar online store. Audit status `excluded`.
* Light checks only (plain requests, Wayback availability API, iTunes Search); no bot wall was bypassed.
* **Audit (major tier):** 22 primary, 17 secondary, 3 manually accepted, 13 excluded, 0 unresolved.
* **Master Directory: 678 -> 681 stores.** xlsx, csv and `data/qatar_ecom.sqlite.gz` regenerated.
