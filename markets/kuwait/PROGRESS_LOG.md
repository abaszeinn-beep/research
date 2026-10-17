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
- **13:36 takeover (billing stop).** New worker resumed from checkpoint `e1eb2ff`/`45082dd`: reinstalled deps,
  dnsmasq cache and Chromium, reset 131 stale `in_progress` rows, ran `requeue` (245, later 266 rows),
  restarted Tranco, CC, DDG search, reference and verify workers. Tranco raw list was missing
  (git-ignored) and was re-downloaded (list 64VVX); Tranco probing reached rank ~18k only (resolver
  degradation, ~5 min per 2,000 ranks); DDG blocked again; `reference retry-none` hung and was killed.
- **~16:30 final.** `reference link`, `reference appstore`, `secondary` and `audit` run; snapshot and
  export refreshed: 353 verified (322 primary, 34 secondary incl. overlap per DB statuses), 927 unverified, 758 rejected.
- **16:44 follow-up (majors).** Probed each unresolved major live. Primary (manual_live): Abyat (/kw/en product JSON-LD KWD, products sitemap), X-cite (KD prices, pdp sitemap), Ooredoo online store (store.ooredoo.com.kw devices, cart), The Sultan Center (Chromium: KD prices, product pages, cart). Secondary (CC capture + App Store kw): Zara, H&M (kw.hm.com), Namshi, Babyshop. Excluded: Alshaya corporate (group), Apple Kuwait (no Apple online store in Kuwait, apple.com/kw/buy is a reseller page). Unresolved with specific reasons: Faces, Shein, Zain, stc, Pottery Barn, West Elm. Wayback CDX/availability went 503 and Common Crawl index API 504, limiting archive proofs.
- **Medium refs.** Ran secondary for all unresolved brand/mall refs, browser verification (250) and requeue of transient failures.
- **Reconciliation.** 353 = 320 primary + 33 secondary among non-duplicate candidates; the earlier 322+34 included verification rows of 3 duplicate candidates. Export now prints primary/secondary split.
- **Tranco.** Resumed with local dnsmasq and concurrency 12; ~70% of probes answered; reached rank ~38k.
- **18:50 final.** 414 verified (363 primary, 51 secondary).
- **18:40 follow-up 2.** Drained the 117 pending (verify workers + 3 requeue passes). Retried the 6 unresolved majors: Pottery Barn / West Elm (Alshaya, Magento Cloud on Fastly) serve a site-wide maintenance 503 on every path incl. robots.txt; Wayback/CC have no product captures in 12 months. Zain: shop channel is KWD but its headless catalog API returns a WAF landing page (not bypassed), Chromium body empty, one CC proof only. Faces: robots lists only faces.ae sitemaps. Shein, stc unchanged. All six remain unresolved with specific reasons (`manual.py`).
- **Deep recheck of 'excluded: no Kuwait storefront'** (`market_ecom/recheck_excluded.py`): robots sitemaps, hreflang, country-selector JSON, App Store seller URLs for 78-91 refs, plus manual GCC franchise path probes (Inditex brands, LEGO, Mango, Homebox, Redtag, Defacto, Swarovski, Dr Nutrition, IKEA, Jarir, Mothercare, Victoria's Secret, etc.); results went through verify / secondary. Caveat: resolver overload from parallel Tranco workers produced false ConnectErrors on the first pass; rerun with Tranco stopped.
- **Tranco.** Resumed 38,001 -> ~52,000 (single worker, concurrency 16; two workers at 20 each overloaded the resolver and were stopped). Rate ~2,000 ranks / 8 min, so rank 200k is not reachable in this session.
- **Final.** 436 verified (375 primary, 61 secondary); 917 unverified; 854 rejected.
