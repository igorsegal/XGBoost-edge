#!/usr/bin/env python3
"""1) проверка на заглядывание вперед обрезкой истории; 2) случайные входы с теми же выходами для заметных результатов."""
import sys, os, random, bisect
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import woodie as W
from algo import load
root = sys.argv[1]; cut = 1672531200   # 2023-01-01
bad = 0
for pair in ('EURUSD', 'USDJPY'):
    full = W.Data(root, pair); part = W.Data(root, pair)
    for B in (part.m1, part.h1):
        n = bisect.bisect_left(B['T'], cut)
        for x in ('T', 'O', 'H', 'L', 'C', 'V', 'SP'): B[x] = B[x][:n]
    P = W.Data.__new__(W.Data); P.__dict__.update(part.__dict__); B = P.h1
    P.T, P.O, P.H, P.L, P.C = (B[x] for x in ('T', 'O', 'H', 'L', 'C')); P.G4, P.i4 = W.group(B, 14400); P.GD, P.iD = W.group(B, 86400); P.st, P.up, P.lo = W.trail(P.G4); P.cache = {}
    P.dstart = {}
    for i, k in enumerate(P.iD): P.dstart.setdefault(k, i)
    P.hour = P.hour[:len(P.T)]
    a = W.jobs_for(full); b = W.jobs_for(P); lim = cut - 40 * 86400
    for n in a:
        x = [t for t in a[n](True) if t[0] < lim]; y = [t for t in b[n](True) if t[0] < lim]
        if x != y: bad += 1; print('РАСХОЖДЕНИЕ', pair, n, len(x), len(y))
    print(pair, 'проверено вариантов', len(a), 'расхождений всего', bad, flush=True)

def baseline(pair, name, yellow, mode, runs=300):
    D = W.Data(root, pair); real = W.run_h4(D, yellow, mode, True); rs = W.stats(real)
    G = D.G4; start = {}
    for i, k in enumerate(D.i4): start.setdefault(k, i)
    res = []
    for r in range(runs):
        rnd = random.Random(r); cand = list(range(60, len(G) - 1)); rnd.shuffle(cand); tr = []; busy = []
        for k in cand:
            if len(tr) >= rs['n']: break
            s = D.st[k]
            if not s: continue
            t = D.T[start[k+1]]; m = k + 1
            while m < len(G) - 1 and D.st[m] == s: m += 1
            x = W.execute(D, t, s, [(1, None)], None, costs=True, limit=D.T[start[min(m + 1, len(G) - 1)]])
            if not x or any(t <= e and x[1] >= b for b, e in busy): continue
            busy.append((t, x[1])); tr.append((t, x[0]))
        res.append(W.stats(tr))
    pf = sorted(z['pf'] for z in res); better = sum(z['pf'] >= rs['pf'] for z in res)
    print(name, pair, 'система', rs['n'], rs['pips'], rs['pf'], '| случайные: медиана PF', pf[len(pf)//2], 'не хуже системы', f'{better}/{runs}', rs['years'])

for y in (5, 6): baseline('USDJPY', f'H4 столбик {y}, до смены шлейфа', y, 'до смены шлейфа')
