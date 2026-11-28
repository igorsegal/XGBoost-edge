# -*- coding: utf-8 -*-
"""Независимый пересчёт восьми идей сканера и сверка сделка в сделку с программой ideas8.
Запуск: python xcheck_ideas8.py <папка BAZA> <папка trades программы> [ID ...]
Считает только по барам до 2025-01-01. Другой способ расчёта: поиск стопа/цели векторами, а не проходом по всем минуткам."""
import sys, os, glob, math, struct, csv
import numpy as np

CUT = 1735689600  # 2025-01-01 UTC
DT = np.dtype([('t', '<i8'), ('o', '<f8'), ('h', '<f8'), ('l', '<f8'), ('c', '<f8'), ('v', '<i8'), ('sp', '<i4'), ('rv', '<i8')])
TFS = {'M5': 300, 'M15': 900, 'H1': 3600, 'H4': 14400, 'D1': 86400}
_cache = {}


class M1:
    def __init__(self, base, pair):
        raw = open(os.path.join(base, pair, pair + '_M1.bin'), 'rb').read()
        assert raw[:8] == b'XFBAR001'
        pt, = struct.unpack_from('<d', raw, 24)
        n, = struct.unpack_from('<q', raw, 32)
        sl, = struct.unpack_from('<i', raw, 56)
        a = np.frombuffer(raw, DT, count=n, offset=60 + sl)
        a = a[a['t'] + 60 <= CUT]
        self.pair, self.pt, self.n = pair, pt, len(a)
        self.t = a['t'].copy()
        self.o, self.h, self.l, self.c = (a[k].astype(float) for k in 'ohlc')
        self.v = a['v'].astype(float)
        self.spp = a['sp'].astype(int)
        self.sp = self.spp * pt
        self.ao, self.ah, self.al, self.ac = self.o + self.sp, self.h + self.sp, self.l + self.sp, self.c + self.sp
        lot = 100.0 if pair == 'XAUUSD' else 100000.0
        self.comm, self.byprice = 7.0 / lot, not pair.endswith('USD')

    def ent(self, d, k):
        return float(self.ao[k] if d > 0 else self.o[k])

    def mkt(self, d, k):  # выход по открытию минутки
        return float(self.o[k] if d > 0 else self.ao[k])


class Bars:
    def __init__(self, m, sec):
        if sec == 86400:
            day = m.t // 86400
            key = (day + (((day + 3) % 7) == 6)) * 86400
        else:
            key = m.t - m.t % sec
        s = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
        self.s, self.e = s, np.r_[s[1:], m.n]
        self.t = key[s]
        self.o = m.o[s]
        self.h = np.maximum.reduceat(m.h, s)
        self.l = np.minimum.reduceat(m.l, s)
        self.c = m.c[self.e - 1]
        self.v = np.add.reduceat(m.v, s)
        self.n = len(s)


def sma(x, p):
    r = np.full(len(x), np.nan)
    w = np.lib.stride_tricks.sliding_window_view(x, p)
    r[p - 1:] = w.sum(axis=1) / p
    return r


def ema(x, p):
    a = 2.0 / (p + 1)
    r = [float(x[0])]
    for v in x[1:].tolist():
        r.append(r[-1] + a * (v - r[-1]))
    return np.array(r)


def smma(x, p):
    r = np.full(len(x), np.nan)
    r[p - 1] = sum(x[:p].tolist()) / p
    for i in range(p, len(x)):
        r[i] = (r[i - 1] * (p - 1) + x[i]) / p
    return r


def trange(b):
    pc = np.r_[b.c[0], b.c[:-1]]
    tr = np.maximum(b.h - b.l, np.maximum(np.abs(b.h - pc), np.abs(b.l - pc)))
    tr[0] = b.h[0] - b.l[0]
    return tr


def atr(b, p):
    tr = trange(b).tolist()
    r = np.full(b.n, np.nan)
    s = 0.0
    for i, v in enumerate(tr):
        s += v
        if i >= p:
            s -= tr[i - p]
        if i >= p - 1:
            r[i] = s / p
    return r


def adx(b, p):
    tr = trange(b)
    up = np.r_[0, np.maximum(np.diff(b.h), 0)]
    dn = np.r_[0, np.maximum(-np.diff(b.l), 0)]
    pm = np.where(up > dn, up, 0.0)
    mm = np.where(dn > up, dn, 0.0)
    nz = np.where(tr != 0, tr, 1)
    pd = np.where(tr != 0, 100 * pm / nz, 0)
    nd = np.where(tr != 0, 100 * mm / nz, 0)
    pd[0] = nd[0] = 0
    pdi, mdi = ema(pd, p), ema(nd, p)
    tot = pdi + mdi
    dx = np.where(tot != 0, 100 * np.abs(pdi - mdi) / np.where(tot != 0, tot, 1), 0)
    dx[0] = 0
    return ema(dx, p)


