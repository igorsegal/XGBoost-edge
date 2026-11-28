// strategies.h - восемь идей сканера. Точные правила: registry/specs/IDEAS8_2026-11-28.md.
#pragma once
#include "engine.h"
#include <cstring>

typedef std::map<std::string, double> Pm;

// 1. VOLCHG_01
struct VolChg : Strategy {
    double thr, tpPts, slPts; int sign;   // sign: 1 только положительный, -1 только отрицательный, 0 оба
    VolChg(double th, double tp, double sl, int sg) : thr(th), tpPts(tp), slPts(sl), sign(sg) {}
    void on_bar(Engine& E, int i) override {
        int x = i - 1; if (x < 1) return; const Tf& b = E.b;
        double s = std::atan(std::log(b.v[x] + 1) - std::log(b.v[x - 1] + 1));
        if (std::fabs(s) <= thr) return;
        if ((sign > 0 && !(s > 0)) || (sign < 0 && !(s < 0))) return;
        int dir = b.c[x] > b.o[x] ? 1 : (b.c[x] < b.o[x] ? -1 : 0);
        if (!dir || !E.pos.empty()) return;
        int k = b.s[i]; double en = E.entry_price(dir, k), pt = E.point();
        E.open(dir, k, x, i, en - dir * slPts * pt, en + dir * tpPts * pt);
    }
};

// 2. RASCHKE_01
struct Raschke : Strategy {
    bool anti, hg; Vd fast, sig, ema, adx;
    int aS = 0, aDir = 1; double aStop = 0;   // 0 IDLE, 1 ждёт откат, 2 ждёт разворот, 3 в сделке
    int hS = 0, hDir = 1; bool needReset = false, external = false, own = false;
    Raschke(bool a, bool h) : anti(a), hg(h) {}
    void init(Engine& E) override {
        const Tf& b = E.b; Vd s3 = i_sma(b.c, 3), s10 = i_sma(b.c, 10); fast.assign(b.n(), NAN); sig.assign(b.n(), NAN);
        for (int i = 9; i < b.n(); ++i) fast[i] = s3[i] - s10[i];
        for (int i = 24; i < b.n(); ++i) { double s = 0; for (int j = i - 15; j <= i; ++j) s += fast[j]; sig[i] = s / 16; }
        ema = i_ema(b.c, 20); adx = i_adx(b, 14);
    }
    void on_closed(Engine&, const Pos&, const Rec&) override { if (!own) external = true; }
    void exitOwn(Engine& E, int k, const char* why) { own = true; E.close_open(0, k, why); own = false; }
    void trade(Engine& E, int dir, int i, double stop, int tag) {
        int k = E.b.s[i]; double en = E.entry_price(dir, k);
        if (dir > 0 && en - stop < 0) stop = en - E.point();
        if (dir < 0 && stop - E.m->o[k] < 0) stop = E.m->o[k] + E.point();
        E.open(dir, k, i - 1, i, stop, 0).tag = tag;
    }
    void doAnti(Engine& E, int i) {
        int x = i - 1; const Tf& b = E.b; double f = fast[x], fp = fast[x - 1], s = sig[x], sp_ = sig[x - 1];
        if (aS == 0) { bool up = sp_ <= 0 && s > 0, dn = sp_ >= 0 && s < 0; if (up || dn) { aS = 1; aDir = up ? 1 : -1; aStop = 0; } }
        else if (aS == 1) {
            if ((aDir > 0 && s < 0) || (aDir < 0 && s > 0)) { aS = 0; return; }
            if ((aDir > 0 && f <= s) || (aDir < 0 && f >= s)) { aStop = aDir > 0 ? b.l[x] : b.h[x]; aS = 2; }
        } else if (aS == 2) {
            if ((aDir > 0 && s < 0) || (aDir < 0 && s > 0)) { aS = 0; return; }
            if (aDir > 0 && f <= s && b.l[x] < aStop) aStop = b.l[x];
            if (aDir < 0 && f >= s && b.h[x] > aStop) aStop = b.h[x];
            bool rev = aDir > 0 ? (fp <= sp_ && f > s) : (fp >= sp_ && f < s);
            if (!rev) return;
            bool ok = aDir > 0 ? b.c[x] > b.c[x - 1] : b.c[x] < b.c[x - 1];
            if (!ok) { aS = 0; return; }
            if (!E.pos.empty()) return;
            trade(E, aDir, i, aStop, 1); aS = 3; hS = 0;
        } else {
            if (E.pos.empty()) { aS = 0; return; }
            bool ex = aDir > 0 ? (fp >= sp_ && f < s) : (fp <= sp_ && f > s);
            if (ex) { exitOwn(E, E.b.s[i], "anti_cross"); aS = 0; }
        }
    }
    void doHg(Engine& E, int i) {
        int x = i - 1; const Tf& b = E.b; bool up = ema[x] > ema[x - 1], dn = ema[x] < ema[x - 1];
        bool strong = adx[x] >= 30 && adx[x] > adx[x - 1] && adx[x - 1] > adx[x - 2];
        if (hS == 0) {
            if (needReset) { if (adx[x] < 30) needReset = false; return; }
            if (strong && (up || dn)) { hDir = up ? 1 : -1; hS = 1; }
        } else if (hS == 1) {
            if (adx[x] < 30) { hS = 0; return; }
            if ((hDir > 0 && dn) || (hDir < 0 && up)) { hS = 0; return; }
            bool touch = hDir > 0 ? b.l[x] <= ema[x] : b.h[x] >= ema[x];
            if (touch && E.pos.empty()) { trade(E, hDir, i, hDir > 0 ? b.l[x] : b.h[x], 2); hS = 2; needReset = true; aS = 0; }
        } else {
            if (E.pos.empty()) { hS = 0; return; }
            if (adx[x] < 20) { exitOwn(E, b.s[i], "hg_adx"); hS = 0; return; }
            if (hDir > 0 ? b.c[x] < ema[x] : b.c[x] > ema[x]) { exitOwn(E, b.s[i], "hg_ema"); hS = 0; }
        }
    }
    void on_bar(Engine& E, int i) override {
        if (i < 60) return;
        if (external) { external = false; aS = 0; hS = 0; }
        if (anti && (E.pos.empty() || aS == 3)) doAnti(E, i);
        if (hg && (E.pos.empty() || hS == 2)) doHg(E, i);
    }
};

