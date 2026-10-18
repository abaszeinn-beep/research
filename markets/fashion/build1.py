import json,sqlite3,re
from merge import load
from classify import cl,nf,wo,me,kd
D=load(["work/probe1.jsonl","work/probe2.jsonl","work/probe3.jsonl","work/probe_guess.jsonl"])
db=sqlite3.connect('../kuwait/data/kuwait_ecom.sqlite')
V={r[0]:r for r in db.execute("select v.key,v.store_name,v.status,v.category,v.market_score,v.reason,v.evidence_url,v.final_url,c.first_source from verifications v left join candidates c on c.key=v.key")}
def feats(o):
    t=" | ".join(o.get("cats",[])+o.get("nav",[]))+" | "+o.get("title","")
    ch=sorted({m.group(0).lower() for m in cl.finditer(t)})
    nfh=sorted({m.group(0).lower() for m in nf.finditer(t)})
    return dict(dc=len(ch),ch=ch,nfh=nfh,w=len(wo.findall(t)),m=len(me.findall(t)),k=len(kd.findall(t)),n_nf=len(nf.findall(t)),n_cl=len(cl.findall(t)))
rows=[]
for k,o in D.items():
    if not o["ok"]: continue
    f=feats(o); v=V.get(k)
    st=v[2] if v else "guess"
    kwok = k.endswith(".kw") or ".kw" in k or o.get("kwsig",0)>=2 or (v and (v[4] or 0)>=2) or (st or "").startswith("verified")
    if f["dc"]>=2 and kwok:
        rows.append((k,st,(v[3] if v else ""),f,o))
if __name__=="__main__":
    print(len(rows))
    for k,st,cat,f,o in sorted(rows,key=lambda r:r[0]):
        print(k,"|",st,"|",cat,"|dc",f["dc"],"cl",f["n_cl"],"nf",f["n_nf"],"w",f["w"],"m",f["m"],"k",f["k"],"|",",".join(f["ch"][:4]),"|",o["title"][:40])
