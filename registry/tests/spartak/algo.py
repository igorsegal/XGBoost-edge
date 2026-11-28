#!/usr/bin/env python3
"""Курс «Алгоритм»: цепочка стартовый - трендовый - финишный ордер по тиковым объёмам. Данные до 2025-01-01.
Запуск: python -I algo.py <каталог баров> <отчёт.json>"""
import sys, struct, json, datetime as dt
UTC = dt.timezone.utc
CUT = int(dt.datetime(2025, 1, 1, tzinfo=UTC).timestamp()); BEGIN = int(dt.datetime(2020, 1, 1, tzinfo=UTC).timestamp())

def load(path, cutoff=CUT):
    b = open(path, 'rb').read(); per, = struct.unpack('<i', b[16:20]); pt, = struct.unpack('<d', b[24:32])
    n, = struct.unpack('<q', b[32:40]); sl, = struct.unpack('<i', b[56:60]); off = 60 + sl
    R = [r for r in struct.iter_unpack('<qddddqiq', b[off:off + 60 * n]) if BEGIN <= r[0] and r[0] + per <= cutoff]
    c = list(zip(*R)); return dict(pt=pt, per=per, T=c[0], O=c[1], H=c[2], L=c[3], C=c[4], V=c[5], SP=c[6])

def us_summer(t):
    d = dt.datetime.fromtimestamp(t, UTC); y = d.year
    s = dt.datetime(y, 3, 8, 7, tzinfo=UTC); s += dt.timedelta(days=(6 - s.weekday()) % 7)
    e = dt.datetime(y, 11, 1, 6, tzinfo=UTC); e += dt.timedelta(days=(6 - e.weekday()) % 7)
    return s <= d < e

