# Qatar ecommerce directory — resume guide

Branch: `cursor/qatar-ecommerce-directory-9c58` (work dir `markets/qatar/`). The pipeline is a market-parameterized
copy of `saudi_ecom/` (Saudi code and deliverables are untouched); the market is chosen with `ECOM_MARKET=qatar`
(default). Market constants (currency regexes, phone, cities/malls, marketplaces to exclude, non-store roots) live in
`market_ecom/market.py`.

## Workspace note

If `/workspace` has been re-provisioned onto another branch, do not switch it; use a separate worktree:

```bash
git -C /workspace fetch origin cursor/qatar-ecommerce-directory-9c58
git -C /workspace worktree add /home/ubuntu/qatar cursor/qatar-ecommerce-directory-9c58   # once
cd /home/ubuntu/qatar/markets/qatar
```

## Restore the environment (idempotent)

```bash
cd markets/qatar
scripts/setup_env.sh          # pip deps, local dnsmasq DNS cache, Tranco list, gunzip data/qatar_ecom.sqlite.gz, Wikidata seeds
```

DNS matters: the VPC resolver (10.0.0.2) and the local cache drop queries when too many lookups for dead domains are
in flight. `setup_env.sh` runs dnsmasq on 127.0.0.1 with `--dns-forward-max=600`; keep the Tranco probe at
concurrency <= 35. Check with `dig +short example.org @127.0.0.1`.

## Workers (each in its own tmux session, logs in `logs/<name>.log`)

```bash
scripts/start_worker.sh verifier-1   market_ecom.verify --concurrency 32 --per-host 2 --worker v1 --reset-stale
scripts/start_worker.sh tranco-probe market_ecom.discover_tranco probe --top 200000 --concurrency 35   # resumable (jobs: tranco_probe)
scripts/start_worker.sh wayback      market_ecom.discover_wayback --streams 4 --since 2025            # resumable (jobs: wayback_hosts)
scripts/start_worker.sh cc-qa        market_ecom.discover_cc --patterns qa --concurrency 3            # resumable (jobs: ccpages/cc)
scripts/start_worker.sh crtsh        market_ecom.discover_crtsh                                       # resumable per query
scripts/start_worker.sh search-ddg   market_ecom.discover_search --engines ddg                        # resumable (queries table)
scripts/start_worker.sh listicles    market_ecom.discover_pages --expand-queries market_ecom/data/listicle_queries_qatar.txt --priority 4
scripts/start_worker.sh reference    market_ecom.reference resolve --kinds brand,mall --no-bing
scripts/start_worker.sh monitor      market_ecom.monitor 600
```

One-off steps:

```bash
python3 -m market_ecom.discover_tranco cctld        # all .qa domains in Tranco top-1M
python3 -m market_ecom.discover_malls               # mall tenant directories -> data/mall_tenants.tsv + candidates
python3 -m market_ecom.reference load               # reference_brands.tsv + Tranco .qa + Wikidata -> reference_stores
python3 -m market_ecom.reference load-malls         # mall tenants -> reference refs (kind=mall)
python3 -m market_ecom.reference retry-none         # re-check refs that found no storefront
python3 -m market_ecom.reference link               # link refs to verified keys
python3 -m market_ecom.secondary --limit 400        # secondary evidence (Wayback/CC product pages, sitemaps, App Store qa)
python3 -m market_ecom.verify_browser --limit 300   # headless-browser pass for JS-only storefronts (no challenge bypass)
python3 -m market_ecom.status                       # counts
```

## Checkpoint (export + snapshot + commit + push)

```bash
scripts/checkpoint.sh "Qatar checkpoint: <what changed>"
```

This runs the reference audit, `market_ecom.export` (xlsx + csv, applies `market_ecom/data/manual_review.tsv`),
`market_ecom.snapshot` (`data/qatar_ecom.sqlite.gz`, page text stripped), then commits and pushes with retries.

## Requeue after an outage

```bash
sqlite3 data/qatar_ecom.sqlite "UPDATE candidates SET status='pending' WHERE key IN (SELECT key FROM verifications
  WHERE reason LIKE 'dns_not_resolved%' OR reason LIKE 'fetch_failed:%' OR reason LIKE 'rate_limited%' OR reason LIKE 'verification_timeout%')"
```

## Manual / targeted reference resolutions (session 3)

- `market_ecom/data/manual_resolutions.json` holds hand-collected resolutions (verified primary, verified secondary with dated
  proofs, exclusions and specific-reason unresolved) for reference brands. `python3 -m market_ecom.manual_resolve` applies it
  idempotently (writes candidates/verifications, `reference_urls` via=manual, and `ref_overrides`); `reference audit` applies
  overrides last. Re-run it after restoring the DB and before the audit/export.
- `scripts/major_probe.py` (Wayback product-path CDX probe + QAR/cart check on the archived page) and `scripts/batch_probe.py`
  (7 Qatar path patterns per brand + Qatar App Store lookup, output `logs/batch_probe.jsonl`, resumable) produced the proofs.
  Host-wide CDX queries time out; always use product-path prefixes.
- After a VM re-provision the committed `data/qatar_ecom.sqlite.gz` is the source of truth (the plain `.sqlite` may be 0 bytes: delete it
  and re-run `scripts/setup_env.sh`).
- Chromium for the browser pass: `python3 -m playwright install chromium --with-deps`.
