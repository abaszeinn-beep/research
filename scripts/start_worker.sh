#!/usr/bin/env bash
# Usage: scripts/start_worker.sh <session-name> <python -m module and args...>
# Starts (or restarts) a pipeline worker in a detached tmux session, logging to logs/<session>.log
set -euo pipefail
cd "$(dirname "$0")/.."
name="$1"; shift
TM="tmux"; [ -f /exec-daemon/tmux.portal.conf ] && TM="tmux -f /exec-daemon/tmux.portal.conf"
$TM kill-session -t "=$name" 2>/dev/null || true
mkdir -p logs
$TM new-session -d -s "$name" -c "$PWD" -- bash -lc "python3 -m $* 2>&1 | tee -a logs/$name.log"
echo "started $name: python3 -m $*"