def rsi(c, p):
    d = np.diff(c)
    g, l = np.maximum(d, 0), np.maximum(-d, 0)
    r = np.full(len(c), np.nan)
    ag, al = g[:p].sum() / p, l[:p].sum() / p
    for i in range(p, len(c)):
        if i > p:
            ag = (ag * (p - 1) + g[i - 1]) / p
            al = (al * (p - 1) + l[i - 1]) / p
        r[i] = 100 - 100 / (1 + ag / al) if al != 0 else (100 if ag != 0 else 50)
    return r


def first_hit(m, d, k0, k1, sl, tp):
    """Первая минутка в [k0,k1), где задет стоп или цель. Возвращает (k, цена, на_открытии) или None."""
    a, w = k0, 256
    while a < k1:
        z = min(k1, a + w)
        if d > 0:
            hit = (m.l[a:z] <= sl) if sl > 0 else np.zeros(z - a, bool)
            if tp > 0:
                hit = hit | (m.h[a:z] >= tp)
        else:
            hit = (m.ah[a:z] >= sl) if sl > 0 else np.zeros(z - a, bool)
            if tp > 0:
                hit = hit | (m.al[a:z] <= tp)
        idx = np.flatnonzero(hit)
        if len(idx):
            k = a + int(idx[0])
            if k > k0:
                op = m.mkt(d, k)
                if (sl > 0 and d * (op - sl) <= 0) or (tp > 0 and d * (op - tp) >= 0):
                    return k, op, True
            if sl > 0 and (m.l[k] <= sl if d > 0 else m.ah[k] >= sl):
                return k, sl, False
            return k, tp, False
        a, w = z, w * 4
    return None


def trade(m, b, d, isig, iin, kin, entry, sl, tp, kout, px):
    pnl = d * (px - entry) - m.comm * (entry if m.byprice else 1.0)
    return dict(ts=int(b.t[isig]), te=int(m.t[kin]), tx=int(m.t[kout]), d=d, entry=entry, exit=px, sl=sl, tp=tp, pnl=pnl, ko=kout, iin=iin)


def finish(m, d, kin, sl, tp, rule_k=None):
    """Выход: стоп/цель раньше rule_k, иначе по открытию rule_k, иначе конец данных.
    Возвращает (k, цена, свободно_с_начала_бара_k)."""
    lim = m.n if rule_k is None else rule_k
    r = first_hit(m, d, kin, lim, sl, tp)
    if r:
        return r
    if rule_k is not None:
        op = m.mkt(d, rule_k)
        gap = (sl > 0 and d * (op - sl) <= 0) or (tp > 0 and d * (op - tp) >= 0)
        return rule_k, op, gap
    return m.n - 1, float(m.c[-1] if d > 0 else m.ac[-1]), False


def busy(pos, k):
    """pos = (k_out, на_открытии). Занята ли позиция в момент открытия минутки k."""
    return pos is not None and not (pos[0] < k or (pos[0] == k and pos[1]))


# ---------------- стратегии ----------------
def volchg(m, b, thr, tpp, slp, sign):
    out, pos = [], None
    lv = np.log(b.v + 1)
    sig = np.arctan(np.r_[0, np.diff(lv)])
    for i in range(2, b.n):
        x = i - 1
        s = sig[x]
        if abs(s) <= thr or (sign > 0 and s <= 0) or (sign < 0 and s >= 0):
            continue
        d = int(np.sign(b.c[x] - b.o[x]))
        k = int(b.s[i])
        if d == 0 or busy(pos, k):
            continue
        en = m.ent(d, k)
        sl, tp = en - d * slp * m.pt, en + d * tpp * m.pt
        ko, px, op = finish(m, d, k, sl, tp)
        pos = (ko, op)
        out.append(trade(m, b, d, x, i, k, en, sl, tp, ko, px))
    return out


