#!/usr/bin/env bash
# Export the shard CSV/summary and push every INTERVAL seconds (default 1800).
cd "$(dirname "$0")/../../.." || exit 1
START=${START:-$(date +%s)}
INTERVAL=${INTERVAL:-1800}
BRANCH=$(git branch --show-current)
while true; do
  sleep "$INTERVAL"
  RT=$(( $(date +%s) - START ))
  PYTHONPATH=. python3 -m markets.usa.shards.export --runtime-s "$RT" --concurrency "${CONCURRENCY:-v1=70,v2=90 asyncio tasks; columnar scan 3 threads}" || continue
  git add markets/usa/shards/*.csv markets/usa/shards/*_summary.json
  git commit -qm "usa_other_platforms checkpoint $(date -u +%Y-%m-%dT%H:%MZ)" || continue
  for d in 4 8 16 32; do git push -q origin "$BRANCH" && break; sleep $d; done
done
