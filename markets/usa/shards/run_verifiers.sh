#!/usr/bin/env bash
# (Re)start the four verifier processes (two per queue; the verifier is CPU-bound, one core each).
cd "$(dirname "$0")/../../.." || exit 1
T="tmux -f /exec-daemon/tmux.portal.conf"
for s in v1a v1b v2a v2b; do $T kill-session -t $s 2>/dev/null; done
sleep 2
sqlite3 markets/usa/shards/work/usa_other_platforms.sqlite "update candidates set status='pending' where status='in_progress'"
start() { $T new-session -d -s "$1" -c "$PWD" "PYTHONPATH=$PWD python3 -m markets.usa.shards.verify_us --concurrency $2 --worker $1 --idle-exit 3600 --where \"$3\" 2>&1 | tee -a logs/usa_$1.log"; }
W="platform_hint IN ('wix','square','squarespace')"
start v1a 45 "AND $W AND rowid % 2 = 0"
start v1b 45 "AND $W AND rowid % 2 = 1"
start v2a 50 "AND NOT coalesce($W, 0) AND rowid % 2 = 0"
start v2b 50 "AND NOT coalesce($W, 0) AND rowid % 2 = 1"