// 3. CTC_P11_01
struct Ctc : Strategy {
    bool active = false, pend = false; int dir = 0, dBar = -1; double prot = 0, cHigh = 0, cLow = 0;
    double buf, tol, stopBuf;
    void init(Engine& E) override { buf = 10 * E.point(); tol = 30 * E.point(); stopBuf = 100 * E.point(); }
    static bool disp(const Bars& m, int k, int d) { double r = m.h[k] - m.l[k]; if (r <= 0) return false; if (d > 0 ? !(m.c[k] > m.o[k]) : !(m.c[k] < m.o[k])) return false; return std::fabs(m.c[k] - m.o[k]) / r >= 0.55 - 1e-12; }
    static double prevHi(const Bars& m, int k) { return std::max(m.h[k - 1], std::max(m.h[k - 2], m.h[k - 3])); }
    static double prevLo(const Bars& m, int k) { return std::min(m.l[k - 1], std::min(m.l[k - 2], m.l[k - 3])); }
    void on_bar(Engine& E, int i) override {
        active = false; pend = false; if (i < 3) return;
        const Tf& b = E.b; const Bars& m = *E.m; int A = i - 3, B = i - 2, C = i - 1;
        double ar = b.h[A] - b.l[A]; if (ar <= 0) return;
        bool aUp = b.c[A] > b.o[A], aDn = b.c[A] < b.o[A], bUp = b.c[B] > b.o[B], bDn = b.c[B] < b.o[B];
        int d = 0; bool comp = false; double ref = 0, pr = 0;
        if (b.h[B] < b.h[A] - buf && b.l[B] > b.l[A] + buf) comp = true;
        else if (aUp && bUp && b.c[B] > b.h[A] + buf) { d = 1; ref = b.h[A]; pr = std::min(b.l[A], b.l[B]); }
        else if (aDn && bDn && b.c[B] < b.l[A] - buf) { d = -1; ref = b.l[A]; pr = std::max(b.h[A], b.h[B]); }
        else if (aDn && bUp && b.l[B] < b.l[A] - buf && b.c[B] >= b.l[A] + ar * 0.5) { d = 1; ref = b.l[A]; pr = b.l[B]; }
        else if (aUp && bDn && b.h[B] > b.h[A] + buf && b.c[B] <= b.h[A] - ar * 0.5) { d = -1; ref = b.h[A]; pr = b.h[B]; }
        else return;
        int s = b.s[C], e = b.e[C]; if (e - s < 5) return;
        bool found = false;
        if (!comp) {
            bool touched = false;
            for (int k = s; k < e; ++k) {
                if (d > 0 ? m.c[k] < pr - buf : m.c[k] > pr + buf) return;
                if (!touched && (d > 0 ? (m.l[k] <= ref + tol && m.c[k] >= ref - buf) : (m.h[k] >= ref - tol && m.c[k] <= ref + buf))) touched = true;
                if (!touched || k - s < 3) continue;
                if (disp(m, k, d) && (d > 0 ? m.c[k] > prevHi(m, k) + buf : m.c[k] < prevLo(m, k) - buf)) { found = true; break; }
            }
        } else {
            int stage = 0;
            for (int k = s; k < e; ++k) {
                if (stage == 0) {
                    if (m.c[k] > b.h[A] + buf && disp(m, k, 1)) { d = 1; ref = b.h[A]; pr = b.l[A]; stage = 1; }
                    else if (m.c[k] < b.l[A] - buf && disp(m, k, -1)) { d = -1; ref = b.l[A]; pr = b.h[A]; stage = 1; }
                    continue;
                }
                if (d > 0 ? m.c[k] < pr - buf : m.c[k] > pr + buf) return;
                if (stage == 1) { if (d > 0 ? (m.l[k] <= ref + tol && m.c[k] >= ref) : (m.h[k] >= ref - tol && m.c[k] <= ref)) stage = 2; continue; }
                if (k - s >= 3 && disp(m, k, d) && (d > 0 ? m.c[k] > prevHi(m, k) + buf : m.c[k] < prevLo(m, k) - buf)) { found = true; break; }
            }
        }
        if (!found) return;
        active = true; dir = d; prot = pr; cHigh = b.h[C]; cLow = b.l[C]; dBar = i;
    }
    void on_open(Engine& E, int i, int k) override {
        if (!pend) return; pend = false;
        if (i != dBar || !E.pos.empty() || E.m->spread[k] > 50) return;
        double en = E.entry_price(dir, k), sl = prot - dir * stopBuf;
        if (dir > 0 ? !(en > sl) : !(en < sl)) return;
        E.open(dir, k, i - 1, i, sl, en + 2 * (en - sl));
    }
    void on_close(Engine& E, int i, int k) override {
        if (!active || i != dBar || k >= E.b.e[i] - 1) return;
        const Bars& m = *E.m;
        if (dir > 0 ? m.c[k] < prot - buf : m.c[k] > prot + buf) { active = false; return; }
        if (disp(m, k, dir) && (dir > 0 ? m.c[k] > cHigh + buf : m.c[k] < cLow - buf)) { pend = true; active = false; }
    }
};