def raschke(m, b, use_a, use_h):
    fast = sma(b.c, 3) - sma(b.c, 10)
    sig = np.full(b.n, np.nan)
    sig[24:] = np.lib.stride_tricks.sliding_window_view(fast[9:], 16).sum(axis=1) / 16
    e, ad = ema(b.c, 20), adx(b, 14)
    fast, sig, e, ad, H, L, C = (v.tolist() for v in (fast, sig, e, ad, b.h, b.l, b.c))
    out = []
    P = None  # открытая позиция
    A = [0, 1, 0.0]  # состояние, направление, стоп
    G = [0, 1]
    reset = False

    def close_stop():
        nonlocal P
        out.append(trade(m, b, P['d'], P['x'], P['i'], P['k'], P['en'], P['sl'], 0, P['ko'], P['px']))
        P = None

    def close_rule(k):
        nonlocal P
        P['ko'], P['px'] = k, m.mkt(P['d'], k)
        close_stop()

    def enter(d, i, stop):
        nonlocal P
        k = int(b.s[i])
        en = m.ent(d, k)
        if d > 0 and en - stop < 0:
            stop = en - m.pt
        if d < 0 and stop - m.o[k] < 0:
            stop = float(m.o[k]) + m.pt
        ko, px, op = finish(m, d, k, stop, 0)
        P = dict(d=d, x=i - 1, i=i, k=k, en=en, sl=stop, ko=ko, px=px, op=op, hit=first_hit(m, d, k, m.n, stop, 0) is not None)

    external = False
    for i in range(1, b.n):
        k0 = int(b.s[i])
        if P and P['hit'] and not busy((P['ko'], P['op']), k0):
            close_stop()
            external = True
        if i < 60:
            continue
        if external:
            external = False
            A[0] = G[0] = 0
        x = i - 1
        f, fp, s, sp = fast[x], fast[x - 1], sig[x], sig[x - 1]
        if use_a and (P is None or A[0] == 3):
            st, d = A[0], A[1]
            if st == 0:
                if sp <= 0 < s:
                    A[:] = [1, 1, 0.0]
                elif sp >= 0 > s:
                    A[:] = [1, -1, 0.0]
            elif st in (1, 2) and d * s < 0:
                A[0] = 0
            elif st == 1:
                if d * (f - s) <= 0:
                    A[0], A[2] = 2, L[x] if d > 0 else H[x]
            elif st == 2:
                if d * (f - s) <= 0:
                    A[2] = min(A[2], L[x]) if d > 0 else max(A[2], H[x])
                if d * (fp - sp) <= 0 and d * (f - s) > 0:
                    if not d * (C[x] - C[x - 1]) > 0:
                        A[0] = 0
                    elif P is None:
                        enter(d, i, A[2])
                        A[0], G[0] = 3, 0
            else:
                if P is None:
                    A[0] = 0
                elif d * (fp - sp) >= 0 and d * (f - s) < 0:
                    close_rule(k0)
                    A[0] = 0
        if use_h and (P is None or G[0] == 2):
            up, dn = e[x] > e[x - 1], e[x] < e[x - 1]
            if G[0] == 0:
                if reset:
                    if ad[x] < 30:
                        reset = False
                elif ad[x] >= 30 and ad[x] > ad[x - 1] > ad[x - 2] and (up or dn):
                    G[:] = [1, 1 if up else -1]
            elif G[0] == 1:
                d = G[1]
                if ad[x] < 30 or (d > 0 and dn) or (d < 0 and up):
                    G[0] = 0
                elif (L[x] <= e[x] if d > 0 else H[x] >= e[x]) and P is None:
                    enter(d, i, L[x] if d > 0 else H[x])
                    G[0], reset, A[0] = 2, True, 0
            else:
                if P is None:
                    G[0] = 0
                elif ad[x] < 20 or G[1] * (C[x] - e[x]) < 0:
                    close_rule(k0)
                    G[0] = 0
    if P:
        close_stop()
    return out


