import sys, os, bisect, random, itertools, datetime as dt, statistics as st
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from zri import *
root = sys.argv[1]
M30, H4, M1 = get(root, 'USDJPY', 'M30'), get(root, 'USDJPY', 'H4'), get(root, 'USDJPY', 'M1')
BASE = EAS['v1.21']
base = ea(M30, H4, BASE); print('v1.21', stats(base))
for s, n in ((1, 'покупки'), (-1, 'продажи')): print(n, stats([t for t in base if t[2] == s]))
# 1. выходы по минутным барам
T1, O1, H1_, L1, SP1 = M1['T'], M1['O'], M1['H'], M1['L'], M1['SP']; pt = M1['pt']
def exact(entry_t, s, sl, rr, be, atr_risk=None):
    i = bisect.bisect_left(T1, entry_t); e = O1[i] + (SP1[i] * pt if s > 0 else 0); risk = s * (e - sl)
    if risk <= 0: return None
    tp = e + s * risk * rr; moved = False
    for j in range(i, len(T1)):
        off = 0 if s > 0 else SP1[j] * pt; o = O1[j] + off
        worst = (L1[j] if s > 0 else H1_[j]) + off; best = (H1_[j] if s > 0 else L1[j]) + off; x = None
        if s * (worst - sl) <= 0: x = sl if s * (o - sl) > 0 else o
        elif s * (best - tp) >= 0: x = tp
        if x is not None: return (entry_t, T1[j], s, (s * (x - e) - e * 7e-5) / risk, s * (x - e) - e * 7e-5)
        if not moved and s * (best - e) >= be * risk: sl = e + s * 5 * pt; moved = True
    return None
# стоп каждой сделки восстанавливаем так же, как в советнике
def entries(p):
    out = []
    for t in ea(M30, H4, p):
        j = bisect.bisect_left(M30['T'], t[0]); s = t[2]
        trs = [max(M30['H'][i], M30['C'][i-1]) - min(M30['L'][i], M30['C'][i-1]) for i in range(j - 14, j)]
        ext = min(M30['L'][j-p['swing']:j]) if s > 0 else max(M30['H'][j-p['swing']:j]); out.append((t[0], s, ext - s * sum(trs) / 14 * p['atr']))
    return out
m = [x for x in (exact(t, s, sl, BASE['rr'], BASE['be']) for t, s, sl in entries(BASE)) if x]
print('выходы по M1', stats(m))
# 2. соседние настройки
res = []
for sw, atr_, rr, be, eng in itertools.product((12, 20, 30), (1.0, 1.5, 2.0), (3, 5, 8), (1.0, 2.0, 99), (0.8, 1.0, 1.3)):
    s = stats(ea(M30, H4, dict(swing=sw, engulf=eng, atr=atr_, maxsl=10**9, rr=rr, be=be, strict=False))); res.append(s)
q = sorted(r['pf'] for r in res)
print('соседние настройки', len(q), 'медиана PF', st.median(q), 'доля >=1.3', round(sum(v >= 1.3 for v in q) / len(q), 2), 'доля >1', round(sum(v > 1 for v in q) / len(q), 2))
# 3. случайные входы: столько же покупок и продаж, тот же фильтр сессии и тренда, те же выходы
e200 = []; v = None
for c in H4['C']: v = c if v is None else v + (c - v) * 2 / 201; e200.append(v)
h4end = [t + H4['per'] for t in H4['T']]; T, O = M30['T'], M30['O']
pool = {1: [], -1: []}
for j in range(30, len(T)):
    h = ((T[j] + (10800 if us_summer(T[j] - T[j] % 3600) else 7200)) % 86400) // 3600
    k = bisect.bisect_right(h4end, T[j]) - 1
    if 8 <= h <= 22 and M30['SP'][j] * M30['pt'] <= 0.25 and k >= 200:
        pool[1 if O[j] >= e200[k] else -1].append(j)
cache = {}
def rnd(j, s):
    if (j, s) not in cache:
        trs = [max(M30['H'][i], M30['C'][i-1]) - min(M30['L'][i], M30['C'][i-1]) for i in range(j - 14, j)]
        ext = min(M30['L'][j-20:j]) if s > 0 else max(M30['H'][j-20:j])
        cache[(j, s)] = exact(T[j], s, ext - s * sum(trs) / 14 * 1.5, 8, 2.0)
    return cache[(j, s)]
nb = sum(t[2] > 0 for t in m); ns = len(m) - nb; random.seed(1); R = []; PF = []
for it in range(300):
    tr = []
    for s, n in ((1, nb), (-1, ns)):
        busy = 0; got = []
        cand = random.sample(pool[s], n * 3)
        for j in sorted(cand):
            if len(got) >= n * 1.0: pass
            if T[j] < busy: continue
            x = rnd(j, s)
            if x: got.append(x); busy = x[1]
        tr += random.sample(got, min(n, len(got)))
    z = stats(tr); R.append(z['R']); PF.append(z['pf'])
a = stats(m)
print('случайные входы: медиана PF', st.median(PF), 'медиана R', st.median(R), '| не хуже советника по PF', round(sum(v >= a['pf'] for v in PF) / len(PF), 3), 'по R', round(sum(v >= a['R'] for v in R) / len(R), 3))
# 4. чувствительность к источнику котировок: условие разрыва между барами
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'zri.py'), encoding='utf-8').read()
alt = src.replace('O[b1] < C[b2] and', 'O[b1] <= C[b2] and').replace('O[b1] > C[b2] and', 'O[b1] >= C[b2] and')
ns_ = {'__name__': 'alt', '__file__': __file__}; exec(compile(alt, 'alt', 'exec'), ns_)
for n, p in EAS.items(): print('нестрогий разрыв USDJPY', n, ns_['stats'](ns_['ea'](M30, H4, p)))
for shift in (1, 3):
    O2 = list(M30['O']); random.seed(shift)
    pts = [O2[i] + random.randint(-shift, shift) * M30['pt'] for i in range(len(O2))]
    B = dict(M30); B['O'] = pts; print(f'цены открытия сдвинуты на ±{shift} пункта', stats(ea(B, H4, BASE)))
for pr in PAIRS:
    B, G = get(root, pr, 'M30'), get(root, pr, 'H4')
    if pr == 'XAUUSD':
        src2 = src.replace('sp <= 25 * pip', 'sp <= 10**9'); ns2 = {'__name__': 'g', '__file__': __file__}; exec(compile(src2, 'g', 'exec'), ns2)
        for n, p in EAS.items(): print('золото без ограничения спреда', n, ns2['stats'](ns2['ea'](B, G, p)))
