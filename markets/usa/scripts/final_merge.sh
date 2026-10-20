#!/bin/bash
# Reproduce the final merge from the pre-merge DB snapshot (git: usa_ecom.sqlite.gz of commit a64d0d9) + shard CSVs.
# usage: scripts/final_merge.sh <pre-merge-snapshot.gz>
set -e
cd "$(dirname "$0")/.."
SNAP=${1:-data/usa_ecom.sqlite.gz}
python3 -c "import gzip,shutil,sys;shutil.copyfileobj(gzip.open('$SNAP'),open('data/usa_ecom.sqlite','wb'))"
rm -f data/usa_ecom.sqlite-wal data/usa_ecom.sqlite-shm
python3 -m mktecom.merge_shards
for f in qa/rescreen_*.jsonl; do python3 -m mktecom.rescreen --apply "$f"; done
python3 -m mktecom.nonstore_filter --apply > qa/nonstore_filter_hits.txt
python3 -m mktecom.major_resolve --replay qa/major_decisions.jsonl
