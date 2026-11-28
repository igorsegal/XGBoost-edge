#!/usr/bin/env python3
"""Метод MYTRADE: тест 100%/50% консолидации и разворотная модель. Зоны по H1, исполнение по M1 (индексы - по H1). Данные только до 2025-01-01.
Запуск: python -I mytrade.py <бары до 2025: M1/H1> <папка raw для индексов> <отчёт.json>"""
import sys, os, json, bisect, datetime as dt, itertools
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from algo import load, UTC, CUT, us_summer
FXM = ('EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'XAUUSD'); IDX = ('SP500', 'NAS100')
LIFE = 480        # сколько часовых баров зона ждет теста (мое допущение)

def srv(t): h = t - t % 3600; return t + (10800 if us_summer(h) else 7200)

class Data:
    def __init__(s, sym, root, raw, cut=CUT):
        if sym in IDX:
            B = load(f'{raw}/{sym}/{sym}_H1.bin', cut); s.m = B; s.h = B; T = list(B['T']); s.per = 3600   # время в raw уже серверное
        else:
            B = load(f'{root}/{sym}/{sym}_H1.bin', cut); s.h = B; s.m = load(f'{root}/{sym}/{sym}_M1.bin', cut); T = [srv(t) for t in B['T']]; s.per = 60
        s.sym = sym; s.T = T; s.O, s.H, s.L, s.C, s.V = (B[x] for x in 'OHLCV'); n = len(T)
        # средний дневной размах по 20 предыдущим дням
        days = {}; 
        for i, t in enumerate(T):
            d = t // 86400
            if d not in days: days[d] = [s.H[i], s.L[i]]
            else: days[d][0] = max(days[d][0], s.H[i]); days[d][1] = min(days[d][1], s.L[i])
        keys = sorted(days); rng = [days[k][0] - days[k][1] for k in keys]; atr = {}
        for q, k in enumerate(keys): atr[k] = sum(rng[q-20:q]) / 20 if q >= 20 else None
        s.atr = [atr[t // 86400] for t in T]
        cs = [0]
        for v in s.V: cs.append(cs[-1] + v)
        s.cs = cs
        hour = 16 if sym in ('SP500', 'NAS100', 'DJ30', 'US2000') else 10          # открытие основной сессии (серверное время)
        s.open_dir = {}
        for i, t in enumerate(T):
            if t % 86400 // 3600 == hour: s.open_dir[t // 86400] = (1 if s.C[i] > s.O[i] else -1 if s.C[i] < s.O[i] else 0, i)
    def vol(s, a, b): return (s.cs[b] - s.cs[a]) / max(b - a, 1)

def zones(D, N, k):
    """Консолидации: тела N часовых свечей умещаются в k дневных размахов; выход - закрытие H1 дальше края на 50% ширины."""
    O, C = D.O, D.C; Z = []; i = N + 480; floor = i - N
    while i < len(C):
        a = i - N + 1
        if a < floor or D.atr[i] is None: i += 1; continue
        top = max(max(O[a:i+1]), max(C[a:i+1])); bot = min(min(O[a:i+1]), min(C[a:i+1])); R = top - bot
        if R <= 0 or R > k * D.atr[i]: i += 1; continue
        e = i + 1
        while e < len(C) and bot - 0.5 * R <= C[e] <= top + 0.5 * R: e += 1
        if e >= len(C): break
        d = 1 if C[e] > top else -1
        zv = D.vol(a, e); base = D.vol(a - 480, a)
        Z.append(dict(a=a, e=e, top=top, bot=bot, R=R, d=d, zv=zv, goodvol=zv >= base, quiet=D.V[e] < 2 * zv))
        floor = e + 1; i = e + N
    # отмена зоны: закрытие H1 глубже 85% ширины со стороны выхода
    for z in Z:
        edge = z['top'] if z['d'] > 0 else z['bot']; z['kill'] = None
        for j in range(z['e'] + 1, len(C)):
            if z['d'] * (edge - C[j]) > 0.85 * z['R']: z['kill'] = j; break
    return Z

def balance_series(D, Z):
    ev = sorted((z['kill'], -z['d']) for z in Z if z['kill'] is not None)       # отменили поддержку -> -1, сопротивление -> +1
    out = [0] * len(D.C); s = 0; q = 0
    for i in range(len(D.C)):
        while q < len(ev) and ev[q][0] <= i: s = ev[q][1]; q += 1
        out[i] = s
    return out

def blocked(Z, i, side, lo, hi, me):
    """Есть ли между входом и целью другая действующая консолидация (то есть зона не разряженная)."""
    for z in Z:
        if z is me or z['e'] >= i or i - z['e'] > LIFE * 3 or (z['kill'] is not None and z['kill'] < i): continue
        if z['d'] == -side and z['top'] > lo and z['bot'] < hi: return True
    return False

def h_of(D, t_m): return bisect.bisect_right(D.T, t_m) - 1       # часовой бар, внутри которого момент t_m

def mtime(D): return D.T if D.sym in IDX else D.MT

def follow(D, j, side, e, sl, tp, costs, same_bar_tp):
    M = D.m; O, H, L, SP, pt = M['O'], M['H'], M['L'], M['SP'], M['pt']
    com = 0 if (not costs or D.sym in IDX) else 0.07 if D.sym == 'XAUUSD' else e * 7e-5 if D.sym == 'USDJPY' else 7e-5
    first = True
    while j < len(O):
        off = 0 if side > 0 else (SP[j] * pt if costs else 0)
        o = O[j] + off; worst = (L[j] if side > 0 else H[j]) + off; best = (H[j] if side > 0 else L[j]) + off
        if side * (worst - sl) <= 0:
            x = sl if (first and not same_bar_tp) or side * (o - sl) > 0 else o
            return (side * (x - e) - com), j
        if (not first or same_bar_tp) and side * (best - tp) >= 0: return (side * (tp - e) - com), j
        first = False; j += 1
    return None

def candidates_test(D, Z, bal, level, rr, filt, costs):
    M = D.m; O, H, L, SP, pt = M['O'], M['H'], M['L'], M['SP'], M['pt']; MT = mtime(D); out = []
    for z in Z:
        side = z['d']
        if filt == 'все' and not (z['goodvol'] and z['quiet']): continue
        edge = z['top'] if side > 0 else z['bot']; E = edge if level == 100 else (z['top'] + z['bot']) / 2; sl = edge - side * 0.8 * z['R']
        if z['e'] + 1 >= len(D.T): continue
        j = bisect.bisect_left(MT, D.T[z['e'] + 1]); end = D.T[min(z['e'] + LIFE, len(D.T) - 1)]
        while j < len(O) and MT[j] <= end:
            sp = SP[j] * pt if costs else 0
            reach = (L[j] + sp <= E) if side > 0 else (H[j] >= E)
            if reach:
                o = O[j] + (sp if side > 0 else 0); entry = o if side * (E - o) > 0 else E
                i = h_of(D, MT[j]); risk = side * (entry - sl)
                if risk <= 0: break
                tp = entry + side * rr * risk
                if filt != 'без фильтров' and bal[i-1] != side: break
                if filt == 'все':
                    od = D.open_dir.get(D.T[i] // 86400)
                    if od and od[1] < i and od[0] == side: break
                    if blocked(Z, i, side, min(entry, tp), max(entry, tp), z): break
                r = follow(D, j, side, entry, sl, tp, costs, False)
                if r: out.append((MT[j], MT[r[1]], r[0] / risk, r[0], side))
                break
            j += 1
    return out

def candidates_rev(D, Z, rr, filt, costs):
    M = D.m; O, SP, pt = M['O'], M['SP'], M['pt']; MT = mtime(D); out = []
    for z in Z:
        k = z['kill']
        if k is None or k - z['e'] > LIFE or k + 1 >= len(D.T): continue
        side = -z['d']; seg = range(z['e'], k + 1)
        far = max(D.H[q] for q in seg) if side < 0 else min(D.L[q] for q in seg)
        j = bisect.bisect_left(MT, D.T[k + 1])
        if j >= len(O): continue
        sp = SP[j] * pt if costs else 0; entry = O[j] + (sp if side > 0 else 0); sl = far + (sp if side < 0 else 0); risk = side * (entry - sl)
        if risk <= 0 or risk > 2.5 * z['R']: continue                          # «если стоп адекватный»
        tp = entry + side * rr * risk
        if filt == 'все':
            if not z['goodvol']: continue
            if max(D.V[q] for q in seg) < 2 * z['zv']: continue                 # ложный выход на больших объемах
            qx = max(seg, key=lambda q: D.H[q]) if side < 0 else min(seg, key=lambda q: D.L[q])
            od = D.open_dir.get(D.T[qx] // 86400)
            if not od or od[1] > k or od[0] != z['d']: continue                              # ложный выход совпадает с направлением открытия
            if blocked(Z, k + 1, side, min(entry, tp), max(entry, tp), z): continue
        r = follow(D, j, side, entry, sl, tp, costs, True)
        if r: out.append((MT[j], MT[r[1]], r[0] / risk, r[0], side))
    return out

def one_at_a_time(c):
    out = []; free = 0
    for x in sorted(c):
        if x[0] > free: out.append(x); free = x[1]
    return out

CONF = [('тест', N, k, lvl, rr, f) for N, k, lvl, rr, f in itertools.product((24, 48), (1.0, 1.5), (100, 50), (2, 3), ('без фильтров', 'баланс', 'все'))] + \
       [('разворот', N, k, 0, rr, f) for N, k, rr, f in itertools.product((24, 48), (1.0, 1.5), (1, 2), ('без фильтров', 'все'))]

def prepare(sym, root, raw, cut=CUT):
    D = Data(sym, root, raw, cut)
    if sym not in IDX: D.MT = [srv(t) for t in D.m['T']]
    return D

def run_conf(D, cache, c, costs=True):
    kind, N, k, lvl, rr, f = c
    if (N, k) not in cache:
        Z = zones(D, N, k); cache[(N, k)] = (Z, balance_series(D, Z))
    Z, bal = cache[(N, k)]
    return one_at_a_time(candidates_test(D, Z, bal, lvl, rr, f, costs) if kind == 'тест' else candidates_rev(D, Z, rr, f, costs))

def work(a):
    sym, root, raw = a; D = prepare(sym, root, raw); cache = {}; res = {}
    for c in CONF:
        res['|'.join(map(str, c))] = dict(net=run_conf(D, cache, c, True), gross=run_conf(D, cache, c, False))
    print(sym, 'готово; зон', {k: len(v[0]) for k, v in cache.items()}, flush=True)
    return sym, res

def stats(tr, i=2):
    x = [v[i] for v in tr]; g = sum(v for v in x if v > 0); l = -sum(v for v in x if v < 0)
    return dict(n=len(x), sum=round(sum(x), 1), pf=round(g / l, 3) if l else 0, win=round(100 * sum(v > 0 for v in x) / len(x)) if x else 0)

if __name__ == '__main__':
    root, raw, out = sys.argv[1:4]
    with Pool(2) as P: R = dict(P.map(work, [(s, root, raw) for s in FXM + IDX], chunksize=1))
    json.dump(R, open(out, 'w'), ensure_ascii=False)
    rows = []
    for key in R['EURUSD']:
        net = [t for s in R for t in R[s][key]['net']]; gr = [t for s in R for t in R[s][key]['gross']]
        rows.append((key, stats(net), stats(gr)))
    big = [r for r in rows if r[1]['n'] >= 100]
    print('вариантов', len(rows), '| с 100+ сделками (все инструменты вместе)', len(big), '| из них PF>=1.3:', sum(r[1]['pf'] >= 1.3 for r in big), '| PF>1:', sum(r[1]['pf'] > 1 for r in big))
    for r in sorted(rows, key=lambda r: -r[1]['pf'])[:14]: print(r[0], 'издержки:', r[1], '| без:', r[2]['pf'])
    import statistics as S
    for kind in ('тест', 'разворот'):
        for f in ('без фильтров', 'баланс', 'все'):
            q = [r for r in rows if r[0].startswith(kind) and r[0].endswith(f)]
            if q: print(f'{kind} / {f}: медиана сделок {S.median(x[1]["n"] for x in q)}, PF с издержками {S.median(x[1]["pf"] for x in q):.2f}, без {S.median(x[2]["pf"] for x in q):.2f}')
