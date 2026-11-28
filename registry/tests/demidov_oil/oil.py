"""Книга по нефти: средняя (H+L+C)/3 первого часа, сигнальная свеча M5 касается её, вход на пробое, стоп 1 единица, цель 2 (первый вход) и 3 (второй).
Исполнение по M1. Запуск: python -I oil.py <бары> <отчёт.json>"""
import sys, os, json, itertools, bisect, datetime as dt, statistics as st
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from algo import load, UTC

def run(M1, M5, p, costs=True, gold=False, jpy=False):
    T, O, H, L, C, SP, pt = (M1[x] for x in ('T', 'O', 'H', 'L', 'C', 'SP', 'pt'))
    t5, o5, h5, l5, c5 = (M5[x] for x in ('T', 'O', 'H', 'L', 'C'))
    days = {}
    for i, t in enumerate(t5): days.setdefault(t // 86400, []).append(i)
    hist = []; tr = []
    for d in sorted(days):
        start = d * 86400 + p['start']; end = min(start + p['len'], d * 86400 + 21 * 3600)
        idx = [i for i in days[d] if start <= t5[i] < end]
        if not idx: continue
        rng = [h5[i] - l5[i] for i in idx]
        first = [i for i in idx if t5[i] < start + 3600]; unit_hist = st.median(hist[-20:]) if len(hist) >= 10 else None
        hist.append(st.median(rng))
        if len(first) < 10 or unit_hist is None: continue
        hi = max(h5[i] for i in first); lo = min(l5[i] for i in first); level = (hi + lo + c5[first[-1]]) / 3
        unit = unit_hist if p['scale'] == 'свеча' else 0.00125 * level
        n = 0; free = start + 3600
        for i in idx:
            if n >= 2: break
            if t5[i] < free or not (l5[i] <= level <= h5[i]): continue
            if p['filter'] and h5[i] - l5[i] > 2 * unit: continue
            sh, sl_ = h5[i], l5[i]; j = bisect.bisect_left(T, t5[i] + 300); pos = None
            while j < len(T) and T[j] < end:
                sp = SP[j] * pt if costs else 0
                if pos is None:
                    up = H[j] + sp > sh; dn = L[j] < sl_
                    if up and dn: s = 1 if C[j] < O[j] else -1          # обе стороны в одну минуту: берём худшую
                    elif up: s = 1
                    elif dn: s = -1
                    else: j += 1; continue
                    e = max(sh, O[j] + sp) if s > 0 else min(sl_, O[j])
                    tp = e + s * unit * (2 if n == 0 else 3); stop = e - s * unit; t0 = T[j]; pos = s
                    # в минуту входа: стоп считаем сработавшим, если закрытие минуты уже за стопом
                    cx = C[j] + (0 if s > 0 else sp); x = stop if s * (cx - stop) <= 0 else None
                else:
                    off = 0 if pos > 0 else sp; o = O[j] + off
                    worst = (L[j] if pos > 0 else H[j]) + off; best = (H[j] if pos > 0 else L[j]) + off; x = None
                    if pos * (worst - stop) <= 0: x = stop if pos * (o - stop) > 0 else o
                    elif pos * (best - tp) >= 0: x = tp
                if x is not None: break
                j += 1
            if pos is None: continue
            if j >= len(T) or T[j] >= end:
                k = j - 1; x = C[k] + (0 if pos > 0 else (SP[k] * pt if costs else 0)); j = k
            com = (0.07 if gold else e * 7e-5 if jpy else 7e-5) if costs else 0
            r = (pos * (x - e) - com) / unit
            tr.append((t0, r, n, x == tp)); n += 1; free = T[j] + 60
    return tr

def stats(tr):
    x = [t[1] for t in tr]; g = sum(v for v in x if v > 0); l = -sum(v for v in x if v < 0); y = {}
    for t in tr:
        k = dt.datetime.fromtimestamp(t[0], UTC).year; y[k] = round(y.get(k, 0) + t[1], 1)
    return dict(n=len(x), R=round(sum(x), 1), pf=round(g / l, 3) if l else 0, target=round(sum(t[3] for t in tr) / max(len(x), 1), 3), win=round(sum(v > 0 for v in x) / max(len(x), 1), 3), years=y)

if __name__ == '__main__':
    root = sys.argv[1]; res = {}
    STARTS = {'03:30 (открытие MCX)': (12600, 52200), '07:00': (25200, 50400), '08:00': (28800, 46800), '13:30': (48600, 27000)}
    for pair in ('XAUUSD', 'EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD'):
        M1 = load(f'{root}/{pair}/{pair}_M1.bin'); M5 = load(f'{root}/{pair}/{pair}_M5.bin')
        for (sn, (s, ln)), sc, fl in itertools.product(STARTS.items(), ('свеча', 'процент'), (False, True)):
            p = dict(start=s, len=ln, scale=sc, filter=fl); kw = dict(gold=pair == 'XAUUSD', jpy=pair == 'USDJPY')
            a = stats(run(M1, M5, p, **kw)); b = stats(run(M1, M5, p, False, **kw))
            res[f'{pair} | старт {sn}, масштаб: {sc}, фильтр: {fl}'] = dict(net=a, gross=b)
        print('готово', pair, flush=True)
    json.dump(res, open(sys.argv[2], 'w'), ensure_ascii=False)
    big = {k: v for k, v in res.items() if v['net']['n'] >= 100}
    print('прогонов', len(res), len(big))
    for k, v in sorted(big.items(), key=lambda kv: -kv[1]['net']['pf'])[:8]: print(k, v['net'], '| без издержек', v['gross']['pf'], v['gross']['target'])
    for key in ('net', 'gross'):
        print(key, 'медиана PF', st.median(v[key]['pf'] for v in big.values()), 'доля до цели', st.median(v[key]['target'] for v in big.values()), 'доля прибыльных', st.median(v[key]['win'] for v in big.values()))
    print('макс доля прибыльных без издержек', max(v['gross']['win'] for v in big.values()))
