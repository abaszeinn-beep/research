# Sonnet QA review of the Grok passes (2026-10-17, UTC)

Scope: independent re-check of the two passes by the untrusted model. Pass 1 = "Finish big retailer coverage" / "Resolve remaining stores" (`2bf92ba`..`23517ef`, plus the verification-rule changes in `verify.py` / `signals.py` / `secondary.py`). Pass 2 = "Medium-store full coverage round" (`cee59c6`..`1dabf41`). Everything was re-checked from the live public sites (robots.txt respected, no CAPTCHA/bot-wall/login bypass, no orders, no paid services). Reviewer tools: `scripts/qa_*.py`; corrections: `data/qa/sonnet_review_corrections.csv` (440 rows, applied to the DB).

## Headline

| Measure | Before | After |
|---|---|---|
| Verified unique stores (Master Directory rows) | 6,384 | **6,640** (6,580 live + 60 secondary evidence) |
| Corrections applied | | 440 |

Net +256: 334 stores added (324 wrongly rejected, including SHEIN, plus 10 rate-limited rows resolved), 79 wrongly verified stores removed (45 rejected, 24 unverified, 10 secondary-evidence stores), and a few duplicate merges.

## Error rates

Counts are over what I could judge from a live fetch (HTTP 429 / dead hosts that returned nothing are shown separately).

### Pass 1 (rules and majors)

