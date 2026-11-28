#!/usr/bin/env python3
"""Итоговый разбор. Выбор только на 2018-2022, подтверждение на 2023-2024. Запуск: python -I deep_an.py <сигналы.pkl>"""
import sys, os, pickle, datetime as dt, itertools, statistics as S
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from deep import *
R = pickle.load(open(sys.argv[1], 'rb'))
year = lambda t: dt.datetime.fromtimestamp(t, UTC).year; Y = {}
# Плата за перенос, доля цены в год (плюс = платим, минус = получаем): (покупка, продажа). Из symbols.raw RoboForex (ставки на конец 2026 г.)
GOLD, SILVER, GOLDEUR = (.0473, -.0150), (.0690, -.0085), (.0370, -.0065)
FEE = dict(XAUUSD=GOLD, XAUAUD=GOLD, XAUJPY=GOLD, XAUEUR=GOLDEUR, XAGUSD=SILVER, XAGAUD=SILVER, XPDUSD=SILVER, XPTUSD=SILVER, USOUSD=(.06, .03), UKOUSD=(.06, .03),
           SP500=(.086, .018), NAS100=(.086, .018), DJ30=(.086, .018), US2000=(.086, .018), GER40=(.072, .018), UK100=(.072, .018), EU50=(.072, .018), FRA40=(.072, .018), HK50=(.072, .018), CHINA50=(.072, .018), SPI200=(.072, .018))
NAMES = [None, 'объем_выноса', 'открытие', 'объем_зоны', 'быстрый', 'край_диапазона', 'по_тренду', 'стоп_узкий', 'разреженная_зона']

def trades(N=48, k=1.0, rr=2.0, hold=0, flt=None, syms=None, cost='брокер'):
    out = []
    for sym in (syms or list(R)):
        free = 0
        for s in R[sym][(N, k)]:
            if s['t'] <= free: continue
            v = s['res'][(rr, hold)]
            if flt and not (v['thin'] if flt == 'разреженная_зона' else s['f'][flt]): continue
            free = v['tout']
            if cost == 'нет': p = v['gross']
            else:
                p = v['pnl']
                if cost == 'брокер': p -= FEE[sym][0 if s['side'] > 0 else 1] / 365 * s['entry'] * v['nights']
            out.append((s['t'], p / s['risk'], s['side'], sym, v['nights']))
    return out
def pf(tr):
    g = sum(x[1] for x in tr if x[1] > 0); l = -sum(x[1] for x in tr if x[1] < 0); return g / l if l else 0
def f(tr): return f"{pf(tr):.2f} ({len(tr)}, {sum(x[1] for x in tr):+.0f}R)"
def split(tr):
    a, b = [], []
    for x in tr: (a if x[0] < 1672531200 else b).append(x)     # 2023-01-01
    return a, b
BASE = list(itertools.product(NS, KS, RRS))

print('== 1. Базовый вариант 48 свечей / 1.0 / цель 2:1, без ограничения по времени')
for c in ('нет', 'без переноса', 'брокер'):
    t = trades(cost=c); a, b = split(t); print(f'  издержки «{c}»: всё {f(t)} | 2018–22 {f(a)} | 2023–24 {f(b)} | без 10 лучших {f(sorted(t, key=lambda x: -x[1])[10:])}')
t = trades(); print('  ночей в позиции: медиана', S.median(x[4] for x in t))
for name, g in (('металлы', METALS), ('нефть', OIL), ('индексы', INDICES)):
    tt = [x for x in t if x[3] in g]; a, b = split(tt); print(f'  {name}: {f(tt)} | 2018–22 {f(a)} | 2023–24 {f(b)} | покупки {f([x for x in tt if x[2]>0])} продажи {f([x for x in tt if x[2]<0])}')
print('  по годам:', {y: f([x for x in t if year(x[0]) == y]) for y in range(2018, 2025)})
print('  по инструментам:', {s: f([x for x in t if x[3] == s]) for s in R})
print('\n== 2. Соседние настройки (100 сочетаний свечи x ширина x цель, без ограничения по времени)')
for c in ('нет', 'без переноса', 'брокер'):
    q = [trades(N, k, rr, cost=c) for N, k, rr in BASE]; sp = [split(x) for x in q]
    print(f'  «{c}»: медиана PF {S.median(map(pf, q)):.2f}; плюс на всём {sum(pf(x)>1 for x in q)}; плюс в обоих периодах {sum(pf(a)>1 and pf(b)>1 for a, b in sp)}; PF>=1.3 в обоих {sum(pf(a)>=1.3 and pf(b)>=1.3 for a, b in sp)}')
print('\n== 3. Срок удержания (медиана по 100 сочетаниям, издержки брокера)')
for hold in HOLDS:
    q = [trades(N, k, rr, hold) for N, k, rr in BASE]; sp = [split(x) for x in q]
    print(f'  {hold or "без ограничения"} дн.: 2018–22 {S.median(pf(a) for a, b in sp):.2f} | 2023–24 {S.median(pf(b) for a, b in sp):.2f} | плюс в обоих {sum(pf(a)>1 and pf(b)>1 for a, b in sp)}')
print('\n== 4. Перебор: все настройки, выбор по 2018–22 (>=100 сделок), проверка на 2023–24')
for c in ('брокер', 'без переноса'):
    allc = []
    for N, k, rr, hold, flt in itertools.product(NS, KS, RRS, HOLDS, NAMES):
        a, b = split(trades(N, k, rr, hold, flt, cost=c)); allc.append((pf(a), len(a), pf(b), len(b), (N, k, rr, hold, flt)))
    ok = sorted([x for x in allc if x[1] >= 100], key=lambda x: -x[0]); top = ok[:20]
    print(f'  «{c}»: вариантов {len(allc)}, с >=100 сделок {len(ok)}; PF>=1.3 в 2018–22: {sum(x[0]>=1.3 for x in ok)}; из них PF>=1.3 и в 2023–24: {sum(x[0]>=1.3 and x[2]>=1.3 for x in ok)}')
    print(f'    20 лучших по 2018–22: медиана PF {S.median(x[0] for x in top):.2f} -> в 2023–24 {S.median(x[2] for x in top):.2f}; в плюсе {sum(x[2]>1 for x in top)} из 20')
    for x in ok[:5]: print(f'    {x[4]}: 2018–22 {x[0]:.2f} ({x[1]}) -> 2023–24 {x[2]:.2f} ({x[3]})')
    if c == 'брокер':
        print('    фильтры по одному (медиана PF 2018–22 / 2023–24 по всем настройкам):')
        for name in NAMES:
            z = [x for x in allc if x[4][4] == name]; print(f'      {str(name):18} {S.median(x[0] for x in z):.2f} / {S.median(x[2] for x in z):.2f}')
