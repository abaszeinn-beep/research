#!/usr/bin/env bash
# Export shard CSV/summary + raw snapshot, commit and push. Loops when called with "loop".
cd "$(dirname "$0")/../../../.." || exit 1
once() {
  python3 markets/usa/shards/tranco_pipeline/export.py > logs/usa_export_last.txt 2>&1 || { tail -5 logs/usa_export_last.txt; return; }
  git add markets/usa/shards/usa_tranco_500k_1m.csv markets/usa/shards/usa_tranco_500k_1m_summary.json \
          markets/usa/shards/work/usa_tranco_500k_1m_raw.jsonl.gz markets/usa/shards/tranco_pipeline
  git commit -qm "usa_tranco_500k_1m checkpoint $(date -u +%Y-%m-%dT%H:%MZ)" || true
  for d in 4 8 16 32; do git push -q -u origin cursor/usa-tranco-500k-1m-ce2b && break; sleep $d; done
  echo "[$(date -u +%FT%TZ)] checkpoint pushed"
}
if [ "$1" = "loop" ]; then
  while true; do sleep 1800; once; done
else
  once
fi
