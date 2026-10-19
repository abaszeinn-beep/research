"""Write USA_Fashion_Stores.xlsx + csv. Run step1 -> step2 -> step3 first (pickles in /tmp)."""
import pandas as pd, json, os, collections
P=os.path.dirname(os.path.abspath(__file__))+'/..';OUT=P+'/../'
main=pd.read_pickle('/tmp/step3_main.pkl');rem=pd.read_pickle('/tmp/step3_removed.pkl');dup=pd.read_pickle('/tmp/step1_dup.pkl')
QA=json.load(open(P+'/merge/qa_results.json'))
main['Gender (before fix)']=main['Gender'];main['Gender']=main['New Gender']
cols=['Store Name','Website','Type','Gender','Platform','Size Tier','Verification Status','Evidence URL','Source part']
out=main[cols].copy();out.to_csv(OUT+'USA_Fashion_Stores.csv',index=False)
ex=[]
for n,f in (('shopify','usa_fashion_shopify_excluded.csv'),('other','usa_fashion_other_excluded.csv')):
    e=pd.read_csv(f'{P}/{f}').fillna('')
    e['Reason']=e['Reason'] if 'Reason' in e else e['Exclusion Reason']
    e['Source part']=n+' (part excluded list)';ex.append(e)
for df,tag in ((dup,'merge: duplicate'),(rem,'merge: sanity-pass removal')):
    e=pd.DataFrame({'Store Name':df['Store Name'],'Website':df.Website,'Platform':df.Platform,'Size Tier':df['Size Tier'],'Stored Category':df.Type,'Reason':df['Reason'] if 'Reason' in df else df['rm'],'Source part':tag+' / '+df['Source part']});ex.append(e)
xc=['Store Name','Website','Platform','Size Tier','Stored Category','Reason','Source part']
exc=pd.concat(ex,ignore_index=True)
for c in xc:
    if c not in exc:exc[c]=''
exc=exc[xc]
def vc(s,name):return pd.DataFrame({name:s.index,'Count':s.values})
raw={'shopify':5705,'other':1480,'discovery':114}
rows=[]
def sec(title,df=None):
    rows.append([title,'','']);
    if df is not None:
        for a,b in df.items():rows.append(['  '+str(a),int(b),''])
    rows.append(['','',''])
rows.append(['USA fashion stores - coverage & method','',''])
sec('Totals')
for k,v in [('Input rows: shopify / other / discovery','5,705 / 1,480 / 114 = 7,299'),('Duplicates removed (registrable domain)',len(dup)),('Sanity-pass removals',len(rem)),('FINAL stores',len(out)),('Excluded sheet rows',len(exc))]:rows.append(['  '+k,v,''])
rows.append(['','',''])
firstpart=main['Source part'].str.split('+').str[0]
sec('Final by source part (incl. merged)',main['Source part'].value_counts())
sec('By type',main.Type.value_counts())
sec('Gender AFTER fix',main.Gender.value_counts())
sec('Gender BEFORE fix (same final rows)',main['Gender (before fix)'].value_counts())
sh=main[main['Source part'].str.startswith('shopify')]
sec('Shopify-part gender before',sh['Gender (before fix)'].value_counts());sec('Shopify-part gender after',sh.Gender.value_counts())
sec('Gender basis',main['Gender basis'].map(lambda x:'fetch failed (old value kept or name-based)' if x.startswith('fetch_failed') or x in('robots','fetch_missing') else x).value_counts())
sec('By platform',main.Platform.value_counts());sec('By size tier',main['Size Tier'].value_counts())
sec('By verification status',main['Verification Status'].map(lambda v:v if len(v)<70 else v[:70]).value_counts())
sec('Excluded by reason (top)',exc.Reason.str.slice(0,90).value_counts().head(25))
rows.append(['QA','',''])
for k,v in QA['lines']:rows.append(['  '+k,v,''])
rows.append(['','',''])
rows.append(['Method','',''])
for l in QA['method']:rows.append(['  '+l,'',''])
rows.append(['','',''])
rows.append(['Known gaps','',''])
for l in QA['gaps']:rows.append(['  '+l,'',''])
cov=pd.DataFrame(rows,columns=['Item','Value',''])
with pd.ExcelWriter(OUT+'USA_Fashion_Stores.xlsx',engine='xlsxwriter',engine_kwargs={'options':{'strings_to_urls':False}}) as w:
    for name,df in (('Fashion Stores',out),('Excluded',exc),('Coverage & Method',cov)):
        df.to_excel(w,sheet_name=name,index=False);ws=w.sheets[name]
        ws.freeze_panes(1,0)
        if name!='Coverage & Method':ws.autofilter(0,0,len(df),len(df.columns)-1);ws.set_column(0,0,38);ws.set_column(1,1,40);ws.set_column(2,8,20)
        else:ws.set_column(0,0,110);ws.set_column(1,1,40)
print(len(out),len(exc));print(out.Type.value_counts(),out.Gender.value_counts(),main['Gender (before fix)'].value_counts(),sep='\n')