| Population | n checked | Wrong | Error rate |
|---|---|---|---|
| Big-retailer decisions listed in the brief (17 inclusions) | 17 | 2 (Pull&Bear, Sivvi: evidence older than ~12 months, one current proof only) | 11.8% of inclusions |
| Big-retailer exclusions listed (9) | 9 | 0 | 0% |
| All 70 `verified_secondary_evidence` stores re-scored against the two-current-proofs rule (365 days, shopping app, real ordering control) | 70 | 10 (Philips, Haier, CarSwitch, Van Cleef, Sivvi, Pull&Bear, Boucheron, Versace, Barn's, Alo Yoga) | 14.3% |
| Reference exclusions of majors | 28 | 1 (SHEIN: `ar.shein.com` serves SAR prices and cart controls; the exclusion came from a geo-redirect seen from a US VM) | 3.6% |
| Stratified random sample (278 stores, status set by Grok rules or re-verified under them) | 278 (251 judgeable) | 18 | **7.2%** overall |
| ... rejected | 128 (119 judgeable) | 5 | 4.2% |
| ... verified | 95 (89 judgeable) | 13 | **14.6%** |
| ... unverified | 55 (42 judgeable) | 0 | 0% (but 3 well-known shops stayed unresolved only because of HTTP 429) |
| ... Salla / Zid / Shopify / WooCommerce / custom | 93 / 30 / 31 / 40 / 84 | 5 / 0 / 0 / 2 / 11 | 5.4% / 0% / 0% / 5.9% / **16.4%** |
| ... rows (re)verified in the last Grok rule round (>= 2026-10-16 19:40) vs earlier | 77 / 201 | 3 / 15 | 4.8% / 8.0% |

Census follow-ups that came out of the sample:

* **Salla `type=service`/`digital` rule.** Of 1,516 Salla stores rejected on product-type rules, 468 had shipped items flagged `is_require_shipping`; re-verifying them with the fixed rule recovered 324 stores (>= 21% of that rejected group). 45 of the first re-verification results were checked live: 5 of the proposed flips were still not goods (trading-course bundles, cooking/slaughter service, courses, device repair, reading programmes) and were left rejected; 40/45 were genuine shops (abayas, football shirts, flowers, dates, tracking devices).
* **Platform label `salesforce-commerce`** came from `sfcc` matched inside arbitrary strings. 34 stores carried that label and counted its "built-in cart" as purchase evidence; re-verification demoted about 24 non-stores. Three real stores (Bloomingdale's, Guess, TechStore) were kept after live inspection.
* **Custom / Wix / Odoo / OpenCart / Salesforce-labelled verified stores (285 re-fetched live):** 63 corrected (about 22%): corporate sites, recruiters, agencies, restaurants, marketplaces, a suspended site, an accounting firm with Wix cart markers. These are verified on weak signals ("N price strings" plus a generic add-to-cart marker); this is where the remaining risk sits.
* **Restaurant and charity rules:** 53 stores re-verified. 13 flipped to verified (restaurant-equipment suppliers, shipped-goods association shops, a fresh-meat grocer); 3 charity donation shops that the first fix wrongly readmitted were kept rejected.

### Pass 2 (medium-store round)

| Population | n | Wrong | Error rate |
|---|---|---|---|
| New verified stores from public sources (Zarafa, Dar Lena, Urjwan, Altamimi, Nutters, Aloqiylat, Mowkly, Lataef, Ghina Aghin, Ghareeb, Rakatt, Al Midhal, Jungle Store, Perfumes Blend, Crearoma, Black Box, Boutiqaat, MAGRABi) | 18 live + 2 secondary | 0 clear errors (Lataef's page is thin, kept; Black Box and Boutiqaat pass the two-proof, 365-day check) | 0% |
| Exclusions (Othaim, moodyul.com, rifaclothing.com) | 3 | 2 (moodyul.com and rifaclothing.com sell shipped goods typed `service` in Salla) | 66.7% |

## Corrected major-retailer decisions

* Pull&Bear (`pullandbear.com|sa`): verified_secondary_evidence -> unverified (Wayback product 2025-09-06 is 405 days old; the app alone is one proof).
* Sivvi (`sivvi.com|sa`): -> unverified (both proofs stale: Wayback 2025-03-06, app 2025-09-19; live fetch still times out).
* Philips Saudi (`philips.sa`) and Haier Saudi (`haier.com|sa`): -> rejected (brand catalogue with "where to buy", no SAR price/cart; the single sitemap proof is not purchase evidence).
* Van Cleef & Arpels: -> unverified (the Wayback proof is a home page; the second proof is a different app).
* CarSwitch: -> rejected (used-car marketplace). Trendyol.sa: -> rejected (multi-seller marketplace).
* Boucheron, Versace, Barn's, Alo Yoga: -> unverified (one proof only; live sites Access Denied or not Saudi).
* SHEIN: wrongly excluded -> verified on `ar.shein.com` (live SAR prices and cart controls; product pages sit behind a risk challenge, which was not touched).
* Kept as decided: Panda, Danube, BinDawood, Next, Ounass, 6th Street/AIVI, IBRAQ, Nayomi, Eyewa, Styli, American Eagle, Brands For Less (Wayback 2026-02-18, plus the app updated 2026-10-13), H&M (`sa.hm.com`), Sharaf DG, Jack & Jones; exclusions of Toys R Us, LC Waikiki, Obeikan, Danube Home, Nana, Othaim, STC, ACE, La Senza stand. Al-Dawaa and Floward are kept: both have a recent Wayback product page plus a Saudi app updated this month, but the apps are in the Health & Fitness / Lifestyle genre, so they would fail the stricter genre rule; flagged weak.

## Corrections by type (440)

| Type | Count |
|---|---|
| Wrong exclusion: shipped goods typed `service`/`digital` on Salla (incl. moodyul.com, rifaclothing.com) | 312 |
| Wrong exclusion: restaurant-equipment suppliers / charity-word or food-word false matches / shipped-goods association shops | 11 |
| Wrong exclusion: geo-redirect (SHEIN) | 1 |
| Wrong inclusion: non-store or weak evidence (corporate sites, services, recruiters, restaurants, cafes, agencies, suspended site) | 63 |
| Wrong inclusion: marketplace / aggregator (Syarah, CarSwitch, Trendyol, Kayak, Soum, Tradeling, Kaf freelance marketplace) | 7 |
| Wrong inclusion: no commerce (Philips, Haier) | 2 |
| Secondary evidence stale or insufficient (Sivvi, Pull&Bear, Van Cleef, Boucheron, Versace, Barn's, Alo Yoga) | 7 |
| Rate-limited (HTTP 429) rows retried politely: resolved to verified / rejected | 10 / 26 |
| Flip candidates reviewed and kept rejected (not in the CSV as changes) | 6 |

## Code review of the Grok rule changes and fixes (separate commits)

* `85c3e5d` Salla: `is_require_shipping` overrides `type=service/digital` (the rule that was rejecting abayas, mugs and gifts).
* `911d5b5` restaurant name rule no longer fires on equipment/supply names; `ebb9341` charity rule spares shipped-goods Salla catalogues of foundations; `146b3ab` `sfcc` matched on a word boundary; `faff40f` trendyol.sa, syarah.com, soum.sa, tradeling.com, kayak.sa added to the marketplace list; `0edfc5f` secondary evidence back to 365 days, genre limited to Shopping / Food & Drink, ordering control must be a real control (not a schema.org `Offer`).
* This review: charity product-name regex widened (iftar, feeding, winter-clothing, endowment items) so the shipped-goods exception no longer readmits donation catalogues (ata.sa); kitchen-equipment catalogues are no longer rejected for a `مطاعم` store name (kitland.com.sa).
* Remaining risks noted, not changed: (1) the generic "N price strings + add-to-cart marker" path verifies corporate sites on Wix/OpenCart (Wix ships cart markers in every template); (2) `is_require_shipping` is the Salla default, so a few service stores slip through (5 seen in 45); (3) 449 rows stay `rate_limited_http_429` and need a slower retry on another day; (4) Shopify and Zid strata showed 0 errors in 57 judged stores.

## Remaining concerns

1. About 22% of custom-platform verified stores needed correction; the unreviewed tail of Salla stores flipped by the shipped-goods rule (about 8% estimated wrong) was not hand-checked store by store.
2. 449 rate-limited rows (including Panda-style Vercel/Cloudflare hosts) are unresolved; 135 medium reference rows and 3 majors (Pull&Bear, Sivvi, Philips) remain unresolved.
3. Al-Dawaa and Floward rest on Wayback plus an app outside the stricter genre list; Messika was kept on a live page plus a Wayback product page.
4. No bot-wall was bypassed, so Boucheron/Versace/Floward-class sites could not be seen live from this network.
