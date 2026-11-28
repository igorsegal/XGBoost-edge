#!/usr/bin/env python3
"""Система H4 из курса «ВУДИ» без изменения настроек на всей доступной истории (включая 2025-2026, открыто по просьбе владельца 26.11.2026).
Часовые бары: raw (серверное время) + BAZA (UTC, переводится в серверное) + MT4 для хвоста USDJPY. Запуск: python -I full.py <uploads> <отчёт.json>"""
import sys, os, json, bisect, random, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from woodie import cci, trail, srv; from rd import xf, hst
UTC = dt.timezone.utc
FX = 'AUDCAD AUDCHF AUDJPY AUDNZD AUDUSD CADCHF CADJPY CHFJPY EURAUD EURCAD EURCHF EURGBP EURJPY EURNZD EURUSD GBPAUD GBPCAD GBPCHF GBPJPY GBPNZD GBPUSD NZDCAD NZDCHF NZDJPY NZDUSD USDCAD USDCHF USDJPY'.split()
OTHER = 'XAUUSD XAGUSD XAUEUR XAUAUD XAUJPY XAGAUD XPDUSD XPTUSD USOUSD UKOUSD SP500 NAS100 DJ30 GER40 UK100 EU50 FRA40 HK50 CHINA50 NETH25 SPI200 US2000'.split()
VAR = [(y, m) for y in (5, 6) for m in ('до смены шлейфа', 'цель 2:1')]

