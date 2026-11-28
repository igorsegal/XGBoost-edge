#!/usr/bin/env python3
"""Разворотная модель MYTRADE на металлах, нефти и индексах: все сигналы сетки параметров с признаками фильтров. Зоны по H1, исполнение по M5.
Данные строго до 2025-01-01. Запуск: python -I deep.py <папка raw> <сигналы.pkl>"""
import sys, os, pickle, datetime as dt, itertools
import numpy as np
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import mytrade as M
UTC = dt.timezone.utc; CUT = int(dt.datetime(2025, 1, 1, tzinfo=UTC).timestamp())
METALS = ['XAUUSD', 'XAGUSD', 'XAUEUR', 'XAUAUD', 'XAUJPY', 'XAGAUD', 'XPDUSD', 'XPTUSD']; OIL = ['USOUSD', 'UKOUSD']
INDICES = ['SP500', 'NAS100', 'DJ30', 'GER40', 'UK100', 'EU50', 'FRA40', 'HK50', 'CHINA50', 'SPI200', 'US2000']
NS = (32, 40, 48, 56, 64); KS = (0.8, 1.0, 1.2, 1.4); RRS = (1.0, 1.5, 2.0, 2.5, 3.0); HOLDS = (0, 7, 14, 28)           # 0 = без ограничения по времени, иначе выход через столько календарных дней
DT = np.dtype([('t', '<i8'), ('o', '<f8'), ('h', '<f8'), ('l', '<f8'), ('c', '<f8'), ('v', '<i8'), ('sp', '<i4'), ('rv', '<i8')])

def read(path, start, cut):
    b = open(path, 'rb').read(); pt = np.frombuffer(b, '<f8', 1, 24)[0]; n = int(np.frombuffer(b, '<i8', 1, 32)[0]); sl = int(np.frombuffer(b, '<i4', 1, 56)[0]); per = int(np.frombuffer(b, '<i4', 1, 16)[0])
    a = np.frombuffer(b, DT, n, 60 + sl)
    nz = a['sp'][(a['sp'] > 0) & (a['t'] >= start) & (a['t'] < cut)]; med = float(np.median(nz)) if len(nz) else 0.0
    a = a[(a['t'] >= start) & (a['t'] + per <= cut)]
    sp = np.where(a['sp'] > 0, a['sp'], med) * pt
    return a, sp, med * pt