// 4. GRAPH_ER_01
struct Graph : Strategy {
    int variant;   // 0 знак по тренду; 1 тренд+RSI; 2 настройки теста автора
    int N = 45, axis = 3, steps = 3; double tpR = 3.0, minProb = 0.35, maxSpreadPts = 60; bool nullGate = true;
    Vd ef, es, atr, rsi; double cnt[45][45], P[45][45], Pk[45][45], bias[45], total = 0, z = 0; bool adj[45][45];
    int prev = -1, barCounter = 0, lastNull = 0, cooldown = 0; bool trained = false; uint32_t seed = 20260813;
    double adv[5] = {0}, fail[5] = {0};
    explicit Graph(int v) : variant(v) { if (v == 2) { axis = 1; N = 15; steps = 4; tpR = 3.9; minProb = 0.875; nullGate = false; } }
    int rnd() { seed = seed * 214013u + 2531011u; return (int)((seed >> 16) & 0x7fff); }
    void init(Engine& E) override {
        const Tf& b = E.b; ef = i_ema(b.c, 21); es = i_ema(b.c, 89); atr = i_atr(b, 14); rsi = i_rsi(b.c, 14);
        if (E.m->symbol.rfind("XAU", 0) == 0) maxSpreadPts = 600;
        std::memset(cnt, 0, sizeof cnt);
        for (int n = 0; n < N; ++n) {
            int t = n / (3 * axis), m = (n % (3 * axis)) % axis; double bt = (t - 2) / 2.0;
            bias[n] = (variant == 1) ? 0.75 * bt + 0.25 * (m - 1) : bt;
        }
    }
    int node(int x) {
        if (x < 113 || std::isnan(atr[x - 100])) return -1;
        double s = 0; for (int k = 1; k <= 100; ++k) s += atr[x - k]; double avg = s / 100; if (avg <= 0 || atr[x] <= 0) return -1;
        double tr = (ef[x] - es[x]) / atr[x], vr = atr[x] / avg;
        int t = tr <= -1.0 ? 0 : tr <= -0.25 ? 1 : tr < 0.25 ? 2 : tr < 1.0 ? 3 : 4;
        int v = vr < 0.85 ? 0 : vr <= 1.25 ? 1 : 2;
        int m = 0; if (axis == 3) m = rsi[x] < 44 ? 0 : rsi[x] <= 56 ? 1 : 2;
        return t * (3 * axis) + v * axis + m;
    }
    void normalise() { for (int i = 0; i < N; ++i) { double s = 0; for (int j = 0; j < N; ++j) s += cnt[i][j]; double d = s + 0.5 * N; for (int j = 0; j < N; ++j) P[i][j] = (cnt[i][j] + 0.5) / d; } }
    // нужна только строка текущей вершины P^steps
    void walk_row(int from, double* row) { double tmp[45]; for (int j = 0; j < N; ++j) row[j] = P[from][j];
        for (int s = 1; s < steps; ++s) { for (int j = 0; j < N; ++j) tmp[j] = 0; for (int m = 0; m < N; ++m) { double a = row[m]; for (int j = 0; j < N; ++j) tmp[j] += a * P[m][j]; } for (int j = 0; j < N; ++j) row[j] = tmp[j]; } }
    double clustering(bool a[45][45]) { double sum = 0; int used = 0, nb[45];
        for (int i = 0; i < N; ++i) { int k = 0; for (int j = 0; j < N; ++j) if (j != i && a[i][j]) nb[k++] = j; if (k < 2) continue; int links = 0; for (int x = 0; x < k - 1; ++x) for (int y = x + 1; y < k; ++y) if (a[nb[x]][nb[y]]) ++links; sum += 2.0 * links / ((double)k * (k - 1.0)); ++used; }
        return used ? sum / used : 0; }
    void null_test() {
        double thr = 1.5 / N; int und = 0;
        for (int i = 0; i < N; ++i) for (int j = 0; j < N; ++j) adj[i][j] = (i != j && P[i][j] > thr);
        for (int i = 0; i < N; ++i) for (int j = i + 1; j < N; ++j) { bool l = adj[i][j] || adj[j][i]; adj[i][j] = adj[j][i] = l; if (l) ++und; }
        double dens = und / (0.5 * N * (N - 1.0)), c0 = clustering(adj), s1 = 0, s2 = 0; static bool r[45][45];
        for (int s = 0; s < 200; ++s) { for (int i = 0; i < N; ++i) for (int j = i + 1; j < N; ++j) { bool e = (rnd() / 32767.0) < dens; r[i][j] = r[j][i] = e; } for (int i = 0; i < N; ++i) r[i][i] = false; double c = clustering(r); s1 += c; s2 += c * c; }
        double mean = s1 / 200, var = s2 / 200 - mean * mean, sd = var > 0 ? std::sqrt(var) : 0; z = sd > 1e-9 ? (c0 - mean) / sd : 0;
    }
    void on_bar(Engine& E, int i) override {
        const int need = 3000 + 100 + 89 + 10;
        if (!trained) {
            if (i + 1 < need) return; int x = i - 1, p = -1;
            for (int q = x - (need - 100 - 3); q <= x; ++q) { int n = node(q); if (n < 0) continue; if (p >= 0) { cnt[p][n] += 1; total += 1; } p = n; }
            prev = p; trained = true; normalise(); if (nullGate) null_test(); return;
        }
        ++barCounter; if (cooldown > 0) --cooldown;
        int x = i - 1, n = node(x); if (n < 0) return;
        for (int a = 0; a < N; ++a) for (int c = 0; c < N; ++c) cnt[a][c] *= 0.999; total *= 0.999;
        if (prev >= 0) { cnt[prev][n] += 1; total += 1; } prev = n;
        normalise();
        if (barCounter - lastNull >= 20) { if (nullGate) null_test(); lastNull = barCounter; }
        if (!E.pos.empty() || cooldown > 0 || total < 300) return;
        int k = E.b.s[i]; if (E.m->spread[k] > maxSpreadPts) return;
        double row[45]; walk_row(n, row); double ex = 0, h = 0; for (int j = 0; j < N; ++j) { ex += row[j] * bias[j]; if (row[j] > 1e-12) h -= row[j] * std::log(row[j]); }
        double conf = 1 - h / std::log((double)N); if (conf < 0) conf = 0;
        if (conf < 0.03 || (nullGate && z < 0.0)) return;
        int dir = ex >= 0.15 ? 1 : (ex <= -0.15 ? -1 : 0); if (!dir || !(atr[x] > 0)) return;
        double en = E.entry_price(dir, k), risk = 2.0 * atr[x];
        E.open(dir, k, x, i, en - dir * risk, en + dir * tpR * risk);
    }
    void manage(Engine& E, int i, int k, size_t j) override {
        static const double LV[5] = {0.5, 1.0, 1.5, 2.0, 3.0};
        Pos& p = E.pos[j]; const Bars& m = *E.m;
        double fav = p.dir > 0 ? m.h[k] : m.l[k] + E.sp(k), cl = p.dir > 0 ? m.c[k] : m.c[k] + E.sp(k);
        bool hitTp = p.dir > 0 ? fav >= p.tp : fav <= p.tp;
        double r = p.dir * (fav - p.entry) / p.risk; if (hitTp) r = p.dir * (p.tp - p.entry) / p.risk;
        while (p.level + 1 < 5 && r >= LV[p.level + 1] - 1e-9) {
            ++p.level; if (p.level - 1 >= 0) adv[p.level - 1] += 1;
            int L = p.level;
            if (L < 4 && LV[L] >= 1.0 && adv[L] + fail[L] >= 12 && (adv[L] + 1) / (adv[L] + fail[L] + 2) < minProb) {
                double px = p.entry + p.dir * LV[L] * p.risk, op = p.dir > 0 ? m.o[k] : m.o[k] + E.sp(k);
                if (k > p.k_in && p.dir * (op - px) > 0) px = op;
                E.close(j, k, px, "prob"); return;
            }
        }
        if (hitTp) return;
        double old = p.sl, a = atr[i - 1];
        if (r >= 1.0 - 1e-9 && !p.be) { double be = p.entry + p.dir * E.sp(k); if (p.dir * (be - p.sl) > 0) p.sl = be; p.be = true; }
        if (r >= 1.5 - 1e-9 && a > 0) { double ns = fav - p.dir * 1.5 * a; if (p.dir * (ns - p.sl) > 0) p.sl = ns; }
        if (p.sl != old && p.dir * (cl - p.sl) <= 0) E.close(j, k, p.sl, "trail");
    }
    void on_closed(Engine&, const Pos& p, const Rec&) override { fail[p.level < 0 ? 0 : p.level] += 1; cooldown = 3; }
};

