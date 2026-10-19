import asyncio,json,sys,aiohttp
from playwright.async_api import async_playwright
import classify
async def one(ctx,s,sem,row,f):
    async with sem:
        try: await asyncio.wait_for(one_(ctx,s,asyncio.Semaphore(1),row,f),70)
        except Exception as e:
            f.write(json.dumps({'key':row[0],'url':row[1],'status':0,'err':'timeout'})+'\n');f.flush()
async def one_(ctx,s,sem,row,f):
    key,url,plat,cat=row[:4]
    res={'key':key,'url':url,'pw':True}
    async with sem:
        page=await ctx.new_page()
        try:
            await page.goto(url,timeout=35000,wait_until='domcontentloaded')
            await page.wait_for_timeout(3500)
            h=await page.content(); final=page.url
            res['status']=200
            if len(h)<1500: res['status']=1
            else: res=await classify.analyze(s,res,h,final,plat)
        except Exception as e:
            res['status']=0;res['err']=str(e)[:60]
        finally:
            await page.close()
    f.write(json.dumps(res,ensure_ascii=False)+'\n');f.flush()
async def main(inp,out,conc):
    rows=json.load(open(inp));done=set()
    try: done={json.loads(l)['key'] for l in open(out)}
    except FileNotFoundError: pass
    rows=[r for r in rows if r[0] not in done]
    f=open(out,'a');sem=asyncio.Semaphore(conc)
    async with async_playwright() as p:
        b=await p.chromium.launch()
        ctx=await b.new_context(user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36',locale='en-AE',ignore_https_errors=True)
        async with aiohttp.ClientSession(headers=classify.UA,connector=aiohttp.TCPConnector(ssl=False)) as s:
            await asyncio.gather(*[one(ctx,s,sem,r,f) for r in rows])
        await b.close()
asyncio.run(main(sys.argv[1],sys.argv[2],int(sys.argv[3])))
