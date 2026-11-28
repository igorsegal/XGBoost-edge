import sys, os, random, bisect, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from disb import *
root = sys.argv[1]; out = {}
for pair in PAIRS:
    data = prepare(root, pair)
    # 1. без подглядывания в будущее: прогон на обрезанной истории даёт те же сделки
    cut = int(dt.datetime(2023, 1, 1, tzinfo=dt.timezone.utc).timestamp()); short = prepare(root, pair, cut)
    for name, ov in VARIANTS.items():
        v = {**BASE, **ov}; a = [t for t in run(pair, data, v) if t['t_out'] < cut - 7 * 86400]; b = [t for t in run(pair, short, v) if t['t_out'] < cut - 7 * 86400]
        assert a == b, (pair, name, len(a), len(b))
    # 2. без издержек и сравнение со случайными входами
    B5, M5 = data[1], data[5]
    for name, ov in VARIANTS.items():
        v = {**BASE, **ov}; tr = run(pair, data, v); g = stats(run(pair, data, {**v, 'com': False}))
        T = B5['T']; first = bisect.bisect_left(T, BEGIN); n = len(T); rnd = random.Random(7); nets = []; N = 200
        for _ in range(N):
            s = 0.0
            for t in tr:
                X = B5 if t['side'] > 0 else M5
                while True:
                    e = rnd.randrange(first, n - v['hold'] - 1)
                    sp = B5['SP'][e] * B5['pt']; price = B5['O'][e] + sp if t['side'] > 0 else -B5['O'][e]
                    r = trade(pair, X, e, price, price - t['risk'], price + v['rr'] * t['risk'], v['hold'], False)
                    if r: break
                s += r['R']
            nets.append(s)
        net = sum(t['R'] for t in tr); nets.sort(); better = 100 * sum(x >= net for x in nets) / N
        risk = sorted(t['risk'] / (10 * B5['pt']) for t in tr)[len(tr) // 2]
        out[f'{pair} | {name}'] = dict(net=round(net, 1), gross=g['R'], gross_pf=g['pf'], rand_mid=round(nets[N // 2], 1), rand_better=better, risk_pips=round(risk, 1), n=len(tr))
        print(f"{pair} | {name}: с издержками {net:.1f}R, без издержек {g['R']}R (PF {g['pf']}); случайные входы: середина {nets[N//2]:.1f}R, не хуже правила {better}%; стоп (середина) {risk:.1f} пп", flush=True)
print('проверка на подглядывание в будущее пройдена')
json.dump(out, open(sys.argv[2], 'w'), ensure_ascii=False)
