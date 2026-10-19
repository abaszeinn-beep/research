#!/usr/bin/env python3
"""Website page counter (sitemap-first, with fallbacks).

Usage:
  pagecount.py --input shards/shard_1.csv --output results/shard_1.csv [--workers 100] [--resume]
  pagecount.py example.com:SA,AE other.com:US          # ad-hoc, prints rows

Input CSV columns: domain, markets (semicolon list e.g. "SA;AE"), listed_urls (optional)
Output CSV columns: domain, market, pages_count, count_method, sitemap_files,
                    top_sitemap_url, count_date, notes
"""
import argparse, array, csv, datetime, gzip, html, json, os, re, sys, threading, time, zlib
import urllib.parse as up
import urllib.robotparser as rp
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import tldextract

requests.packages.urllib3.disable_warnings()
_TLD = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)

UA = "Mozilla/5.0 (compatible; PageCountResearchBot/1.0; +sitemap-counter)"
CONNECT_T, READ_T = 8, 25
TRACK = re.compile(r"^(utm_.*|gclid|fbclid)$", re.I)
FILE_EXT = re.compile(r"\.(jpe?g|png|webp|gif|svg|bmp|tiff?|avif|pdf|mp4|mov|avi|webm|mkv|mp3|wav|zip|rar|gz|ico|css|js|json|xml|docx?|xlsx?|pptx?|apk|exe)$", re.I)
MEDIA_SM = re.compile(r"(?<![a-z])(image|images|img|video|videos)(?![a-z])", re.I)
SM_CANDIDATES = ["/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml",
                 "/wp-sitemap.xml", "/sitemap.xml.gz", "/sitemaps.xml"]
LOC_RE = re.compile(r"<((?:[\w.-]+:)?)loc>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?\s*</\1loc>", re.S)

LANGS = {"en", "ar", "fr", "es", "de", "it", "pt", "nl", "tr", "ru", "zh", "ja", "ko", "hi", "ur", "fa", "he", "sv", "da", "no", "pl", "cs", "el", "th", "vi", "id", "ms", "bn", "ta"}
MARKET_TOK = {"sa": "SA", "ksa": "SA", "saudi": "SA", "saudiarabia": "SA", "ae": "AE", "uae": "AE",
              "emirates": "AE", "qa": "QA", "qatar": "QA", "kw": "KW", "kuwait": "KW",
              "us": "US", "usa": "US"}
OTHER_TOK = {"bh", "bahrain", "om", "oman", "eg", "egypt", "jo", "jordan", "lb", "lebanon", "iq", "iraq",
             "ma", "morocco", "tn", "dz", "ly", "ye", "sy", "ps", "sd", "gb", "uk", "ca", "au", "nz", "ie",
             "eu", "in", "pk", "tr", "cn", "hk", "sg", "my", "ph", "th", "jp", "kr", "mx", "br", "ar-ar",
             "cl", "co", "fr", "de", "it", "es", "nl", "be", "ch", "at", "se", "dk", "no", "fi", "pl",
             "pt", "gr", "ru", "ua", "za", "ng", "ke", "global", "int", "intl", "row", "mena", "gcc"}

NOW = lambda: datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


class Unavailable(Exception):
    pass


def split_dom(host):
    e = _TLD(host)
    return (getattr(e, 'top_domain_under_public_suffix', None) or e.registered_domain or host.lower())


def host_of(url):
    u = url if "//" in url else "https://" + url
    return (up.urlsplit(u).hostname or "").lower()


def canon_host(h):
    return h[4:] if h.startswith("www.") else h


def locale_market(tok_seg):
    """Return (is_locale, market_or_None, country_or_None)."""
    s = tok_seg.lower()
    if s in ("saudi-arabia",):
        return True, "SA", "SA"
    if len(s) > 14:
        return False, None, None
    toks = re.split(r"[-_]", s)
    mk = None
    other = False
    for t in toks:
        if t in MARKET_TOK:
            mk = MARKET_TOK[t]
        elif t in OTHER_TOK:
            other = True
        elif t in LANGS:
            pass
        else:
            return False, None, None
    if mk:
        return True, mk, mk
    if other and not all(t in LANGS for t in toks):
        # 'en-gb', 'de-ch' etc -> some other country, but bare language codes are not countries
        return True, None, "other"
    return False, None, None


