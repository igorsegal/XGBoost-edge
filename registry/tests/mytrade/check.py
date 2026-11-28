#!/usr/bin/env python3
"""1) заглядывание вперед: обрезка истории на 2023-01-01; 2) проверка отобранных вариантов на инструментах и годах, не участвовавших в отборе;
3) случайные входы с теми же стопами и целями. Все данные до 2025-01-01. Запуск: python -I check.py <бары> <raw>"""
import sys, os, random, bisect, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import mytrade as M, algo
root, raw = sys.argv[1:3]; CUT23 = M.srv(1672531200)
SEL = [('разворот', 48, 1.0, 0, 2, 'без фильтров'), ('разворот', 48, 1.0, 0, 1, 'все'), ('разворот', 48, 1.5, 0, 1, 'все'), ('разворот', 48, 1.5, 0, 2, 'все'),
       ('тест', 24, 1.5, 50, 3, 'все'), ('тест', 48, 1.0, 100, 3, 'баланс')]
bad = 0; total = 0; ONE = M.one_at_a_time
for sym in ('EURUSD', 'XAUUSD'):
    a = M.prepare(sym, root, raw); b = M.prepare(sym, root, raw, 1672531200); ca = {}; cb = {}
    for c in M.CONF:
        M.one_at_a_time = sorted      # сравниваются все сигналы: незакрытая в обрезке позиция иначе «освобождает» место следующим
        x = [t for t in M.run_conf(a, ca, c) if t[1] < CUT23 - 86400]; y = [t for t in M.run_conf(b, cb, c) if t[1] < CUT23 - 86400]; total += len(x)
        if x != y: bad += 1; print('РАСХОЖДЕНИЕ', sym, c, len(x), len(y))
print('заглядывание вперед: сравнено сделок', total, 'расхождений', bad, flush=True)
M.one_at_a_time = ONE

# --- независимая проверка: raw, исполнение по H1 ---
FX = 'AUDCAD AUDCHF AUDJPY AUDNZD AUDUSD CADCHF CADJPY CHFJPY EURAUD EURCAD EURCHF EURGBP EURJPY EURNZD EURUSD GBPAUD GBPCAD GBPCHF GBPJPY GBPNZD GBPUSD NZDCAD NZDCHF NZDJPY NZDUSD USDCAD USDCHF'.split()
algo.BEGIN = 0; M.IDX = tuple(FX) + ('XAGUSD', 'SP500', 'NAS100', 'DJ30', 'GER40', 'UK100', 'EU50', 'FRA40', 'HK50', 'CHINA50', 'SPI200', 'US2000', 'USOUSD', 'UKOUSD', 'XAGAUD', 'XAUAUD')
class Raw(M.Data):
    def __init__(s, sym, cut):
        super().__init__(sym, root, raw, cut)
def raw_run(sym, c, cut, cache):
    Dd, zc = cache.setdefault((sym, cut), (Raw(sym, cut), {}))
    return M.run_conf(Dd, zc, c)
# комиссия за валютные пары добавляется внутри follow
orig = M.follow
def follow(D, j, side, e, sl, tp, costs, sb):
    r = orig(D, j, side, e, sl, tp, costs, sb)
    if r and costs and D.sym in FX: r = (r[0] - e * 7e-5, r[1])
    return r
M.follow = follow
yr = lambda t: dt.datetime.fromtimestamp(t, algo.UTC).year
cache = {}
sets = [('27 валютных пар, 2018–2019', FX, 0, 2019), ('22 пары вне отбора, 2020–2024', [s for s in FX if s not in ('EURUSD', 'GBPUSD', 'AUDUSD')], 2020, 2024),
        ('металлы, нефть, индексы вне отбора, 2018–2024', ['XAGUSD', 'DJ30', 'GER40', 'UK100', 'EU50', 'FRA40', 'HK50', 'CHINA50', 'SPI200', 'US2000', 'USOUSD', 'UKOUSD', 'XAGAUD', 'XAUAUD'], 0, 2024)]
for c in SEL:
    print('\n', '|'.join(map(str, c)))
    for name, lst, lo, hi in sets:
        allt = []; good = 0; cnt = 0
        for s in lst:
            if not os.path.exists(f'{raw}/{s}/{s}_H1.bin'): continue
            tr = [t for t in raw_run(s, c, algo.CUT, cache) if lo <= yr(t[0]) <= hi]
            if tr: cnt += 1; good += sum(t[2] for t in tr) > 0
            allt += tr
        print(f'  {name}: {M.stats(allt)} прибыльных инструментов {good} из {cnt}', flush=True)

# --- случайные входы: тот же инструмент и год, та же сторона, тот же стоп в дневных размахах, та же цель (исполнение по H1) ---
print('\nслучайные входы для разворот|48|1.0|0|2|без фильтров')
M.follow = follow; MAIN = ('EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'XAUUSD', 'SP500', 'NAS100')
def prep_main():
    algo.BEGIN = 1577836800; M.IDX = ('SP500', 'NAS100'); out = {}
    for s in MAIN:
        D = M.prepare(s, root, raw); D.m = D.h; D.MT = D.T; out[s] = D
    return out
def prep_oos():
    algo.BEGIN = 0; lst = sets[2][1]; M.IDX = tuple(FX) + tuple(lst); return {s: Raw(s, algo.CUT) for s in lst}
M.follow = follow
for name, prep in (('7 основных инструментов', prep_main), ('металлы, нефть, индексы вне отбора', prep_oos)):
    DS = prep(); FXsave = FX; real = []; meta = []
    for s, D in DS.items():
        Z = M.zones(D, 48, 1.0)
        for z in Z:
            for t in M.candidates_rev(D, [z], 2, 'без фильтров', True):
                i = M.h_of(D, t[0]); entry = D.O[i] + (D.m['SP'][i] * D.m['pt'] if t[4] > 0 else 0); risk = t[3] / t[2] if abs(t[2]) > 1e-12 else None
                if risk and D.atr[i]: real.append((s, t, risk / D.atr[i]))
    chosen = []; free = {}
    for s, t, q in sorted(real, key=lambda r: (r[0], r[1][0])):
        if t[0] > free.get(s, 0): chosen.append((s, t, q)); free[s] = t[1]
    rs = M.stats([t for _, t, _ in chosen]); pool = {}
    for s, D in DS.items():
        for i in range(600, len(D.T) - 1):
            if D.atr[i]: pool.setdefault((s, yr(D.T[i])), []).append(i)
    res = []
    for run in range(300):
        rnd = random.Random(run); tr = []
        for s, t, q in chosen:
            D = DS[s]; side = t[4]
            for _ in range(20):
                i = rnd.choice(pool[(s, yr(t[0]))]); sp = D.m['SP'][i] * D.m['pt']; e = D.O[i] + (sp if side > 0 else 0); risk = q * D.atr[i]
                r = M.follow(D, i, side, e, e - side * risk, e + side * 2 * risk, True, True)
                if r: tr.append((0, 0, r[0] / risk)); break
        res.append(M.stats(tr)['pf'])
    res.sort(); longs = M.stats([t for _, t, _ in chosen if t[4] > 0]); shorts = M.stats([t for _, t, _ in chosen if t[4] < 0])
    print(f'  {name} (H1): метод {rs} | случайные: медиана PF {res[150]}, 95-й процент {res[285]}, не хуже метода {sum(v >= rs["pf"] for v in res)}/300 | покупки {longs} продажи {shorts}', flush=True)