def ctc(m, b):
    out, pos = [], None
    pt = m.pt
    buf, tol, sbuf = 10 * pt, 30 * pt, 100 * pt
    O, H, L, C = (v.tolist() for v in (m.o, m.h, m.l, m.c))

    def disp(k, d):
        r = H[k] - L[k]
        return r > 0 and d * (C[k] - O[k]) > 0 and abs(C[k] - O[k]) / r >= 0.55 - 1e-12

    def broke(k, d):
        return C[k] > max(H[k - 3:k]) + buf if d > 0 else C[k] < min(L[k - 3:k]) - buf

    for i in range(3, b.n):
        ao, ah, al, ac = float(b.o[i - 3]), float(b.h[i - 3]), float(b.l[i - 3]), float(b.c[i - 3])
        bo, bh, bl, bc = float(b.o[i - 2]), float(b.h[i - 2]), float(b.l[i - 2]), float(b.c[i - 2])
        rng = ah - al
        if rng <= 0:
            continue
        comp = bh < ah - buf and bl > al + buf
        d = ref = prot = 0
        if not comp:
            if ac > ao and bc > bo and bc > ah + buf:
                d, ref, prot = 1, ah, min(al, bl)
            elif ac < ao and bc < bo and bc < al - buf:
                d, ref, prot = -1, al, max(ah, bh)
            elif ac < ao and bc > bo and bl < al - buf and bc >= al + rng * 0.5:
                d, ref, prot = 1, al, bl
            elif ac > ao and bc < bo and bh > ah + buf and bc <= ah - rng * 0.5:
                d, ref, prot = -1, ah, bh
            else:
                continue
        s, e = int(b.s[i - 1]), int(b.e[i - 1])
        if e - s < 5:
            continue
        k, ok = s, False
        if comp:
            while k < e:
                if C[k] > ah + buf and disp(k, 1):
                    d, ref, prot = 1, ah, al
                    break
                if C[k] < al - buf and disp(k, -1):
                    d, ref, prot = -1, al, ah
                    break
                k += 1
            if k >= e:
                continue
            ret = False
            for j in range(k + 1, e):
                if (C[j] < prot - buf) if d > 0 else (C[j] > prot + buf):
                    break
                if not ret:
                    ret = (L[j] <= ref + tol and C[j] >= ref) if d > 0 else (H[j] >= ref - tol and C[j] <= ref)
                elif j - s >= 3 and disp(j, d) and broke(j, d):
                    ok = True
                    break
        else:
            seen = False
            for j in range(s, e):
                if (C[j] < prot - buf) if d > 0 else (C[j] > prot + buf):
                    break
                if not seen:
                    seen = (L[j] <= ref + tol and C[j] >= ref - buf) if d > 0 else (H[j] >= ref - tol and C[j] <= ref + buf)
                if seen and j - s >= 3 and disp(j, d) and broke(j, d):
                    ok = True
                    break
        if not ok:
            continue
        chi, clo = float(b.h[i - 1]), float(b.l[i - 1])
        for j in range(int(b.s[i]), int(b.e[i]) - 1):
            if (C[j] < prot - buf) if d > 0 else (C[j] > prot + buf):
                break
            if disp(j, d) and ((C[j] > chi + buf) if d > 0 else (C[j] < clo - buf)):
                q = j + 1
                if not busy(pos, q) and m.spp[q] <= 50:
                    en = m.ent(d, q)
                    sl = prot - d * sbuf
                    if d * (en - sl) > 0:
                        tp = en + 2 * (en - sl)
                        ko, px, op = finish(m, d, q, sl, tp)
                        pos = (ko, op)
                        out.append(trade(m, b, d, i - 1, i, q, en, sl, tp, ko, px))
                break
    return out