def tag_url(host, path):
    labels = host.split(".")
    if len(labels) > 2:
        first = labels[0] if labels[0] != "www" else (labels[1] if len(labels) > 3 else "")
        if first in MARKET_TOK:
            return MARKET_TOK[first]
        if first in OTHER_TOK and len(first) > 2:
            return "other"
    seg = path.split("/", 2)[1] if path.startswith("/") and len(path) > 1 else ""
    if seg:
        ok, mk, ctry = locale_market(seg)
        if ok:
            return mk or "other"
    return ""


class Host:
    """Per-host politeness: serialised requests with a min gap."""
    gap = 0.1
    def __init__(self):
        self.lock = threading.Lock(); self.last = 0.0


class Fetcher:
    def __init__(self, deadline):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept": "*/*", "Accept-Encoding": "gzip, deflate"})
        self.deadline = deadline
        self.last_err = None
        self.last_status = None
        self.lock = threading.Lock()
        self.last_t = 0.0

    def _pace(self):
        with self.lock:
            w = Host.gap - (time.time() - self.last_t)
            if w > 0: time.sleep(w)
            self.last_t = time.time()

    def get(self, url, retries=2, stream=False, timeout=(CONNECT_T, READ_T), **kw):
        for i in range(retries + 1):
            if time.time() > self.deadline: raise Unavailable("timeout: domain time budget exceeded")
            self._pace()
            try:
                r = self.s.get(url, timeout=timeout, stream=stream, verify=False, allow_redirects=True, **kw)
                self.last_status = r.status_code
                if r.status_code in (429, 502, 503, 504) and i < retries:
                    ra = r.headers.get("Retry-After", "")
                    time.sleep(min(float(ra) if ra.isdigit() else 2 ** (i + 1), 20))
                    r.close(); continue
                return r
            except requests.RequestException as e:
                self.last_err = type(e).__name__ + ": " + str(e)[:80]
                time.sleep(2 ** i * 0.5)
        return None


def iter_locs(r, deadline):
    """Stream a sitemap response -> yields (kind, [locs]). kind in index/urlset."""
    dec = None
    buf = ""
    kind = None
    first = True
    for chunk in r.iter_content(chunk_size=262144):
        if time.time() > deadline: raise Unavailable("timeout")
        if first:
            first = False
            if chunk[:2] == b"\x1f\x8b":
                dec = zlib.decompressobj(16 + zlib.MAX_WBITS)
        if dec is not None:
            try: chunk = dec.decompress(chunk)
            except zlib.error: return
        buf += chunk.decode("utf-8", "ignore")
        if kind is None:
            if "<sitemapindex" in buf[:20000]: kind = "index"
            elif "<urlset" in buf[:20000]: kind = "urlset"
            elif len(buf) > 20000: return
            else: continue
            yield kind, []
        last = 0; locs = []
        for m in LOC_RE.finditer(buf):
            last = m.end()
            if m.group(1) in ("image:", "video:"): continue
            v = m.group(2).strip()
            if "&" in v: v = html.unescape(v)
            locs.append(v)
        buf = buf[last:] if last else buf[-4096:] if len(buf) > 1_000_000 else buf
        if locs: yield kind, locs
    if dec is not None:
        try:
            tail = dec.flush().decode("utf-8", "ignore")
            for m in LOC_RE.finditer(buf + tail):
                if m.group(1) in ("image:", "video:"): continue
                yield kind or "urlset", [html.unescape(m.group(2).strip())]
        except Exception:
            pass


_HOSTC = {}


def _host_info(h, rds):
    key = (h, id(rds))
    v = _HOSTC.get(key)
    if v is None:
        ok = split_dom(h) in rds
        hk = h[4:] if h.startswith("www.") else h
        labels = hk.split(".")
        ht = ""
        if len(labels) > 2:
            first = h.split(".")[0] if h.split(".")[0] != "www" else (h.split(".")[1] if len(h.split(".")) > 3 else "")
            if first in MARKET_TOK: ht = MARKET_TOK[first]
            elif first in OTHER_TOK and len(first) > 2: ht = "other"
        v = (ok, hk, ht)
        if len(_HOSTC) < 200000: _HOSTC[key] = v
    return v


_SEGC = {}


def norm_key(url, rds):
    s = url.strip()
    if s.startswith("https://"): rest = s[8:]
    elif s.startswith("http://"): rest = s[7:]
    else: return None, None
    cut = len(rest)
    for ch in "/?#":
        k = rest.find(ch)
        if 0 <= k < cut: cut = k
    hp = rest[:cut]
    if "@" in hp or ":" in hp:
        try:
            u = up.urlsplit(s)
        except ValueError:
            return None, None
        if not u.hostname: return None, None
        hp = u.hostname
    tail = rest[cut:]
    frag = tail.find("#")
    if frag >= 0: tail = tail[:frag]
    qi = tail.find("?")
    path, query = (tail, "") if qi < 0 else (tail[:qi], tail[qi + 1:])
    if not path: path = "/"
    h = hp.lower()
    ok, hk, ht = _host_info(h, rds)
    if not ok: return None, None
    if FILE_EXT.search(path): return None, None
    q = ""
    if query:
        qs = [(k, v) for k, v in up.parse_qsl(query, keep_blank_values=True) if not TRACK.match(k)]
        q = "?" + up.urlencode(qs) if qs else ""
    kp = path.rstrip("/") if len(path) > 1 else ""
    if kp == "/": kp = ""
    tag = ht
    if not tag:
        seg = path.split("/", 2)[1] if len(path) > 1 else ""
        if seg:
            tag = _SEGC.get(seg)
            if tag is None:
                ok2, mk, ctry = locale_market(seg)
                tag = (mk or "other") if ok2 else ""
                if len(_SEGC) < 100000: _SEGC[seg] = tag
    return f"{hk}{kp}{q}", tag


class SitemapCrawl:
    def __init__(self, fetcher, rds, robots):
        self.f, self.rds, self.robots = fetcher, rds, robots
        self.seen_sm = set(); self.files = 0; self.skipped = []; self.failed = []
        self.hashes = array.array('Q'); self.tagarr = array.array('B'); self.tagids = {}
        self.tags = {}; self.raw = 0; self.dups = 0
        self.lock = threading.Lock()

    def add(self, locs):
        with self.lock:
            for l in locs:
                self.raw += 1
                k, t = norm_key(l, self.rds)
                if k is None: continue
                ti = self.tagids.setdefault(t, len(self.tagids))
                self.hashes.append(hash(k) & 0xFFFFFFFFFFFFFFFF)
                self.tagarr.append(ti)

    def finalize(self):
        """Exact dedupe over 64-bit hashes (compact arrays, bounded memory); fills self.tags / self.dups."""
        import numpy as np
        n = len(self.hashes)
        if n == 0:
            self.tags = {}; self.dups = 0; return
        h = np.frombuffer(self.hashes, dtype=np.uint64)
        tg = np.frombuffer(self.tagarr, dtype=np.uint8)
        _, idx = np.unique(h, return_index=True)
        names = {v: k for k, v in self.tagids.items()}
        cnt = np.bincount(tg[idx], minlength=len(self.tagids))
        self.tags = {names[i]: int(c) for i, c in enumerate(cnt) if c}
        self.dups = n - len(idx)
        self.hashes = array.array("Q"); self.tagarr = array.array("B")

    def run(self, tops):
        stack = list(tops)
        pool = None
        for rnd in range(3):
            while stack:
                batch = []
                while stack and len(batch) < 8:
                    s = stack.pop()
                    if s in self.seen_sm: continue
                    self.seen_sm.add(s)
                    base = up.urlsplit(s).path.rsplit("/", 1)[-1]
                    if MEDIA_SM.search(base):
                        self.skipped.append(s); continue
                    batch.append(s)
                if not batch: continue
                if len(batch) == 1:
                    stack.extend(self.one(batch[0]))
                else:
                    if pool is None: pool = ThreadPoolExecutor(4)
                    for kids in pool.map(self.one, batch): stack.extend(kids)
                if self.files > 6000: break
            retry = [u for u, e in self.failed if e not in (404, 410, "unparseable")]
            if not retry: break
            self.failed = [x for x in self.failed if x[0] not in retry]
            for u in retry: self.seen_sm.discard(u)
            time.sleep(3 * (rnd + 1))
            stack = retry
        if pool: pool.shutdown()

    def one(self, s):
        kids = []
        r = self.f.get(s, stream=True)
        if r is None:
            self.failed.append((s, self.f.last_err)); return kids
        if r.status_code != 200:
            self.failed.append((s, r.status_code)); r.close(); return kids
        try:
            got = False
            for kind, locs in iter_locs(r, self.f.deadline):
                got = True
                if kind == "index":
                    kids.extend(up.urljoin(s, l) for l in locs)
                else:
                    self.add(locs)
            if got: self.files += 1
            else: self.failed.append((s, "unparseable"))
        except Unavailable:
            raise
        except Exception as e:
            self.failed.append((s, type(e).__name__))
        finally:
            r.close()
        return kids


def count_domain(domain, markets, deadline_s=3600):
    """Returns list of row dicts (one per market)."""
    deadline = time.time() + deadline_s
    f = Fetcher(deadline)
    rds = {split_dom(domain)}
    notes = []
    today = NOW()

    def rows(count, method, files=0, top="", note=""):
        out = []
        for m in markets:
            c = count[m] if isinstance(count, dict) else count
            mm = method[m] if isinstance(method, dict) else method
            out.append(dict(domain=domain, market=m, pages_count="" if c is None else c, count_method=mm,
                            sitemap_files=files, top_sitemap_url=top, count_date=today, notes=note))
        return out

    try:
        # 1. reach the site: robots.txt on https/http, bare/www
        base = None; robots_txt = None; status_seen = []
        for scheme in ("https", "http"):
            for h in (domain, "www." + domain if not domain.startswith("www.") else domain[4:]):
                r = f.get(f"{scheme}://{h}/robots.txt", retries=0, timeout=(6, 15))
                if r is None: continue
                status_seen.append(r.status_code)
                final = host_of(r.url)
                if split_dom(final) not in rds:
                    rds.add(split_dom(final)); notes.append(f"redirects to {final}")
                if r.status_code == 200 and "html" not in r.headers.get("content-type", "") or (r.status_code == 200 and "user-agent" in r.text[:5000].lower()):
                    robots_txt = r.text; base = f"{scheme}://{host_of(r.url)}"; break
                if r.status_code < 500 and base is None:
                    base = f"{scheme}://{host_of(r.url)}"
                if r.status_code in (403, 401, 429, 406, 451, 503):
                    base = base or f"{scheme}://{host_of(r.url)}"
            if robots_txt is not None: break
            if base: break
        if base is None:
            why = f.last_err or f"HTTP {f.last_status}"
            raise Unavailable(f"unreachable ({why})")
        blocked_status = [s for s in status_seen if s in (401, 403, 406, 429, 451, 503)]

        robots = None
        if robots_txt:
            robots = rp.RobotFileParser(); robots.parse(robots_txt.splitlines())
            if not robots.can_fetch(UA, base + "/") and not robots.can_fetch("*", base + "/"):
                raise Unavailable("blocked by robots.txt (Disallow: /)")
        tops = []
        if robots_txt:
            tops = [up.urljoin(base + "/", m.strip()) for m in re.findall(r"(?im)^\s*sitemap:\s*(\S+)", robots_txt)]
        how = "robots.txt"
        if not tops:
            how = "guess"
            for c in SM_CANDIDATES:
                r = f.get(base + c, retries=1, stream=True, timeout=(CONNECT_T, 20))
                ok = False
                if r is not None and r.status_code == 200:
                    try:
                        for kind, locs in iter_locs(r, deadline): ok = True; break
                    except Unavailable: raise
                    except Exception: pass
                if r is not None: r.close()
                if ok: tops = [base + c]; break
        if tops:
            cr = SitemapCrawl(f, rds, robots); cr.run(tops); cr.finalize()
            total = sum(cr.tags.values())
            if cr.files > 0 and total > 0:
                return _market_rows(domain, markets, cr, tops, today, how, notes)
            notes.append("sitemap present but yielded no countable URLs" + (f" ({cr.failed[:2]})" if cr.failed else ""))
        else:
            notes.append("no sitemap found")
        if blocked_status and not tops:
            raise Unavailable(f"blocked by site: HTTP {blocked_status[0]} on robots.txt; not bypassed")
        n, method, note = fallback(f, base, domain, rds, robots)
        if n is None:
            reason = "; ".join(x for x in notes + [note] if x) or "no sitemap; fallbacks returned nothing"
            if blocked_status: reason = f"blocked (HTTP {blocked_status[0]}); " + reason
            return rows(None, f"Not available ({reason})", note="; ".join(notes))
        return rows(n, method, 0, "", "; ".join(notes + [note]))
    except Unavailable as e:
        return rows(None, f"Not available ({e})", note="; ".join(notes))
    except Exception as e:  # pragma: no cover
        return rows(None, f"Not available (error: {type(e).__name__}: {str(e)[:60]})", note="; ".join(notes))


def _market_rows(domain, markets, cr, tops, today, how, notes):
    tags = cr.tags
    total = sum(tags.values())
    tagged = {k: v for k, v in tags.items() if k}
    countries = {k for k in tagged if k != "other"}
    segmented = len(tagged) >= 2 and sum(tagged.values()) / total >= 0.3 and len(countries | ({"other"} & set(tagged))) >= 1
    out = []
    n = list(notes)
    n.append(f"raw={cr.raw} dupes_removed={cr.dups}")
    if cr.skipped: n.append(f"media sitemaps skipped={len(cr.skipped)}")
    if cr.failed: n.append(f"failed sitemap fetches={len(cr.failed)}: " + "; ".join(f"{u}:{e}" for u, e in cr.failed[:3]))
    if segmented:
        n.append("country split " + ",".join(f"{k or 'untagged'}={v}" for k, v in sorted(tags.items(), key=lambda x: -x[1])[:8]))
    for m in markets:
        if segmented:
            c = tags.get(m, 0)
            method = f"sitemap ({m} pages only)"
        else:
            c = total
            method = "sitemap"
        out.append(dict(domain=domain, market=m, pages_count=c, count_method=method, sitemap_files=cr.files,
                        top_sitemap_url=" | ".join(tops[:5]) + (f" (+{len(tops)-5} more)" if len(tops) > 5 else ""),
                        count_date=today, notes="; ".join(n)))
    return out


ARCHIVE_SEM = threading.Semaphore(3)
SHOP_PAT = re.compile(r"(?:of|من)\s+(\d[\d,]*)\s+(?:results|products|items|منتج)|\b(\d[\d,]{0,8})\s+(?:products|items|results|منتج(?:ات)?)\b", re.I)


def fallback(f, base, domain, rds, robots):
    def allowed(u):
        return robots is None or robots.can_fetch("*", u)
    # a. shop-page totals
    for path in ("/shop", "/products", "/collections/all", "/store", "/all-products"):
        u = base + path
        if not allowed(u): continue
        r = f.get(u, retries=0, timeout=(CONNECT_T, 15))
        if r is not None and r.status_code == 200 and "html" in r.headers.get("content-type", "html"):
            m = SHOP_PAT.search(re.sub(r"<[^>]+>", " ", r.text[:600000]))
            if m:
                return int((m.group(1) or m.group(2)).replace(",", "")), "shop-page total", f"{path}: '{m.group(0)}'"
    # b. platform counts
    if allowed(base + "/products.json"):
        r = f.get(base + "/products.json?limit=250&page=1", retries=1)
        if r is not None and r.status_code == 200 and r.text.lstrip().startswith("{") and '"products"' in r.text[:200]:
            total, p = 0, 1
            while p <= 400:
                rr = f.get(f"{base}/products.json?limit=250&page={p}", retries=1)
                if rr is None or rr.status_code != 200: break
                try: n = len(rr.json().get("products", []))
                except Exception: break
                total += n
                if n < 250: break
                p += 1
            nc = 0
            for p in range(1, 40):
                col = f.get(f"{base}/collections.json?limit=250&page={p}", retries=1)
                if col is None or col.status_code != 200: break
                try: k = len(col.json().get("collections", []))
                except Exception: break
                nc += k
                if k < 250: break
            return total + nc, "platform product count", f"shopify products={total} + collections={nc}; /pages not enumerable"
    if allowed(base + "/wp-json/wc/store/products"):
        r = f.get(base + "/wp-json/wc/store/products?per_page=1", retries=1)
        if r is not None and r.status_code == 200 and "X-WP-Total" in r.headers:
            return int(r.headers["X-WP-Total"]), "platform product count", "woocommerce X-WP-Total (products only)"
    # c. archive: own host (+www; the CDX urlkey merges www, other subdomains are excluded)
    h = canon_host(domain)
    with ARCHIVE_SEM:
        n = 0
        for attempt in range(3):
            n = 0
            r = f.get("https://web.archive.org/cdx/search/cdx", retries=2, stream=True, timeout=(10, 120), params={
                "url": h + "/*", "output": "txt", "fl": "urlkey", "collapse": "urlkey",
                "filter": ["mimetype:text/html", "statuscode:200"]})
            if r is None or r.status_code != 200:
                err = f"HTTP {r.status_code}" if r is not None else f.last_err
                time.sleep(5 * (attempt + 1)); continue
            try:
                head = True; bad = False
                for line in r.iter_lines():
                    if head:
                        head = False
                        if line.lstrip().startswith(b"<"): bad = True; break
                    if line: n += 1
                r.close()
                if bad:
                    err = "wayback offline"; time.sleep(5 * (attempt + 1)); continue
                if n == 0:
                    return None, None, "no sitemap/shop total/platform count and no archive captures"
                return n, "archive", "wayback CDX unique urlkeys (html,200; own host + www only)"
            except requests.RequestException as e:
                err = type(e).__name__; time.sleep(5 * (attempt + 1))
        return None, None, f"no sitemap/shop total/platform count; wayback unavailable ({err})"


FIELDS = ["domain", "market", "pages_count", "count_method", "sitemap_files", "top_sitemap_url", "count_date", "notes"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input"); ap.add_argument("--output")
    ap.add_argument("--workers", type=int, default=100)
    ap.add_argument("--deadline", type=int, default=3600)
    ap.add_argument("args", nargs="*")
    a = ap.parse_args()
    items = []
    if a.input:
        for r in csv.DictReader(open(a.input, encoding="utf-8")):
            items.append((r["domain"], [m for m in r["markets"].split(";") if m]))
    for x in a.args:
        d, _, m = x.partition(":")
        items.append((d, (m or "SA").split(",")))
    done = set()
    out = None
    if a.output:
        os.makedirs(os.path.dirname(a.output) or ".", exist_ok=True)
        exists = os.path.exists(a.output)
        if exists:
            done = {r["domain"] for r in csv.DictReader(open(a.output, encoding="utf-8"))}
        out = open(a.output, "a", newline="", encoding="utf-8")
        w = csv.DictWriter(out, FIELDS)
        if not exists: w.writeheader()
    else:
        w = csv.DictWriter(sys.stdout, FIELDS); w.writeheader()
    items = [i for i in items if i[0] not in done]
    lock = threading.Lock(); n = 0; t0 = time.time()
    with ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(count_domain, d, m, a.deadline): d for d, m in items}
        for fu in as_completed(futs):
            try: rs = fu.result()
            except Exception as e:
                rs = [dict(domain=futs[fu], market="", pages_count="", count_method=f"Not available (error {e})",
                           sitemap_files=0, top_sitemap_url="", count_date=NOW(), notes="")]
            with lock:
                for r in rs: w.writerow(r)
                (out or sys.stdout).flush(); n += 1
                if a.output and n % 200 == 0:
                    print(f"{n}/{len(items)} done, {time.time()-t0:.0f}s", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
