# Partner Discovery Spec (shared by all research agents)

## Products
- **Autommerce OS**: AI operating system for ecommerce: catalog intelligence (AI product data entry/enrichment, supplier sheets), media automation (AI product imagery, galleries), store operations (AI store assistant, bulk catalog ops, sync, workflows), SEO growth (programmatic collections, topical authority). From ~$1,500/month. Targets established mid-to-large online retailers with substantial catalogs.
- **Persona AI**: AI personal shopping assistant, virtual fitting room, size/fit recommendations, styling, outfit bundling for FASHION / apparel / footwear / sportswear / luxury ecommerce. From ~$1,500/month + 3% attributed GMV.

## Goal
Find real agencies/consultancies that already serve ESTABLISHED ecommerce merchants and could refer/resell/co-sell/white-label these products.
Client quality > agency size > visibility. Boutique firms with recognizable ecommerce clients are welcome.

## The 19 approved categories (use these EXACT strings)
Group A (shared):
1. Ecommerce Website Development Agencies
2. Ecommerce Digital Marketing & Performance Agencies
3. Ecommerce Consulting & Strategy Firms
4. Ecommerce CRO & UX/UI Agencies
5. Ecommerce System Integration Companies
6. Ecommerce Technology & Digital Transformation Firms
Group B (Autommerce OS):
7. Ecommerce SEO Agencies & Consultants
8. Ecommerce PIM / ERP / Inventory Management Consultants
9. Ecommerce Product Catalog Management & Data Entry Agencies
10. Ecommerce Product Photography & Creative Production Agencies
11. Ecommerce Automation & Workflow Consulting Firms
12. Ecommerce Product Feed Management Specialists
Group C (Persona AI):
13. Fashion Ecommerce Consulting Firms
14. Fashion Ecommerce Digital Marketing Agencies
15. Fashion Ecommerce Technology Consultants
16. Fashion Ecommerce Personalization & Customer Experience Agencies
17. Fashion Ecommerce CRO & Conversion Optimization Agencies
18. Fashion Ecommerce Sizing, Fit & Returns Optimization Specialists
19. Fashion Ecommerce Merchandising & Styling Consultants

## Product Fit (exactly one)
- `Both`: verified access to established ecommerce merchants AND evidence of fashion/apparel/footwear/luxury clients.
- `Autommerce OS`: general ecommerce ops/catalog/SEO/infrastructure; no fashion client evidence.
- `Persona AI`: fashion-specialized (fashion marketing, fit, styling, fashion CX).
Never assign Both without fashion-client evidence.

## Qualification (ALL must hold)
1. Real, operating business with an identifiable official website (root domain, https://).
2. Offers services in an approved category with clear ECOMMERCE specialization (ecommerce service pages, ecommerce case studies, named online retail clients, Shopify/Adobe/BigCommerce/SFCC/Woo partner status, etc.).
3. Client portfolio indicates merchants plausibly able to pay ~$1,500/month (recognizable brands, established retailers, multi-brand stores, enterprise retail).
4. Market presence: HQ, active office, or verifiable ecommerce clients in that country. Do NOT add a firm to a country just because it says "we serve worldwide".
Exclude: generic agencies without ecommerce focus, brochure-site shops, micro-business-only shops, solo freelancers, inactive/closed firms, pure merchants/brands, pure competitors with no partnership angle (e.g. other virtual try-on SaaS vendors), unverified names. Platform SaaS vendors themselves (Shopify, Akeneo, etc.) are NOT partners; their implementation partners ARE.

## Research methods (use as many as possible)
- WebSearch with many query variants (English + Arabic for Middle East: e.g. "شركة تطوير متاجر إلكترونية الرياض", "وكالة تسويق متاجر إلكترونية الكويت", "تصميم متجر سلة", "شركاء زد", "Salla partners", "Zid partners").
- Agency directories: Clutch, GoodFirms, DesignRush, Sortlist, TechBehemoths, The Manifest, Agency Spotter, Top Interactive Agencies, etc. (search results / WebFetch pages; Clutch may block direct fetch - use search snippets and other directories).
- Platform partner directories: Shopify Partners (shopify.com/partners/directory), Adobe Solution Partners, BigCommerce partners, WooExperts, Salesforce Commerce Cloud partners, commercetools, VTEX, Salla/Zid (KSA), Magento, Shopware.
- Retail tech ecosystems: Akeneo, Salsify, Pimcore, inRiver, NetSuite, Odoo, Microsoft Dynamics, Klaviyo partners, Feedonomics, Channable, Productsup, Yotpo, Nosto, Dynamic Yield, Algolia partners etc. -> their certified agency partners in the market.
- Reverse research: well-known retailers in the market -> who built/marketed their ecommerce (case studies, credits, press).
- Articles/listicles ("top ecommerce agencies in X 2025/2026"), award lists, conference exhibitor/sponsor lists (Seamless Middle East, Shoptalk, eTail, etc.), associations.
- Use the shell (curl + python) where helpful to fetch pages that WebFetch can't, but respect blocks.
Keep doing discovery rounds until new searches yield few new qualified firms.

## Verification
For each candidate, check its official site (WebFetch or curl) or strong third-party evidence. Record ONE evidence URL and a short note (e.g. "Shopify Plus partner; clients: Ounass, Namshi"). If not verifiable -> exclude. Never fabricate names, URLs, clients.

## Output (write incrementally, save often)
Write a CSV (UTF-8, comma-separated, quote fields with commas) to the path given in your task, with header:
`Company Name,Website,Category,Product Fit,Country,Evidence URL,Evidence Note`
- Country is one of: Lebanon, Kuwait, UAE, Qatar, Saudi Arabia, United States.
- A company may have multiple rows only for different countries (each independently justified).
- One row per company per country; choose its most representative category.
- Order strongest-qualified first.
Append to the file every ~10-20 verified companies so work is never lost.
