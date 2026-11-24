#!/usr/bin/env python3
"""xcheck_expr_example.py - независимая проверка движка условий на правиле EXAMPLE_RSI_PULLBACK_01.
Сигналы и сделки считаются заново отдельным кодом на Python и сравниваются с результатом тестера по трём отрезкам.
Использование: python xcheck_expr_example.py <папка raw с барами> <результат тестера .json> [rsi_period rsi_low rsi_high ema_period]"""
import struct, sys, json, bisect, os

def load(p):
    b = open(p, 'rb').read(); sl, = struct.unpack('<i', b[56:60]); off = 60 + sl; n, = struct.unpack('<q', b[32:40]); pt, = struct.unpack('<d', b[24:32]); per, = struct.unpack('<i', b[16:20])
    R = [struct.unpack('<qddddqiq', b[off + 60 * i:off + 60 * (i + 1)]) for i in range(n)]
    return pt, per, [r[0] for r in R], [r[1] for r in R], [r[2] for r in R], [r[3] for r in R], [r[4] for r in R], [r[6] for r in R]

raw, resf = sys.argv[1], sys.argv[2]
rsi_p, lo, hi, ema_p = [float(v) for v in sys.argv[3:7]] if len(sys.argv) >= 7 else (14, 30, 70, 50)
rsi_p, ema_p = int(rsi_p), int(ema_p)
pt, per, T, O, H, L, C, SP = load(os.path.join(raw, 'EURUSD', 'EURUSD_H1.bin')); n = len(C)
_, per4, T4, _, _, _, C4, _ = load(os.path.join(raw, 'EURUSD', 'EURUSD_H4.bin'))
# RSI (Wilder)
rsi = [None] * n; ag = al = 0.0
for i in range(1, rsi_p + 1):
    d = C[i] - C[i - 1]; ag += max(d, 0); al += max(-d, 0)
ag /= rsi_p; al /= rsi_p; rsi[rsi_p] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
for i in range(rsi_p + 1, n):
    d = C[i] - C[i - 1]; ag = (ag * (rsi_p - 1) + max(d, 0)) / rsi_p; al = (al * (rsi_p - 1) + max(-d, 0)) / rsi_p
    rsi[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
# EMA на H4
ema4 = [None] * len(C4); k = 2 / (ema_p + 1); e = sum(C4[:ema_p]) / ema_p; ema4[ema_p - 1] = e
for j in range(ema_p, len(C4)):
    e = e + k * (C4[j] - e); ema4[j] = e
close4 = [T4[j] + per4 for j in range(len(C4))]           # момент закрытия каждого бара H4
sig = [0] * n
for i in range(n):
    j = bisect.bisect_right(close4, T[i] + per) - 1        # последний бар H4, закрытый к закрытию бара H1
    if j < 0 or ema4[j] is None or rsi[i] is None: continue
    l = rsi[i] < lo and C[i] > ema4[j]; s = rsi[i] > hi and C[i] < ema4[j]
    sig[i] = 0 if (l and s) else (1 if l else (-1 if s else 0))
tr = [H[0] - L[0]] + [max(H[i] - L[i], abs(H[i] - C[i - 1]), abs(L[i] - C[i - 1])) for i in range(1, n)]
atr = [None] * n
for i in range(13, n): atr[i] = sum(tr[i - 13:i + 1]) / 14
end = T[-1] + 3600; Y = 365 * 86400; s0 = end - 5 * Y; s1 = s0 + 3 * Y; s2 = s1 + Y
comm = 7 / 100000; free = 0; trades = []; first = next(i for i in range(n) if T[i] >= s0)
for x in range(n - 1):
    if not sig[x] or x < first - 1 or x < free or atr[x] is None: continue
    e_ = x + 1
    if e_ + 23 >= n: break
    d = 2 * atr[x]; sp = SP[e_] * pt; dr = sig[x]
    entry = O[e_] + sp if dr > 0 else O[e_]; stop = entry - d if dr > 0 else entry + d; exitp = None
    for kk in range(e_, e_ + 24):
        if dr > 0:
            if kk > e_ and O[kk] <= stop: exitp = O[kk]; break
            if L[kk] <= stop: exitp = stop; break
        else:
            ao = O[kk] + SP[kk] * pt; ah = H[kk] + SP[kk] * pt
            if kk > e_ and ao >= stop: exitp = ao; break
            if ah >= stop: exitp = stop; break
    if exitp is None: kk = e_ + 23; exitp = C[kk] if dr > 0 else C[kk] + SP[kk] * pt
    pnl = (exitp - entry if dr > 0 else entry - exitp) - comm
    trades.append((T[e_], pnl / (10 * pt), x)); free = kk
res = json.load(open(resf, encoding='utf-8'))['rules'][0]['segments']; bad = 0
for name, a, b in (("train", s0, s1), ("validation", s1, s2), ("clean", s2, end + 1)):
    ps = [p for t, p, _ in trades if a <= t < b]; gw = sum(p for p in ps if p > 0); gl = -sum(p for p in ps if p < 0)
    r = next(s for s in res if s["segment"] == name)
    ok = len(ps) == r["trades"] and abs(sum(ps) - r["net_pips"]) < 0.11 and abs((gw / gl if gl else 999) - r["profit_factor"]) < 0.002
    bad += 0 if ok else 1
    print(f"{'OK ' if ok else 'ОШИБКА'} {name}: Python сделок {len(ps)}, нетто {sum(ps):.1f}, PF {(gw / gl if gl else 999):.3f}  |  тестер сделок {r['trades']}, нетто {r['net_pips']}, PF {r['profit_factor']}")
print("ИТОГ:", "СОВПАЛО" if bad == 0 else "РАСХОЖДЕНИЯ")
sys.exit(1 if bad else 0)
