#!/usr/bin/env python3
"""Курс «Вуди»: Woodie Instant (H1), система H4, система 13-100, советник WoodieSystem EA v1 и v2.
Шлейф точек (закрытый индикатор ForexMT4Systems_TR2) восстановлен как Gann HiLo: LWMA(5) максимумов и минимумов H4.
Исполнение по M1. Запуск: python -I woodie.py <бары> <отчёт.json>"""
import sys, os, json, bisect, datetime as dt
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from algo import load, UTC, us_summer

def srv(t): h = t - t % 3600; return t + (10800 if us_summer(h) else 7200)

def group(B, sec):
    G = []; idx = []
    for i, t in enumerate(B['T']):
        k = srv(t) // sec
        if not G or G[-1]['k'] != k: G.append(dict(k=k, o=B['O'][i], h=B['H'][i], l=B['L'][i], c=B['C'][i]))
        else:
            g = G[-1]; g['h'] = max(g['h'], B['H'][i]); g['l'] = min(g['l'], B['L'][i]); g['c'] = B['C'][i]
        idx.append(len(G) - 1)
    return G, idx

def cci(H, L, C, n):
    tp = [(h + l + c) / 3 for h, l, c in zip(H, L, C)]; out = [0.0] * len(tp)
    for i in range(n - 1, len(tp)):
        w = tp[i-n+1:i+1]; m = sum(w) / n; d = sum(abs(x - m) for x in w) / n; out[i] = (tp[i] - m) / (0.015 * d) if d else 0.0
    return out

def trail(G):
    """Состояние тренда по закрытым барам H4 и границы, действующие для каждого бара."""
    up = [None] * len(G); lo = [None] * len(G); st = [0] * len(G); s = 0
    for k in range(len(G)):
        if k >= 5:
            up[k] = sum(G[k-5+m]['h'] * (m + 1) for m in range(5)) / 15; lo[k] = sum(G[k-5+m]['l'] * (m + 1) for m in range(5)) / 15
            if G[k]['c'] > up[k]: s = 1
            elif G[k]['c'] < lo[k]: s = -1
        st[k] = s
    return st, up, lo

