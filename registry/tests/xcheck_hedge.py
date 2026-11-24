# Независимая проверка: Hedge + симуляция сделок на Python (код отдельный от C++)
import struct, math
def load(p):
    b=open(p,'rb').read(); sl,=struct.unpack('<i',b[56:60]); off=60+sl; n,=struct.unpack('<q',b[32:40]); pt,=struct.unpack('<d',b[24:32])
    R=[struct.unpack('<qddddqiq',b[off+60*i:off+60*(i+1)]) for i in range(n)]
    return pt,[r[0] for r in R],[r[1] for r in R],[r[2] for r in R],[r[3] for r in R],[r[4] for r in R],[r[6] for r in R]
pt,T,O,H,L,C,SP=load((__import__('sys').argv[1] if len(__import__('sys').argv)>1 else r'D:\AHexaTrader\1DataFiles\raw\EURUSD\EURUSD_H1.bin')); n=len(C)
def sma(x,p):
    o=[None]*n; s=0
    for i in range(n):
        s+=x[i]
        if i>=p: s-=x[i-p]
        if i>=p-1: o[i]=s/p
    return o
def ema(x,p):
    k=2/(p+1); e=x[0]; o=[e]
    for i in range(1,n): e=x[i]*k+e*(1-k); o.append(e)
    return o
mf,ms=sma(C,10),sma(C,50); m20=sma(C,20)
sd=[None]*n
for i in range(19,n):
    w=C[i-19:i+1]; mu=sum(w)/20; sd[i]=math.sqrt(max(0,sum(v*v for v in w)/20-mu*mu))
rsi=[None]*n; ag=al=0
for i in range(1,15):
    d=C[i]-C[i-1]; ag+=max(d,0); al+=max(-d,0)
ag/=14; al/=14; rsi[14]=100 if al==0 else 100-100/(1+ag/al)
for i in range(15,n):
    d=C[i]-C[i-1]; ag=(ag*13+max(d,0))/14; al=(al*13+max(-d,0))/14; rsi[i]=100 if al==0 else 100-100/(1+ag/al)
ef,es=ema(C,12),ema(C,26); macd=[a-b for a,b in zip(ef,es)]; sg=ema(macd,9); hist=[a-b for a,b in zip(macd,sg)]
def votes(i):
    v=[0]*5
    if mf[i] is not None and ms[i] is not None: v[0]=1 if mf[i]>ms[i] else (-1 if mf[i]<ms[i] else 0)
    if rsi[i] is not None: v[1]=1 if rsi[i]<30 else (-1 if rsi[i]>70 else 0)
    if m20[i] is not None:
        up=m20[i]+2*sd[i]; lo=m20[i]-2*sd[i]; v[2]=1 if C[i]>up else (-1 if C[i]<lo else 0)
    v[3]=1 if hist[i]>0 else (-1 if hist[i]<0 else 0)
    if i>=19:
        mx=max(H[i-19:i+1]); mn=min(L[i-19:i+1]); v[4]=1 if C[i]>=mx else (-1 if C[i]<=mn else 0)
    return v
eta=math.sqrt(8*math.log(5)/2000); w=[0.2]*5; pv=[0]*5; sig=[0]*n
for i in range(n):
    if i>=1 and any(pv):
        s=1 if C[i]>C[i-1] else (-1 if C[i]<C[i-1] else 0)
        w=[wi*math.exp(-eta*(0.5-0.5*pv[k]*s)) for k,wi in enumerate(w)]; t=sum(w); w=[x/t for x in w]
    v=votes(i); pv=v
    if i>=59:
        e=sum(w[k]*v[k] for k in range(5)); sig[i]=1 if e>=0.2 else (-1 if e<=-0.2 else 0)
# ATR14 (простое среднее TR)
tr=[H[0]-L[0]]+[max(H[i]-L[i],abs(H[i]-C[i-1]),abs(L[i]-C[i-1])) for i in range(1,n)]
atr=[None]*n
for i in range(13,n): atr[i]=sum(tr[i-13:i+1])/14
end=T[-1]+3600; Y=365*86400; s0=end-5*Y; s2=s0+4*Y
comm=7/100000; free=0; trades=[]
for x in range(n-1):
    if not sig[x] or T[x]<s0-3600 or x<free or atr[x] is None: continue
    if T[x+1]<s0: continue
    e=x+1
    if e+23>=n: break
    d=2*atr[x]; sp=SP[e]*pt; dirn=sig[x]
    entry=O[e]+sp if dirn>0 else O[e]; stop=entry-d if dirn>0 else entry+d
    exitp=None
    for k in range(e,e+24):
        if dirn>0:
            if k>e and O[k]<=stop: exitp=O[k]; break
            if L[k]<=stop: exitp=stop; break
        else:
            a_o=O[k]+SP[k]*pt; a_h=H[k]+SP[k]*pt
            if k>e and a_o>=stop: exitp=a_o; break
            if a_h>=stop: exitp=stop; break
    if exitp is None: k=e+23; exitp=C[k] if dirn>0 else C[k]+SP[k]*pt
    pnl=(exitp-entry if dirn>0 else entry-exitp)-comm
    trades.append((T[e],pnl/(10*pt))); free=k
cl=[p for t,p in trades if t>=s2]
gw=sum(p for p in cl if p>0); gl=-sum(p for p in cl if p<0)
print('clean trades',len(cl),'net',round(sum(cl),1),'PF',round(gw/gl,3))
