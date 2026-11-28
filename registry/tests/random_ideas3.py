#!/usr/bin/env python3
"""Случайные входы для тестов с нетто > 0 (500 прогонов) и сверка с заявлением автора по TOKYO_BREAK_01.
Запуск: python random_ideas3.py <каталог баров> <каталог сделок Python из xcheck_ideas3.py>"""
import sys, os, json, random, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xcheck_common import load, dev_windows, DEV_CUT, month
from xcheck_ideas3 import atr14, commission

bars, own = sys.argv[1:3]
def pf(v):
    g = sum(x for x in v if x > 0); l = -sum(x for x in v if x < 0); return g / l if l else float('inf')

def one(B, pair, e, d, dist, tdist, hold):
    sp = B['SP'][e] * B['pt']; entry = B['O'][e] + sp if d > 0 else B['O'][e]
    stop = entry - d * dist; tp = entry + d * tdist if tdist else None; ex = None
    end = min(e + hold, len(B['C'])) - 1
    for k in range(e, end + 1):
        s = B['SP'][k] * B['pt'] if d < 0 else 0
        o, h, l = B['O'][k] + s, B['H'][k] + s, B['L'][k] + s
        if k > e and d * (o - stop) <= 0: ex = o; break
        if d * ((l if d > 0 else h) - stop) <= 0: ex = stop; break
        if tp is not None and d * ((h if d > 0 else l) - tp) >= 0: ex = tp; break
    if ex is None: ex = B['C'][end] + (B['SP'][end] * B['pt'] if d < 0 else 0)
    return d * (ex - entry) - commission(pair, entry)

def run(name, B, pair, items, first, rule_net, seed):
    """items: (сторона, расстояние стопа, расстояние цели или 0, свечей удержания)"""
    rnd = random.Random(seed); n = len(B['C']); better = 0; nets = []
    for _ in range(500):
        s = 0.0
        for d, dist, tdist, hold in items: s += one(B, pair, rnd.randrange(first, n - hold), d, dist, tdist, hold)
        s /= 10 * B['pt']; nets.append(s); better += s >= rule_net
    nets.sort()
    print(f"  {name}: правило {rule_net:.1f} пп; случайные: середина {nets[250]:.1f}, 5% {nets[25]:.1f}, 95% {nets[475]:.1f}; не хуже правила {better / 5:.1f}%")
    return better / 500

W0 = None
for pair, suf in (('USDJPY', ''), ('USDJPY', '_pnn'), ('XAUUSD', ''), ('XAUUSD', '_pnn')):
    B = load(f'{bars}/{pair}/{pair}_H4.bin', DEV_CUT); A = atr14(B)
    sig = dict(json.load(open(f'{own}/iso_pnn_{pair}_H4{suf}.json'))['sig'])
    start = dev_windows(B['T'][0])[0][1]; n = len(B['C']); first = next(i for i in range(n) if B['T'][i] >= start)
    free = 0; tr = []
    for x in range(n - 1):   # те же сделки, что в тестере: сигнал, вход на следующей свече, 24 свечи или стоп
        if x not in sig or x + 1 < first or x < free or A[x] is None: continue
        e = x + 1
        if e + 23 >= n: break
        d = sig[x]; dist = 2 * A[x]; sp = B['SP'][e] * B['pt']; entry = B['O'][e] + sp if d > 0 else B['O'][e]; stop = entry - d * dist; k = e; ex = None
        for k in range(e, e + 24):
            s = B['SP'][k] * B['pt'] if d < 0 else 0; o = B['O'][k] + s; adverse = B['L'][k] if d > 0 else B['H'][k] + s
            if k > e and d * (o - stop) <= 0: ex = o; break
            if d * (adverse - stop) <= 0: ex = stop; break
        if ex is None: k = e + 23; ex = B['C'][k] + (B['SP'][k] * B['pt'] if d < 0 else 0)
        tr.append((e, d, dist, k - e + 1, d * (ex - entry) - commission(pair, entry))); free = k
    test = [t for t in tr if t[0] >= first]
    net = sum(t[4] for t in test) / (10 * B['pt'])
    print(f'ISO_PNN {pair} H4{suf}: сделок {len(test)}')
    run('удержание как у каждой сделки', B, pair, [(d, ds, 0, h) for _, d, ds, h, _ in test], first, net, 1)
    run('удержание по правилу, 24 свечи', B, pair, [(d, ds, 0, 24) for _, d, ds, h, _ in test], first, net, 2)

for pair in ('GBPUSD', 'EURUSD'):
    B = load(f'{bars}/{pair}/{pair}_M15.bin', DEV_CUT); data = json.load(open(f'{own}/tokyo_break_{pair}_M15.json'))
    start = dev_windows(B['T'][0])[0][1]; idx = {t: i for i, t in enumerate(B['T'])}; first = idx[next(t for t in B['T'] if t >= start)]
    test = [t for t in data['trades'] if t['t_in'] >= start]
    net = sum(t['pnl'] for t in test) / (10 * B['pt'])
    if net > 0:
        print(f'TOKYO_BREAK {pair} M15: сделок {len(test)}')
        items = [(t['d'], abs(t['entry'] - t['sl']), abs(t['tp'] - t['entry']), idx[t['t_out']] - idx[t['t_in']] + 1) for t in test]
        run('удержание как у каждой сделки', B, pair, items, first, net, 3)
        run('удержание по правилу, до 32 свечей', B, pair, [(d, a, b, 32) for d, a, b, _ in items], first, net, 4)
    for label, a, z in (('2020-07..2024', start, DEV_CUT), ('2022..2024 (период автора вне подбора)', month(2022, 1), DEV_CUT)):
        q = [t for t in data['trades'] if a <= t['t_in'] < z]
        p = [t['pnl'] / (10 * B['pt']) for t in q]; r = [t['R'] for t in q]; wr = [t['R'] * t['w'] for t in q]
        print(f"TOKYO {pair} {label}: сделок {len(q)}, нетто {sum(p):.1f} пп, PF {pf(p):.2f}; в долях риска {sum(r):+.2f}R PF {pf(r):.2f}; с весами автора {sum(wr):+.2f}R PF {pf(wr):.2f}; побед {100 * sum(x > 0 for x in p) / max(len(p), 1):.1f}%")
        for y in (2020, 2021, 2022, 2023, 2024) if a == start else ():
            yy = [t['pnl'] / (10 * B['pt']) for t in q if month(y, 1) <= t['t_in'] < month(y + 1, 1)]
            print(f"    {y}: сделок {len(yy)}, нетто {sum(yy):.1f} пп, PF {pf(yy):.2f}")