class Data:
    def __init__(s, root, pair):
        s.pair = pair; s.m1 = load(f'{root}/{pair}/{pair}_M1.bin'); s.h1 = load(f'{root}/{pair}/{pair}_H1.bin'); B = s.h1
        s.T, s.O, s.H, s.L, s.C = (B[x] for x in ('T', 'O', 'H', 'L', 'C')); s.pip = B['pt'] * 10
        s.G4, s.i4 = group(B, 14400); s.GD, s.iD = group(B, 86400); s.st, s.up, s.lo = trail(s.G4); s.cache = {}
        s.dstart = {}
        for i, k in enumerate(s.iD): s.dstart.setdefault(k, i)
        s.hour = [srv(t) % 86400 // 3600 for t in s.T]
    def cci(s, n):
        if n not in s.cache: s.cache[n] = cci(s.H, s.L, s.C, n)
        return s.cache[n]
    def dot(s, i, j):
        """+1/-1, если на часовом баре i (смотрим в момент открытия бара j) стоит точка смены тренда."""
        k = s.i4[i]
        if k < 6: return 0
        if k == s.i4[j]:
            p = s.O[j]; now = 1 if p > s.up[k] else -1 if p < s.lo[k] else s.st[k-1]
        else: now = s.st[k]
        return now if now != s.st[k-1] else 0

# ---------- исполнение ----------
def execute(D, t_open, side, legs, sl, p_be=None, costs=True, flip_exit=None, ladder=None, limit=None):
    """legs: [(вес, цель в пунктах или None)]. Возвращает (пункты на единицу суммарного веса, время выхода)."""
    M = D.m1; T, O, H, L, SP, pt = (M[x] for x in ('T', 'O', 'H', 'L', 'SP', 'pt')); pip = D.pip
    j = bisect.bisect_left(T, t_open)
    if j >= len(T): return None
    sp0 = SP[j] * pt if costs else 0; e = O[j] + (sp0 if side > 0 else 0)
    live = [[w, e + side * tp * pip if tp else None] for w, tp in legs]; stop = e - side * sl * pip if sl else None
    total = sum(w for w, _ in legs); res = 0.0; com = ((e * 7e-5) if D.pair == 'USDJPY' else 7e-5) if costs else 0
    hit = 0; end = limit if limit else T[-1] + 60
    while j < len(T):
        off = 0 if side > 0 else (SP[j] * pt if costs else 0); o = O[j] + off
        if T[j] >= end:
            for w, _ in live: res += w * (side * (o - e) - com)
            return res / total / pip, T[j]
        worst = (L[j] if side > 0 else H[j]) + off; best = (H[j] if side > 0 else L[j]) + off
        if stop is not None and side * (worst - stop) <= 0:
            x = stop if side * (o - stop) > 0 else o
            for w, _ in live: res += w * (side * (x - e) - com)
            return res / total / pip, T[j]
        rest = []
        for w, tp in live:
            if tp is not None and side * (best - tp) >= 0: res += w * (side * (tp - e) - com); hit += 1
            else: rest.append([w, tp])
        live = rest
        if not live: return res / total / pip, T[j]
        n = len(live); gain = side * (best - e) / pip
        if p_be and n in p_be:
            lvl, off_ = p_be[n]
            if gain >= lvl:
                ns = e + side * off_ * pip
                if stop is None or side * (ns - stop) > 0:
                    if side * (e + side * gain * pip - ns) > 0: stop = ns
        if ladder and hit in ladder:
            ns = e + side * ladder[hit] * pip
            if side * (ns - stop) > 0: stop = ns
        j += 1
    return None

# ---------- советник ----------
V2 = dict(first2=True, lvl=99, cci=3, f1=0, f2=140, f3=40, f31=10, f32=9, f4=10, f5=False, f7=False, f71=False, f9=False, w100=13, w100lvl=23.6,
          legs=[(8, 15), (4, 23), (2, 60)], sl=40, be={2: (12, 12), 1: (20, 20)})
V1 = dict(first2=False, lvl=76.4, cci=10, f1=60, f2=140, f3=50, f31=0, f32=0, f4=20, f5=True, f7=True, f71=True, f9=True, w100=100, w100lvl=38.2,
          legs=[(1, 25), (1, 60), (1, 90)], sl=38.2, be={2: (5, 5), 1: (30, 30)})

def ea_signal(D, j, p):
    O, H, L, C, pip = D.O, D.H, D.L, D.C, D.pip; w = D.cci(p['cci'])
    idir = 0; lt = None
    for i in range(0 if p['first2'] else 1, min(j - 40, 600)):
        d = D.dot(j - i, j)
        if not d: continue
        n = 1
        for q in range(1, 5):
            if D.dot(j - i - q, j) == d: n += 1
            else: break
        if p['first2']:
            if n > 1: idir, lt = d, i + n - 1; break
        else: idir, lt = d, i; break
    if not idir: return 0
    if D.hour[j] < 1 or D.hour[j] >= 23: return 0
    s = idir; cross = -1; sig = -1
    for i in range(1, lt):
        a, b = w[j-i], w[j-i-1]
        if s * b > 0 and s * a < 0: cross = i; break
    last = (1, 2)
    if cross != -1:
        rev = -1
        for i in range(cross, 0, -1):
            a, b = s * w[j-i], s * w[j-i-1]; last = (i, i + 1)
            if rev == -1:
                if a < -p['lvl']: rev = i
            elif a > -p['lvl'] and b < -p['lvl']: sig = i; break
    if sig == -1 and p['f1'] > 0 and lt > 2:
        rng = range(j - (lt - 2 if p['first2'] else lt), j)
        if len(rng) and (max(H[q] for q in rng) - min(L[q] for q in rng)) / pip >= p['f1']:
            d1, d2 = s * w[j-1], s * w[j-2]
            if d1 > -p['lvl'] and -p['lvl'] < d2 < 0 and d2 < d1: sig = 1; last = (1, 2)
    if sig == -1 or sig > 1: return 0
    t = j - lt; idays = D.iD[j] - D.iD[t]
    if p['f9']:
        v = D.cci(p['w100'])[j-1]
        if (s > 0 and v < p['w100lvl']) or (s < 0 and v > -p['w100lvl']): return 0
    if s * w[j-last[1]] < -p['lvl'] and s * w[j-last[0]] > 0: return 0
    if p['f7'] and idays <= 1:
        for i in range(lt + 1, min(j - 40, 600)):
            if D.dot(j - i, j):
                if D.iD[j-(i-1)] == D.iD[t]: return 0
                break
    if p['f71'] and idays == 0: return 0
    o1, h1, l1, c1 = O[j-1], H[j-1], L[j-1], C[j-1]
    if p['f5'] and (h1 - max(o1, c1)) + (min(o1, c1) - l1) >= abs(o1 - c1): return 0
    if p['f31'] and (h1 - l1) / pip < p['f31']: return 0
    if p['f32']:
        k = D.i4[j-1]; line = D.lo[k] if s > 0 else D.up[k]
        if line and abs(line - c1) / pip < p['f32']: return 0
    if p['f4']:
        top = lt if p['first2'] else lt - 1
        for i in range(top, -1, -1):
            q = j - i; prev = q - 1; pc = C[prev]; po = O[prev]; op = O[q]; col = 1 if pc > po else -1 if pc < po else 0
            if s > 0 and ((col == 1 and (op - pc) / pip >= p['f4']) or (col == -1 and (op - po) / pip >= p['f4'])): return 0
            if s < 0 and ((col == -1 and (pc - op) / pip >= p['f4']) or (col == 1 and (po - op) / pip >= p['f4'])): return 0
    if p['f3']:
        if p['first2']:
            for i in range(lt, 0, -1):
                col = None; mx = mn = 0
                for m in range(2):
                    q = j - i - m; c_ = 1 if C[q] > O[q] else -1 if C[q] < O[q] else 0
                    if col is None: col = c_
                    if c_ != col: break
                    mx = H[q] if mx == 0 else max(mx, H[q]); mn = L[q] if mn == 0 else min(mn, L[q])
                    if (mx - mn) / pip >= p['f3']: return 0
        elif any((H[j-i] - L[j-i]) / pip >= p['f3'] for i in range(1, lt + 1)): return 0
    if p['f2']:
        if p['first2']:
            a = D.dstart[max(D.iD[j] - 3, 0)]; hs = H[a:j] + (O[j],); ls = L[a:j] + (O[j],)
        else: hs = H[j-lt:j]; ls = L[j-lt:j]
        if hs and (max(hs) - min(ls)) / pip >= p['f2']: return 0
    return s

def run_ea(D, p, costs):
    out = []; free = 0
    for j in range(700, len(D.T)):
        if D.T[j] < free: continue
        s = ea_signal(D, j, p)
        if s:
            r = execute(D, D.T[j], s, p['legs'], p['sl'], p['be'], costs)
            if r: out.append((D.T[j], r[0])); free = r[1] + 1
    return out

# ---------- документы ----------
def run_instant(D, window, costs):
    w1 = D.cci(100); w10 = D.cci(10); H, L, C, T, pip = D.H, D.L, D.C, D.T, D.pip
    ema = []; v = None
    for c in C: v = c if v is None else v + (c - v) * 2 / 35; ema.append(v)
    out = []; free = 0
    for i in range(200, len(T) - 3):
        if T[i+1] < free: continue
        for s in (1, -1):                       # +1 покупка
            entered = any(s * w1[q-1] < -38.2 and -38.2 <= s * w1[q] <= 38.2 for q in range(i - window + 1, i + 1)) and -38.2 <= s * w1[i] <= 38.2
            if not entered: continue
            if not (s * w10[i] < 0 and s * w10[i-1] < s * w10[i] and s * w10[i-1] <= s * w10[i-2]): continue
            if not (s * (ema[i] - ema[i-1]) > 0 and L[i] - (0 if s > 0 else 0) <= ema[i] <= H[i] and s * (C[i] - ema[i]) > 0): continue
            k = i + 1                           # выход: бар не обновил экстремум -> закрытие следующего
            while k < len(T) - 2 and (H[k] > H[k-1] if s > 0 else L[k] < L[k-1]): k += 1
            lim = T[k+1] + 3600
            q = i + 2 if D.hour[i+1] == 0 else i + 1        # сигнал в 24:00 -> вход в 01:00
            if T[q] >= lim: continue
            r = execute(D, T[q], s, [(1, None)], None, costs=costs, limit=lim)
            if r: out.append((T[q], r[0])); free = r[1] + 1
            break
    return out

def run_h4(D, yellow, mode, costs):
    G = D.G4; H4c = [g['c'] for g in G]
    w32 = cci([g['h'] for g in G], [g['l'] for g in G], H4c, 32); w2 = cci([g['h'] for g in G], [g['l'] for g in G], H4c, 2)
    start = {}
    for i, k in enumerate(D.i4): start.setdefault(k, i)
    out = []; free = 0; used = None; cnt = {1: 0, -1: 0}; armed = 0
    for k in range(60, len(G) - 1):
        for sg in (1, -1): cnt[sg] = cnt[sg] + 1 if sg * w32[k] > 0 else 0
        s = D.st[k]
        if not s: continue
        if cnt[-s] == 0 and armed == s: armed = 0
        if cnt[-s] == yellow: armed = s           # желтый столбик по другую сторону нуля
        if armed != s or -s * w32[k] <= 0 or -s * w2[k] <= 0: continue
        t = D.T[start[k+1]]
        if t < free: continue
        armed = 0
        if mode == 'до смены шлейфа':
            m = k + 1
            while m < len(G) - 1 and D.st[m] == s: m += 1
            r = execute(D, t, s, [(1, None)], None, costs=costs, limit=D.T[start[min(m + 1, len(G) - 1)]])
        else:
            a = sum(G[q]['h'] - G[q]['l'] for q in range(k - 13, k + 1)) / 14 / D.pip
            r = execute(D, t, s, [(1, 2 * a)], a, costs=costs)
        if r: out.append((t, r[0])); free = r[1] + 1
    return out

def run_13(D, conservative, sl, costs):
    w13 = D.cci(13); w100 = D.cci(100); T = D.T; out = []; free = 0; sigday = None; s = 0; seen = False; lastk = None
    for j in range(200, len(T)):
        k = D.i4[j-1]
        if D.i4[j] != k and D.st[k] != D.st[k-1] and D.st[k]: s = D.st[k]; sigday = D.iD[j-1]; seen = False
        if not s or D.iD[j] != sigday + 1: continue
        v = -s * w13[j-1]                          # для продажи: подъем выше +76.4 и возврат в 0..76.4
        if v > 76.4: seen = True; continue
        if seen and 0 < v <= 76.4:
            seen = False; sig = s; s = 0
            if D.hour[j] == 0 or T[j] < free: continue
            if conservative and not (sig * w100[j-1] > 38.2 and sig * (w13[j-1] - w13[j-2]) > 0): continue
            r = execute(D, T[j], sig, [(1, 10), (1, 20), (1, 40), (1, 90)], sl, costs=costs, ladder={1: 3, 2: 13, 3: 23})
            if r: out.append((T[j], r[0])); free = r[1] + 1
    return out

def stats(tr):
    x = [v for _, v in tr]; g = sum(v for v in x if v > 0); l = -sum(v for v in x if v < 0); y = {}
    for t, v in tr:
        k = dt.datetime.fromtimestamp(t, UTC).year; y[k] = round(y.get(k, 0) + v, 1)
    return dict(n=len(x), pips=round(sum(x), 1), pf=round(g / l, 3) if l else 0, years=y)

def jobs_for(D):
    jobs = {'советник v2': lambda c: run_ea(D, V2, c), 'советник v1': lambda c: run_ea(D, V1, c)}
    for w in (1, 5, 10): jobs[f'Instant H1, окно {w}'] = lambda c, w=w: run_instant(D, w, c)
    for y in (5, 6):
        for m in ('до смены шлейфа', 'цель 2:1'): jobs[f'H4, столбик {y}, {m}'] = lambda c, y=y, m=m: run_h4(D, y, m, c)
    for cons in (False, True):
        for sl in (40, 70): jobs[f"13-100 {'консервативная' if cons else 'агрессивная'}, стоп {sl}"] = lambda c, cons=cons, sl=sl: run_13(D, cons, sl, c)
    return jobs

def work(a):
    root, pair = a; D = Data(root, pair); res = {}
    for n, f in jobs_for(D).items():
        net = f(True); r = dict(net=stats(net), gross=stats(f(False)), trades=net); res[f'{pair} | {n}'] = r
        print(pair, '|', n, r['net']['n'], r['net']['pips'], r['net']['pf'], '| без издержек', r['gross']['pf'], flush=True)
    return res

if __name__ == '__main__':
    root = sys.argv[1]
    with Pool(2) as P: out = P.map(work, [(root, q) for q in ('EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD')], chunksize=1)
    res = {k: v for d in out for k, v in d.items()}; json.dump(res, open(sys.argv[2], 'w'), ensure_ascii=False)
    big = {k: v for k, v in res.items() if v['net']['n'] >= 100}
    print('всего', len(res), 'с 100+ сделками', len(big))
    for k, v in sorted(big.items(), key=lambda kv: -kv[1]['net']['pf'])[:5]: print(k, v['net'], v['gross']['pf'])
    pool = {}
    for k, v in res.items(): pool.setdefault(k.split(' | ')[1], []).extend(v['trades'])
    print('--- все 4 пары вместе')
    for k, v in pool.items(): s = stats(v); print(k, s['n'], s['pips'], s['pf'])
