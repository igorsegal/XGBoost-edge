#!/usr/bin/env python3
"""Система H4 из документа на истории MT4 (H4), включая годы, которые не участвовали в подборе (до 2020). Данные после 2024 отрезаются сразу.
Запуск: python -I oos.py <папка с .hst> <отчёт.json>"""
import sys, os, struct, random, json, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from woodie import cci, trail, stats
UTC = dt.timezone.utc; CUT = 1735689600; Y2020 = 1577836800
PIP = dict(EURUSD=1e-4, GBPUSD=1e-4, XAUUSD=0.1, CHFJPY=0.01)
SPREAD = dict(EURUSD=1.0, GBPUSD=1.5, XAUUSD=3.0, CHFJPY=3.0)   # пункты

def read(path):
    b = open(path, 'rb').read(); ver = struct.unpack('<i', b[:4])[0]; assert ver == 401, ver
    G = []
    for p in range(148, len(b) - 59, 60):
        t, o, h, l, c = struct.unpack('<qdddd', b[p:p+40])
        if t < CUT: G.append(dict(t=t, o=o, h=h, l=l, c=c))
    return G

def system(G, pair, yellow, mode):
    pip = PIP[pair]; sp = SPREAD[pair] * pip
    com = lambda e: 0.07 if pair == 'XAUUSD' else e * 7e-5 if pair.endswith('JPY') else 7e-5
    H = [g['h'] for g in G]; L = [g['l'] for g in G]; C = [g['c'] for g in G]
    st = trail(G)[0]; w32 = cci(H, L, C, 32); w2 = cci(H, L, C, 2)
    def close(k, s, a=None):
        e = G[k]['o'] + (sp if s > 0 else 0)
        if a is None:
            m = k
            while m < len(G) - 1 and st[m] == s: m += 1
            q = min(m + 1, len(G) - 1); x = G[q]['o'] + (sp if s < 0 else 0)
            return (s * (x - e) - com(e)) / pip, q
        stop = e - s * a; tp = e + s * 2 * a
        for q in range(k, len(G)):
            off = sp if s < 0 else 0; o = G[q]['o'] + off
            worst = (G[q]['l'] if s > 0 else G[q]['h']) + off; best = (G[q]['h'] if s > 0 else G[q]['l']) + off
            if s * (worst - stop) <= 0:
                x = stop if s * (o - stop) > 0 else o; return (s * (x - e) - com(e)) / pip, q
            if s * (best - tp) >= 0: return (s * (tp - e) - com(e)) / pip, q
        return None
    out = []; free = 0; cnt = {1: 0, -1: 0}; armed = 0
    for k in range(60, len(G) - 1):
        for sg in (1, -1): cnt[sg] = cnt[sg] + 1 if sg * w32[k] > 0 else 0
        s = st[k]
        if not s: continue
        if cnt[-s] == 0 and armed == s: armed = 0
        if cnt[-s] == yellow: armed = s
        if armed != s or -s * w32[k] <= 0 or -s * w2[k] <= 0: continue
        if k + 1 < free: continue
        armed = 0
        a = None if mode == 'до смены шлейфа' else sum(G[q]['h'] - G[q]['l'] for q in range(k - 13, k + 1)) / 14
        r = close(k + 1, s, a)
        if r: out.append((G[k+1]['t'], r[0])); free = r[1] + 1
    return out, st, close

def rnd_base(G, st, close, n, lo, hi, runs=300):
    cand0 = [k for k in range(60, len(G) - 1) if st[k] and lo <= G[k+1]['t'] < hi]; res = []
    for r in range(runs):
        rnd = random.Random(r); cand = cand0[:]; rnd.shuffle(cand); tr = []; busy = []
        for k in cand:
            if len(tr) >= n: break
            x = close(k + 1, st[k])
            if any(k + 1 <= e and x[1] >= b for b, e in busy): continue
            busy.append((k + 1, x[1])); tr.append((G[k+1]['t'], x[0]))
        res.append(stats(tr)['pf'])
    return sorted(res)

if __name__ == '__main__':
    root = sys.argv[1]; data = {p: read(f'{root}/{p}240.hst') for p in PIP}; res = {}
    for p, G in data.items():
        yr = {}
        for g in G: y = dt.datetime.fromtimestamp(g['t'], UTC).year; yr[y] = yr.get(y, 0) + 1
        print(p, 'баров', len(G), 'годы:', {y: n for y, n in yr.items()})
    for yellow in (5, 6):
        for mode in ('до смены шлейфа', 'цель 2:1'):
            pool = {'до 2020': [], '2020-2024': []}
            for p, G in data.items():
                tr, st, close = system(G, p, yellow, mode)
                # годы с редкими барами (дырявая история) в счет не идут
                yr = {}
                for g in G: y = dt.datetime.fromtimestamp(g['t'], UTC).year; yr[y] = yr.get(y, 0) + 1
                tr = [x for x in tr if yr[dt.datetime.fromtimestamp(x[0], UTC).year] >= 1200]
                for per, lo, hi in (('до 2020', 0, Y2020), ('2020-2024', Y2020, CUT)):
                    part = [x for x in tr if lo <= x[0] < hi]; pool[per] += part
                    if not part: continue
                    s = stats(part); res[f'{p} | {yellow} | {mode} | {per}'] = s
                    line = f"{p} столбик {yellow}, {mode}, {per}: сделок {s['n']} пунктов {s['pips']} PF {s['pf']}"
                    if mode == 'до смены шлейфа' and s['n'] >= 10:
                        full = [k for k in range(len(G)) if yr[dt.datetime.fromtimestamp(G[k]['t'], UTC).year] >= 1200]
                        b = rnd_base(G, st, close, s['n'], max(lo, G[full[0]]['t']), hi)
                        line += f" | случайные: медиана {b[len(b)//2]}, не хуже {sum(v >= s['pf'] for v in b)}/{len(b)}"
                    print(line, flush=True)
            for per, tr in pool.items():
                s = stats(tr); res[f'все | {yellow} | {mode} | {per}'] = s
                print(f"== все вместе, столбик {yellow}, {mode}, {per}: сделок {s['n']} пунктов {s['pips']} PF {s['pf']}")
    json.dump(res, open(sys.argv[2], 'w'), ensure_ascii=False)
