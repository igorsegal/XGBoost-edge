"""Золото: пороги в пунктах и объёме переведены по масштабу минутных баров относительно AUDUSD."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from algo import *
import statistics as st
def typical(B, tf_days):
    r, v = [], []
    for day in tf_days:
        for m, i in day:
            if 30 <= m < 150: r.append((B['H'][i] - B['L'][i]) / B['pt']); v.append(B['V'][i])
    r.sort(); v.sort(); return r, v
root = sys.argv[1]; res = {}
for tf, base in (('M1', M1), ('M15', M15)):
    A = load(f'{root}/AUDUSD/AUDUSD_{tf}.bin'); G = load(f'{root}/XAUUSD/XAUUSD_{tf}.bin'); gd = server_days(G)
    ar, av = typical(A, server_days(A)); gr, gv = typical(G, gd)
    k = st.median(gr) / st.median(ar)
    def same_rank(x): q = sum(1 for z in av if z < x) / len(av); return gv[min(int(q * len(gv)), len(gv) - 1)]
    p = {**base, 'sbrange': base['sbrange'] * k, 'away': base['away'] * k, 'bend': base['bend'] * k, 'sl': base['sl'] * k, 'tp': base['tp'] * k,
         'v0': same_rank(base['v0']), 'vmid': same_rank(base['vmid'])}
    print(tf, 'пункты x', round(k, 1), 'объём от', p['v0'], 'граница', p['vmid'])
    for name, pp in ((f'{tf} по документу', p), (f'{tf} объём выше', {**p, 'v0': p['v0'] * 1.5, 'vmid': p['vmid'] * 1.5})):
        tr = run('XAUUSD', G, gd, pp); g = run('XAUUSD', G, gd, {**pp, 'costs': False}); s, s0 = stats(tr), stats(g)
        print(f"XAUUSD | {name}: сделок {s['n']}, PF {s['pf']} | без издержек PF {s0['pf']}", s['years']); res[name] = dict(net=s, gross=s0)
# лучший из валютных вариантов: годы и разброс
B = load(f'{root}/EURUSD/EURUSD_M1.bin'); d = server_days(B)
p = VARIANTS['M1 после 01:15, бар от 40']
for c in (True, False):
    tr = run('EURUSD', B, d, {**p, 'costs': c}); x = [t['pips'] for t in tr]
    print('EURUSD лучший', 'после издержек' if c else 'без издержек', len(x), round(st.mean(x), 2), 't =', round(st.mean(x) / st.stdev(x) * len(x) ** .5, 2), stats(tr)['years'])
json.dump(res, open('gold.json', 'w'), ensure_ascii=False)
