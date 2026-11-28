#!/usr/bin/env python3
"""Золото на независимых годах 2014-2017: часовой истории нет, поэтому тот же метод на барах H4 из MT4 (48 часовых свечей = 12 четырехчасовых).
Сначала сверка H4-версии с H1/M5 на 2018-2024. Запуск: python -I gold_old.py XAUUSD240.hst"""
import sys, datetime as dt, itertools, statistics as S
import numpy as np
H = np.dtype([('t', '<i8'), ('o', '<f8'), ('h', '<f8'), ('l', '<f8'), ('c', '<f8'), ('v', '<i8'), ('sp', '<i4'), ('rv', '<i8')])
ts = lambda y: int(dt.datetime(y, 1, 1, tzinfo=dt.timezone.utc).timestamp()); year = lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc).year
b = open(sys.argv[1], 'rb').read(); A = np.frombuffer(b, H, (len(b) - 148) // 60, 148); A = A[A['t'] < ts(2025)]
T = A['t'].tolist(); O, Hi, L, C = (A[x].tolist() for x in 'ohlc'); aH, aL, aO = np.array(A['h']), np.array(A['l']), np.array(A['o'])
SP, COM, LB = 0.30, 0.07, 120           # спред $0.30, комиссия $0.07 за унцию
days = {}
for t, h, l in zip(T, Hi, L):
    k = t // 86400; x = days.setdefault(k, [h, l]); x[0] = max(x[0], h); x[1] = min(x[1], l)
keys = sorted(days); rng = [days[k][0] - days[k][1] for k in keys]; atr = {k: (sum(rng[q-20:q]) / 20 if q >= 20 else None) for q, k in enumerate(keys)}; ATR = [atr[t // 86400] for t in T]
def zones(N, k):
    Z = []; i = N + LB; floor = i - N
    while i < len(C):
        a = i - N + 1
        if a < floor or ATR[i] is None: i += 1; continue
        top = max(max(O[a:i+1]), max(C[a:i+1])); bot = min(min(O[a:i+1]), min(C[a:i+1])); R = top - bot
        if R <= 0 or R > k * ATR[i]: i += 1; continue
        e = i + 1
        while e < len(C) and bot - 0.5 * R <= C[e] <= top + 0.5 * R: e += 1
        if e >= len(C): break
        Z.append(dict(e=e, top=top, bot=bot, R=R, d=1 if C[e] > top else -1)); floor = e + 1; i = e + N
    for z in Z:
        edge = z['top'] if z['d'] > 0 else z['bot']; z['kill'] = next((j for j in range(z['e'] + 1, len(C)) if z['d'] * (edge - C[j]) > 0.85 * z['R']), None)
    return Z
def play(j, side, e, sl, tp, hold=0):
    off = SP if side < 0 else 0; i = j; lim = T[j] + hold * 86400 if hold else None
    while i < len(C):
        if lim and T[i] >= lim: return side * (O[i] + off - e), i
        if side * ((L[i] if side > 0 else Hi[i]) + off - sl) <= 0:
            o = O[i] + off; return side * ((sl if side * (o - sl) > 0 else o) - e), i
        if side * ((Hi[i] if side > 0 else L[i]) + off - tp) >= 0: return side * (tp - e), i
        i += 1
    return side * (C[-1] + off - e), len(C) - 1
Zc = {}
def sig(N, k):
    if (N, k) not in Zc:
        out = []
        for z in zones(N, k):
            q = z['kill']
            if q is None or q - z['e'] > LB or q + 1 >= len(C): continue
            side = -z['d']; e = z['e']; far = float(aH[e:q+1].max()) if side < 0 else float(aL[e:q+1].min()); j = q + 1
            entry = O[j] + (SP if side > 0 else 0); sl = far + (SP if side < 0 else 0); risk = side * (entry - sl)
            if 0 < risk <= 2.5 * z['R'] and ATR[q]: out.append(dict(j=j, side=side, entry=entry, risk=risk, fast=q - e <= 6))
        Zc[(N, k)] = out
    return Zc[(N, k)]
def trades(N=12, k=1.0, rr=2.0, lo=2014, hi=2017, swap=False, hold=0, fast=False):
    out = []; free = 0
    for s in sig(N, k):
        if s['j'] <= free or (fast and not s['fast']): continue
        side, e, r = s['side'], s['entry'], s['risk']; g, i = play(s['j'], side, e, e - side * r, e + side * rr * r, hold); free = i
        p = g - COM
        if swap: p -= (0.0473 if side > 0 else -0.0150) / 365 * e * (T[i] // 86400 - T[s['j']] // 86400)
        if lo <= year(T[s['j']]) <= hi: out.append((T[s['j']], p / r, side, s))
    return out
def pf(t):
    g = sum(x[1] for x in t if x[1] > 0); l = -sum(x[1] for x in t if x[1] < 0); return g / l if l else 0
f = lambda t: f"{pf(t):.2f} ({len(t)}, {sum(x[1] for x in t):+.1f}R)"
print('бары H4', len(T), dt.datetime.fromtimestamp(T[0], dt.timezone.utc).date(), '-', dt.datetime.fromtimestamp(T[-1], dt.timezone.utc).date(), '| цена', C[0], '->', C[-1])
for lab, lo, hi in (('сверка 2018–2024', 2018, 2024), ('независимые 2014–2017', 2014, 2017)):
    print(f'== {lab}')
    for sw in (False, True):
        t = trades(lo=lo, hi=hi, swap=sw); print(f"  базовый, {'с платой за перенос' if sw else 'без переноса'}: {f(t)} | покупки {f([x for x in t if x[2]>0])} продажи {f([x for x in t if x[2]<0])}")
    print('    по годам:', {y: f([x for x in trades(lo=lo, hi=hi) if year(x[0]) == y]) for y in range(lo, hi + 1)})
    q = [trades(N, k, rr, lo, hi) for N, k, rr in itertools.product((8, 10, 12, 14, 16), (0.8, 1.0, 1.2, 1.4), (1.0, 1.5, 2.0, 2.5, 3.0))]
    print(f'  100 соседних настроек (без переноса): медиана PF {S.median(map(pf, q)):.2f}, плюс {sum(pf(x)>1 for x in q)}/100, PF>=1.3: {sum(pf(x)>=1.3 for x in q)}/100')
    print('  вариант «быстрая отмена + выход через 7 дней» (золото):', f(trades(lo=lo, hi=hi, hold=7, fast=True)))
    base = trades(lo=lo, hi=hi); rng_ = np.random.default_rng(1); js = [i for i in range(LB, len(C) - 1) if lo <= year(T[i]) <= hi]; res = []
    for _ in range(1000):
        tr = []
        for x in base:
            s = x[3]; side = x[2]; j = int(rng_.choice(js)); e = O[j] + (SP if side > 0 else 0); r = s['risk'] / s['entry'] * e; g, i = play(j, side, e, e - side * r, e + side * 2 * r); tr.append((0, (g - COM) / r))
        res.append(pf(tr))
    res = np.array(res); print(f'  случайные входы в ту же сторону: медиана {np.median(res):.2f}, 95% {np.quantile(res,.95):.2f}, не хуже метода {int((res>=pf(base)).sum())}/1000')
