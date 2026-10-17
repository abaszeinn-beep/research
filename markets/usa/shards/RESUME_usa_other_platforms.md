# usa_other_platforms: resume guide

Work DB (`work/usa_other_platforms.sqlite`) is git-ignored and is lost when the VM stops. Rebuild it from pushed files:

1. `pip install tldextract duckdb httpx aiohttp beautifulsoup4 lxml selectolax`
2. Tranco: `curl -L -o markets/usa/shards/work/tranco_top1m.csv.zip https://tranco-list.eu/top-1m.csv.zip`
3. `PYTHONPATH=. python3 -m markets.usa.shards.export --restore markets/usa/shards/usa_other_platforms*.csv` (screened keys)
4. `PYTHONPATH=. python3 -m markets.usa.shards.pending_queue --load` (pending queue, priority-ordered, already excludes screened keys)
   (alternative: re-run `cc_columnar` over CC-MAIN-2026-39/34/30, ~35 min, then `prioritize`)
5. `markets/usa/shards/run_verifiers.sh` (4 verifier processes) and `START=$(date +%s) markets/usa/shards/checkpoint.sh` (export + push every 30 min)
6. Before stopping: `export`, then `pending_queue` to refresh the queue file.

Priority (`prioritize.py`): platform tier (SFCC > Magento/BigCommerce > Shopware > Shift4Shop/Volusion > Woo/PrestaShop > Wix/Square) + custom-domain bonus + Tranco rank bonus + log(hits).
