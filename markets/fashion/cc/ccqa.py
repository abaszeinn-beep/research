import sys,re,gzip,json,subprocess,io,collections
crawl=sys.argv[1]; idx=sys.argv[2]
lines=open(idx,encoding='utf-8',errors='replace').read().split('\n')
sel=[]
for i,l in enumerate(lines):
    if l.startswith('qa,'): sel.append(i)
first=max(0,sel[0]-1); last=sel[-1]
blocks=[]
for i in range(first,last+1):
    p=lines[i].split('\t')
    if len(p)>=4: blocks.append((p[1],int(p[2]),int(p[3])))
import urllib.request,time
FASH=re.compile(r"abaya|jalab|kaftan|qaftan|dress|women|ladies|men's|mens|/men/|modest|cloth|apparel|fashion|thob|hijab|lingerie|wear|boutique|collections/|عباي|ملابس|فساتين|ازياء|أزياء|ثوب",re.I)
hosts=collections.defaultdict(lambda:[0,[]])
out=open(f'cc_{crawl}_qa_urls.tsv','w')
for n,(f,off,ln) in enumerate(blocks):
    for att in range(4):
        try:
            req=urllib.request.Request(f'https://data.commoncrawl.org/cc-index/collections/{crawl}/indexes/{f}',headers={'Range':f'bytes={off}-{off+ln-1}'})
            data=urllib.request.urlopen(req,timeout=60).read(); break
        except Exception as e: time.sleep(2*(att+1)); data=None
    if not data: print('fail',n,file=sys.stderr); continue
    for l in gzip.decompress(data).decode('utf-8','replace').split('\n'):
        if not l.startswith('qa,'): continue
        try:
            surt,ts,js=l.split(' ',2); j=json.loads(js)
        except Exception: continue
        if j.get('status')!='200': continue
        u=j['url']
        if FASH.search(u): out.write(u+'\n')
        h=hosts[re.sub(r'^https?://','',u).split('/')[0].lower()]; h[0]+=1
print(len(blocks),len(hosts))
json.dump({h:v[0] for h,v in hosts.items()},open(f'cc_{crawl}_qa_hosts.json','w'))
