"""Прогон на обрезанной истории должен давать те же прошлые сделки."""
import sys, os, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from algo import *
cut = int(dt.datetime(2022, 7, 1, tzinfo=UTC).timestamp())
for pair in PAIRS:
    for name in ('M1 по документу', 'M15 по документу'):
        p = VARIANTS[name]; path = f"{sys.argv[1]}/{pair}/{pair}_{p['tf']}.bin"
        A = load(path); B = load(path, cut)
        a = [t for t in run(pair, A, server_days(A), p) if t['t_out'] < cut - 86400]; b = [t for t in run(pair, B, server_days(B), p) if t['t_out'] < cut - 86400]
        assert a == b, (pair, name, len(a), len(b)); print('совпало', pair, name, len(a))
