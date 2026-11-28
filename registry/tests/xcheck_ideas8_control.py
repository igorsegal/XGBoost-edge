# -*- coding: utf-8 -*-
"""Независимая проверка контроля «выход по правилу» для ZSCORE_01 H4 и SEYKOTA_01 портфель H4.
Исход каждого возможного случайного входа считается заранее, затем 500 выборок.
Запуск: python xcheck_ideas8_control.py <папка BAZA> <папка trades>"""
import sys, os, csv, numpy as np
import xcheck_ideas8 as X

base, trdir = sys.argv[1], sys.argv[2]
rng = np.random.default_rng(7)


def run(vid, name, pairs):
    real, pools = [], []
    for pair in pairs:
        m = X.M1(base, pair)
        b = X.Bars(m, 14400)
        start = 1604188800 if pair == 'AUDUSD' else 1593561600
        rows = [r for r in csv.DictReader(open(os.path.join(trdir, f'{vid}__{name}__{pair}.csv'))) if r['counted'] == '1']
        real += [float(r['pnl']) / (10 * m.pt) for r in rows]
        if vid == 'ZSCORE_01':
            w = np.lib.stride_tricks.sliding_window_view(b.c, 20)
            z = np.full(b.n, np.nan)
            dev = b.c[19:] - w.mean(axis=1)
            dev[np.abs(dev) < 1e-9] = 0
            z[19:] = dev / w.std(axis=1)
        else:
            f, s, a = X.ema(b.c, 20), X.ema(b.c, 200), X.atr(b, 20)
        for d in (1, -1):
            cnt = sum(1 for r in rows if int(r['dir']) == d)
            out = []
            first = 21 if vid == 'ZSCORE_01' else 201
            for i in range(max(first, 61), b.n):
                if b.t[i] < start:
                    continue
                x = i - 1
                k = int(b.s[i])
                if vid == 'ZSCORE_01':
                    if not d * z[x] < 0:
                        continue
                    j = next((j for j in range(i + 1, b.n) if d * z[j - 1] >= 0), None)
                    px = m.mkt(d, int(b.s[j])) if j is not None else float(m.c[-1] if d > 0 else m.ac[-1])
                else:
                    if not d * (f[x] - s[x]) > 0:
                        continue
                    sl = m.ent(d, k) - d * 3.0 * a[x]
                    j = next((j for j in range(i + 1, b.n) if d * (f[j - 1] - s[j - 1]) < 0), None)
                    px = X.finish(m, d, k, sl, 0, None if j is None else int(b.s[j]))[1]
                out.append((d * (px - m.ent(d, k)) - m.comm * (m.ent(d, k) if m.byprice else 1.0)) / (10 * m.pt))
            pools.append((np.array(out), cnt))
    r = np.array(real)
    rpf = r[r > 0].sum() / -r[r <= 0].sum()
    nets, pfs, ok = [], [], 0
    for _ in range(500):
        q = np.concatenate([p[rng.integers(0, len(p), c)] for p, c in pools])
        net, pf = q.sum(), q[q > 0].sum() / -q[q <= 0].sum()
        nets.append(net)
        pfs.append(pf)
        ok += net > 0 and pf >= 1.3 and len(q) >= 100
    nets, pfs = np.array(nets), np.array(pfs)
    print(f'{vid} {name}: настоящий PF {rpf:.3f}; случайные медиана PF {np.median(pfs):.3f}; не хуже по нетто {100*(nets>=r.sum()).mean():.1f}%; по PF {100*(pfs>=rpf).mean():.1f}%; прошли планку {ok/5:.1f}%', flush=True)


for p in ('EURUSD', 'GBPUSD', 'AUDUSD'):
    run('ZSCORE_01', p + '_H4', [p])
run('SEYKOTA_01', 'PORTFOLIO_H4', ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD'])
