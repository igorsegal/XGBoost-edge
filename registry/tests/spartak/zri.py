#!/usr/bin/env python3
"""«Зри в корень» (Спартак): уровни H1, разворотный момент на M5/M15, стоп за областью. Механизация слайдов.
Плюс советник LiquidityReversal_SMC из папки курса (M30). Запуск: python -I zri.py <бары> <отчёт.json>"""
import sys, os, json, bisect, datetime as dt, itertools
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from algo import load, UTC, CUT, us_summer

def atr(B, n=14):
    out = []; a = None; pc = None
    for h, l, c in zip(B['H'], B['L'], B['C']):
        tr = h - l if pc is None else max(h, pc) - min(l, pc); a = tr if a is None else a + (tr - a) / n; out.append(a); pc = c
    return out

def fractals(B, k):
    """(бар подтверждения, вид +1 впадина / -1 вершина, номер бара)."""
    H, L = B['H'], B['L']; res = []
    for i in range(k, len(H) - k):
        if L[i] == min(L[i-k:i+k+1]) and L[i] < min(L[i-k:i]): res.append((i + k, 1, i))
        if H[i] == max(H[i-k:i+k+1]) and H[i] > max(H[i-k:i]): res.append((i + k, -1, i))
    return sorted(res)

def trend_series(B, k):
    """По времени закрытия бара: +1 растущие вершины и впадины, -1 падающие, 0 иначе."""
    lo, hi, times, vals = [], [], [], []
    for c, kind, i in fractals(B, k):
        (lo if kind > 0 else hi).append(B['L'][i] if kind > 0 else B['H'][i])
        v = 0
        if len(lo) > 1 and len(hi) > 1:
            if lo[-1] > lo[-2] and hi[-1] > hi[-2]: v = 1
            elif lo[-1] < lo[-2] and hi[-1] < hi[-2]: v = -1
        times.append(B['T'][c] + B['per']); vals.append(v)
    return times, vals

def zones_events(H1, k, A):
    """События по закрытию баров H1: новые уровни (вершина или впадина)."""
    ev = {}
    for c, kind, i in fractals(H1, k):
        o, cl = H1['O'][i], H1['C'][i]; w = 0.15 * A[i]
        if kind > 0: lo = H1['L'][i]; hi = max(min(o, cl), lo + w)
        else: hi = H1['H'][i]; lo = min(max(o, cl), hi - w)
        ev.setdefault(c, []).append((kind, lo, hi))
    return ev

