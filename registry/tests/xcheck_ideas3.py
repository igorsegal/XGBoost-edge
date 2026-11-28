#!/usr/bin/env python3
"""Независимая проверка трёх идей (TOKYO_BREAK_01, SAVGOL_01, ISO_PNN_01): отдельный код на Python,
сделка в сделку с тестером (стратегии) и окно в окно (правило с общим выходом).
Запуск: python xcheck_ideas3.py <каталог баров> <каталог результатов> <каталог сделок> [каталог для сделок Python]"""
import sys, os, csv, math, datetime as dt
from fractions import Fraction
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import json
from xcheck_common import load, trades, compare, dev_windows, DEV_CUT, month

def us_summer(t):
    """Летнее время США по дате: второе воскресенье марта .. первое воскресенье ноября (без пакета tzdata, чтобы работало в Windows)."""
    day = dt.datetime.fromtimestamp(t, dt.timezone.utc).date()
    sundays = lambda m: [dt.date(day.year, m, k) for k in range(1, 15) if dt.date(day.year, m, k).weekday() == 6]
    return sundays(3)[1] <= day < sundays(11)[0]

def atr14(B):
    H, L, C = B['H'], B['L'], B['C']; out = [None] * len(C); tr = []
    for i in range(len(C)):
        tr.append(H[i] - L[i] if i == 0 else max(H[i], C[i - 1]) - min(L[i], C[i - 1]))
        if i >= 13: out[i] = math.fsum(tr[-14:]) / 14
    return out

def commission(pair, entry):
    return 7 / (100 if pair.startswith('XAU') else 100000) * (1 if pair.endswith('USD') else entry)

def hit(B, i, p, entry_bar):
    """Стоп/цель внутри свечи i: цена выхода и метка либо None."""
    o, h, l, s = B['O'][i], B['H'][i], B['L'][i], B['SP'][i] * B['pt']
    if p['d'] < 0: o, h, l = o + s, h + s, l + s
    d = p['d']
    if not entry_bar and d * (o - p['stop']) <= 0: return o, 'S'
    if d * ((l if d > 0 else h) - p['stop']) <= 0: return p['stop'], 'S'
    if d * ((h if d > 0 else l) - p['tp']) >= 0: return p['tp'], 'TP'
    return None

def market(B, i, d):  # закрытие позиции по открытию свечи i
    return B['O'][i] if d > 0 else B['O'][i] + B['SP'][i] * B['pt']

def record(out, pair, B, p, i, px):
    pnl = p['d'] * (px - p['entry']) - commission(pair, p['entry'])
    out.append(dict(t_in=B['T'][p['i']], t_out=B['T'][i], d=p['d'], entry=p['entry'], exit=px, sl=p['sl'], tp=p['tp'],
                    pnl=pnl, R=pnl / abs(p['entry'] - p['sl']), w=p.get('w', 1.0)))

