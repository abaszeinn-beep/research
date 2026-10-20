# StoreLeads public "top stores" gap check (free data only)

Collected 20 Oct 2026 from public StoreLeads report pages (no login, no payment).
`storeleads_gap.csv`: one row per registrable domain (www stripped) per market.

## What is public
- `https://storeleads.app/reports/{platform}/{CC}/top-stores` shows only **5 domains** (ranked by StoreLeads worldwide rank), with name, rank and created date. Pagination (`/2`) returns the same 5. No traffic or sales figures are shown.
- More domains come from the city/region sub-pages linked from each platform/country page (5 each). All of these were crawled for every platform that has stores in the country (214 platform x country combinations, 7,989 rows -> 5,520 unique domains).
- Apparel-filtered tables are public only as **global** tables (`/reports/{platform}/category/Apparel[/subcategory]`, 10 stores each, no country). A country+apparel table is not public.

## Columns
`category`: `in_master` = in our master directory; `a` = missing, looks like a genuine physical-goods store; `b` = in our unverified/rejected/audit lists (reason given); `c` = not a fit (digital, service, food, marketplace, B2B, media, non-commercial, foreign ccTLD, parked, or no storefront evidence); `d` = unreachable/blocked/JS-only. `confidence` is `low` for "no storefront evidence" (c) and all d rows. The a/c/d split is an automated homepage heuristic, not manual review; spot-check of ~70 category-a rows suggests roughly 65-75% are real physical-goods stores.

## Results
| Market | SL domains | In our master | a | b | c | d | Top-5 country tables overlap |
|---|---|---|---|---|---|---|---|
| SA | 550 | 73 (13.3%) | 205 | 73 | 163 | 36 | 15.8% of 139 |
| AE | 518 | 63 (12.2%) | 83 | 66 | 230 | 76 | 11.6% of 207 |
| QA | 162 | 45 (27.8%) | 30 | 31 | 47 | 9 | 28.4% of 88 |
| KW | 176 | 29 (16.5%) | 63 | 14 | 50 | 20 | 20.2% of 89 |
| US | 4,114 | 275 (6.7%) | 452 | 254 | 2,795 | 338 | 7.3% of 409 |

Overlap by StoreLeads rank band (share in our master): SA <=50k 43.5% (n=23), 50-250k 35.6% (87); AE 25.7% (35), 22.6% (53); QA 50% (2), 61.9% (21); KW 44.4% (9), 39.1% (23); US 18.8% (1,309), 1.5% (810).

Fashion: global apparel tables (6,261 domains) overlap our fashion lists at SA 24, AE 5, QA 0, KW 3, US 98 domains. Proxy (homepage title/meta fashion keywords among the collected country domains): SA 4/16, AE 2/28, QA 3/11, KW 3/11, US 25/249 are in our fashion list.

## Caveats
- StoreLeads lists only the top-ranked stores per slice, so this tests coverage of the largest stores, not the long tail.
- Country is StoreLeads' "country of operation"; sub-domains such as `store.x.org.sa` collapse to the registrable domain.
- Homepage checks were one GET per domain; 403/JS-only sites are category d, not verified either way.
