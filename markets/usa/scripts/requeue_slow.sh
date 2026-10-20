#!/usr/bin/env bash
# Every 20 min: rate-limited / timed-out candidates go back to the slow lane (priority -1, verifier-slow).
cd "$(dirname "$0")/.."
while true; do
  python3 - <<'PY'
import sqlite3
c = sqlite3.connect('data/usa_ecom.sqlite', timeout=120)
n = c.execute("""UPDATE candidates SET status='pending', priority=-1 WHERE status='unverified' AND attempts < 4 AND key IN
   (SELECT key FROM verifications WHERE reason LIKE 'rate_limited%' OR reason LIKE 'fetch_failed:timeout%' OR reason='verification_timeout')""").rowcount
c.commit(); print('requeued', n, flush=True)
PY
  sleep 1200
done