def server_days(B):
    """Сутки серверного времени автора (UTC+2 зимой, UTC+3 летом): списки (минута суток, индекс бара)."""
    cache = {}; days = {}
    for i, t in enumerate(B['T']):
        h = t // 3600
        if h not in cache: cache[h] = 10800 if us_summer(h * 3600) else 7200
        s = t + cache[h]; days.setdefault(s // 86400, []).append((s % 86400 // 60, i))
    return [days[k] for k in sorted(days)]

def run(pair, B, days, p):
    O, H, L, C, V, SP, pt, T = (B[k] for k in ('O', 'H', 'L', 'C', 'V', 'SP', 'pt', 'T'))
    pip = 10 * pt
    trades = []
    base = p
    for day in days:
        p = base
        idx = [i for _, i in day]; mins = [m for m, _ in day]; n = len(idx)
        sb = next((k for k in range(n) if p['from'] <= mins[k] < p['sb_until'] and H[idx[k]] - L[idx[k]] >= p['sbrange'] * pt
                   and p['v0'] <= V[idx[k]] < p['vmax']), None)
        if sb is None: continue
        i = idx[sb]; vs = V[i]
        if p.get('adds') and vs > 150: p = {**p, 'away': 100}
        hi, lo = (H[i], L[i]) if H[i] - L[i] <= 100 * pt else (max(O[i], C[i]), min(O[i], C[i]))
        mid = (hi + lo) / 2; kv = p['k1'] if vs <= p['vmid'] else p['k2']
        state = 'away'; side = 0; pos = None; mark = None; vt = None
        def close(k, price, why):
            nonlocal pos
            d, entry, ei, kind = pos; j = idx[k]
            c = 7 / 100000 * (1 if pair.endswith('USD') else entry) if p['costs'] else 0
            trades.append(dict(kind=kind, d=d, t_in=T[ei], t_out=T[j], pips=(d * (price - entry) - c) / pip, why=why)); pos = None
        def openpos(k, d, kind):
            nonlocal pos
            j = idx[k]; sp = SP[j] * pt if p['costs'] else 0
            pos = (d, O[j] + sp if d > 0 else O[j], j, kind)
        order = None   # что открыть/закрыть на открытии следующего бара
        for k in range(sb + 1, n):
            j = idx[k]; sp = SP[j] * pt if p['costs'] else 0
            if mins[k] >= p['close_at']:
                if pos: close(k, O[j] if pos[0] > 0 else O[j] + sp, '22:00')
                break
            if order:
                act, d, kind = order; order = None
                if act == 'flip':
                    if pos: close(k, O[j] if pos[0] > 0 else O[j] + sp, 'сигнал')
                    if mins[k] < p['last_entry']: openpos(k, d, kind)
            if pos:                                           # стоп и цель внутри бара, стоп раньше
                d, entry = pos[0], pos[1]; off = 0 if d > 0 else sp
                stop = entry - d * p['sl'] * pt
                tp = mid if pos[3] == 'финишный' else (entry + d * p['tp'] * pt if p['tp'] else None)
                if d > 0:
                    if L[j] <= stop: close(k, min(stop, O[j]), 'стоп')
                    elif tp is not None and tp > entry and H[j] >= tp and pos[2] != j: close(k, tp, 'цель')
                else:
                    if H[j] + off >= stop: close(k, max(stop, O[j] + off), 'стоп')
                    elif tp is not None and tp < entry and L[j] + off <= tp and pos[2] != j: close(k, tp, 'цель')
            if k < 2: continue
            c0, c1, c2 = C[j], C[idx[k-1]], C[idx[k-2]]
            if state == 'away':
                if C[j] >= hi + p['away'] * pt: side = -1; state = 'turn'
                elif C[j] <= lo - p['away'] * pt: side = 1; state = 'turn'
            elif state == 'turn':                             # вершина (для продажи) или впадина линии закрытий
                if side * (c0 - c1) >= p['bend'] * pt and side * (c1 - c2) <= 0:
                    if mins[k] >= p['last_entry']: break
                    order = ('flip', side, 'стартовый'); state = 'tb'; mark = k + 1
            elif state in ('tb', 'fb'):
                need = kv * vs if state == 'tb' else vt * 1.05
                if k >= mark + p['gap'] and V[j] >= need:
                    vt = V[j]; mark = k; state = 'll' if state == 'tb' else 'hh'
            elif state in ('ll', 'hh'):                       # новый крайний уровень за look баров в сторону прежнего движения
                if state == 'll' and k <= mark + p['gap'] and V[j] > vt: vt = V[j]; mark = k
                prev = [C[idx[m]] for m in range(max(0, k - p['look']), k)]
                new_low, new_high = c0 < min(prev), c0 > max(prev)
                hit = (new_low if side < 0 else new_high) if state == 'll' else (new_high if side < 0 else new_low)
                if k >= mark + p['gap'] and hit:
                    if state == 'll': order = ('flip', -side, 'трендовый'); state = 'fb'; mark = k + 1
                    else: order = ('flip', side, 'финишный'); state = 'done'
        if pos: close(n - 1, C[idx[-1]] if pos[0] > 0 else C[idx[-1]] + (SP[idx[-1]] * pt if p['costs'] else 0), 'конец суток')
    return trades

def stats(tr):
    x = [t['pips'] for t in tr]; g = sum(v for v in x if v > 0); l = -sum(v for v in x if v < 0)
    y = {}
    for t in tr:
        k = dt.datetime.fromtimestamp(t['t_in'], UTC).year; y[k] = round(y.get(k, 0) + t['pips'], 1)
    return dict(n=len(x), pips=round(sum(x), 1), pf=round(g / l, 3) if l else 0, years=y)

M1 = dict(tf='M1', costs=True, **{'from': 30}, sb_until=1260, last_entry=1260, close_at=1320, sbrange=20, v0=60, vmax=10**9, vmid=98, k1=2.0, k2=1.618,
          away=30, bend=2, gap=10, look=100, sl=500, tp=500)
M15 = {**M1, 'tf': 'M15', 'from': 75, 'v0': 444, 'vmax': 10**9, 'vmid': 82, 'k1': 2.0, 'k2': 1.618, 'away': 100, 'look': 60}
VARIANTS = {'M1 по документу': M1, 'M1 объём от 100': {**M1, 'v0': 100, 'vmid': 140}, 'M1 стоп 400': {**M1, 'sl': 400, 'tp': 0},
            'M1 изгиб 10': {**M1, 'bend': 10}, 'M1 после 01:15, бар от 40': {**M1, 'from': 75, 'sbrange': 40, 'vmax': 200},
            'M15 по документу': M15, 'M15 отход 30': {**M15, 'away': 30}}
PAIRS = ['AUDUSD', 'EURUSD', 'GBPUSD', 'USDJPY']
VARIANTS['M1 с дополнениями по объёму'] = {**M1, 'adds': True, 'vmax': 200}
if __name__ == '__main__':
    root = sys.argv[1]; res = {}
    for pair in PAIRS:
        data = {}
        for tf in ('M1', 'M15'):
            B = load(f'{root}/{pair}/{pair}_{tf}.bin'); data[tf] = (B, server_days(B))
        for name, p in VARIANTS.items():
            B, days = data[p['tf']]; tr = run(pair, B, days, p); g = run(pair, B, days, {**p, 'costs': False})
            s = stats(tr); s0 = stats(g); parts = {k: (stats([t for t in tr if t['kind'] == k]), stats([t for t in g if t['kind'] == k])) for k in ('стартовый', 'трендовый', 'финишный')}
            res[f'{pair} | {name}'] = dict(net=s, gross=s0, parts=parts)
            print(f"{pair} | {name}: сделок {s['n']}, итог {s['pips']} пп, PF {s['pf']} | без издержек {s0['pips']} пп, PF {s0['pf']} | " +
                  ' '.join(f"{k[:5]} {v[0]['n']}/{v[0]['pf']}/{v[1]['pf']}" for k, v in parts.items()), flush=True)
    json.dump(res, open(sys.argv[2], 'w'), ensure_ascii=False)
