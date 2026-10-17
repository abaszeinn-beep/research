# UAE progress log (UTC)

Metrics snapshots every 10 minutes: `logs/progress_metrics.jsonl`.

## 2026-10-17

* **11:41** Start on branch `cursor/uae-ecommerce-directory-73c6` (based on the Saudi pipeline branch). Read the Saudi `RESUME.md` / `PROGRESS_LOG.md`.
* **11:45 Channel tests from this VM:** Bing returns unrelated results (same degradation as the Saudi run), DuckDuckGo html/lite "anomaly" page, Google JS interstitial, Brave 429, Mojeek 403, Ecosia 403, Yahoo 500, Qwant API 403, Startpage/Yandex redirects to challenge. Working: Tranco list download, Common Crawl CDX (intermittent 504), Wayback CDX, iTunes Search API (country=ae), Wikidata SPARQL. No search API keys in the environment.
* **11:50** Copied `saudi_ecom/` to `markets/uae/mkt_ecom/` and moved every market-specific constant into `mkt_ecom/market.py` (currency AED/د.إ/Dhs/درهم, +971 and local phone formats, TRN, trade licence/DED/free zone, emirates and districts, `.ae` ccTLD and non-store suffixes, `/en-ae` `/ae-en` `/ae/en` `/uae` paths and `ae.`/`uae.` subdomains, Emirates Post/Aramex/tabby/tamara, Shopify country AE, marketplaces noon/Amazon.ae/Dubizzle/…). The Saudi package and deliverables are untouched.
* **12:00** Verifier sanity check: IKEA `/ae/en`, Mumzworld, Danube Home verified; noon excluded as marketplace; Sharaf DG, Lulu are 403 bot walls (left for browser/secondary pass).
* **12:05** New discovery modules: `discover_tranco.py` (all `.ae` + market-named domains; homepage probe of the global top-200k for `-AE` hreflang / UAE locale links / brand `.ae` links; DNS probe of `ae.`/`uae.`/`en-ae.`/`ae-en.` subdomains with a wildcard control), `discover_appstore.py` (UAE App Store shopping apps → seller websites), Wikidata UAE organisations with websites (1,148), UAE reference brands TSV (319 rows + 208 GCC brands from the Saudi list re-resolved for the UAE).
* **12:10** The DNS probe saturated the VPC resolver (git push and fetches failed with "could not resolve host"); added a local dnsmasq cache forwarding to public resolvers (`scripts/setup_env.sh`).
* **12:19–12:30** The VM was rebooted and the working tree was reset. Code was safe (pushed at 12:12) but the un-snapshotted SQLite DB was lost. Re-ran setup and all discovery steps from scratch; added `scripts/checkpoint.sh` + a 30-minute checkpoint loop that commits the export and a compressed DB snapshot.
* **12:40** All DNS (VPC and public) timed out for about a minute: a network-level DNS rate limit triggered by the probe plus dnsmasq's `all-servers` fan-out. Removed `all-servers`, lowered DNS-probe concurrency to 15 and homepage-probe concurrency to 80; re-queued candidates that failed DNS/fetch during the outage.