def bars(root, p):
    """Куски непрерывной часовой истории: [(t, o, h, l, c, спред в цене)]."""
    _, pt, R = xf(f'{root}/raw/{p}/{p}_H1.bin'); med = sorted(r[5] for r in R)[len(R)//2] or 1
    A = {r[0]: (r[0], r[1], r[2], r[3], r[4], (r[5] or med) * pt) for r in R}
    b = f'{root}/BAZA/{p}/{p}_H1.bin'
    if os.path.exists(b):
        _, ptb, Q = xf(b); Z = [(srv(r[0]), r[1], r[2], r[3], r[4], r[5] * ptb) for r in Q]
        A = {t: v for t, v in A.items() if not Z[0][0] <= t <= Z[-1][0]}; A.update({z[0]: z for z in Z})
    if p == 'USDJPY':
        last = max(A)
        for t, o, h, l, c in hst(f'{root}/RoboForex-DemoPro/USDJPY60.hst'):
            if t > last: A[t] = (t, o, h, l, c, 0.005)
    X = [A[t] for t in sorted(A)]; n = len(X)
    X = [x for i, x in enumerate(X) if min(x[0] - X[i-1][0] if i else 9e9, X[i+1][0] - x[0] if i < n - 1 else 9e9) <= 14400]
    segs = [[X[0]]]
    for x in X[1:]:
        if x[0] - segs[-1][-1][0] > 86400 * 6: segs.append([])
        segs[-1].append(x)
    return pt, [s for s in segs if len(s) >= 1000]

class Seg:
    def __init__(s, B):
        s.B = B; G = []; s.start = []
        for i, (t, o, h, l, c, sp) in enumerate(B):
            k = t // 14400
            if not G or G[-1]['k'] != k: G.append(dict(k=k, o=o, h=h, l=l, c=c)); s.start.append(i)
            else:
                g = G[-1]; g['h'] = max(g['h'], h); g['l'] = min(g['l'], l); g['c'] = c
        s.G = G; H = [g['h'] for g in G]; L = [g['l'] for g in G]; C = [g['c'] for g in G]
        s.st = trail(G)[0]; s.w32 = cci(H, L, C, 32); s.w2 = cci(H, L, C, 2)
        s.atr = [sum(H[q] - L[q] for q in range(max(0, k - 13), k + 1)) / 14 for k in range(len(G))]
    def trade(s, k, side, mode):
        """Вход на открытии бара H4 k+1. Возвращает (разница цен после издержек, номер часового бара выхода) или None, если позиция еще открыта."""
        B = s.B; i = s.start[k+1]; e = B[i][1] + (B[i][5] if side > 0 else 0); com = e * 7e-5
        if mode == 'до смены шлейфа':
            m = k + 1
            while m < len(s.G) and s.st[m] == side: m += 1
            if m + 1 >= len(s.G): return None
            j = s.start[m+1]; x = B[j][1] + (B[j][5] if side < 0 else 0); return side * (x - e) - com, j
        a = s.atr[k]; stop = e - side * a; tp = e + side * 2 * a
        for j in range(i, len(B)):
            t, o, h, l, c, sp = B[j]; off = sp if side < 0 else 0
            if side * ((l if side > 0 else h) + off - stop) <= 0:
                x = stop if side * (o + off - stop) > 0 else o + off; return side * (x - e) - com, j
            if side * ((h if side > 0 else l) + off - tp) >= 0: return side * (tp - e) - com, j
        return None
    def run(s, yellow, mode):
        out = []; free = 0; cnt = {1: 0, -1: 0}; armed = 0; opened = []
        for k in range(60, len(s.G) - 1):
            for sg in (1, -1): cnt[sg] = cnt[sg] + 1 if sg * s.w32[k] > 0 else 0
            d = s.st[k]
            if not d: continue
            if cnt[-d] == 0 and armed == d: armed = 0
            if cnt[-d] == yellow: armed = d
            if armed != d or -d * s.w32[k] <= 0 or -d * s.w2[k] <= 0: continue
            i = s.start[k+1]
            if i <= free: continue
            armed = 0; r = s.trade(k, d, mode)
            if r: out.append(dict(t=s.B[i][0], out=s.B[r[1]][0], side=d, x=r[0], a=r[0] / s.atr[k])); free = r[1]
            else: opened.append(dict(t=s.B[i][0], side=d, price=s.B[i][1])); free = len(s.B)
        return out, opened

def st(tr, key):
    x = [v[key] for v in tr]; g = sum(v for v in x if v > 0); l = -sum(v for v in x if v < 0)
    return dict(n=len(x), sum=round(sum(x), 1), pf=round(g / l, 2) if l else None, win=sum(v > 0 for v in x))
year = lambda t: dt.datetime.fromtimestamp(t, UTC).year
PER = [('до 2019', 0, 2018), ('2019–2024', 2019, 2024), ('2025–2026', 2025, 2100)]

def baseline(segs, real, mode, lo, hi, runs=300):
    n = len(real); cand = [(q, k) for q, s in enumerate(segs) for k in range(60, len(s.G) - 1) if s.st[k] and lo <= year(s.B[s.start[k+1]][0]) <= hi]; res = []
    for r in range(runs):
        rnd = random.Random(r); c = cand[:]; rnd.shuffle(c); tr = []; busy = []
        for q, k in c:
            if len(tr) >= n: break
            s = segs[q]; v = s.trade(k, s.st[k], mode)
            if not v: continue
            i = s.start[k+1]
            if any(q == a and i <= e and v[1] >= b for a, b, e in busy): continue
            busy.append((q, i, v[1])); tr.append(dict(x=v[0]))
        res.append(st(tr, 'x')['pf'] or 99)
    return sorted(res)

if __name__ == '__main__':
    root = sys.argv[1]; J = {}
    pt, S = bars(root, 'USDJPY'); segs = [Seg(s) for s in S]
    for s in segs: print('USDJPY кусок', dt.datetime.fromtimestamp(s.B[0][0], UTC).date(), '—', dt.datetime.fromtimestamp(s.B[-1][0], UTC).date(), len(s.B))
    for y, m in VAR:
        tr = []; op = []
        for s in segs:
            a, b = s.run(y, m); tr += a; op += b
        for v in tr: v['x'] /= pt * 10
        print(f'\nUSDJPY столбик {y}, {m}: всего', st(tr, 'x'), 'открытые:', [(str(dt.datetime.fromtimestamp(o['t'], UTC)), o['side'], o['price']) for o in op])
        for name, lo, hi in PER + [('в том числе 2020–2024', 2020, 2024), ('2025', 2025, 2025), ('2026', 2026, 2026)]:
            part = [v for v in tr if lo <= year(v['t']) <= hi]; line = f'  {name}: {st(part, "x")}'
            if m == 'до смены шлейфа' and part and name in ('до 2019', '2025–2026', 'в том числе 2020–2024'):
                real = [dict(x=v['x']) for v in part]; b = baseline(segs, real, m, lo, hi)
                line += f' | случайные: медиана PF {b[len(b)//2]}, не хуже {sum(z >= st(part, "x")["pf"] for z in b)}/300'
            print(line)
        yrs = {}
        for v in tr: yrs.setdefault(year(v['t']), []).append(v['x'])
        print('  по годам:', {k: (len(v), round(sum(v))) for k, v in sorted(yrs.items())})
        J[f'{y}|{m}'] = tr
        best = sorted(tr, key=lambda v: -v['x'])[:3]; tot = sum(v['x'] for v in tr)
        print('  три лучшие сделки:', [(str(dt.datetime.fromtimestamp(v['t'], UTC).date()), v['side'], round(v['x'])) for v in best], 'без них итог', round(tot - sum(v['x'] for v in best)))
    ALL = {}; have = []
    for p in FX + OTHER + ['BTCUSD']:
        if not os.path.exists(f'{root}/raw/{p}/{p}_H1.bin'): continue
        _, S = bars(root, p); ss = [Seg(s) for s in S]; have.append((p, len(ss), str(dt.datetime.fromtimestamp(ss[0].B[0][0], UTC).date()) if ss else None, str(dt.datetime.fromtimestamp(ss[-1].B[-1][0], UTC).date()) if ss else None))
        for y, m in VAR:
            for s in ss: ALL.setdefault((p, y, m), []).extend(s.run(y, m)[0])
    print('\nинструменты:', have)
    for grp, lst in (('28 валютных пар', FX), ('металлы, нефть, индексы, биткоин', OTHER + ['BTCUSD'])):
        for y, m in VAR:
            print(f'\n== {grp}, столбик {y}, {m} (в единицах среднего размаха свечи H4)')
            for name, lo, hi in PER:
                part = [v for p in lst for v in ALL.get((p, y, m), []) if lo <= year(v['t']) <= hi]
                good = [p for p in lst if (z := st([v for v in ALL.get((p, y, m), []) if lo <= year(v['t']) <= hi], 'a'))['n'] and z['sum'] > 0]
                total = sum(1 for p in lst if any(lo <= year(v['t']) <= hi for v in ALL.get((p, y, m), [])))
                print(f'  {name}: {st(part, "a")} прибыльных инструментов {len(good)} из {total}')
    json.dump(dict(usdjpy=J, all={f'{p}|{y}|{m}': v for (p, y, m), v in ALL.items()}), open(sys.argv[2], 'w'), ensure_ascii=False)
