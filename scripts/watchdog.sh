#!/usr/bin/env bash
# Restart a verifier whose log hasn't been written for >6 minutes (event-loop stall / crash).
cd "$(dirname "$0")/.."
while true; do
  now=$(date +%s)
  for v in 1 2 3 4; do
    log="logs/verifier-$v.log"
    [ -f "$log" ] || continue
    age=$(( now - $(stat -c %Y "$log") ))
    if [ "$age" -gt 360 ]; then
      echo "$(date -u +%FT%TZ) verifier-$v stale ${age}s -> restart"
      case $v in
        1) where="platform_hint='salla'"; conc=48 ;;
        2) where="coalesce(platform_hint,'') NOT IN ('salla','zid','shopify')"; conc=64 ;;
        3) where="platform_hint='zid'"; conc=12 ;;
        4) where="platform_hint='shopify'"; conc=3 ;;
      esac
      tmux -f /exec-daemon/tmux.portal.conf kill-session -t "=verifier-$v" 2>/dev/null
      pkill -9 -f "worker v$v " 2>/dev/null
      sleep 2
      python3 -c "import sqlite3;c=sqlite3.connect('data/saudi_ecom.sqlite',timeout=120);c.execute(\"UPDATE candidates SET status='pending' WHERE status='in_progress' AND $where\");c.commit()"
      scripts/start_worker.sh "verifier-$v" saudi_ecom.verify --concurrency $conc --per-host 2 --worker v$v --where "\"AND $where\""
    fi
  done
  sleep 120
done
