#!/usr/bin/env bash
# Export deliverables + compressed DB snapshot, then commit and push (retries 4/8/16/32 s on network errors).
cd "$(dirname "$0")/.."
python3 -m mkt_ecom.export && python3 -m mkt_ecom.snapshot || exit 1
cd /workspace
git add markets/uae/UAE_Ecommerce_Master_Directory.xlsx markets/uae/UAE_Ecommerce_Master_Directory.csv \
        markets/uae/data/uae_ecom.sqlite.gz markets/uae/data/reference_universe.csv markets/uae/logs/progress_metrics.jsonl \
        markets/uae/mkt_ecom markets/uae/scripts markets/uae/*.md markets/uae/.gitignore 2>/dev/null
git commit -qm "${1:-UAE checkpoint: export and DB snapshot}" || exit 0
for d in 4 8 16 32; do git push -q -u origin cursor/uae-ecommerce-directory-73c6 && exit 0; sleep $d; done