def tokyo(B, pair):
    O, H, L, C, T, pt = (B[k] for k in ('O', 'H', 'L', 'C', 'T', 'pt')); A = atr14(B); n = len(C)
    local = []
    cache = {}
    for t in T:
        key = t // 3600
        if key not in cache:
            cache[key] = 10800 if us_summer(t) else 7200
        local.append(t + cache[key])
    days = {}
    for i in range(n):
        d = local[i] // 86400
        if d not in days: days[d] = [H[i], L[i]]
        else: days[d] = [max(days[d][0], H[i]), min(days[d][1], L[i])]
    order = sorted(days); before = {order[k]: days[order[k - 1]] for k in range(1, len(order))}
    inside = [2 * 3600 <= x % 86400 < 10 * 3600 for x in local]
    out = []; p = None; box = None; acc = []
    for i in range(n):
        if p:
            r = hit(B, i, p, i == p['i'])
            if r: record(out, pair, B, p, i, r[0]); p = None
        last = i == n - 1
        if p:
            p['k'] += 1; d = p['d']
            back = d * (C[i] - (p['edge'] - d * 0.25 * p['R'])) < 0
            if back or local[i] % 86400 >= 21 * 3600 + 45 * 60 or p['k'] >= 32:
                if not last: record(out, pair, B, p, i + 1, market(B, i + 1, d)); p = None
            elif p['k'] >= 16 and not last:
                ns = C[i] - d * 1.5 * p['atr']; m = O[i + 1] if d > 0 else O[i + 1] + B['SP'][i + 1] * pt
                if d * (ns - p['stop']) > 0 and d * (m - ns) > 0: p['stop'] = ns
        if inside[i]:
            if i == 0 or not inside[i - 1]: acc = []; box = None
            acc.append(i); continue
        if i and inside[i - 1]:
            hi = max(H[k] for k in acc); lo = min(L[k] for k in acc)
            box = dict(hi=hi, lo=lo, R=hi - lo, atr=A[i], n=0, used=set(), traded=False) if len(acc) >= 8 and hi > lo and A[i] else None
        if not box: continue
        box['n'] += 1
        if box['n'] > 48 or box['traded'] or p: continue
        if 1 not in box['used'] and C[i] > box['hi'] + 0.05 * box['atr']: d = 1
        elif -1 not in box['used'] and C[i] < box['lo'] - 0.05 * box['atr']: d = -1
        else: continue
        box['used'].add(d); day = local[i] // 86400
        if day not in before: continue
        ph, pl = before[day]; edge = box['hi'] if d > 0 else box['lo']
        if ((ph - box['hi']) if d > 0 else (box['lo'] - pl)) / pt > 50 + 1e-6: continue
        if H[i] <= L[i] or abs(C[i] - O[i]) / (H[i] - L[i]) < 0.8 - 1e-9: continue
        dist = max((0.6 if d > 0 else 1.5) * box['R'], 0.5 * box['atr'], 3 * B['SP'][i] * pt)
        sl = edge - d * dist; tp = C[i] + d * (0.85 if d > 0 else 0.30) * box['R']
        if last: continue
        e = O[i + 1] + B['SP'][i + 1] * pt if d > 0 else O[i + 1]
        if d * (e - sl) <= 0 or d * (tp - e) <= 0: continue
        age = box['n']; w = (0.6 if age <= 2 else 1.0 if age <= 6 else 0.4 if age <= 14 else 0.6) * (0.6 if d < 0 else 1.0)
        p = dict(i=i + 1, d=d, entry=e, sl=sl, stop=sl, tp=tp, edge=edge, R=box['R'], atr=box['atr'], k=0, w=w); box['traded'] = True
    if p: record(out, pair, B, p, n - 1, C[-1] if p['d'] > 0 else C[-1] + B['SP'][-1] * pt)
    return out

def sg_weights(N=21):
    X = [[Fraction((k - (N - 1)) ** j) for j in range(3)] for k in range(N)]
    M = [[sum(X[k][a] * X[k][b] for k in range(N)) for b in range(3)] + [Fraction(int(a == b)) for b in range(3)] for a in range(3)]
    for c in range(3):                      # Гаусс-Жордан в дробях
        M[c] = [v / M[c][c] for v in M[c]]
        for r in range(3):
            if r != c: M[r] = [x - M[r][c] * y for x, y in zip(M[r], M[c])]
    res = []
    for row in (1, 2):
        w = [sum(M[row][3 + a] * X[k][a] for a in range(3)) for k in range(N)]
        den = math.lcm(*[f.denominator for f in w]); res.append([int(f * den) for f in w])
    return res

def savgol(B, pair):
    O, C, pt = B['O'], B['C'], B['pt']; n = len(C); w1, w2 = sg_weights(); Y = [round(c / pt) for c in C]
    rp = 0.01 if pair.startswith('XAU') else pt
    sign = lambda v: (v > 0) - (v < 0)
    out = []; p = None; prev = 0
    for i in range(n):
        if p:
            r = hit(B, i, p, i == p['i'])
            if r: record(out, pair, B, p, i, r[0]); p = None
        if i < 20: continue
        win = Y[i - 20:i + 1]
        v = sign(sum(a * b for a, b in zip(w1, win))); a = sign(sum(x * b for x, b in zip(w2, win)))
        if not p:
            d = 1 if (v > 0 and a > 0 and prev <= 0) else -1 if (v < 0 and a < 0 and prev >= 0) else 0
            if d and i + 1 < n:
                e = O[i + 1] + B['SP'][i + 1] * pt if d > 0 else O[i + 1]
                p = dict(i=i + 1, d=d, entry=e, sl=e - d * 500 * rp, stop=e - d * 500 * rp, tp=e + d * 1000 * rp)
        elif p['d'] * a < 0 or p['d'] * v <= 0:
            if i + 1 < n: record(out, pair, B, p, i + 1, market(B, i + 1, p['d'])); p = None
        prev = a
    if p: record(out, pair, B, p, n - 1, C[-1] if p['d'] > 0 else C[-1] + B['SP'][-1] * pt)
    return out

