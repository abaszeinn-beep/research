import asyncio,httpx,json,time,random,sys,os
import pandas as pd
from urllib.parse import urlsplit
s=pd.read_pickle('/tmp/w/scoped.pkl')
s=s[s.pre!='not']
OUT='/tmp/w/fetch.jsonl'
done=set()
if os.path.exists(OUT):
    for l in open(OUT):
        try: done.add(json.loads(l)['u'])
        except: pass
todo=[u for u in s['Root Domain / Storefront URL'] if u not in done]
print(len(todo),'todo',flush=True)
rate=[4.0]; last=[0.0]; lock=asyncio.Lock(); recent=[]
async def tick():
    async with lock:
        now=time.monotonic(); w=max(0,last[0]+1/rate[0]-now); last[0]=max(now,last[0])+1/rate[0]
    if w: await asyncio.sleep(w)
UA={'User-Agent':'Mozilla/5.0 (compatible; ResearchDirectoryBot/1.0)','Accept':'application/json'}
async def get(c,url):
    class R: pass
    for a in range(5):
        await tick()
        p=await asyncio.create_subprocess_exec('curl','-s','-L','--compressed','-m','20','--max-filesize','8000000','-A','Mozilla/5.0 (compatible; ResearchDirectoryBot/1.0)','-w','\n%{http_code}',url,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
        out,_=await p.communicate()
        body,_,code=out.rpartition(b'\n'); code=int(code or 0)
        if code in (429,430):
            rate[0]=max(1.0,rate[0]*0.8); await asyncio.sleep(3*2**a+random.random()); continue
        if code==0: return None,'curl%d'%p.returncode
        r=R(); r.status_code=code; r.body=body
        r.json=lambda: json.loads(body)
        recent.append(code); return r,None
    return None,'429'
def compact(js):
    out=[]
    for p in js.get('products',[])[:250]:
        out.append([p.get('title','')[:90],p.get('product_type','')[:40],(p.get('tags') if isinstance(p.get('tags'),list) else str(p.get('tags','')).split(', '))[:8],p.get('vendor','')[:40]])
    return out
async def work(c,u,f,sem):
    async with sem:
        b=u.rstrip('/'); res={'u':u}
        r,err=await get(c,b+'/products.json?limit=250')
        if r is not None and r.status_code==200:
            try: res['p']=compact(r.json()); res['src']=b+'/products.json?limit=250'
            except Exception: res['err']='badjson'
        else: res['err']=err or r.status_code
        if 'p' not in res or not res['p']:
            r,err=await get(c,b+'/collections.json?limit=250')
            if r is not None and r.status_code==200:
                try: res['c']=[[x.get('title',''),x.get('handle','')] for x in r.json().get('collections',[])][:100]; res['csrc']=b+'/collections.json'
                except Exception: pass
        f.write(json.dumps(res)+'\n'); f.flush()
async def main():
    from concurrent.futures import ThreadPoolExecutor
    asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(64))
    sem=asyncio.Semaphore(30)
    f=open(OUT,'a')
    async with httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(local_address="0.0.0.0",limits=httpx.Limits(max_connections=60)),timeout=15,follow_redirects=True) as c:
        async def mon():
            while True:
                await asyncio.sleep(30)
                n=len(recent); bad=sum(1 for x in recent if x in(403,)); recent.clear()
                if rate[0]<4: rate[0]=min(4,rate[0]*1.5)
                print(time.strftime('%X'),'rate',round(rate[0],1),'n30s',n,flush=True)
        m=asyncio.create_task(mon())
        # interleave hosts by shuffling
        random.shuffle(todo)
        await asyncio.gather(*[work(c,u,f,sem) for u in todo])
        m.cancel()
asyncio.run(main())
