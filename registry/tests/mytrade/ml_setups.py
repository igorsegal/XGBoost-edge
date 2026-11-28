#!/usr/bin/env python3
"""MYTRADE_ML_01: модель на окнах сетапов разворотной модели (правила - registry/specs/MYTRADE_ML_01.md).
Запуск: python -I ml_setups.py <raw> <sig.pkl> [проверки]   (сначала deep.py, чтобы получить sig.pkl)"""
import sys, os, pickle, datetime as dt, time, warnings
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deep import D, METALS, OIL, INDICES, CUT, com
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.neural_network import MLPRegressor
from sklearn.exceptions import ConvergenceWarning
warnings.filterwarnings('ignore', category=ConvergenceWarning)
UTC = dt.timezone.utc; ts = lambda y, m=1: int(dt.datetime(y, m, 1, tzinfo=UTC).timestamp())
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'deep_an.py'), encoding='utf-8').read()
exec(src[src.index('GOLD, SILVER, GOLDEUR'):src.index('NAMES = [')])          # ставки платы за перенос FEE
FILT = ['объем_выноса', 'открытие', 'объем_зоны', 'быстрый', 'край_диапазона', 'по_тренду', 'стоп_узкий']
WIN = [(ts(y, m), ts(y, 7) if m == 1 else ts(y + 1)) for y in range(2020, 2025) for m in (1, 7)]
assert WIN[-1][1] == CUT

def features(d, s, N, k, thin):
    """Только то, что известно к моменту входа: закрытые часовые свечи до бара входа."""
    T = d.T; last = int(np.searchsorted(T, s['t'], side='right')) - 2
    if last < 480: return None
    assert T[last] + 3600 <= s['t']
    side, e, atr = s['side'], s['entry'], s['atr']
    C = np.array(d.C[last-480:last+1]); H = np.array(d.H[last-480:last+1]); L = np.array(d.L[last-480:last+1]); V = np.array(d.V[last-480:last+1], float)
    x = list(side * (C[::-1][:48] - e) / atr); mv = V[1:].mean() or 1.0
    for b in range(12):
        a, z = len(C) - 4 * (b + 1), len(C) - 4 * b
        x.append(V[a:z].sum() / (4 * mv))
    for b in range(12):
        a, z = len(C) - 4 * (b + 1), len(C) - 4 * b
        x.append((H[a:z].max() - L[a:z].min()) / atr)
    lo, hi = L[1:].min(), H[1:].max(); pos = (e - lo) / (hi - lo) if hi > lo else 0.5
    hour = s['t'] % 86400 / 3600; wd = dt.datetime.fromtimestamp(s['t'], UTC).weekday()
    x += [s['risk'] / atr, s['risk'] / e, s['sp'] / s['risk'], pos if side > 0 else 1 - pos, side * (C[-1] - C[-121]) / atr, side * (C[-1] - C[0]) / atr,
          np.sin(hour * np.pi / 12), np.cos(hour * np.pi / 12), wd, side, d.sym in METALS, d.sym in OIL, d.sym in INDICES, N, k]
    x += [float(s['f'][n]) for n in FILT] + [float(thin)]
    return np.array(x, float)

