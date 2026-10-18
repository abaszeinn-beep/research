"""Live homepage/nav check for non-Shopify USA stores. Resumable; output jsonl."""
import asyncio, httpx, json, re, sys, time, os, pandas as pd
from urllib.parse import urlparse, urljoin
from collections import defaultdict
IN, OUT = sys.argv[1], sys.argv[2]
UA = "Mozilla/5.0 (compatible; research-directory-bot/1.0)"
A = re.compile(r'<a\b[^>]*?href=["\']([^"\'#][^"\']*)["\'][^>]*>(.*?)</a>', re.I | re.S)
TAG = re.compile(r'<[^>]+>')
done = set()
if os.path.exists(OUT):
    for l in open(OUT):
        done.add(json.loads(l)['url'])
rows = [r for r in pd.read_pickle(IN).to_dict('records') if r['url'] not in done]
hostlock = defaultdict(asyncio.Lock); hostlast = defaultdict(float)
SHARED = ('square.site','bigcartel.com','wixsite.com','company.site','mybigcommerce.com','squarespace.com','ecwid.com','shoplightspeed.com')
async def get(c, url, host, delay):
    async with hostlock[host]:
        w = delay - (time.time() - hostlast[host])
        if w > 0: await asyncio.sleep(w)
        hostlast[host] = time.time()
        return await c.get(url)
async def work(c, r, sem, fo):
    async with sem:
        url = r['url']; host = urlparse(url).netloc
        delay = 1.0 if host.endswith(SHARED) else 0.0
        out = {'url': url, 'ok': False}
        try:
            resp = await get(c, url, host, delay)
            out['status'] = resp.status_code; out['final'] = str(resp.url)
            if resp.status_code == 200:
                h = resp.text[:600000]; out['ok'] = True
                t = re.search(r'<title[^>]*>(.*?)</title>', h, re.I | re.S)
                out['title'] = TAG.sub('', t.group(1)).strip()[:200] if t else ''
                d = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)', h, re.I)
                out['desc'] = d.group(1)[:300] if d else ''
                links = []; seen = set()
                for hr, tx in A.findall(h):
                    tx = re.sub(r'\s+', ' ', TAG.sub(' ', tx)).strip()[:60]
                    k = (hr, tx)
                    if k in seen: continue
                    seen.add(k); links.append((urljoin(str(resp.url), hr)[:200], tx))
                    if len(links) >= 400: break
                out['links'] = links
                if (r.get('platform') == 'woocommerce'):
                    try:
                        base = f"{urlparse(str(resp.url)).scheme}://{urlparse(str(resp.url)).netloc}"
                        wr = await get(c, base + '/wp-json/wc/store/products/categories?per_page=100&hide_empty=true', host, delay)
                        if wr.status_code == 200:
                            out['woocats'] = [x.get('name') for x in wr.json()][:100]
                    except Exception: pass
            elif resp.status_code in (403, 429, 503): out['blocked'] = True
        except Exception as e:
            out['err'] = type(e).__name__
        fo.write(json.dumps(out) + '\n'); fo.flush()
async def main():
    sem = asyncio.Semaphore(int(sys.argv[3]) if len(sys.argv) > 3 else 60)
    lim = httpx.Limits(max_connections=100)
    async with httpx.AsyncClient(headers={'User-Agent': UA}, timeout=httpx.Timeout(15), follow_redirects=True, limits=lim, verify=False) as c:
        with open(OUT, 'a') as fo:
            await asyncio.gather(*(work(c, r, sem, fo) for r in rows))
asyncio.run(main())