// 5. ENVGATOR_01: сигнал статьи, выход проекта (24 бара, стоп 2 ATR)
struct EnvGator : Strategy {
    std::vector<int> sg; Vd atr;
    void init(Engine& E) override {
        const Tf& b = E.b; int n = b.n(); Vd med(n); for (int i = 0; i < n; ++i) med[i] = (b.h[i] + b.l[i]) / 2;
        Vd ma = i_sma(b.c, 20), jaw = i_smma(med, 13), teeth = i_smma(med, 8), lips = i_smma(med, 5); atr = i_atr(b, 14); sg.assign(n, 0);
        int up = 0, dn = 0, lastB = -3, lastS = -3;
        for (int i = 1; i < n; ++i) {
            if (std::isnan(jaw[i])) continue;
            int st = (lips[i] > teeth[i] && teeth[i] > jaw[i]) ? 1 : ((jaw[i] > teeth[i] && teeth[i] > lips[i]) ? -1 : 0);
            if (st > 0) { ++up; dn = 0; } else if (st < 0) { ++dn; up = 0; } else up = dn = 0;
            if (std::isnan(ma[i - 1])) continue;
            double lo = ma[i] * 0.995, hi = ma[i] * 1.005, lo1 = ma[i - 1] * 0.995, hi1 = ma[i - 1] * 1.005;
            bool buy = (up >= 2 || st == 0), sell = (dn >= 2 || st == 0);
            bool lowerIn = b.c[i] <= lo && b.c[i - 1] > lo1, upperIn = b.c[i] >= hi && b.c[i - 1] < hi1;
            if (buy && lowerIn && i - lastB >= 3) { sg[i] = 1; lastB = i; }
            else if (sell && upperIn && i - lastS >= 3) { sg[i] = -1; lastS = i; }
        }
    }
    void on_bar(Engine& E, int i) override {
        int x = i - 1; if (x < 0 || !sg[x] || !E.pos.empty() || !(atr[x] > 0) || i + 23 >= E.b.n()) return;
        int k = E.b.s[i]; double en = E.entry_price(sg[x], k);
        E.open(sg[x], k, x, i, en - sg[x] * 2.0 * atr[x], 0);
    }
    void on_close(Engine& E, int i, int k) override {
        if (E.pos.empty() || k != E.b.e[i] - 1 || i != E.pos[0].i_in + 23) return;
        E.close(0, k, E.pos[0].dir > 0 ? E.m->c[k] : E.m->c[k] + E.sp(k), "time");
    }
};

