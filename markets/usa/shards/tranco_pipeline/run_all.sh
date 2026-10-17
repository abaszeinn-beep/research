#!/usr/bin/env bash
# Start (or restart stalled) shard workers in tmux. Safe to re-run: workers resume from their JSONL.
#   bash run_all.sh          start everything that is not running
#   bash run_all.sh watch    loop: restart any worker whose output stalled (event-loop hang) or that died
cd "$(dirname "$0")/../../../.." || exit 1
TM="tmux -f /exec-daemon/tmux.portal.conf"
W=data/work/usa_tranco_500k_1m
P=markets/usa/shards/tranco_pipeline
mkdir -p logs "$W"

cmd_for() {
  case "$1" in
    usa-w[0-3]) i=${1#usa-w}; echo "python3 $P/worker.py --worker $i --of 4 --concurrency 200 2>&1 | tee -a logs/usa_w$i.log";;
    usa-shopify) echo "while true; do python3 $P/worker.py --mode shopify --concurrency 40 --shopify-concurrency 24 --rate 6 --max-rate 12 2>&1 | tee -a logs/usa_shopify.log; sleep 120; done";;
    usa-secondary) echo "while true; do python3 $P/secondary.py --concurrency 30 --wayback-concurrency 3 --wayback-gap 0.6 2>&1 | tee -a logs/usa_secondary.log; sleep 300; done";;
    usa-checkpoint) echo "bash $P/checkpoint.sh loop 2>&1 | tee -a logs/usa_checkpoint.log";;
  esac
}
out_for() {
  case "$1" in
    usa-w[0-3]) echo "$W/results_w${1#usa-w}.jsonl";;
    usa-shopify) echo "$W/results_shopify.jsonl";;
    usa-secondary) echo "$W/results_secondary.jsonl";;
  esac
}
log_for() {
  case "$1" in
    usa-w[0-3]) echo "logs/usa_w${1#usa-w}.log";;
    usa-shopify) echo "logs/usa_shopify.log";;
    usa-secondary) echo "logs/usa_secondary.log";;
  esac
}
SESSIONS="usa-w0 usa-w1 usa-w2 usa-w3 usa-shopify usa-secondary usa-checkpoint"

start() {
  $TM has-session -t "=$1" 2>/dev/null && return
  $TM new-session -d -s "$1" -c "$PWD" "$(cmd_for "$1")"
  echo "[$(date -u +%FT%TZ)] started $1"
}

check() {
  local s=$1 out log age
  out=$(out_for "$s"); log=$(log_for "$s")
  [ -z "$out" ] && return
  if [[ $s == usa-w* ]] && grep -q "finished in" "$log" 2>/dev/null && ! $TM has-session -t "=$s" 2>/dev/null; then return; fi
  if [[ $s == usa-w* ]] && tail -n 3 "$log" 2>/dev/null | grep -q "finished in"; then return; fi
  [ -f "$out" ] || return
  age=$(( $(date +%s) - $(stat -c %Y "$out") ))
  local limit=420
  [[ $s == usa-secondary ]] && limit=1200
  [[ $s == usa-shopify ]] && limit=900
  if [ "$age" -gt "$limit" ] && tail -n 2 "$log" | grep -q "remaining=[1-9]"; then
    echo "[$(date -u +%FT%TZ)] $s stalled (${age}s); restarting"
    pkill -f "$(cmd_for "$s" | cut -d' ' -f1-4)" 2>/dev/null
    $TM kill-session -t "=$s" 2>/dev/null
    sleep 2
    start "$s"
  fi
}

if [ "$1" = "watch" ]; then
  while true; do
    for s in $SESSIONS; do
      if [[ $s == usa-w* ]] && grep -q "finished in" "$(log_for "$s")" 2>/dev/null; then continue; fi
      start "$s"; check "$s"
    done
    sleep 60
  done
else
  for s in $SESSIONS; do start "$s"; done
fi
