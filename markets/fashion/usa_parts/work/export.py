import pandas as pd, json, re, datetime
O=pd.read_pickle('/tmp/O.pkl');E=pd.read_pickle('/tmp/E.pkl')
P='/tmp/w/markets/fashion/usa_parts/'
cols=['Store Name','Website','Type','Gender','Platform','Size Tier','Verification Status','Evidence URL','Source','Matched Signal']
O=O.drop_duplicates('Website')
O['Store Name']=O['Store Name'].str.strip()
O[cols].sort_values('Store Name',key=lambda s:s.str.lower()).to_csv(P+'usa_fashion_other.csv',index=False)
E['Store Name']=E['Store Name'].astype(str)
ec=['Store Name','Website','Platform','cat','Size Tier','Exclusion Reason','live','Source']
E=E[ec].rename(columns={'cat':'Stored Category','live':'Live Check'})
E=E[E['Exclusion Reason']!='not fashion by stored category']
E.to_csv(P+'usa_fashion_other_excluded.csv',index=False)
tot=int(len(pd.read_pickle('/tmp/ns2.pkl')))
S={'generated_utc':datetime.datetime.utcnow().isoformat()+'Z','non_shopify_rows_in_master':tot,
 'rows_live_checked':int((pd.read_pickle('/tmp/res.pkl').live!='notchecked').sum()),
 'rows_not_live_checked_stored_category_not_fashion':int((pd.read_pickle('/tmp/res.pkl').live=='notchecked').sum()),
 'fashion_stores':len(O),'by_type':O.Type.value_counts().to_dict(),'by_gender':O.Gender.value_counts().to_dict(),
 'by_type_gender':{f'{a} / {b}':int(c) for (a,b),c in O.groupby(['Type','Gender']).size().items()},
 'by_platform':O.Platform.value_counts().to_dict(),'by_size_tier':O['Size Tier'].value_counts().to_dict(),
 'by_verification_status':O['Verification Status'].value_counts().to_dict(),
 'excluded_by_reason':E['Exclusion Reason'].value_counts().to_dict(),
 'excluded_listed_rows':len(E),
 'notable_majors':O[O['Size Tier']=='Brand-Major']['Store Name'].tolist()}
json.dump(S,open(P+'usa_fashion_other_summary.json','w'),indent=1)
print(len(O),len(E))
