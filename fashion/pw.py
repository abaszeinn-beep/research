import asyncio, json, sqlite3, sys, re, pickle
from playwright.async_api import async_playwright
from fk import *
import urllib.parse as up
DB='/tmp/sa/fashion/scan3.sqlite'
JS="""()=>{const a=[...document.querySelectorAll('a[href]')].map(x=>[x.href,(x.innerText||x.textContent||'').trim().slice(0,80)]);
 const cats=[...document.querySelectorAll('nav a, header a, [class*=menu] a, [class*=categor] a')].map(x=>(x.innerText||'').trim().slice(0,60));
 return {a:a.slice(0,600),cats:cats.slice(0,300),title:document.title,len:document.body.innerText.length}}"""
CATLINK=re.compile(r'/c\d{4,}|/categor|/collections?/|product-category|/category/|/cat/|/shop/',re.I)
async def work(ctxf,q,res):
    while True:
        try: key,url=q.get_nowait()
        except asyncio.QueueEmpty: return
        ctx=await ctxf(); pg=await ctx.new_page()
        try:
            await pg.goto(url,wait_until='domcontentloaded',timeout=35000)
            await pg.wait_for_timeout(5000)
            d=await pg.evaluate(JS)
            cat=[]; prod=[]
            for h,t in d['a']:
                (cat if CATLINK.search(h) else prod).append(t); (cat if CATLINK.search(h) else prod).append(up.unquote(up.urlparse(h).path).replace('-',' '))
            cat+=d['cats']
            ca=analyze("\n".join(cat)); al=analyze("\n".join(cat+prod+[d['title']]))
            res.append((key,1,",".join(ca['strong']),",".join(al['strong']),int(al['women']),int(al['men']),int(al['uni']),int(al['kid']),int(al['adult']),d['len'],None))
        except Exception as e:
            res.append((key,0,'','',0,0,0,0,0,0,type(e).__name__))
        finally:
            await pg.close(); await ctx.close()
async def main(rows):
    q=asyncio.Queue()
    for r in rows: q.put_nowait(r)
    res=[]
    async with async_playwright() as p:
        b=await p.chromium.launch(headless=True)
        async def ctxf(): return await b.new_context(locale='ar-SA',user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36')
        ts=[asyncio.create_task(work(ctxf,q,res)) for _ in range(5)]
        while not all(t.done() for t in ts):
            await asyncio.sleep(15); print(len(res),q.qsize(),flush=True)
        await b.close()
    c=sqlite3.connect(DB,timeout=60)
    c.execute("create table if not exists pw(key text primary key,ok int,cat_tokens text,all_tokens text,women int,men int,uni int,kid int,adult int,textlen int,err text)")
    c.executemany("insert or replace into pw values(?,?,?,?,?,?,?,?,?,?,?)",res); c.commit()
if __name__=="__main__":
    rows=json.load(open(sys.argv[1])); asyncio.run(main(rows))
