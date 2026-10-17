# Kuwait ecommerce directory — progress log (UTC)

All times are 2026-10-17 UTC.

- **Start.** Read `saudi_ecom/RESUME.md` and `PROGRESS_LOG.md`. Copied the package to
  `markets/kuwait/market_ecom/` and moved every Saudi-specific value (currency, phone, cities, malls,
  locale paths/subdomains, payment and shipping providers, Accept-Language, App Store country, Tranco
  ccTLD) into `market.py` (`MARKET=kuwait`). Renamed the Saudi-named fields (`saudi_score` →
  `market_score`, etc.). Saudi code untouched.
- **Channel tests from this VM.** DuckDuckGo html works with a ~9 s gap. Bing returns a JS-only page.
  Mojeek, Ecosia and Qwant return 403, Brave 429, Startpage and Yandex show CAPTCHAs, Yahoo loops. No
  search API keys in the environment. Common Crawl index works with frequent 504s. Wayback CDX works per
  domain; TLD-wide `*.kw` needs authorisation and `com.kw` returned 503. iTunes Search (country=kw) and
  Wikidata SPARQL work. Tranco list 64VVX has only 74 .kw domains.
- **Reference universe.** 194 brand references (user brief, Alshaya / Landmark / Chalhoub / Apparel
  group portfolios, analyst seeds) plus 34 Tranco .kw refs plus 600 tenants from The Avenues' live
  directory. Other mall directories (360, Al Kout, Assima, …) failed to connect or were JS-only.
- **First commit** `e085c2e` (market config, Tranco probe, DDG search, reference seeds).
- **QA fixes** (commit `d02b545`): false positives kaspersky.com and itsordable.com blocklisted; a strong
  Kuwait signal is now required (locale tag alone is not enough); restaurant detection (menu sections,
  MNASATI/Ordable food platforms); generic Arabic place words removed; Shopify edge-IP politeness
  bucket; one sample product page is fetched when a sitemap is found; DNS fallback without `www`.
- **12:19–12:30 VM restart.** The working DB and uncommitted files were lost; code survived in git.
  Added DB auto-restore from the committed snapshot, the `scripts/checkpoint.sh` loop (snapshot +
  export + commit + push every 20 min), Tranco `--start`, Common Crawl collinfo retry. Reinstalled a
  local dnsmasq cache and Playwright. Reloaded references and restarted all workers (commit `1f081ce`).
- **12:45.** Browser verification loop started (Chromium, `ar-KW`, `Asia/Kuwait`, no CAPTCHA solving).
