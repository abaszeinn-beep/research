#!/usr/bin/env bash
# One-time VM setup: Python deps, Playwright Chromium, and a local caching DNS forwarder.
# The VPC resolver rate-limits under the Tranco/verifier load; dnsmasq forwards to public resolvers with a large cache.
set -euo pipefail
pip install -q httpx selectolax beautifulsoup4 lxml tldextract pandas openpyxl playwright aiodns
(python3 -m playwright install --with-deps chromium >/tmp/pw.log 2>&1 &)
if ! command -v dnsmasq >/dev/null; then
  sudo apt-get update -q >/dev/null 2>&1 || true
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q dnsmasq >/dev/null
fi
sudo bash -c 'cat > /etc/dnsmasq.d/mkt.conf <<EOF
listen-address=127.0.0.1
bind-interfaces
no-resolv
server=1.1.1.1
server=8.8.8.8
server=1.0.0.1
server=8.8.4.4
cache-size=100000
dns-forward-max=1000
neg-ttl=600
EOF
pkill dnsmasq || true
dnsmasq --conf-file=/etc/dnsmasq.d/mkt.conf
[ -f /etc/resolv.conf.orig ] || cp /etc/resolv.conf /etc/resolv.conf.orig
printf "nameserver 127.0.0.1\nnameserver 10.0.0.2\noptions timeout:2 attempts:2\n" > /etc/resolv.conf'
getent hosts github.com
