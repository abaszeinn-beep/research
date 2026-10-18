import asyncio, httpx, sqlite3, re, json, time, random
from fk import *
from scan import get, page_text, find_evidence, UA
import scan
DB=scan.DB
def flat(cats,out):
    for c in cats or []:
        out.append(c.get('name') or ''); flat(c.get('sub_categories'),out)
async def one(cl,row,sem,res):
    key,url=row
    async with sem:
        try:
            r=await get(cl,url,'salla.sa' if 'salla.sa/' in url else re.sub(r'https?://([^/]+).*',r'\1',url))
            m=re.search(r'"store":\{"id":(\d+)',r.text)
            if not m: res.append((key,None,'nostoreid')); return
            h={"Store-Identifier":m.group(1),"Accept":"application/json","Referer":url,"User-Agent":UA}
            names=[]
            cr=await get2(cl,"https://api.salla.dev/store/v1/products/categories",h)
            cats=[]
            if cr is not None and cr.status_code==200: flat(cr.json().get('data'),cats)
            pr=await get2(cl,"https://api.salla.dev/store/v1/products?per_page=30",h)
            if pr is not None and pr.status_code==200:
                for p in pr.json().get('data',[]): names.append(p.get('name') or ''); names.append((p.get('category') or {}).get('name') or '')
            res.append((key,(cats,names),None))
        except Exception as e: res.append((key,None,type(e).__name__))
async def get2(cl,url,h):
    sem=scan.HS.sem.setdefault('api.salla.dev',asyncio.Semaphore(4))
    async with sem:
        for i in range(3):
            try:
                r=await cl.get(url,headers=h,timeout=20)
                if r.status_code==429: await asyncio.sleep(5); continue
                return r
            except Exception: await asyncio.sleep(2)
    return None
async def main():
    c=sqlite3.connect(DB)
    rows=c.execute("select key,url from scan where platform='salla' and strong='' and ok=1 and src not like '%salla-api%'").fetchall()
    random.shuffle(rows); print(len(rows),flush=True)
    sem=asyncio.Semaphore(60); res=[]
    async with httpx.AsyncClient(verify=False) as cl:
        tasks=[asyncio.create_task(one(cl,r,sem,res)) for r in rows]
        n=0
        while tasks:
            await asyncio.sleep(10); tasks=[t for t in tasks if not t.done()]
            b,res[:]=res[:],[]
            for key,d,err in b:
                if d is None: c.execute("update scan set src=src||'+salla-api-fail' where key=?",(key,)); continue
                cats,names=d; text="\n".join(str(x or "") for x in cats+names); a=analyze(text)
                ev=None;sig=None
                if a['strong'] or len(a['weak'])>=2:
                    mm=KW.search(text); sig=mm.group(0) if mm else None
                    c.execute("update scan set strong=?,weak=?,women=?,men=?,uni=?,kid=?,adult=?,signal=?,evidence_url=?,src=src||'+salla-api' where key=?",(",".join(a['strong']),",".join(a['weak']),int(a['women']),int(a['men']),int(a['uni']),int(a['kid']),int(a['adult']),sig,None,key))
                else: c.execute("update scan set src=src||'+salla-api', kid=?, women=?, men=? where key=?",(int(a['kid']),int(a['women']),int(a['men']),key))
            c.commit(); n+=len(b); print(n,len(tasks),flush=True)
asyncio.run(main())