// 6. ZSCORE_01
struct ZScore : Strategy {
    Vd z;
    void init(Engine& E) override {
        const Tf& b = E.b; z.assign(b.n(), NAN);
        for (int i = 19; i < b.n(); ++i) { double s = 0; for (int j = i - 19; j <= i; ++j) s += b.c[j]; double mu = s / 20, v = 0; for (int j = i - 19; j <= i; ++j) v += (b.c[j] - mu) * (b.c[j] - mu); double sd = std::sqrt(v / 20), dev = b.c[i] - mu; if (std::fabs(dev) < 1e-9) dev = 0; /* Close ровно на средней: z = 0, без шума округления */ z[i] = sd > 0 ? dev / sd : 0; }
    }
    void on_bar(Engine& E, int i) override {
        int x = i - 1; if (x < 20) return; double cur = z[x], pr = z[x - 1]; int k = E.b.s[i];
        bool had = !E.pos.empty();
        if (had && (E.pos[0].dir > 0 ? cur >= 0 : cur <= 0)) E.close_open(0, k, "mean");
        if (!had) { if (pr < -2 && cur >= -2) E.open(1, k, x, i, 0, 0); else if (pr > 2 && cur <= 2) E.open(-1, k, x, i, 0, 0); }
    }
};

// 7. DTB_01
struct Dtb : Strategy {
    int mode;   // 0 лучшая граница, 1 худшая, 2 без трейлинга
    struct Sw { bool hi; double price; int idx; };
    std::vector<Sw> sw; int state = 0, dir = 0, bars = 0, lastEnd = -1; double neck = 0, extreme = 0;
    explicit Dtb(int m) : mode(m) {}
    void add(bool hi, double price, int idx) { for (auto& s : sw) if (s.idx == idx && s.hi == hi) return; sw.push_back({hi, price, idx}); if (sw.size() > 80) sw.erase(sw.begin()); }
    void detect(const Tf& b, int i) {
        const int L = 5; if (i + 1 < 2 * L + 2) return; int c = i - (L + 1); bool hi = true, lo = true;
        for (int k = 1; k <= L; ++k) { if (b.h[c + k] >= b.h[c] || b.h[c - k] > b.h[c]) hi = false; if (b.l[c + k] <= b.l[c] || b.l[c - k] < b.l[c]) lo = false; }
        if (hi) add(true, b.h[c], c); if (lo) add(false, b.l[c], c);
    }
    void pattern() {
        if (state != 0 || sw.size() < 3) return; int n = (int)sw.size(); Sw last = sw[n - 1]; bool top = last.hi;
        int pr = -1; for (int i = n - 2; i >= 0; --i) if (sw[i].hi == top) { pr = i; break; }
        if (pr < 0 || sw[pr].idx < lastEnd) return;
        double nk = 0; int nkIdx = -1; for (int i = pr + 1; i < n - 1; ++i) if (sw[i].hi != top && (nkIdx < 0 || (top ? sw[i].price < nk : sw[i].price > nk))) { nk = sw[i].price; nkIdx = sw[i].idx; }
        if (nkIdx < 0) return;
        double p1 = sw[pr].price, p2 = last.price, height = top ? (p1 + p2) / 2 - nk : nk - (p1 + p2) / 2;
        if (height <= 0 || std::fabs(p1 - p2) > 0.10 * height + 1e-12) return;
        if (last.idx - sw[pr].idx < 10) return;
        double a = nkIdx - sw[pr].idx, c = last.idx - nkIdx; if (a <= 0 || c <= 0 || 100.0 * std::min(a, c) / std::max(a, c) < 50.0) return;
        state = 1; dir = top ? -1 : 1; neck = nk; extreme = top ? std::max(p1, p2) : std::min(p1, p2); lastEnd = last.idx; bars = 0;
    }
    void on_bar(Engine& E, int i) override {
        const Tf& b = E.b; if (i < 1) return; detect(b, i); pattern();
        if (state == 0) return; ++bars; int x = i - 1;
        if (dir < 0 ? b.h[x] > extreme : b.l[x] < extreme) { state = 0; return; }
        if (bars > 50) { state = 0; return; }
        if (!(dir < 0 ? b.c[x] < neck : b.c[x] > neck)) return;
        state = 0;
        int k = b.s[i]; double pt = E.point(), en = E.entry_price(dir, k), md = std::max(1, E.m->spread[k]) * pt;
        double sl = extreme - dir * 3000 * pt; if (dir * (en - sl) < md) sl = en - dir * md;
        double height = std::fabs(extreme - neck), tp = neck + dir * height; if (dir * (tp - en) < md) tp = en + dir * md;
        E.open(dir, k, x, i, sl, tp);
    }
    void manage(Engine& E, int, int k, size_t j) override {
        if (mode == 2) return; Pos& p = E.pos[j]; const Bars& m = *E.m; double pt = E.point(), tr = 300 * pt, need = 1300 * pt;
        double fav = p.dir > 0 ? m.h[k] : m.l[k] + E.sp(k), cl = p.dir > 0 ? m.c[k] : m.c[k] + E.sp(k), op = p.dir > 0 ? m.o[k] : m.o[k] + E.sp(k);
        if (p.dir * (fav - p.entry) < need - 1e-9) return;
        double ns = fav - p.dir * tr; if (!(p.dir * (ns - p.sl) > 1e-9)) return;
        if (mode == 0) {
            if (p.dir * (fav - p.tp) >= 0) return;
            p.sl = ns; if (p.dir * (cl - p.sl) <= 0) E.close(j, k, p.sl, "trail");
        } else {
            // худший порядок внутри минуты: стоп срабатывает сразу после первого включения или сдвига
            double first = p.entry + p.dir * (need - tr);
            double px = p.dir * (p.sl - first) >= -1e-9 ? (p.dir * ((op - p.dir * tr) - p.sl) > 0 ? op - p.dir * tr : p.sl) : first;
            E.close(j, k, px, "trail");
        }
    }
};

// 8. SEYKOTA_01
struct Seykota : Strategy {
    Vd f, s, adx, atr;
    void init(Engine& E) override { f = i_ema(E.b.c, 20); s = i_ema(E.b.c, 200); adx = i_adx(E.b, 14); atr = i_atr(E.b, 20); }
    void on_bar(Engine& E, int i) override {
        int x = i - 1; if (x < 200) return; int k = E.b.s[i];
        if (!E.pos.empty()) { if (E.pos[0].dir > 0 ? f[x] < s[x] : f[x] > s[x]) E.close_open(0, k, "cross"); return; }
        if (adx[x] < 20) return;
        int dir = (f[x - 1] < s[x - 1] && f[x] > s[x]) ? 1 : ((f[x - 1] > s[x - 1] && f[x] < s[x]) ? -1 : 0); if (!dir) return;
        double dist = 3.0 * atr[x], ref = dir > 0 ? E.m->o[k] + E.sp(k) : E.m->o[k];
        E.open(dir, k, x, i, ref - dir * dist, 0);
    }
};
