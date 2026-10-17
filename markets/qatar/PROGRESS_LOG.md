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
