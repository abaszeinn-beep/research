# Progress log (UTC)

Automated metrics snapshots every 10 minutes: `logs/progress_metrics.jsonl`.

## 2026-10-16

* **11:27** Start. VM: 4 vCPU, 15 GB RAM, Python 3.12. No search API keys in environment.
* **11:30 Phase 1 — channel tests** (see RESUME.md table): Bing (cc=SA) works; DuckDuckGo html works for ~2 queries then challenge; DuckDuckGo lite works intermittently; Google JS-blocked; Brave 429; Mojeek 403; Yandex/Startpage CAPTCHA; Common Crawl CDX works (flaky 502s); crt.sh works but low yield (wildcard certs).
* **11:33** Probed storefront mechanics: Salla merchant pages `salla.sa/<slug>` are fetchable (salla.com marketing site is Cloudflare-blocked, irrelevant); Salla closed stores show `المتجر مغلق حالياً`; Salla storefront API `api.salla.dev/store/v1/products` (Store-Identifier header, the same call the storefront JS makes) returns product lists with product `type`; Zid lists products server-side on `/products/`; Shopify `/meta.json` exposes shop country/currency.
* **11:36** Common Crawl worker started (salla.sa prefix ×40 crawls, *.zid.store ×40, salla.store, *.sa ×3, *.myshopify.com ×3).
* **11:47** Async verifier v1 started (48 concurrent). First run hit Salla 429s at ~500 checks/min → added adaptive per-host throttling (salla.sa 3 concurrent, ≥0.35 s gap, Retry-After) and re-queued rate-limited items.
* **11:50** Search worker started (5,869 generated queries; Bing primary).
* **11:53** Seeds (~330 known retailers/brands' Saudi storefronts) loaded as candidates.
* **11:56** crt.sh + zid.sa showcase harvested (small yields). Headless-browser pass tested: Akamai/Cloudflare-protected retailers (Zara, H&M, Sephora, Home Centre, Centrepoint, Al-Dawaa, Golden Scent) still 403 from this VM — kept as Unverified (no bypass).
* **12:00** Second Common Crawl worker for `*.sa` and second verifier v2 (64 concurrent, non-Salla only) started; listicle expansion worker started.
* **12:05** QA sample of verified non-Salla `.sa` sites showed false positives (charities with donation carts, a sports club, an education site, Salla's own site) and category errors from Arabic substring matches. Fixed: Arabic word-boundary category matching, charity exclusion, organization-site → manual review, stricter custom-platform evidence, demo-store exclusion. Re-queued ~1,700 earlier decisions for re-verification under the new rules.
* **12:10** DuckDuckGo html switched to CAPTCHA; switched to DDG lite endpoint with long backoff; purged wrongly cached DDG queries.