class D:
    def __init__(s, root, sym, cut=CUT):
        start = int(dt.datetime(2018, 3, 17, tzinfo=UTC).timestamp()) if sym == 'DJ30' else int(dt.datetime(2017, 11, 7, tzinfo=UTC).timestamp())
        h, _, _ = read(f'{root}/{sym}/{sym}_H1.bin', start, cut); m, msp, s.spmed = read(f'{root}/{sym}/{sym}_M5.bin', start, cut)
        s.sym = sym; s.T = h['t'].tolist(); s.O, s.H, s.L, s.C, s.V = (h[x].tolist() for x in 'ohlcv')
        s.mt = np.array(m['t']); s.mo, s.mh, s.ml = np.array(m['o']), np.array(m['h']), np.array(m['l']); s.msp = msp; s.mc = np.array(m['c'])
        s.hH, s.hL = np.array(h['h']), np.array(h['l'])
        days = {}
        for t, hi, lo in zip(s.T, s.H, s.L):
            d = t // 86400
            if d not in days: days[d] = [hi, lo]
            else: days[d][0] = max(days[d][0], hi); days[d][1] = min(days[d][1], lo)
        keys = sorted(days); rng = [days[k][0] - days[k][1] for k in keys]; atr = {k: (sum(rng[q-20:q]) / 20 if q >= 20 else None) for q, k in enumerate(keys)}
        s.atr = [atr[t // 86400] for t in s.T]
        cs = [0]
        for v in s.V: cs.append(cs[-1] + v)
        s.cs = cs; hour = 16 if sym in ('SP500', 'NAS100', 'DJ30', 'US2000') else 10; s.open_dir = {}
        for i, t in enumerate(s.T):
            if t % 86400 // 3600 == hour: s.open_dir[t // 86400] = ((s.C[i] > s.O[i]) - (s.C[i] < s.O[i]), i)
    def vol(s, a, b): return (s.cs[b] - s.cs[a]) / max(b - a, 1)

def follow(d, j, side, e, sl, tp, hold=0):
    """Первый бар M5, где достигнут стоп или цель; в одном баре - стоп. Продажа закрывается с учетом спреда.
    hold>0: не позже чем через hold дней по открытию бара. Если данные кончились - переоценка по последней цене."""
    n = len(d.mt); end = int(np.searchsorted(d.mt, d.mt[j] + hold * 86400)) if hold else n; a = j; step = 2000
    while a < end:
        b = min(a + step, end); off = d.msp[a:b] if side < 0 else 0
        if side > 0: s_hit = d.ml[a:b] <= sl; t_hit = d.mh[a:b] >= tp
        else: s_hit = d.mh[a:b] + off >= sl; t_hit = d.ml[a:b] + off <= tp
        hit = s_hit | t_hit
        if hit.any():
            q = int(hit.argmax()); i = a + q
            if s_hit[q]:
                o = d.mo[i] + (d.msp[i] if side < 0 else 0); x = sl if side * (o - sl) > 0 else o
            else: x = tp
            return side * (x - e), i
        a = b; step *= 2
    i = min(end, n - 1); x = (d.mo[i] if end < n else d.mc[i]) + (d.msp[i] if side < 0 else 0)
    return side * (x - e), i

def com(sym, e): return 0.07 if sym == 'XAUUSD' else e * 7e-5 if sym in METALS else 0.0

def signals(d, N, k):
    Z = M.zones(d, N, k); out = []
    for z in Z:
        q = z['kill']
        if q is None or q - z['e'] > M.LIFE or q + 1 >= len(d.T): continue
        side = -z['d']; e = z['e']
        ext = e + int((d.hH[e:q+1].argmax() if side < 0 else d.hL[e:q+1].argmin())); far = d.H[ext] if side < 0 else d.L[ext]
        j = int(np.searchsorted(d.mt, d.T[q+1]))
        if j >= len(d.mt): continue
        sp = float(d.msp[j]); entry = float(d.mo[j]) + (sp if side > 0 else 0); sl = far + (sp if side < 0 else 0); risk = side * (entry - sl)
        if risk <= 0 or risk > 2.5 * z['R'] or not d.atr[q]: continue
        od = d.open_dir.get(d.T[ext] // 86400); lo = float(d.hL[max(q-480, 0):q+1].min()); hi = float(d.hH[max(q-480, 0):q+1].max()); pos = ((z['top'] + z['bot']) / 2 - lo) / (hi - lo) if hi > lo else 0.5
        f = dict(объем_выноса=max(d.V[e:q+1]) >= 2 * z['zv'], открытие=bool(od) and od[1] <= q and od[0] == z['d'], объем_зоны=bool(z['goodvol']),
                 быстрый=q - e <= 24, край_диапазона=(pos >= 0.5) if z['d'] > 0 else (pos <= 0.5), по_тренду=(d.C[q] - d.C[max(q-480, 0)]) * side > 0, стоп_узкий=risk <= 1.5 * z['R'])
        res = {}
        for rr in RRS:
            tp = entry + side * rr * risk; thin = not M.blocked(Z, q + 1, side, min(entry, tp), max(entry, tp), z)
            for hold in HOLDS:
                g, i = follow(d, j, side, entry, sl, tp, hold); pnl = g - com(d.sym, entry); tout = int(d.mt[i]); nights = tout // 86400 - int(d.mt[j]) // 86400
                res[(rr, hold)] = dict(tout=tout, pnl=float(pnl), gross=float(g + sp), nights=int(nights), thin=thin)
        out.append(dict(sym=d.sym, t=int(d.mt[j]), side=side, entry=entry, risk=float(risk), atr=d.atr[q], sp=sp, f=f, res=res))
    return out

def work(a):
    root, sym, cut = a; d = D(root, sym, cut); out = {(N, k): signals(d, N, k) for N, k in itertools.product(NS, KS)}
    print(sym, 'H1', len(d.T), 'M5', len(d.mt), f'спред-замена {d.spmed:.5g}', 'сигналов 48/1.0:', len(out[(48, 1.0)]), flush=True)
    return sym, out

if __name__ == '__main__':
    root, out = sys.argv[1:3]; cut = int(sys.argv[3]) if len(sys.argv) > 3 else CUT
    assert cut <= CUT, 'экзамен 2025+ не открывается'
    syms = [s for s in METALS + OIL + INDICES if len(sys.argv) <= 4 or s in sys.argv[4].split(',')]
    with Pool(2) as P: R = dict(P.map(work, [(root, s, cut) for s in syms], chunksize=1))
    pickle.dump(R, open(out, 'wb'))