def iso_signals(B, mode):
    O, H, L, C, pt = (B[k] for k in ('O', 'H', 'L', 'C', 'pt')); n = len(C)
    cl = lambda v, a=-1.0, b=1.0: min(max(v, a), b)
    rsi = [None] * n; g = [0.0] + [max(C[i] - C[i - 1], 0) for i in range(1, n)]; l = [0.0] + [max(C[i - 1] - C[i], 0) for i in range(1, n)]
    ag = sum(g[1:15]) / 14; al = sum(l[1:15]) / 14
    for i in range(14, n):
        if i > 14: ag += (g[i] - ag) / 14; al += (l[i] - al) / 14
        rsi[i] = 100.0 if al == 0 else 100 * ag / (ag + al)
    lo = [min(L[i - 4:i + 1]) if i >= 4 else None for i in range(n)]; hi = [max(H[i - 4:i + 1]) if i >= 4 else None for i in range(n)]
    K = [None] * n; D = [None] * n
    for i in range(6, n):
        num = sum(C[j] - lo[j] for j in range(i - 2, i + 1)); den = sum(hi[j] - lo[j] for j in range(i - 2, i + 1))
        K[i] = 100.0 if den == 0 else 100 * num / den
        if i >= 8: D[i] = (K[i] + K[i - 1] + K[i - 2]) / 3
    raw = [None] * n
    for i in range(15, n):
        s = 0.28 * cl((rsi[i] - 50) / 35) + 0.22 * cl((K[i] - 50) / 40) + 0.20 * cl((rsi[i] - rsi[i - 1]) / 10) + 0.15 * cl((K[i] - K[i - 1]) / 15) + 0.15 * cl((K[i] - D[i]) / 15)
        raw[i] = cl(0.5 + 0.5 * s, 0, 1)
    up = [1 if i + 6 < n and C[i + 6] > C[i] else 0 for i in range(n)]
    def feats(i):
        rg = H[i] - L[i]; loc = 0.5 if rg <= pt else cl((C[i] - L[i]) / rg, 0, 1)
        span = max(H[i - 10:i + 1]) - min(L[i - 10:i + 1]); mom = 0.5 if span <= pt else cl(0.5 + 0.5 * (C[i] - C[i - 10]) / span, 0, 1)
        return (rsi[i] / 100, K[i] / 100, D[i] / 100, loc, mom, raw[i])
    F = [None] * n
    if mode: 
        for i in range(25, n): F[i] = feats(i)
    sig = [0] * n; start = 100 + 200 + 6 + 10
    for i in range(start, n):
        x = raw[i]; lng = x >= 0.5 + 0.05; sht = x <= 0.5 - 0.05
        if not (lng or sht): continue
        js = range(i - 205, i - 5)          # 200 свечей, исход каждой известен к свече i
        agg = {}
        pairs = sorted((raw[j], up[j]) for j in js)
        xs = []; blocks = []                # блок: [сумма, вес, число точек x]
        for v, y in pairs:
            if xs and abs(v - xs[-1][0]) <= 1e-9: xs[-1][1] += y; xs[-1][2] += 1
            else: xs.append([v, y, 1])
        for v, s, w in xs:
            blocks.append([s, w, 1])
            while len(blocks) > 1 and blocks[-2][0] * blocks[-1][1] > blocks[-1][0] * blocks[-2][1]:
                s2, w2, c2 = blocks.pop(); blocks[-1][0] += s2; blocks[-1][1] += w2; blocks[-1][2] += c2
        fit = [b[0] / b[1] for b in blocks for _ in range(b[2])]; gx = [q[0] for q in xs]
        if x <= gx[0]: p = fit[0]
        elif x >= gx[-1]: p = fit[-1]
        else:
            k = next(k for k in range(len(gx) - 1) if gx[k] <= x <= gx[k + 1])
            p = fit[k] + (x - gx[k]) / (gx[k + 1] - gx[k]) * (fit[k + 1] - fit[k])
        p = cl(p, 0.01, 0.99)
        if mode:
            q = F[i]; tot = [0.0, 0.0]; cnt = [0, 0]
            for j in range(i - 6, i - 186, -1):
                k = math.exp(-sum((a - b) ** 2 for a, b in zip(q, F[j])) / (2 * 0.12 ** 2)); tot[up[j]] += k; cnt[up[j]] += 1
            pn = 0.5
            if min(cnt) >= 5:
                u, d = tot[1] / cnt[1], tot[0] / cnt[0]
                if u + d > 1e-15: pn = cl(u / (u + d), 0.01, 0.99)
            p = cl((1 - 0.495) * p + 0.495 * pn, 0.01, 0.99)
        if lng and p >= 0.55 - 1e-9: sig[i] = 1
        elif sht and 1 - p >= 0.55 - 1e-9: sig[i] = -1
    return sig

