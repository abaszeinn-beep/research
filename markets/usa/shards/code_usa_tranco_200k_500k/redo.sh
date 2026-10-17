#!/usr/bin/env bash
# Re-run pass for one worker with the current verifier: Shopify-throttled (429) and timed-out domains plus all
# verified/unverified hits. MODE=defer skips Shopify-hosted domains (left untouched); MODE=only runs just those, paced.
cd "$(dirname "$0")"
python3 pipeline.py --worker "$1" --nworkers 4 --concurrency "${CONC:-100}" --shopify-mode "${MODE:-defer}" --shopify-rps "${SHOPIFY_RPS:-0}" \
  --redo "((status='blocked' AND json_extract(hint,'\$.http')=429) OR (status='error' AND reason='timeout') OR status IN ('unverified','verified')) AND ts < '${SINCE:-2026-10-17T13:11:47Z}'"
