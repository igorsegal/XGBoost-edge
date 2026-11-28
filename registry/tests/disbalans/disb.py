#!/usr/bin/env python3
"""Правило из курса «Торговля по дисбалансам» (расшифровки 02liveinvest): зона дисбаланса H4, вход на M5.
Запуск: python -I disb.py <каталог баров> [отчет.json]. Данные только до 2025-01-01."""
import sys, struct, json, bisect, random, datetime as dt
DEV_CUT = int(dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc).timestamp())
BEGIN = int(dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc).timestamp())

def load(path, cutoff=DEV_CUT):
    b = open(path, 'rb').read(); per, = struct.unpack('<i', b[16:20]); pt, = struct.unpack('<d', b[24:32])
    n, = struct.unpack('<q', b[32:40]); sl, = struct.unpack('<i', b[56:60]); off = 60 + sl
    R = [r for r in struct.iter_unpack('<qddddqiq', b[off:off + 60 * n]) if BEGIN - 200 * 86400 <= r[0] and r[0] + per <= cutoff]
    c = list(zip(*R))
    return dict(pt=pt, per=per, T=c[0], O=c[1], H=c[2], L=c[3], C=c[4], SP=c[6])

def mirror(B):
    """Зеркало для продаж: цена с минусом, bid и ask меняются местами (ask зеркала = -bid)."""
    sp = [s * B['pt'] for s in B['SP']]
    return dict(pt=B['pt'], per=B['per'], T=B['T'], SP=B['SP'],
                O=[-(o + s) for o, s in zip(B['O'], sp)], H=[-(x + s) for x, s in zip(B['L'], sp)],
                L=[-(x + s) for x, s in zip(B['H'], sp)], C=[-(x + s) for x, s in zip(B['C'], sp)])

def negate(B):
    return dict(B, O=[-x for x in B['O']], H=[-x for x in B['L']], L=[-x for x in B['H']], C=[-x for x in B['C']])

def atr14(B):
    H, L, C = B['H'], B['L'], B['C']; tr = [H[0] - L[0]] + [max(H[i] - L[i], abs(H[i] - C[i-1]), abs(L[i] - C[i-1])) for i in range(1, len(C))]
    return [None if i < 13 else sum(tr[i-13:i+1]) / 14 for i in range(len(C))]

def d1_trend(D):
    e = None; out = []
    for c in D['C']:
        e = c if e is None else e + (c - e) * 2 / 51; out.append(1 if c > e else -1)
    return out

def commission(pair, price):
    lot = 100 if pair.startswith('XAU') else 100000
    return 7 / lot * (1 if pair.endswith('USD') else abs(price))

def setups(pair, B5, S4, S5, X5, D, side, v):
    """B5 - настоящие бары; S4/S5 - bid (для продаж с минусом), по ним зоны и сигналы; X5 - цены выхода."""
    T4, H4, L4, C4 = S4['T'], S4['H'], S4['L'], S4['C']
    T, O, H, L, C, SP, pt = (S5[k] for k in ('T', 'O', 'H', 'L', 'C', 'SP', 'pt'))
    A = atr14(S4); tr = d1_trend(D); TD = D['T']; n = len(T); out = []
    for j in range(15, len(T4)):
        lo, hi = H4[j-2], L4[j]
        if not (hi > lo and hi - lo >= v['minsize'] * A[j]): continue
        avail = T4[j] + S4['per']
        if avail < BEGIN: continue
        dead = None
        for k in range(j + 1, min(j + 1 + v['life'], len(T4))):
            if C4[k] < lo: dead = T4[k] + S4['per']; break
        until = dead if dead is not None else (T4[min(j + v['life'], len(T4) - 1)] + S4['per'])
        i = bisect.bisect_left(T, avail)
        while i < n and T[i] < until and L[i] > hi: i += 1
        if i >= n or T[i] >= until: continue
        touch = i; bear = None   # верхний край последнего встречного дисбаланса M5
        for k in range(max(2, touch - v['corr']), touch):
            if H[k] < L[k-2]: bear = L[k-2]
        inv = None; k = None; ext = L[touch]
        for i in range(touch, min(touch + v['window'], n)):
            if dead is not None and T[i] >= dead: break
            ext = min(ext, L[i])
            if inv is None:
                if bear is not None and C[i] > bear: inv = i
                elif H[i] < L[i-2]: bear = L[i-2]
            if inv is None: continue
            if v['entry'] == 'market': k = i; break
            if L[i] > H[i-2]: k = i; break
            if i - inv >= 12: k = None; break
        else: k = None
        if inv is None or k is None or (dead is not None and T[i] >= dead): continue
        if v['entry'] == 'limit' and not L[k] > H[k-2]: continue
        if v['trend']:
            x = bisect.bisect_right(TD, T[k] + B5['per'] - 86400) - 1
            if x < 50 or tr[x] != side: continue
        buf = SP[k] * pt
        stop = (ext if v['stop'] == 'swing' else H[k-2]) - buf
        if v['entry'] == 'market':
            if k + 1 >= n: continue
            e = k + 1; price = O[e] + SP[e] * pt if side > 0 else O[e] - 0.0
            price = ask(S5, B5, side, e, 'O')
        else:
            limit = L[k]; e = None
            for m in range(k + 1, min(k + 1 + v['pending'], n)):
                if ask(S5, B5, side, m, 'L') <= limit: e = m; price = min(limit, ask(S5, B5, side, m, 'O')); break
            if e is None: continue
        risk = price - stop
        if risk <= 0: continue
        tr_ = trade(pair, X5, e, price, stop, price + v['rr'] * risk, v['hold'], v['entry'] == 'limit', v['com'])
        if tr_: out.append(dict(side=side, zone=T4[j], t_in=T[e], entry=price, risk=risk, **tr_))
    return out

