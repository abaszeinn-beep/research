#!/usr/bin/env bash
# Export deliverables + compressed DB snapshot, commit and push (retries 4/8/16/32 s on network errors).
cd "$(dirname "$0")/.."
export ECOM_MARKET=${ECOM_MARKET:-qatar}
python3 -m market_ecom.reference audit >/dev/null 2>&1
python3 -m market_ecom.export && python3 -m market_ecom.snapshot
cd ../..
git add markets/qatar
git commit -qm "${1:-Qatar checkpoint: export + DB snapshot}" || true
for d in 0 4 8 16 32; do sleep $d; git push -q origin HEAD && { echo pushed; break; }; done
