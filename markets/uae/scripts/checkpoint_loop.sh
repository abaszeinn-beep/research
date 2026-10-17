#!/usr/bin/env bash
cd "$(dirname "$0")/.."
while true; do sleep 1800; bash scripts/checkpoint.sh "UAE periodic checkpoint $(date -u +%FT%TZ)" 2>&1 | tail -3; done
