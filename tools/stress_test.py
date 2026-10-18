import pandas as pd, numpy as np, os, shutil, sys, subprocess, random
random.seed(1); np.random.seed(1)
src=sys.argv[1] if len(sys.argv)>1 else 'data'; dst='stress/data'; shutil.rmtree('stress',ignore_errors=True); os.makedirs(dst)
R={n:pd.read_csv(f'{src}/{n}.csv',dtype=str,keep_default_na=False) for n in "customers products sellers locations orders order_items payments shipping returns".split()}
def mut(df,col,frac,fn):
    idx=df.sample(frac=frac,random_state=2).index; df.loc[idx,col]=df.loc[idx,col].map(fn)
# new labels / spellings
mut(R['products'],'category',.05,lambda v:'Pet Supplies')            # totally new category
mut(R['products'],'category',.05,lambda v:v.upper()+' ')             # case/space
mut(R['orders'],'order_status',.02,lambda v:'Out for Delivery')       # new status
mut(R['orders'],'order_status',.02,lambda v:'CANCELED')
mut(R['payments'],'payment_method',.03,lambda v:'Apple Pay')
mut(R['payments'],'payment_method',.03,lambda v:'Credit/Debit Card')
mut(R['customers'],'gender',.05,lambda v:'N/A')
# new date formats
mut(R['orders'],'order_date',.02,lambda v:v.replace('-','.') if '-' in v else v)       # 2024.11.23? (only iso ones)
mut(R['orders'],'order_date',.01,lambda v:'20240512')
mut(R['orders'],'order_date',.01,lambda v:'NULL')
mut(R['shipping'],'shipped_date',.02,lambda v:'2024-05-12 14:33:00')
mut(R['payments'],'payment_date',.02,lambda v:'12-May-2024')
# numeric weirdness
mut(R['order_items'],'unit_price',.01,lambda v:'PKR 1,250.50')
mut(R['order_items'],'quantity',.01,lambda v:'Two')
mut(R['order_items'],'quantity',.005,lambda v:'N/A')
mut(R['products'],'list_price',.01,lambda v:'N/A')
# missing strings
mut(R['customers'],'email',.05,lambda v:'null')
mut(R['customers'],'city_id',.05,lambda v:'N/A')
# extra column + reorder + header case on one table
R['orders']['new_col']='x'; R['orders']=R['orders'][R['orders'].columns[::-1]]
# duplicate primary key w/ different content, orphan seller, new city
R['sellers']=pd.concat([R['sellers'],R['sellers'].head(3).assign(seller_name='CHANGED')])
R['order_items'].loc[R['order_items'].sample(50,random_state=3).index,'seller_id']='S9999'
R['order_items'].loc[R['order_items'].sample(50,random_state=4).index,'product_id']=''
R['orders'].loc[R['orders'].sample(50,random_state=5).index,'ship_city_id']='99999'
for n,df in R.items(): df.to_csv(f'{dst}/{n}.csv',index=False)