def zri(E, H1, D1, p, costs=True):
    A1 = atr(H1); ev = zones_events(H1, p['k'], A1)
    tr = trend_series(H1, p['k']) if p['trend'] == 'H1' else trend_series(D1, 3) if p['trend'] == 'D1' else None
    zones = []; trades = []; pos = {1: None, -1: None}; hi_i = 0; n1 = len(H1['T'])
    O, H, L, C, SP, T, pt = (E[x] for x in ('O', 'H', 'L', 'C', 'SP', 'T', 'pt')); per = E['per']; pend = []
    com = lambda price: (7 / 100000 if abs(price) < 500 else 7 / 100 / 1) if costs else 0
    for j in range(len(T)):
        sp = SP[j] * pt if costs else 0
        for s, stop, tgt, z in pend:                       # вход на открытии бара после сигнала
            if pos[s] is not None: continue
            e = s * O[j] + (sp if s > 0 else 0); risk = e - stop
            if risk <= 2 * sp or risk <= 0: continue
            if p['target'] == 'уровень':
                cand = [(s * (q['lo'] if s > 0 else q['hi'])) for q in zones if q['dir'] == -s]
                cand = [c for c in cand if c - e >= risk]
                if not cand: continue
                tp = min(cand)
            else: tp = e + 3 * risk
            pos[s] = (e, stop, tp, T[j], risk)
        pend = []
        for s in (1, -1):
            if pos[s] is None: continue
            e, stop, tp, t0, risk = pos[s]
            if s > 0: o, hh, ll = O[j], H[j], L[j]
            else: o, hh, ll = -(O[j] + sp), -(L[j] + sp), -(H[j] + sp)
            x = None
            if ll <= stop: x = min(stop, o)
            elif hh >= tp: x = max(tp, o) if o >= tp else tp
            if x is not None:
                price = abs(e); c = 0
                if costs: c = price * 7 / 100000 if E['jpy'] else (0.07 if E['gold'] else 0.00007)
                trades.append((t0, T[j], s, (x - e - c) / risk, (x - e - c))); pos[s] = None
        now = T[j] + per
        while hi_i < n1 and H1['T'][hi_i] + H1['per'] <= now:      # закрылся бар H1
            a = A1[hi_i]; c = H1['C'][hi_i]; keep = []
            for z in zones:
                broken = c < z['lo'] - 0.1 * a if z['dir'] > 0 else c > z['hi'] + 0.1 * a
                if broken:
                    if z['flip']: continue
                    z = dict(dir=-z['dir'], lo=z['lo'], hi=z['hi'], born=hi_i, flip=True, st=None, used=False)
                if hi_i - z['born'] <= p['age']: keep.append(z)
            zones = keep
            for kind, lo, hi in ev.get(hi_i, []): zones.append(dict(dir=kind, lo=lo, hi=hi, born=hi_i, flip=False, st=None, used=False))
            hi_i += 1
        if hi_i < 30: continue
        a = A1[hi_i - 1]; t = 0
        if tr:
            m = bisect.bisect_right(tr[0], now) - 1; t = tr[1][m] if m >= 0 else 0
        for z in zones:
            s = z['dir']
            if z['used']: continue
            top, bot = (z['hi'], z['lo']) if s > 0 else (-z['lo'], -z['hi'])
            lo_ = L[j] if s > 0 else -H[j]; cl = s * C[j]
            if z['st'] is None:
                if lo_ <= top and cl >= bot - 0.5 * a and j > 0 and s * C[j-1] > top: z['st'] = [lo_, 0, lo_ < bot, j]
                continue
            st = z['st']; st[0] = min(st[0], lo_); st[2] = st[2] or lo_ < bot
            if cl < bot - 0.5 * a or j - st[3] > p['wait']: z['st'] = None; z['used'] = cl < bot - 0.5 * a; continue
            st[1] = st[1] + 1 if cl > top else 0
            if p['rm'] == 'закрепление': sig = st[1] >= 2
            elif p['rm'] == 'прорыв':
                prev = H[max(j-8, 0):j] if s > 0 else [-x for x in L[max(j-8, 0):j]]
                sig = bool(prev) and cl > max(prev)
            else: sig = st[2] and cl > top
            if sig:
                z['used'] = True
                if (tr is None or t == s) and pos[s] is None and not any(q[0] == s for q in pend):
                    pend.append((s, st[0] - 0.1 * a, None, z))
    return trades

def ea(M30, H4, p, costs=True):
    """LiquidityReversal_SMC, режим B (строгие фильтры), как в коде: безубыток и тейк в R; после безубытка прочее не срабатывает."""
    O, H, L, C, SP, T, pt = (M30[x] for x in ('O', 'H', 'L', 'C', 'SP', 'T', 'pt'))
    digits = len(f'{pt:.8f}'.rstrip('0').split('.')[1]); pip = pt * 10 if digits in (3, 5) else pt
    A = []; trs = []
    for i in range(len(T)):
        trs.append(H[i] - L[i] if i == 0 else max(H[i], C[i-1]) - min(L[i], C[i-1])); A.append(sum(trs[max(0, i-13):i+1]) / min(i + 1, 14))
    e200 = []; v = None
    for c in H4['C']: v = c if v is None else v + (c - v) * 2 / 201; e200.append(v)
    h4end = [t + H4['per'] for t in H4['T']]; trades = []; pos = {1: None, -1: None}; nb = p['swing']
    for j in range(nb + 6, len(T)):
        sp = SP[j] * pt if costs else 0
        b1, b2 = j - 1, j - 2; hour = ((T[j] + (10800 if us_summer(T[j] - T[j] % 3600) else 7200)) % 86400) // 3600
        sig = []
        if 8 <= hour <= 22 and sp <= 25 * pip:
            m = bisect.bisect_right(h4end, T[j]) - 1
            ema = None if m < 200 else e200[m] + (O[j] - e200[m]) * 2 / 201
            body = C[b1] - O[b1]
            bull = C[b1] >= min(L[j-5-nb+1:j-4]) and body > 0 and O[b1] < C[b2] and C[b1] > O[b2] and body >= p['engulf'] * (O[b2] - C[b2])
            bear = C[b1] <= max(H[j-5-nb+1:j-4]) and -body > 0 and O[b1] > C[b2] and C[b1] < O[b2] and -body >= p['engulf'] * (C[b2] - O[b2])
            if ema is not None and not (bull and O[j] < ema) and not (bear and O[j] > ema):
                for s, ok in ((1, bull), (-1, bear)):
                    if ok and (not p['strict'] or (s * body / pip >= 18 and abs(body) >= 0.75 * A[b1])): sig.append(s)
        for s in sig:
            if pos[s] is not None: continue
            e = O[j] + sp if s > 0 else O[j]
            ext = min(L[j-nb:j]) if s > 0 else max(H[j-nb:j]); sl = ext - s * A[b1] * p['atr']
            risk = s * (e - sl)
            if risk <= 0 or (s * ((O[j] + sp if s > 0 else O[j]) - sl)) / pip > p['maxsl']: continue
            pos[s] = [e, sl, e + s * risk * p['rr'], risk, T[j], False]
        for s in (1, -1):
            if pos[s] is None: continue
            e, sl, tp, risk, t0, be = pos[s]; off = 0 if s > 0 else sp
            o = O[j] + off; worst = (L[j] if s > 0 else H[j]) + off; best = (H[j] if s > 0 else L[j]) + off; x = None
            if s * (worst - sl) <= 0: x = sl if s * (o - sl) > 0 else o
            elif s * (best - tp) >= 0: x = tp
            if x is not None:
                c = 0
                if costs: c = e * 7 / 100000 if M30['jpy'] else (0.07 if M30['gold'] else 0.00007)
                trades.append((t0, T[j], s, (s * (x - e) - c) / risk, s * (x - e) - c)); pos[s] = None
            elif not be and s * (best - e) >= p['be'] * risk: pos[s][1] = e + s * 5 * pt; pos[s][5] = True
    return trades

