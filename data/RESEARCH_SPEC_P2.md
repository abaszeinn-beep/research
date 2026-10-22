# PHASE 2 PLAYBOOK: LISTICLE / ARTICLE / RANKING-DRIVEN DISCOVERY

Read /opt/cursor/artifacts/research/SPEC.md FIRST (products, 19 exact categories, product-fit rules, qualification and verification rules, CSV header). Everything there still applies and is STRICT. This playbook adds the discovery method for phase 2.

## Why phase 2
Phase 1 found ~930 companies mostly via partner directories and reverse research. Phase 2 must catch the companies that phase 1 missed by systematically harvesting every "best/top ecommerce <category> agencies in <place>" article, ranking, roundup, directory category page, award list and community thread for the assigned market and categories, then verifying each named company.

## Already-found companies (DO NOT re-add)
Final lists so far: /opt/cursor/artifacts/deliverables/Autommerce_Partners_<Country>.csv (Lebanon, Kuwait, UAE, Qatar, Saudi_Arabia, United_States). Before verifying any candidate, check whether its domain/name is already in the file for that country. A company already listed for ANOTHER country may still be added to YOUR country if it qualifies there independently (own office or named clients in your country).
Also avoid duplicating other phase-2 agents: before appending, skim /opt/cursor/artifacts/research/raw/p2_*.csv for the same country.

## THE LOOP (repeat until saturated)
1. QUERY GENERATION. For each assigned (market x category) generate many query variants and run them with WebSearch:
   - "best ecommerce SEO agencies in <market/city/state> 2026" and 2025, "top 10 / top 20 / top 50 ... ", "leading ... companies", "ranked", "list of ... agencies", "<category> agency <city>", "<category> consultants <market>", "who built <retailer> website", "agencies that work with <platform> in <market>", "<platform> partner <market>".
   - Platforms: Shopify/Shopify Plus, Magento/Adobe Commerce, BigCommerce, WooCommerce, Salesforce Commerce Cloud, commercetools, VTEX, Shopware, SAP Commerce, Salla, Zid, Odoo, NetSuite, Dynamics, Akeneo/Pimcore/Salsify/inRiver, Klaviyo, Feedonomics/Channable/Productsup, Google Shopping, Amazon.
   - Sub-geographies: every relevant city/state/emirate.
   - Synonyms: "ecommerce agency / online store developers / web store builders / ecommerce consultancy / digital commerce firm / DTC agency / retail technology partner".
   - For Middle East markets also run Arabic queries (e.g. "افضل شركات تصميم متاجر الكترونية في السعودية", "افضل شركة سيو للمتاجر الالكترونية", "افضل وكالة تسويق للمتاجر الالكترونية في الكويت", "شركات تصوير منتجات للمتاجر الالكترونية").
2. LISTICLE HARVEST. From search results open and READ the actual listicle/ranking pages (WebFetch; if blocked use curl with a browser user-agent; if Clutch/GoodFirms/DesignRush block you, use their search-engine snippets, cached/AMP versions, or other sites that republish the lists). Extract EVERY company named (not just the top 3). Also open page 2/3 of listicle series, "alternatives to <agency>" pages, "agencies like <agency>", "<directory> category page" pages, agency award lists (Shopify/Klaviyo/Adobe/BigCommerce partner awards, Inc. 5000 ecommerce agencies, Deloitte Fast 500, regional awards), conference sponsor/exhibitor/speaker lists, Reddit/Quora/Facebook-group/LinkedIn-post recommendations visible in search snippets, "clients" pages of retailers.
3. SNOWBALL. For each good listicle also search: "<company> competitors", "<company> alternatives", "agencies similar to <company>"; for each qualified company also open its case-study clients and awards to discover peers.
4. CANDIDATE TRIAGE. For each unique name not already listed: find the official site (never the directory profile), open services + case studies/clients + about/contact (office/country) pages. Apply SPEC.md qualification rules strictly: real operating business, clear ecommerce specialization in an approved category, named established merchant clients (not micro/small only), market presence in YOUR country, product fit by the SPEC rules (Both only with fashion/apparel/footwear/luxury client evidence). Check the site is alive (not expired/parked) and the company is not acquired/closed.
5. SOURCE LOG. Maintain /opt/cursor/artifacts/research/raw/p2_sources_<STREAMNAME>.md: one line per listicle/source read: URL | category/market | #companies named | #new qualified added. This lets us measure saturation.
6. SATURATION. Stop a (market x category) only after at least 15 distinct query variants AND 3 consecutive listicle/sources in a row that yield no new qualified company. Then move to the next category. Revisit categories with zero or few rows with different angles (platform-specific, city-specific, Arabic, snowball).
7. APPEND results to your output CSV every 5 verified companies (header: Company Name,Website,Category,Product Fit,Country,Evidence URL,Evidence Note). Quote fields containing commas. Website = root domain with https://. Country = exactly one of Lebanon, Kuwait, UAE, Qatar, Saudi Arabia, United States. Category = one exact approved string. Product Fit = Both / Autommerce OS / Persona AI.

## Rules reminders
- Never fabricate. Exclude unverified, freelancers, micro-business-only agencies, closed/acquired firms, SaaS vendors, pure merchants.
- A company that is in a listicle is NOT automatically qualified: listicles and directories are discovery sources only.
- Prefer breadth: every discovered name gets verified or consciously rejected. Keep a rejected list with reasons at /opt/cursor/artifacts/research/raw/p2_rejected_<STREAMNAME>.md (one line each: name | reason) so nobody re-checks them.
- Final reply format: rows added (by category and Product Fit), #sources read, #queries run, categories still thin, ideas for what else to try. Keep it concise.