def graph(m, b, variant):
    axis, steps, tpR, minp, gate, N = 3, 3, 3.0, 0.35, True, 45
    if variant == 2:
        axis, steps, tpR, minp, gate, N = 1, 4, 3.9, 0.875, False, 15
    maxsp = 600 if m.pair.startswith('XAU') else 60
    ef, es, at, rs = ema(b.c, 21), ema(b.c, 89), atr(b, 14), rsi(b.c, 14)
    nodes = [-1] * b.n
    atl = at.tolist()
    for x in range(113, b.n):
        avg = sum(atl[x - 100:x][::-1]) / 100
        if avg <= 0 or atl[x] <= 0:
            continue
        tr, vr = (ef[x] - es[x]) / atl[x], atl[x] / avg
        t = 0 if tr <= -1 else 1 if tr <= -0.25 else 2 if tr < 0.25 else 3 if tr < 1 else 4
        v = 0 if vr < 0.85 else 1 if vr <= 1.25 else 2
        mm = 0 if axis == 1 else (0 if rs[x] < 44 else 1 if rs[x] <= 56 else 2)
        nodes[x] = t * 3 * axis + v * axis + mm
    q = np.arange(N)
    bias = (q // (3 * axis) - 2) / 2.0
    if variant == 1:
        bias = 0.75 * bias + 0.25 * ((q % (3 * axis)) % axis - 1)
    # генератор MSVC, посчитанный пачкой
    pairs = N * (N - 1) // 2
    total_r = 200 * pairs
    A = np.empty(total_r, np.uint32)
    Cc = np.empty(total_r, np.uint32)
    a, c = 1, 0
    for k in range(total_r):
        a = (a * 214013) & 0xffffffff
        c = (c * 214013 + 2531011) & 0xffffffff
        A[k], Cc[k] = a, c
    seed = np.uint32(20260813)
    iu = np.triu_indices(N, 1)
    eye = np.eye(N, dtype=bool)

    def clus(adj):  # adj: (g,N,N) float32
        deg = adj.sum(axis=2, dtype=np.float64)
        tri = ((adj @ adj) * adj).sum(axis=2, dtype=np.float64)  # = 2*связи
        use = deg >= 2
        val = np.where(use, tri / np.where(use, deg * (deg - 1), 1), 0)
        cnt = use.sum(axis=1)
        return np.where(cnt > 0, val.sum(axis=1) / np.maximum(cnt, 1), 0)

    cnt = np.zeros((N, N))
    z = 0.0

    def norm():
        return (cnt + 0.5) / (cnt.sum(axis=1) + 0.5 * N)[:, None]

    def nulltest(P):
        nonlocal seed, z
        ad = (P > 1.5 / N) & ~eye
        ad = ad | ad.T
        dens = (ad.sum() / 2) / (0.5 * N * (N - 1))
        c0 = clus(ad[None].astype(np.float32))[0]
        st = A * seed + Cc
        seed = st[-1]
        bits = (((st >> np.uint32(16)) & np.uint32(0x7fff)) / 32767.0 < dens).reshape(200, pairs)
        R = np.zeros((200, N, N), np.float32)
        R[:, iu[0], iu[1]] = bits
        R[:, iu[1], iu[0]] = bits
        cs = clus(R).tolist()
        s1 = sum(cs)
        s2 = sum(v * v for v in cs)
        mean = s1 / 200
        var = s2 / 200 - mean * mean
        sd = math.sqrt(var) if var > 0 else 0
        z = (c0 - mean) / sd if sd > 1e-9 else 0

    LV = [0.5, 1.0, 1.5, 2.0, 3.0]
    adv, fail = [0] * 5, [0] * 5
    out = []
    P_ = None
    cooldown = bars = last = 0
    total = 0.0
    prev = -1
    need = 3000 + 100 + 89 + 10
    O, H, L, C, AO, AH, AL, AC, SP = (v.tolist() for v in (m.o, m.h, m.l, m.c, m.ao, m.ah, m.al, m.ac, m.sp))

    def close(k, px):
        nonlocal P_, cooldown
        p = P_
        out.append(trade(m, b, p['d'], p['x'], p['i'], p['k'], p['en'], p['sl0'], p['tp'], k, px))
        fail[max(p['lvl'], 0)] += 1
        cooldown = 3
        P_ = None

    def minute(i, k):
        p = P_
        d, sl, tp = p['d'], p['sl'], p['tp']
        op = O[k] if d > 0 else AO[k]
        if k > p['k']:
            if d * (op - sl) <= 0 or d * (op - tp) >= 0:
                return close(k, op)
        if (L[k] <= sl) if d > 0 else (AH[k] >= sl):
            return close(k, sl)
        fav = H[k] if d > 0 else AL[k]
        hit = d * (fav - tp) >= 0
        r = d * ((tp if hit else fav) - p['en']) / p['risk']
        while p['lvl'] < 4 and r >= LV[p['lvl'] + 1] - 1e-9:
            p['lvl'] += 1
            n = p['lvl']
            if n >= 1:
                adv[n - 1] += 1
            if n < 4 and LV[n] >= 1.0 and adv[n] + fail[n] >= 12 and (adv[n] + 1) / (adv[n] + fail[n] + 2) < minp:
                px = p['en'] + d * LV[n] * p['risk']
                if k > p['k'] and d * (op - px) > 0:
                    px = op
                return close(k, px)
        if hit:
            return close(k, tp)
        old = sl
        if r >= 1.0 - 1e-9 and not p['be']:
            be = p['en'] + d * SP[k]
            if d * (be - p['sl']) > 0:
                p['sl'] = be
            p['be'] = True
        a_ = atl[i - 1]
        if r >= 1.5 - 1e-9 and a_ > 0:
            ns = fav - d * 1.5 * a_
            if d * (ns - p['sl']) > 0:
                p['sl'] = ns
        cl = C[k] if d > 0 else AC[k]
        if p['sl'] != old and d * (cl - p['sl']) <= 0:
            return close(k, p['sl'])

    trained = False
    for i in range(b.n):
        k0, k1 = int(b.s[i]), int(b.e[i])
        if P_ and k0 > P_['k']:
            op = m.mkt(P_['d'], k0)
            if P_['d'] * (op - P_['sl']) <= 0 or P_['d'] * (op - P_['tp']) >= 0:
                close(k0, op)
        if not trained:
            if i + 1 >= need:
                x = i - 1
                p = -1
                for j in range(x - (need - 103), x + 1):
                    nd = nodes[j]
                    if nd < 0:
                        continue
                    if p >= 0:
                        cnt[p, nd] += 1
                        total += 1
                    p = nd
                prev, trained = p, True
                if gate:
                    nulltest(norm())
        else:
            bars += 1
            if cooldown > 0:
                cooldown -= 1
            x = i - 1
            nd = nodes[x]
            if nd >= 0:
                cnt *= 0.999
                total *= 0.999
                if prev >= 0:
                    cnt[prev, nd] += 1
                    total += 1
                prev = nd
                P = norm()
                if bars - last >= 20:
                    if gate:
                        nulltest(P)
                    last = bars
                if P_ is None and cooldown == 0 and total >= 300 and m.spp[k0] <= maxsp:
                    row = P[nd]
                    for _ in range(steps - 1):
                        row = row @ P
                    ex = float(row @ bias)
                    pos = row[row > 1e-12]
                    conf = max(0.0, 1 + float((pos * np.log(pos)).sum()) / math.log(N))
                    d = 1 if ex >= 0.15 else -1 if ex <= -0.15 else 0
                    if d and conf >= 0.03 and (not gate or z >= 0) and atl[x] > 0:
                        en = m.ent(d, k0)
                        risk = 2.0 * atl[x]
                        P_ = dict(d=d, x=x, i=i, k=k0, en=en, risk=risk, sl=en - d * risk, sl0=en - d * risk, tp=en + d * tpR * risk, lvl=-1, be=False)
        if P_:
            for k in range(k0, k1):
                if k > k0 or P_['k'] <= k:
                    minute(i, k)
                if P_ is None:
                    break
    if P_:
        close(m.n - 1, float(m.c[-1] if P_['d'] > 0 else m.ac[-1]))
    return out


def envgator(m, b):
    med = (b.h + b.l) / 2
    ma = sma(b.c, 20)
    j, t, l = smma(med, 13), smma(med, 8), smma(med, 5)
    a = atr(b, 14)
    up = (l > t) & (t > j)
    dn = (j > t) & (t > l)
    lb = ls = -3
    out, pos = [], None
    sg = [0] * b.n
    for i in range(20, b.n):
        cu = up[i] and up[i - 1]
        cd = dn[i] and dn[i - 1]
        neutral = not up[i] and not dn[i]
        if (cu or neutral) and b.c[i] <= ma[i] * 0.995 and b.c[i - 1] > ma[i - 1] * 0.995 and i - lb >= 3:
            sg[i], lb = 1, i
        elif (cd or neutral) and b.c[i] >= ma[i] * 1.005 and b.c[i - 1] < ma[i - 1] * 1.005 and i - ls >= 3:
            sg[i], ls = -1, i
    for i in range(1, b.n - 23):
        d = sg[i - 1]
        k = int(b.s[i])
        if not d or busy(pos, k) or not a[i - 1] > 0:
            continue
        en = m.ent(d, k)
        sl = en - d * 2.0 * a[i - 1]
        lim = int(b.e[i + 23])
        r = first_hit(m, d, k, lim, sl, 0)
        if r:
            ko, px, op = r
        else:
            ko, px, op = lim - 1, float(m.c[lim - 1] if d > 0 else m.ac[lim - 1]), False
        pos = (ko, op)
        out.append(trade(m, b, d, i - 1, i, k, en, sl, 0, ko, px))
    return out


def zscore(m, b):
    w = np.lib.stride_tricks.sliding_window_view(b.c, 20)
    z = np.full(b.n, np.nan)
    mu = w.mean(axis=1)
    sd = w.std(axis=1)
    dev = b.c[19:] - mu
    dev[np.abs(dev) < 1e-9] = 0  # Close ровно на средней: z = 0
    z[19:] = np.where(sd > 0, dev / np.where(sd > 0, sd, 1), 0)
    long_ex = np.flatnonzero(z >= 0) + 1
    short_ex = np.flatnonzero(z <= 0) + 1
    out = []
    i = 21
    while i < b.n:
        x = i - 1
        d = 1 if (z[x - 1] < -2 <= z[x]) else -1 if (z[x - 1] > 2 >= z[x]) else 0
        if not d:
            i += 1
            continue
        k = int(b.s[i])
        arr = long_ex if d > 0 else short_ex
        p = np.searchsorted(arr, i + 1)
        if p < len(arr) and arr[p] < b.n:
            j = int(arr[p])
            ko = int(b.s[j])
            px = m.mkt(d, ko)
            out.append(trade(m, b, d, x, i, k, m.ent(d, k), 0, 0, ko, px))
            i = j + 1
        else:
            out.append(trade(m, b, d, x, i, k, m.ent(d, k), 0, 0, m.n - 1, float(m.c[-1] if d > 0 else m.ac[-1])))
            break
    return out


def dtb(m, b, mode):
    H, L, C = b.h.tolist(), b.l.tolist(), b.c.tolist()
    pt = m.pt
    piv = []  # (верх?, цена, номер бара)
    out = []
    st = None
    last_end = -1
    for i in range(1, b.n):
        c = i - 6
        if i >= 11:
            if H[c] > max(H[c + 1:c + 6]) and H[c] >= max(H[c - 5:c]):
                piv.append((True, H[c], c))
            if L[c] < min(L[c + 1:c + 6]) and L[c] <= min(L[c - 5:c]):
                piv.append((False, L[c], c))
            del piv[:-80]
        if st is None and len(piv) >= 3:
            top, p2, i2 = piv[-1]
            prior = next((n for n in range(len(piv) - 2, -1, -1) if piv[n][0] == top), None)
            if prior is not None and piv[prior][2] >= last_end:
                _, p1, i1 = piv[prior]
                mids = [s for s in piv[prior + 1:-1] if s[0] != top]
                if mids:
                    neck = min(mids, key=lambda s: s[1]) if top else max(mids, key=lambda s: s[1])
                    nk, ni = neck[1], neck[2]
                    hgt = (p1 + p2) / 2 - nk if top else nk - (p1 + p2) / 2
                    a_, c_ = ni - i1, i2 - ni
                    if hgt > 0 and abs(p1 - p2) <= 0.10 * hgt + 1e-12 and i2 - i1 >= 10 and a_ > 0 and c_ > 0 and 100.0 * min(a_, c_) / max(a_, c_) >= 50:
                        st = dict(d=-1 if top else 1, neck=nk, ext=max(p1, p2) if top else min(p1, p2), age=0)
                        last_end = i2
        if st is None:
            continue
        st['age'] += 1
        x = i - 1
        d, neck, ext = st['d'], st['neck'], st['ext']
        if (H[x] > ext if d < 0 else L[x] < ext) or st['age'] > 50:
            st = None
            continue
        if not d * (C[x] - neck) > 0:
            continue
        st = None
        k = int(b.s[i])
        en = m.ent(d, k)
        md = max(1, int(m.spp[k])) * pt
        sl = ext - d * 3000 * pt
        if d * (en - sl) < md:
            sl = en - d * md
        tp = neck + d * abs(ext - neck)
        if d * (tp - en) < md:
            tp = en + d * md
        sl0 = sl
        if mode == 2:
            ko, px, _ = finish(m, d, k, sl, tp)
        else:
            need, tr = 1300 * pt, 300 * pt
            fav_all = (m.h[k:] - en) if d > 0 else (en - m.al[k:])
            idx = np.flatnonzero(fav_all >= need - 1e-9)
            act = k + int(idx[0]) if len(idx) else m.n
            r = first_hit(m, d, k, act, sl, tp)
            if r:
                ko, px, _ = r
            else:
                ko = px = None
                for q in range(act, m.n):
                    op = float(m.o[q] if d > 0 else m.ao[q])
                    if q > k and (d * (op - sl) <= 0 or d * (op - tp) >= 0):
                        ko, px = q, op
                        break
                    if (m.l[q] <= sl) if d > 0 else (m.ah[q] >= sl):
                        ko, px = q, sl
                        break
                    fav = float(m.h[q] if d > 0 else m.al[q])
                    if d * (fav - en) >= need - 1e-9:
                        ns = fav - d * tr
                        if d * (ns - sl) > 1e-9:
                            if mode == 0:
                                if d * (fav - tp) < 0:
                                    sl = ns
                                    cl = float(m.c[q] if d > 0 else m.ac[q])
                                    if d * (cl - sl) <= 0:
                                        ko, px = q, sl
                                        break
                            else:
                                first = en + d * (need - tr)
                                if d * (sl - first) >= -1e-9:
                                    px = op - d * tr if d * ((op - d * tr) - sl) > 0 else sl
                                else:
                                    px = first
                                ko = q
                                break
                    if d * (fav - tp) >= 0:
                        ko, px = q, tp
                        break
                if ko is None:
                    ko, px = m.n - 1, float(m.c[-1] if d > 0 else m.ac[-1])
        out.append(trade(m, b, d, x, i, k, en, sl0, tp, ko, px))
    return out


def seykota(m, b):
    f, s, ad, a = ema(b.c, 20), ema(b.c, 200), adx(b, 14), atr(b, 20)
    out = []
    i = 201
    while i < b.n:
        x = i - 1
        d = 1 if (f[x - 1] < s[x - 1] and f[x] > s[x]) else -1 if (f[x - 1] > s[x - 1] and f[x] < s[x]) else 0
        if not d or ad[x] < 20:
            i += 1
            continue
        k = int(b.s[i])
        en = m.ent(d, k)
        sl = float((m.ao[k] if d > 0 else m.o[k]) - d * 3.0 * a[x])
        j = next((j for j in range(i + 1, b.n) if d * (f[j - 1] - s[j - 1]) < 0), None)
        ko, px, op = finish(m, d, k, sl, 0, None if j is None else int(b.s[j]))
        out.append(trade(m, b, d, x, i, k, en, sl, 0, ko, px))
        # следующий бар, на котором можно входить
        bar = int(np.searchsorted(b.s, ko, side='right') - 1)
        if ko == m.n - 1 and j is None:
            break
        if j is not None and ko == int(b.s[j]) and not op:
            i = j + 1
        elif ko == int(b.s[bar]) and op:
            i = max(bar, i + 1)
        else:
            i = bar + 1
    return out


def build(vid, name, m, b):
    if vid == 'VOLCHG_01':
        tp, sl = (1000, 600) if 'tp1000' in name else (500, 300)
        sign = 0 if name.endswith('_both') else -1 if name.endswith('negative') else 1
        return volchg(m, b, 0.3, tp, sl, sign)
    if vid == 'RASCHKE_01':
        return raschke(m, b, not name.endswith('_grail'), not name.endswith('_anti'))
    if vid == 'CTC_P11_01':
        return ctc(m, b)
    if vid == 'GRAPH_ER_01':
        return graph(m, b, 1 if name.endswith('bias2') else 2 if name.endswith('author') else 0)
    if vid == 'ENVGATOR_01':
        return envgator(m, b)
    if vid == 'ZSCORE_01':
        return zscore(m, b)
    if vid == 'DTB_01':
        return dtb(m, b, 0 if name.endswith('_best') else 1 if name.endswith('_worst') else 2)
    if vid == 'SEYKOTA_01':
        return seykota(m, b)
    raise ValueError(vid)


def tf_of(vid, name):
    for k in ('M15', 'M5', 'H1', 'H4', 'D1'):
        if '_' + k in name:
            return TFS[k]
    raise ValueError(name)


def main():
    base, trdir = sys.argv[1], sys.argv[2]
    only = set(sys.argv[3:])
    files = sorted(glob.glob(os.path.join(trdir, '*.csv')))
    files.sort(key=lambda p: os.path.basename(p).split('__')[2])
    total = bad = nfiles = 0
    for path in files:
        vid, name, pair = os.path.basename(path)[:-4].split('__')
        if only and vid not in only:
            continue
        if pair not in _cache:
            _cache.clear()
            _cache[pair] = M1(base, pair)
        m = _cache[pair]
        b = Bars(m, tf_of(vid, name))
        mine = sorted(build(vid, name, m, b), key=lambda r: (r['te'], r['ts'], r['d'], r['entry']))
        theirs = list(csv.DictReader(open(path)))
        diff = abs(len(mine) - len(theirs))
        first = None
        for u, v in zip(mine, theirs):
            eq = (u['ts'] == int(v['signal_time']) and u['te'] == int(v['entry_time']) and u['tx'] == int(v['exit_time']) and u['d'] == int(v['dir'])
                  and all(abs(u[a] - float(v[c])) < 2e-6 for a, c in (('entry', 'entry'), ('exit', 'exit'), ('sl', 'sl'), ('tp', 'tp'), ('pnl', 'pnl'))))
            if not eq:
                diff += 1
                if first is None:
                    first = (u, v)
        nfiles += 1
        total += len(theirs)
        bad += diff
        print(f'{vid:12s} {name:22s} {pair}  сделок: программа {len(theirs)}, пересчёт {len(mine)}, расхождений {diff}', flush=True)
        if first:
            print('   пересчёт :', {k: first[0][k] for k in ('ts', 'te', 'tx', 'd', 'entry', 'exit', 'sl', 'tp', 'pnl')})
            print('   программа:', dict(first[1]), flush=True)
    print(f'ИТОГО: файлов {nfiles}, сделок {total}, расхождений {bad} -> {"СОВПАЛО" if bad == 0 and nfiles else "ЕСТЬ РАСХОЖДЕНИЯ"}')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
