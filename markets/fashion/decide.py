import re,json,collections
from classify import cl,nf,wo,me,kd
def decide(o):
    cats=o.get("cats",[]); nav=o.get("nav",[])
    txt_c=" | ".join(cats); txt_n=" | ".join(nav)
    title=o.get("title","")
    allt=txt_c+" | "+txt_n+" | "+title
    def hits(rx,t): return [m.group(0).lower() for m in rx.finditer(t)]
    ch=hits(cl,allt); nh=hits(nf,allt)
    navch=hits(cl,txt_n+" "+title); 
    w=len(hits(wo,allt)); m=len(hits(me,allt)); k=len(hits(kd,allt))
    res={"cl":len(ch),"nf":len(nh),"w":w,"m":m,"k":k,"kw":sorted(set(ch))[:8]}
    return res
if __name__=="__main__":
    rows=[json.loads(l) for l in open("work/probe1.jsonl")]
    import random
    ok=[o for o in rows if o["ok"]]
    for o in ok: o["d"]=decide(o)
    f=[o for o in ok if o["d"]["cl"]>=2]
    print(len(ok),len(f))
    for o in random.sample(f,40): print(o["key"],o["platform"],o["d"])