def stats(tr):
    x = [t[3] for t in tr]; g = sum(v for v in x if v > 0); l = -sum(v for v in x if v < 0); y = {}
    for t in tr:
        k = dt.datetime.fromtimestamp(t[0], UTC).year; y[k] = round(y.get(k, 0) + t[3], 1)
    return dict(n=len(x), R=round(sum(x), 1), pf=round(g / l, 3) if l else 0, years=y)

PAIRS = ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'XAUUSD']
GRID = [dict(k=5, age=500, wait=48, tf=a, rm=b, trend=c, target=d) for a, b, c, d in itertools.product(
    ('M15', 'M5'), ('закрепление', 'прорыв', 'ложный пробой'), ('нет', 'H1', 'D1'), ('уровень', '3R'))]
EAS = {'v1.25 строгий': dict(swing=18, engulf=1.2, atr=1.0, maxsl=400, rr=5, be=1.5, strict=True),
       'v1.25 без строгости': dict(swing=18, engulf=1.2, atr=1.0, maxsl=400, rr=5, be=1.5, strict=False),
       'v1.21': dict(swing=20, engulf=1.0, atr=1.5, maxsl=10**9, rr=8, be=2.0, strict=False)}

def get(root, pair, tf, cutoff=CUT):
    B = load(f'{root}/{pair}/{pair}_{tf}.bin', cutoff); B['jpy'] = pair == 'USDJPY'; B['gold'] = pair == 'XAUUSD'; return B

def work(arg):
    root, pair = arg; res = {}
    D = {tf: get(root, pair, tf) for tf in ('M5', 'M15', 'M30', 'H1', 'H4', 'D1')}
    for p in GRID:
        name = f"{p['tf']} {p['rm']} тренд:{p['trend']} цель:{p['target']}"
        res[f'{pair} | {name}'] = dict(net=stats(zri(D[p['tf']], D['H1'], D['D1'], p)), gross=stats(zri(D[p['tf']], D['H1'], D['D1'], p, False)))
    for name, p in EAS.items():
        res[f'{pair} | советник {name}'] = dict(net=stats(ea(D['M30'], D['H4'], p)), gross=stats(ea(D['M30'], D['H4'], p, False)))
    print('готово', pair, flush=True); return res

if __name__ == '__main__':
    root = sys.argv[1]
    with Pool(min(len(PAIRS), os.cpu_count())) as P: out = P.map(work, [(root, q) for q in PAIRS])
    res = {k: v for d in out for k, v in d.items()}; json.dump(res, open(sys.argv[2], 'w'), ensure_ascii=False)
    big = {k: v for k, v in res.items() if v['net']['n'] >= 100}
    print('прогонов', len(res), 'с 100+ сделками', len(big))
    for k, v in sorted(big.items(), key=lambda kv: -kv[1]['net']['pf'])[:12]: print(k, v['net'], '| без издержек', v['gross']['pf'])
    for k, v in res.items():
        if 'советник' in k: print(k, v['net']['n'], v['net']['pf'], v['gross']['pf'])
    import statistics as st
    print('медиана PF', st.median(v['net']['pf'] for v in big.values()), 'без издержек', st.median(v['gross']['pf'] for v in big.values()))