def candidates(raw, R):
    best = {}
    for (sym, key, s) in ((sym, key, s) for sym in R for key, v in R[sym].items() for s in v):
        u = (sym, s['t'], s['side']); rank = (abs(key[0] - 48), abs(key[1] - 1.0), key[0], key[1])
        if u not in best or rank < best[u][0]: best[u] = (rank, key, s)
    data = {sym: D(raw, sym) for sym in R}; out = []
    for (sym, t, side), (_, key, s) in sorted(best.items(), key=lambda q: (q[0][1], q[0][0], q[0][2])):
        if t < ts(2018): continue
        x = features(data[sym], s, *key, s['res'][(2.0, 0)]['thin'])
        if x is None: continue
        c = dict(sym=sym, t=t, side=side, x=x, s=s, key=key)
        for hold in (0, 7):
            v = s['res'][(2.0, hold)]; p = v['pnl'] - FEE[sym][0 if side > 0 else 1] / 365 * s['entry'] * v['nights']
            c[hold] = (p / s['risk'], v['tout'])
        out.append(c)
    cnt = {}
    for c in out: u = (c['sym'], c['side'], c['t'] // 86400); cnt[u] = cnt.get(u, 0) + 1
    for c in out: c['w'] = 1 / cnt[(c['sym'], c['side'], c['t'] // 86400)]
    return out, data

class Set:
    def __init__(q, cands, hold):
        q.X = np.array([c['x'] for c in cands]); q.y = np.array([c[hold][0] for c in cands]); q.out = np.array([c[hold][1] for c in cands])
        q.t = np.array([c['t'] for c in cands]); q.w = np.array([c['w'] for c in cands]); q.sym = np.array([c['sym'] for c in cands]); q.side = np.array([c['side'] for c in cands])

def fit_predict(model, Xtr, ytr, wtr, Xte):
    if model == 'A':
        m = HistGradientBoostingRegressor(max_iter=200, max_depth=3, learning_rate=0.03, min_samples_leaf=50, l2_regularization=1.0, early_stopping=False, random_state=42)
        return m.fit(Xtr, ytr, sample_weight=wtr).predict(Xte)
    mu = Xtr.mean(0); sd = Xtr.std(0); sd[sd == 0] = 1; a = np.clip((Xtr - mu) / sd, -8, 8); b = np.clip((Xte - mu) / sd, -8, 8)
    return np.mean([MLPRegressor(hidden_layer_sizes=(16,), alpha=1.0, max_iter=500, random_state=seed).fit(a, ytr, sample_weight=wtr).predict(b) for seed in range(1, 6)], axis=0)

def walk(S, model, leak=False, shuffle_seed=None):
    X = np.column_stack([S.X, S.y]) if leak else S.X; pred = np.full(len(S.y), np.nan); sizes = []
    rng = np.random.default_rng(shuffle_seed) if shuffle_seed is not None else None
    for a, b in WIN:
        tr = np.flatnonzero(S.out < a); te = np.flatnonzero((S.t >= a) & (S.t < b)); assert S.t[tr].max() < a
        ytr = S.y[tr] if rng is None else rng.permutation(S.y[tr])
        pred[te] = fit_predict(model, X[tr], ytr, S.w[tr], X[te]); sizes.append((len(tr), len(te)))
    return pred, sizes

def take(S, mask):
    free = {}; got = []
    for i in np.flatnonzero(mask):
        if S.t[i] <= free.get(S.sym[i], 0): continue
        free[S.sym[i]] = S.out[i]; got.append(i)
    return np.array(got, int)
def pf(r):
    g = r[r > 0].sum(); l = -r[r < 0].sum(); return g / l if l else 0.0
f = lambda r: f"PF {pf(r):.2f}, сделок {len(r)}, {r.sum():+.0f}R"
test_mask = lambda S: S.t >= WIN[0][0]
def selected(S, pred): return take(S, test_mask(S) & (np.nan_to_num(pred, nan=-9) >= 0.10))

def random_test(S, pred, runs=1000, seed=7):
    real = pf(S.y[selected(S, pred)]); rng = np.random.default_rng(seed); res = []
    idx = [np.flatnonzero((S.t >= a) & (S.t < b)) for a, b in WIN]
    for _ in range(runs):
        p = pred.copy()
        for te in idx: p[te] = rng.permutation(pred[te])
        res.append(pf(S.y[selected(S, p)]))
    res = np.array(res); return float(np.median(res)), float(np.quantile(res, .95)), (1 + int((res >= real).sum())) / (runs + 1)

def report(S, pred, name):
    g = selected(S, pred); r = S.y[g]; med, q95, p = random_test(S, pred)
    print(f'\n== {name}: {f(r)}, прибыльных {100*(r>0).mean() if len(r) else 0:.0f}%')
    print(f'   случайный отбор: медиана PF {med:.2f}, 95% {q95:.2f}; p = {p:.3f}')
    ok = r.sum() > 0 and pf(r) >= 1.3 and len(r) >= 100 and p <= 0.025
    print('   критерии:', 'ПРОЙДЕНЫ' if ok else 'не пройдены')
    h = S.t[g] < ts(2023); print(f'   2020–2022: {f(r[h])} | 2023–2024: {f(r[~h])}')
    print('   по полугодиям:', ' '.join(f"{pf(r[(S.t[g]>=a)&(S.t[g]<b)]):.2f}({((S.t[g]>=a)&(S.t[g]<b)).sum()})" for a, b in WIN))
    for lab, grp in (('металлы', METALS), ('нефть', OIL), ('индексы', INDICES)): print(f'   {lab}: {f(r[np.isin(S.sym[g], grp)])}')
    print(f'   без 10 лучших: {f(np.sort(r)[:-10])}')
    te = test_mask(S) & ~np.isnan(pred); corr = np.corrcoef(pred[te], S.y[te])[0, 1]
    print(f'   связь прогноза с итогом на невиданных (корреляция): {corr:+.3f}; доля прогнозов выше порога {100*(pred[te]>=0.10).mean():.0f}%')

if __name__ == '__main__':
    raw, sig = sys.argv[1:3]; R = pickle.load(open(sig, 'rb')); t0 = time.time()
    cands, data = candidates(raw, R); print('кандидатов', len(cands), '| признаков', len(cands[0]['x']), '| базовая доля прибыльных', f"{100*np.mean([c[0][0]>0 for c in cands]):.0f}%")
    if len(sys.argv) < 4:
        for hold in (0, 7):
            S = Set(cands, hold); print('\n' + ('######## ГЛАВНЫЙ РАСЧЕТ: цель 2:1 без ограничения по времени' if hold == 0 else '######## ДЛЯ СВЕДЕНИЯ: выход не позже 7 дней'))
            a = take(S, test_mask(S)); print('все сетапы без модели:', f(S.y[a]))
            for model, name in (('A', 'A: деревья'), ('B', 'B: нейросеть')):
                pred, sizes = walk(S, model); print('примеров обучение/проверка по окнам:', sizes) if model == 'A' else None
                report(S, pred, name)
    else:                                       # проверки; какие именно - третий аргумент: look, A или B
        S = Set(cands, 0); what = sys.argv[3]
        if what == 'look':
            cut = ts(2023); bad = n = 0
            for sym in R:
                d = D(raw, sym, cut); d.msp = data[sym].msp[:len(d.mt)]
                for c in cands:
                    if c['sym'] != sym or c['t'] >= cut - 86400: continue
                    x = features(d, c['s'], *c['key'], c['s']['res'][(2.0, 0)]['thin']); n += 1; bad += x is None or not np.allclose(x, c['x'])
            print(f'проверка 3, признаки на обрезанной истории: проверено {n}, расхождений {bad}', flush=True)
        else:
            pred, _ = walk(S, what, leak=True); print(f'проверка 1, подставная подсказка, модель {what}: {f(S.y[selected(S, pred)])} ({time.time()-t0:.0f} с)', flush=True)
            a = pf(S.y[take(S, test_mask(S))]); v = []
            for i in range(20 if what == 'A' else 3):
                v.append(pf(S.y[selected(S, walk(S, what, shuffle_seed=100 + i)[0])]))
                print(f'проверка 2, перемешанные ответы, модель {what}: прогонов {len(v)}, PF от {min(v):.2f} до {max(v):.2f}, медиана {np.median(v):.2f}; все сетапы {a:.2f} ({time.time()-t0:.0f} с)', flush=True)
    print(f'время {time.time()-t0:.0f} с')
