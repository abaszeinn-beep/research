import sqlite3, asyncio, aiohttp, json, sys, re, collections
from fashion_lib import *
db=sqlite3.connect('../qatar/data/qatar_ecom.sqlite'); db.row_factory=sqlite3.Row
rows=db.execute("""select v.key,v.final_url,v.store_name,v.platform,v.category,v.status,v.reason,v.market_score,c.url from verifications v left join candidates c on c.key=v.key
 where v.status like 'verified%' or (v.status='unverified' and v.reason not like 'dns%' and v.reason not like 'http_4%' and v.reason not like 'fetch_failed%' and v.reason not like 'service_style%'
   and v.reason not like 'http_5%' and (v.key like '%.qa' or v.market_score>=1 or v.reason like 'insufficient%' or v.reason like 'partial%' or v.reason like 'weak%' or v.reason like 'js_rend%'))""").fetchall()
todo=[dict(r) for r in rows]
extra=json.load(open('extra_urls.json')) if len(sys.argv)>1 else []
if extra: todo=[{'key':e['key'],'final_url':e['url'],'store_name':e['name'],'platform':'','category':'','status':'new','reason':'','market_score':0,'url':e['url']} for e in extra]
print(len(todo),file=sys.stderr)
out=open(sys.argv[1] if len(sys.argv)>1 else 'probe_main.jsonl','a'); done=set()
async def main():
    conn=aiohttp.TCPConnector(limit=50,limit_per_host=2,ssl=sslctx(),ttl_dns_cache=300)
    async with aiohttp.ClientSession(connector=conn,headers={'User-Agent':UA,'Accept-Language':'en'}) as s:
        sem=asyncio.Semaphore(30); n=0
        async def one(r):
            nonlocal n
            u=r['final_url'] or r['url'] or 'https://'+r['key'].split('|')[0]
            if not u.startswith('http'): u='https://'+u
            async with sem:
                try: p=await asyncio.wait_for(probe(s,u),90)
                except Exception as e: p={'ok':False,'err':'timeout','url':u}
            p['key']=r['key']; p['name']=r['store_name']; p['dbcat']=r['category']; p['dbstatus']=r['status']; p['dbreason']=r['reason']; p['dbplat']=r['platform']
            out.write(json.dumps(p,ensure_ascii=False)+'\n'); n+=1
            if n%200==0: out.flush(); print(n,file=sys.stderr)
        await asyncio.gather(*[one(r) for r in todo])
asyncio.run(main()); out.close()
