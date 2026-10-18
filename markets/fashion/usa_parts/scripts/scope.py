import pandas as pd,re
s=pd.read_pickle('/tmp/w/shop.pkl')
s['cat']=s['Source Category'].fillna('')
FASH={'Apparel & Fashion','Fashion & Apparel','Fashion - Women','Fashion - Sportswear & Streetwear','Fashion - Men','Fashion - Activewear & Streetwear'}
NOT={'Food & Beverage','Furniture','Tools, Hardware & Industrial','Automotive & Powersports','Pet Supplies','Garden & Outdoor Living','Home Improvement & Hardware','Firearms Accessories & Tactical','Computers & Electronics','Musical Instruments & Gear','Lighting & Electrical','Automotive Parts & Accessories','Industrial & Tools','Grocery & Food','Garden & Agriculture','Chocolates, Candy & Baked Goods','Coffee & Tea','Vape, Smoke & Tobacco','Wine, Beer & Spirits','Home Appliances','CBD, Vape & Smoke','Health, Vitamins & Supplements','Gaming','Cleaning & Household Supplies','Medical Supplies & Equipment','Electronic Components & Hobby Electronics','Marine & RV','Wholesale & B2B Supplies','Kitchen & Dining','Pharmacy & Wellness','Beverages, Wine & Spirits','Electronic Components','Candy, Chocolate & Bakery','Bikes & Micromobility','Pharmacy & Medical Supplies','Hunting, Firearms Accessories & Tactical','Packaging & Shipping Supplies','Wholesale & B2B','Building Materials','Chocolates & Sweets','Healthcare & Medical Equipment','Agriculture & Gardening','Tires & Wheels','Smoke & Vape Accessories','Electronics & Accessories','Mobiles & Accessories','Kitchenware & Tableware','Home & Kitchen','Bedding & Bath','Bedding, Mattresses & Textiles','Flowers, Gifts & Party','Beauty & Cosmetics','Fragrance','Fragrances','Perfume & Fragrance','Flowers, Gifts & Party','Office & School Supplies'}
KW=re.compile(r"apparel|clothing|clothes|wear\b|tees?\b|t-?shirt|hoodie|denim|jeans|threads|outfit|boutique|fashion|couture|lingerie|swim|activewear|streetwear|merch|attire|dress|style|closet|wardrobe|co\.|goods|supply|brand",re.I)
def sc(r):
    c=r['cat']
    if c in FASH: return 'fashion'
    if c in NOT: return 'not' if not re.search(r"apparel|clothing|tees?\b|t-?shirt|hoodie|denim|boutique|fashion|lingerie|swim|activewear|streetwear|merch|threads",r['Store Name'],re.I) else 'maybe'
    return 'maybe'
s['pre']=s.apply(sc,axis=1)
print(s.pre.value_counts())
s.to_pickle('/tmp/w/scoped.pkl')
