import json,sqlite3,re
from decide import decide
db=sqlite3.connect('../kuwait/data/kuwait_ecom.sqlite')
V={r[0]:r for r in db.execute("select key,store_name,status,category,market_score,reason,evidence_url,final_url from verifications")}
rows=[json.loads(l) for l in open("work/probe1.jsonl")]
out=[]
for o in rows:
    v=V.get(o["key"]); st=v[2] if v else "none"
    o["vstatus"]=st; o["vcat"]=v[3] if v else ""; o["vname"]=v[1] if v else ""; o["ms"]=(v[4] or 0) if v else 0
    o["d"]=decide(o) if o["ok"] else None
    cat=(o["vcat"] or "").lower()
    o["prefashion"]= any(x in cat for x in("fashion","abaya","apparel","sport","lingerie","clothing"))
    out.append(o)
if __name__=="__main__":
    import collections
    ver=[o for o in out if o["vstatus"].startswith("verified")]
    print("verified",len(ver), "prefashion",sum(o["prefashion"] for o in ver))
    live=[o for o in ver if o["ok"]]
    print("live",len(live))
    cand=[o for o in out if not o["vstatus"].startswith("verified") and o["ok"] and o["d"]["cl"]>=2 and (o["key"].endswith(".kw") or o["ms"]>=2)]
    print("nonverified cand",len(cand))
    for o in cand: print(o["key"],o["vstatus"],o["ms"],o["d"]["cl"],o["d"]["nf"],o["d"]["kw"][:4],o["title"][:50])