def ask(S5, B5, side, i, f):
    """Цена входа: покупка по ask, продажа по bid (в зеркальных координатах)."""
    sp = B5['SP'][i] * B5['pt']
    if side > 0: return S5[f][i] + sp
    real = {'O': 'O', 'L': 'H'}[f]
    return -B5[real][i]

def trade(pair, S5, e, price, stop, tp, hold, limit, com_on=True):
    """Выход по bid (в зеркале bid = -ask, он уже лежит в O/H/L/C). Стоп проверяется раньше цели."""
    O, H, L, C = S5['O'], S5['H'], S5['L'], S5['C']; n = len(C)
    if e + 1 >= n: return None
    ex = None; end = min(e + hold, n)
    for k in range(e, end):
        if k > e and O[k] <= stop: ex = O[k]; break
        if L[k] <= stop: ex = stop; break
        if (k > e or not limit) and H[k] >= tp: ex = tp; break
    if ex is None:
        if end - e < hold: return None
        k = end - 1; ex = C[k]
    com = commission(pair, price) if com_on else 0; gross = ex - price
    return dict(t_out=S5['T'][k], exit=ex, R=(gross - com) / (price - stop), pips=(gross - com) / (10 * S5['pt']))

def one_at_a_time(trs):
    free = 0; out = []
    for t in sorted(trs, key=lambda t: (t['t_in'], t['zone'])):
        if t['t_in'] >= free: out.append(t); free = t['t_out'] + 300
    return out

def run(pair, data, v):
    B4, B5, D, N4, N5, M5 = data
    if not v['com']:                                  # без издержек: нулевой спред и комиссия
        B5 = dict(B5, SP=[0] * len(B5['T'])); N5 = dict(N5, SP=B5['SP']); M5 = mirror(B5)
    trs = setups(pair, B5, B4, B5, B5, D, 1, v) + setups(pair, B5, N4, N5, M5, D, -1, v)
    return one_at_a_time(trs)


def stats(tr):
    R = [t['R'] for t in tr]; g = sum(x for x in R if x > 0); l = -sum(x for x in R if x < 0)
    yrs = {}
    for t in tr:
        y = dt.datetime.fromtimestamp(t['t_in'], dt.timezone.utc).year; yrs[y] = round(yrs.get(y, 0) + t['R'], 1)
    return dict(n=len(R), R=round(sum(R), 1), avg=round(sum(R) / len(R), 3) if R else 0, pf=round(g / l, 3) if l else 0,
                win=round(100 * sum(x > 0 for x in R) / len(R), 1) if R else 0, pips=round(sum(t['pips'] for t in tr), 1), years=yrs)

BASE = dict(minsize=0.1, life=60, corr=36, window=288, entry='limit', pending=48, stop='swing', rr=3.0, hold=1440, trend=False, com=True)
VARIANTS = {'основной (лимит, стоп за экстремумом, цель 3R)': {}, 'цель 2R': dict(rr=2.0), 'вход по рынку после перебития': dict(entry='market'),
            'стоп за дисбалансом M5': dict(stop='gap'), 'только по направлению D1': dict(trend=True)}
PAIRS = ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'XAUUSD']

def prepare(root, pair, cutoff=DEV_CUT, zone='H4', entry='M5'):
    B4, B5, D = (load(f'{root}/{pair}/{pair}_{tf}.bin', cutoff) for tf in (zone, entry, 'D1'))
    return B4, B5, D, negate(B4), negate(B5), mirror(B5)

if __name__ == '__main__':
    root = sys.argv[1]; res = {}; allt = {}
    for pair in PAIRS:
        data = prepare(root, pair)
        for name, ov in VARIANTS.items():
            tr = run(pair, data, {**BASE, **ov}); s = stats(tr); res[f'{pair} | {name}'] = s; allt[f'{pair} | {name}'] = tr
            print(f"{pair} | {name}: сделок {s['n']}, итог {s['R']}R, на сделку {s['avg']}R, PF {s['pf']}, побед {s['win']}%, по годам {s['years']}", flush=True)
    if len(sys.argv) > 2: json.dump(dict(stats=res, trades=allt), open(sys.argv[2], 'w'), ensure_ascii=False)
