#!/usr/bin/env bash
# Rebuild the runtime environment after a VM re-provision (idempotent). Run from markets/qatar.
set -uo pipefail
cd "$(dirname "$0")/.."
pip install -q httpx selectolax beautifulsoup4 lxml tldextract pandas openpyxl playwright
# local DNS cache: the VPC resolver times out under ~100 concurrent fetches
if ! pgrep -x dnsmasq >/dev/null; then
  command -v dnsmasq >/dev/null || sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q dnsmasq >/dev/null
  sudo dnsmasq --listen-address=127.0.0.1 --bind-interfaces --no-resolv --server=10.0.0.2 --cache-size=150000 \
       --dns-forward-max=1500 --neg-ttl=600 --no-hosts --pid-file=/tmp/dnsmasq.pid
  printf "nameserver 127.0.0.1\nnameserver 10.0.0.2\noptions timeout:2 attempts:2\n" | sudo tee /etc/resolv.conf >/dev/null
fi
mkdir -p data/raw logs
[ -s data/raw/tranco.csv ] || { curl -sL "https://tranco-list.eu/download/64VVX/1000000" | tr -d '\r' > data/raw/tranco.csv; }
[ -f data/qatar_ecom.sqlite ] || { [ -f data/qatar_ecom.sqlite.gz ] && gunzip -k data/qatar_ecom.sqlite.gz; }
python3 scripts/fetch_wikidata.py
echo "setup ok: $(wc -l < data/raw/tranco.csv) tranco rows"
