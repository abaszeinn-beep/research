import pandas as pd,json,sys
sys.path.insert(0,'.')
from classify import *
I=pd.read_csv('inc.csv');E=pd.read_csv('exc.csv');F={}
for l in open('fetch.jsonl'):
    d=json.loads(l)
    if d.get('p'):F[d['u']]=d
I['d']='INC';E['d']='EXC';E=E[E.Reason.str.startswith('Live products')]
seed=int(sys.argv[1]);a=I.sample(70,random_state=seed);b=E.sample(30,random_state=seed)
for _,r in pd.concat([a,b]).iterrows():
    p=F.get(r.Website,{}).get('p',[])
    cl=[q[0][:22] for q in p if prod_flags(q)[0]][:2]
    print(r.d,r['Store Name'][:26],'|',r.get('Type','-')[:4] if r.d=='INC' else '-',r.get('Gender','-') if r.d=='INC' else '-','|',str(r.get('Stored Category',''))[:14],'|',r.get('Matched Signal','')[:14] if r.d=='INC' else r.Reason[14:36],'|',cl,'|',sorted({q[1] for q in p if q[1]})[:3])
