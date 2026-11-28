# сверка исходов сделок простым циклом по барам M5 + цифры по прежним 14 инструментам
import sys, os, random, io
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.argv=[sys.argv[0],'sig.pkl']
src=open('deep_an.py',encoding='utf-8').read(); exec(src.split("print('== 1.")[0])
data={s:D('/mnt/user-data/uploads/raw',s) for s in R}; random.seed(5); bad=n=0
pool=[(sym,key,s) for sym in R for key,v in R[sym].items() for s in v]
for sym,key,s in random.sample(pool,600):
    d=data[sym]; rr=random.choice(RRS); hold=random.choice(HOLDS); side=s['side']; e=s['entry']; r=s['risk']; sl=e-side*r; tp=e+side*rr*r
    j=int(np.searchsorted(d.mt,s['t'])); i=j; x=None
    while i<len(d.mt):
        off=float(d.msp[i]) if side<0 else 0.0; o=float(d.mo[i])+off
        if hold and d.mt[i]>=d.mt[j]+hold*86400: x=o; break
        worst=float(d.ml[i] if side>0 else d.mh[i])+off; best=float(d.mh[i] if side>0 else d.ml[i])+off
        if side*(worst-sl)<=0: x=sl if side*(o-sl)>0 else o; break
        if side*(best-tp)>=0: x=tp; break
        i+=1
    if x is None: i=len(d.mt)-1; x=float(d.mc[i])+(float(d.msp[i]) if side<0 else 0)
    v=s['res'][(rr,hold)]; n+=1; bad+= abs(side*(x-e)-com(sym,e)-v['pnl'])>1e-9 or int(d.mt[i])!=v['tout']
print('выборочная сверка исходов:',n,'расхождений',bad)
old=['XAGUSD','DJ30','GER40','UK100','EU50','FRA40','HK50','CHINA50','SPI200','US2000','USOUSD','UKOUSD','XAGAUD','XAUAUD']
for c in ('без переноса','брокер'): print('прежние 14, база,',c,f(trades(syms=old,cost=c)))
