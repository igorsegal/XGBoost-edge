#!/usr/bin/env python3
"""Проверки: соседи прошедших вариантов, случайные входы, заглядывание в будущее. Запуск: python -I deep_check.py <raw> <sig.pkl>"""
import sys, os, itertools, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import numpy as np
raw, sig = sys.argv[1:3]; sys.argv = [sys.argv[0], sig]
import io, contextlib
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'deep_an.py'), encoding='utf-8').read(); exec(src.split("print('== 1.")[0])
GOLDS = ['XAUUSD', 'XAUAUD', 'XAUEUR']
data = {s: D(raw, s) for s in R}
def baseline(N, k, rr, hold, flt, syms=None, runs=500, seed=1):
    t = trades(N, k, rr, hold, flt, syms=syms); idx = {(s['sym'], s['t']): s for sym in R for s in R[sym][(N, k)]}
    rng = np.random.default_rng(seed); out = []
    for _ in range(runs):
        tr = []
        for x in t:
            s = idx[(x[3], x[0])]; d = data[x[3]]; j = int(rng.integers(0, len(d.mt) - 3000)); side = x[2]
            e = float(d.mo[j]) + (float(d.msp[j]) if side > 0 else 0); risk = s['risk'] / s['entry'] * e
            g, i = follow(d, j, side, e, e - side * risk, e + side * rr * risk, hold); night = int(d.mt[i]) // 86400 - int(d.mt[j]) // 86400
            p = g - com(d.sym, e) - FEE[d.sym][0 if side > 0 else 1] / 365 * e * night
            tr.append((int(d.mt[j]), p / risk, side))
        out.append(pf(tr))
    out = np.array(out); return pf(t), len(t), float(np.median(out)), float(np.quantile(out, .95)), int((out >= pf(t)).sum()), runs
print('== варианты, прошедшие PF>=1.3 в обоих периодах (издержки брокера, >=100 сделок в 2018–22)')
allc = []
for N, k, rr, hold, flt in itertools.product(NS, KS, RRS, HOLDS, NAMES):
    a, b = split(trades(N, k, rr, hold, flt))
    if len(a) >= 100 and pf(a) >= 1.3 and pf(b) >= 1.3: allc.append((N, k, rr, hold, flt))
for c in allc:
    t = trades(*c); a, b = split(t)
    print(c, f'всё {f(t)} | {f(a)} | {f(b)} | без 10 лучших {pf(sorted(t, key=lambda x: -x[1])[10:]):.2f}')
    p, n, med, q95, ge, runs = baseline(*c); print(f'     случайные входы: медиана {med:.2f}, 95% {q95:.2f}, не хуже метода {ge}/{runs}')
if allc:
    N, k, rr, hold, flt = allc[0]
    print('  соседи первого (PF всё): свечи', {n: round(pf(trades(n, k, rr, hold, flt)), 2) for n in NS}, '\n  ширина', {x: round(pf(trades(N, x, rr, hold, flt)), 2) for x in KS}, '\n  цель', {x: round(pf(trades(N, k, x, hold, flt)), 2) for x in RRS}, '\n  срок', {x: round(pf(trades(N, k, rr, x, flt)), 2) for x in HOLDS})
    by = trades(*allc[0]); print('  по группам:', {g: f([x for x in by if x[3] in v]) for g, v in (('металлы', METALS), ('нефть', OIL), ('индексы', INDICES))}, '\n  по годам:', {y: f([x for x in by if year(x[0]) == y]) for y in range(2018, 2025)})
print('\n== золото (XAUUSD, XAUAUD, XAUEUR), базовый вариант')
t = trades(syms=GOLDS); a, b = split(t); print(f'  всё {f(t)} | 2018–22 {f(a)} | 2023–24 {f(b)} | покупки {f([x for x in t if x[2]>0])} продажи {f([x for x in t if x[2]<0])}')
p, n, med, q95, ge, runs = baseline(48, 1.0, 2.0, 0, None, syms=GOLDS); print(f'  случайные входы в ту же сторону: медиана {med:.2f}, 95% {q95:.2f}, не хуже метода {ge}/{runs}')
gq = [trades(N, k, rr, 0, None, syms=GOLDS) for N, k, rr in BASE]; sp = [split(x) for x in gq]
import statistics as S
print(f'  100 соседних настроек: медиана PF 2018–22 {S.median(pf(a) for a, b in sp):.2f}, 2023–24 {S.median(pf(b) for a, b in sp):.2f}; плюс в обоих {sum(pf(a)>1 and pf(b)>1 for a, b in sp)}')
p, n, med, q95, ge, runs = baseline(48, 1.0, 2.0, 0, None); print(f'базовый, все инструменты: PF {p:.2f} ({n}); случайные: медиана {med:.2f}, 95% {q95:.2f}, не хуже {ge}/{runs}')
print('\n== заглядывание в будущее: сигналы на данных, обрезанных по 2023-01-01, против полных')
cut = int(dt.datetime(2023, 1, 1, tzinfo=UTC).timestamp()); total = bad = 0
for sym in R:
    d = D(raw, sym, cut)
    d.msp = data[sym].msp[:len(d.mt)]      # замена нулевых спредов та же, что в полном прогоне: сравниваются только сами сигналы
    for key in itertools.product(NS, KS):
        new = {s['t']: s for s in signals(d, *key)}; old = {s['t']: s for s in R[sym][key] if s['t'] < cut - 86400}
        for t, o in old.items():
            total += 1; n = new.get(t)
            if n is None or n['side'] != o['side'] or n['f'] != o['f'] or abs(n['entry'] - o['entry']) > o['sp'] + 1e-9 or any(n['res'][k2]['thin'] != o['res'][k2]['thin'] for k2 in n['res']): bad += 1
print(f'  проверено сигналов {total}, расхождений {bad}')
