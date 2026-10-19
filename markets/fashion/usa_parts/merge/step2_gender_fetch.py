"""Re-derive gender from /collections.json, /products.json (Shopify) or homepage nav (others).
Adaptive global limiter 4-8 req/s, 429 backoff, robots.txt respected, no challenge bypass. Resumable (jsonl)."""
import pandas as pd, subprocess, json, re, time, threading, os, sys
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
from concurrent.futures import ThreadPoolExecutor
OUT='/tmp/gender_fetch.jsonl'
UA='Mozilla/5.0 (compatible; FashionDirectoryResearch/1.0; +https://github.com/abaszeinn-beep/research)'
W={'women','womens','woman','ladies','lady','her','hers','female','females','misses','womenswear'}
M={'men','mens','man','him','his','male','males','guys','gentlemen','menswear'}
U={'unisex','genderless','genderneutral','allgender'}
def toks(s):
    s=s.lower().replace("’","'")
    s=re.sub(r"(women|men|woman|man|lady|ladies)'s",r"\1s",s)
    s=s.replace('gender neutral','genderneutral').replace('gender-neutral','genderneutral').replace('all gender','allgender')
    return set(re.findall(r'[a-z]+',s))
def flags(s):
    t=toks(s); return (bool(t&W),bool(t&M),bool(t&U))
class Lim:
    def __init__(s): s.rate=6.0;s.next=0;s.lock=threading.Lock();s.ok=0;s.n429=0
    def wait(s):
        with s.lock:
            now=time.time();t=max(now,s.next);s.next=t+1/s.rate
        if t>now:time.sleep(t-now)
    def hit(s):
        with s.lock:s.rate=max(4.0,s.rate*0.75);s.ok=0;s.n429+=1;s.next=max(s.next,time.time())+2
    def good(s):
        with s.lock:
            s.ok+=1
            if s.ok>=100:s.rate=min(8.0,s.rate+0.5);s.ok=0
L=Lim()
def get(url,maxb=8_000_000):
    for att in range(4):
        L.wait()
        try:
            p=subprocess.run(['curl','-sS','-L','--max-time','20','--max-filesize',str(maxb),'-A',UA,'-w','\n%{http_code}',url],capture_output=True,timeout=30)
        except Exception as e: return -1,''
        out=p.stdout.decode('utf8','ignore');
        body,_,code=out.rpartition('\n')
        try:code=int(code)
        except:return -1,''
        if code==429:
            L.hit();time.sleep(min(60,5*2**att));continue
        if code==200:L.good()
        return code,body
    return 429,''
robots={}
def allowed(host,scheme,path):
    if host not in robots:
        c,b=get(f'{scheme}://{host}/robots.txt',500_000)
        rp=RobotFileParser();
        if c==200 and '<html' not in b[:200].lower(): rp.parse(b.splitlines());robots[host]=rp
        else: robots[host]=None
    rp=robots[host]
    return True if rp is None else rp.can_fetch('*',path)
def tally(items):
    w=m=u=0
    for a,b,c in items:
        if a:w+=1
        if b:m+=1
        if c:u+=1
    return w,m,u
def shop(base,host,scheme):
    r={'mode':'shopify'}
    if not allowed(host,scheme,'/collections.json'): r['robots_blocked']=True;return r
    c,b=get(f'{base}/collections.json?limit=250')
    r['coll_status']=c
    if c==200:
        try:
            cols=json.loads(b).get('collections',[])
            items=[flags(x.get('handle','')+' '+x.get('title','')) for x in cols if x.get('products_count',1)!=0]
            r['coll_n']=len(items);r['coll']=tally(items)
        except Exception:r['coll_status']=-2
    if allowed(host,scheme,'/products.json'):
        c,b=get(f'{base}/products.json?limit=250')
        r['prod_status']=c
        if c==200:
            try:
                ps=json.loads(b).get('products',[])
                items=[]
                for p in ps:
                    tg=p.get('tags',[]);tg=' '.join(tg) if isinstance(tg,list) else str(tg)
                    items.append(flags(f"{p.get('title','')} {p.get('product_type','')} {tg}"))
                r['prod_n']=len(items);r['prod']=tally(items)
            except Exception:r['prod_status']=-2
    else:r['robots_blocked_products']=True
    return r
def home(base,host,scheme):
    r={'mode':'home'}
    if not allowed(host,scheme,'/'): r['robots_blocked']=True;return r
    c,b=get(base+'/',3_000_000);r['home_status']=c
    if c==200:
        if re.search(r'(just a moment|attention required|captcha|access denied)',b[:3000],re.I) and len(b)<20000: r['home_status']=-3;return r
        texts=re.findall(r'<a\b[^>]*href=["\']([^"\']*)["\'][^>]*>(.*?)</a>',b,re.I|re.S)
        items=[]
        for h,t in texts:
            t=re.sub(r'<[^>]+>',' ',t)[:80];h=urlparse(h).path
            items.append(flags(h.replace('/',' ').replace('-',' ')+' '+t))
        r['home_n']=len(items);r['home']=tally(items)
    return r
def work(row):
    u=row['Website'];pu=urlparse(u if '://' in u else 'https://'+u)
    host=pu.netloc;scheme=pu.scheme or 'https';base=f'{scheme}://{host}'
    try:r=shop(base,host,scheme) if row['Platform']=='shopify' else home(base,host,scheme)
    except Exception as e:r={'error':str(e)[:100]}
    r['key']=row['key'];return r
if __name__=='__main__':
    d=pd.read_pickle('/tmp/step1.pkl')
    done=set()
    if os.path.exists(OUT):done={json.loads(l)['key'] for l in open(OUT)}
    rows=[r for _,r in d.iterrows() if r['key'] not in done]
    print('todo',len(rows),flush=True)
    f=open(OUT,'a');n=0
    with ThreadPoolExecutor(16) as ex:
        for r in ex.map(work,rows):
            f.write(json.dumps(r)+'\n');n+=1
            if n%100==0:f.flush();print(n,'rate',L.rate,'429s',L.n429,time.strftime('%X'),flush=True)
