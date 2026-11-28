import sys, os, random, bisect, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from disb import *
root = sys.argv[1]; out = {}
def rnd_cmp(data, v, tr, N=500):
    """Случайные входы без издержек: те же стороны, стопы, цели и срок."""
    B5, N5 = data[1], data[4]; z = [0] * len(B5['T']); B0 = dict(B5, SP=z); M0 = mirror(B0)
    T = B5['T']; first = bisect.bisect_left(T, BEGIN); n = len(T); rnd = random.Random(11); nets = []
    for _ in range(N):
        s = 0.0
        for t in tr:
            X = B0 if t['side'] > 0 else M0
            while True:
                e = rnd.randrange(first, n - v['hold'] - 1); price = X['O'][e]
                r = trade('EURUSD', X, e, price, price - t['risk'], price + v['rr'] * t['risk'], v['hold'], False, False)
                if r: break
            s += r['R']
        nets.append(s)
    nets.sort(); net = sum(t['R'] for t in tr)
    return net, nets[N // 2], nets[int(N * .95)], 100 * sum(x >= net for x in nets) / N
print('== USDJPY: покупки и продажи; без издержек против случайных без издержек')
data = prepare(root, 'USDJPY')
for name, ov in VARIANTS.items():
    v = {**BASE, **ov}; tr = run('USDJPY', data, v); g = run('USDJPY', data, {**v, 'com': False})
    a, mid, p95, better = rnd_cmp(data, v, g)
    sides = {d: stats([t for t in tr if t['side'] == d]) for d in (1, -1)}
    print(f"{name}: покупки {sides[1]['n']} / {sides[1]['R']}R, продажи {sides[-1]['n']} / {sides[-1]['R']}R | без издержек {a:.1f}R; случайные: середина {mid:.1f}, 95% {p95:.1f}, не хуже {better}%", flush=True)
print('== USDJPY: устойчивость к настройкам (с издержками)')
for ov in (dict(minsize=0), dict(minsize=0.25), dict(life=30), dict(life=120), dict(window=144), dict(window=576), dict(pending=24), dict(pending=96), dict(corr=18), dict(corr=72), dict(rr=2.5), dict(rr=4.0), dict(hold=720), dict(hold=2880)):
    s = stats(run('USDJPY', data, {**BASE, **ov})); print(f"  {ov}: сделок {s['n']}, итог {s['R']}R, PF {s['pf']}", flush=True)
for zone, entry, ov, label in (('D1', 'M15', dict(life=30, window=96, hold=480), 'зона D1, вход M15'),
                               ('H4', 'M1', dict(corr=60, window=1440, pending=120, hold=7200), 'зона H4, вход M1')):
    print('==', label)
    for pair in PAIRS:
        data = prepare(root, pair, zone=zone, entry=entry)
        for name, o2 in VARIANTS.items():
            if name.startswith('стоп за'): continue
            v = {**BASE, **ov, **o2}; s = stats(run(pair, data, v)); g = stats(run(pair, data, {**v, 'com': False}))
            out[f'{pair} {label} | {name}'] = dict(net=s, gross=g)
            print(f"{pair} | {name}: сделок {s['n']}, с издержками {s['R']}R (PF {s['pf']}), без издержек {g['R']}R (PF {g['pf']})", flush=True)
json.dump(out, open(sys.argv[2], 'w'), ensure_ascii=False)
