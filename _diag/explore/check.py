import time, pandas as pd, numpy as np
from _diag.explore.harness import *
t=time.time(); df=load_all(); print("load",time.time()-t, len(df))
t=time.time(); r=run(df,{},tests=["2324","2425","2526"]); print("run",time.time()-t, len(r))
old=pd.read_csv("_diag/xg_matches.csv"); old=old[old.model=="xg_w0.3"]
m=r.merge(old,on="match_id")
print(len(m), np.abs(m.p_h-m.p_home_win).max(), np.abs(m.p_d-m.p_draw).max())
print("ll new",ll(r).mean(),"old",old.log_loss.mean())
