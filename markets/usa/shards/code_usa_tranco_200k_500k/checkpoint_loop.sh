#!/usr/bin/env bash
# Every 15 minutes: dump state, export CSV/summary, commit and push (retries with backoff on network errors).
cd "$(dirname "$0")"
while true; do
  sleep "${INTERVAL:-900}"
  python3 checkpoint.py save && python3 export.py
  cd /workspace
  git add markets/usa/shards/state_usa_tranco_200k_500k markets/usa/shards/usa_tranco_200k_500k*.csv markets/usa/shards/usa_tranco_200k_500k_summary.json markets/usa/shards/code_usa_tranco_200k_500k/*.py markets/usa/shards/code_usa_tranco_200k_500k/*.sh 2>/dev/null
  git commit -qm "usa_tranco_200k_500k checkpoint $(date -u +%H:%MZ)" && for d in 4 8 16 32; do git push -q -u origin cursor/usa-tranco-200k-500k-a63c && break; sleep $d; done
  cd - >/dev/null
done