if __name__ == '__main__':
    bars, res_dir, tr_dir = sys.argv[1:4]; own = sys.argv[4] if len(sys.argv) > 4 else None
    bad = 0
    names = [('tokyo_break', 'GBPUSD', 'M15'), ('tokyo_break', 'EURUSD', 'M15'), ('savgol', 'XAUUSD', 'M5'), ('savgol', 'GBPUSD', 'M15'), ('savgol', 'EURUSD', 'H1')]
    for kind, pair, tf in names:
        n = f'{kind}_{pair}_{tf}'
        B = load(f'{bars}/{pair}/{pair}_{tf}.bin', DEV_CUT)
        py = (tokyo if kind == 'tokyo_break' else savgol)(B, pair)
        cpp = list(csv.DictReader(open(f'{tr_dir}/{n}.csv')))
        diff = abs(len(py) - len(cpp))
        for a, b in zip(py, cpp):
            if (a['t_in'] != int(b['entry_time']) or a['t_out'] != int(b['exit_time']) or a['d'] != int(b['dir'])
                    or any(abs(a[k] - float(b[c])) > 1e-6 for k, c in (('entry', 'entry'), ('exit', 'exit'), ('sl', 'sl'), ('tp', 'tp'), ('pnl', 'pnl')))
                    or (kind == 'tokyo_break' and abs(a['w'] - float(b['why'].split('w=')[1])) > 1e-9)): diff += 1
        print(f"{'OK ' if not diff else 'ОШИБКА'} {n}: сделок Python {len(py)}, тестер {len(cpp)}, расхождений {diff}")
        res = json.load(open(f"{res_dir}/{n}_wf.json" if os.path.exists(f"{res_dir}/{n}_wf.json") else f"{res_dir}/{n}.json", encoding='utf-8'))
        bad += compare(res, [(t['t_in'], t['pnl'] / (10 * B['pt'])) for t in py], B['T'][0]) if pair != 'AUDUSD' else 0
        bad += bool(diff)
        if own: json.dump(dict(pt=B['pt'], trades=py), open(f'{own}/{n}.json', 'w'))
    for pair in ('EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'XAUUSD'):
        B = load(f'{bars}/{pair}/{pair}_H4.bin', DEV_CUT)
        for mode, suf in ((0, ''), (1, '_pnn')):
            n = f'iso_pnn_{pair}_H4{suf}'
            sig = iso_signals(B, mode)
            tr = trades(B, sig, pair, dev_windows(B['T'][0])[0][1])
            res = json.load(open(f'{res_dir}/{n}.json', encoding='utf-8'))
            bad += compare(res, tr, B['T'][0])
            if own: json.dump(dict(sig=[(i, s) for i, s in enumerate(sig) if s]), open(f'{own}/{n}.json', 'w'))
    print('ИТОГ ПРОВЕРКИ:', 'РАСХОЖДЕНИЙ НЕТ' if not bad else f'ЕСТЬ РАСХОЖДЕНИЯ ({bad})')
    sys.exit(1 if bad else 0)
