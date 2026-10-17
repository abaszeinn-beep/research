#!/usr/bin/env bash
# Every 20 min: consistent DB snapshot + export + commit + push (survives VM restarts).
cd "$(dirname "$0")/.."
while true; do
  sleep "${CHECKPOINT_EVERY:-1200}"
  python3 -m market_ecom.snapshot || true
  python3 -m market_ecom.status > /dev/null 2>&1 || true
  timeout 900 python3 -m market_ecom.export || true
  cd /workspace
  git add markets/kuwait
  git commit -qm "Kuwait checkpoint: DB snapshot and directory export $(date -u +%H:%M)" || true
  for d in 4 8 16 32; do git push -q origin cursor/kuwait-ecommerce-directory-f1cc && break; sleep $d; done
  cd - > /dev/null
done
