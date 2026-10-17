#!/usr/bin/env bash
# Periodic checkpoint: compressed DB snapshot + commit + push (survives VM resets). Usage: scripts/checkpoint.sh [interval_s]
cd "$(dirname "$0")/.."
interval="${1:-1800}"
while true; do
  sleep "$interval"
  python3 -m mktecom.snapshot || continue
  cd /workspace
  git add markets/usa/data/*.gz markets/usa/mktecom markets/usa/scripts 2>/dev/null
  git commit -qm "USA checkpoint: DB snapshot $(date -u +%H:%MZ)" && \
    for d in 4 8 16 32; do git push -q -u origin cursor/usa-ecommerce-directory-fe40 && break; sleep $d; done
  cd - >/dev/null
done
