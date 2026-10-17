# Kuwait ecommerce directory — how to resume

Branch: `cursor/kuwait-ecommerce-directory-f1cc`. Work directory: `markets/kuwait/`.
The pipeline is a market-parameterised copy of `saudi_ecom/` (package `market_ecom`, market chosen by
`MARKET=kuwait`, the default). The Saudi code and deliverables at the repo root are not touched.

## Deliverables

| File | What |
|---|---|
| `Kuwait_Ecommerce_Master_Directory.xlsx` | Sheets: Master Directory (Store Name, Root Domain / Storefront URL — verified only), Verification Evidence, Unverified Candidates, Research Coverage, Major Retailer Coverage Audit |
| `Kuwait_Ecommerce_Master_Directory.csv` | Master Directory as CSV |
| `data/kuwait_ecom.sqlite.gz` | Compressed DB snapshot (all candidates, verifications, evidence, sources, queries, jobs) |
| `data/reference_universe.csv` | Reference universe with tier, source and resolution |
| `data/coverage_gaps.txt` | Known gaps (rendered into the Research Coverage sheet) |
| `PROGRESS_LOG.md` | Timeline of the run |

## 1. Environment after a fresh VM / reboot

```bash
cd /workspace && git fetch origin cursor/kuwait-ecommerce-directory-f1cc && git checkout cursor/kuwait-ecommerce-directory-f1cc
pip install httpx tldextract pandas openpyxl playwright lxml   # if missing
python3 -m playwright install --with-deps chromium              # only for the browser pass

# Local DNS cache (the VM resolver drops lookups under ~30+ concurrent requests).
sudo apt-get install -y dnsmasq
sudo tee /etc/dnsmasq.d/kw.conf >/dev/null <<'EOF'
no-resolv
listen-address=127.0.0.1
bind-interfaces
all-servers
cache-size=100000
server=10.0.0.2
server=1.1.1.1
server=8.8.8.8
server=1.0.0.1
server=8.8.4.4
EOF
sudo cp /etc/resolv.conf /etc/resolv.conf.bak
sudo dnsmasq --conf-file=/etc/dnsmasq.d/kw.conf --user=root      # no systemd on the VM
printf 'nameserver 127.0.0.1\noptions timeout:2 attempts:3\n' | sudo tee /etc/resolv.conf
```

The DB (`data/kuwait_ecom.sqlite`) is git-ignored. `db.connect()` restores it automatically from
`data/kuwait_ecom.sqlite.gz` when it is missing, so no manual restore is needed.

## 2. Workers (each in its own tmux session, logs in `logs/<session>.log`)

```bash
cd /workspace/markets/kuwait
S=scripts/start_worker.sh
$S kw-tranco-a market_ecom.discover_tranco --start 1 --top 150000 --concurrency 32
$S kw-tranco-b market_ecom.discover_tranco --start 150001 --top 300000 --concurrency 32
$S kw-cc       market_ecom.discover_cc --patterns kw,ordable.com,zyda.com,expandcart.com --concurrency 2
$S kw-search   market_ecom.discover_search --engines ddg
$S kw-appstore market_ecom.discover_appstore
$S kw-reference market_ecom.reference resolve --kinds brand,mall --no-bing
$S kw-verify-1 market_ecom.verify --concurrency 32 --per-host 2 --worker v1 --where "AND coalesce(platform_hint,'') NOT IN ('shopify','salla','zid')"
$S kw-verify-2 market_ecom.verify --concurrency 8 --per-host 2 --worker v2 --where "AND platform_hint IN ('shopify','salla','zid')"
tmux -f /exec-daemon/tmux.portal.conf new-session -d -s kw-browser -c "$PWD" -- bash -lc \
  'while true; do python3 -m market_ecom.verify_browser --concurrency 3 --limit 600 2>&1 | tee -a logs/kw-browser.log; sleep 1500; done'
tmux -f /exec-daemon/tmux.portal.conf new-session -d -s kw-checkpoint -c "$PWD" -- bash -lc 'scripts/checkpoint.sh 2>&1 | tee -a logs/checkpoint.log'
```

Every discovery worker is resumable: Tranco probes checkpoint per 2,000-rank chunk (`jobs` kind
`tranco_probe`), Common Crawl pages are recorded in `jobs`, search and App Store terms are cached in
`queries`. Re-running a worker skips completed work.

Status: `python3 -m market_ecom.status`.

## 3. Finishing steps

```bash
cd /workspace/markets/kuwait
python3 -m market_ecom.reference retry-none
python3 -m market_ecom.reference link
python3 -m market_ecom.reference appstore
python3 -m market_ecom.secondary --limit 1000 --concurrency 6
python3 -m market_ecom.reference audit
python3 -m market_ecom.snapshot && python3 -m market_ecom.export
cd /workspace && git add markets/kuwait && git commit -m "Kuwait: export" && git push -u origin cursor/kuwait-ecommerce-directory-f1cc
```

To re-check transient failures (rate limits, DNS, timeouts), reset them to `new` and let the
verifiers pick them up:

```sql
UPDATE candidates SET status='new' WHERE status='unverified' AND key IN (
  SELECT key FROM verifications WHERE reason LIKE 'rate_limited%' OR reason LIKE 'fetch_failed:%');
```

## Verification rules (summary)

- Verified (`verified` / method http or browser): live storefront, physical products with product
  pages, a purchase path (cart/checkout or platform API), not a service/digital/restaurant/charity site,
  market score ≥ 4 including at least one strong Kuwait signal (.kw domain, KWD currency code, KWD prices,
  +965 phone, or Shopify shop country KW). A Kuwait locale tag on its own is not enough.
- `verified_secondary_evidence`: storefront is bot-walled or geo-redirected; at least two independent
  current proofs (e.g. App Store seller URL in the kw store, Kuwait locale sitemap/robots, archived
  product page with KWD prices).
- Excluded marketplaces/aggregators and non-store roots are listed in `market_ecom/common.py`
  (`MARKETPLACE_ROOTS`, `NON_STORE_ROOTS`).
