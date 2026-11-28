// engine.h - общий исполнитель для восьми идей сканера: сигналы по барам рабочего таймфрейма, исполнение по M1.
// Правила и допущения: registry/specs/IDEAS8_2026-11-28.md. Чтение баров берётся из тестера проекта (bars.h).
#pragma once
#include "../bars.h"
#include <algorithm>

// Бары рабочего таймфрейма собираются из M1 (сверено с файлами BAZA: OHLC и объём совпадают).
// D1: воскресный вечер входит в понедельник.
struct Tf { std::vector<int64_t> t; std::vector<double> o, h, l, c, v; std::vector<int> s, e; int n() const { return (int)t.size(); } };

inline Tf aggregate(const Bars& m, int sec) {
    Tf a; int64_t last = LLONG_MIN;
    for (int k = 0; k < (int)m.size(); ++k) {
        int64_t key;
        if (sec == 86400) { int64_t d = m.t[k] / 86400; if ((d + 3) % 7 == 6) ++d; key = d * 86400; } else key = m.t[k] / sec * sec;
        if (key != last) { last = key; a.t.push_back(key); a.o.push_back(m.o[k]); a.h.push_back(m.h[k]); a.l.push_back(m.l[k]); a.c.push_back(m.c[k]); a.v.push_back(m.v[k]); a.s.push_back(k); a.e.push_back(k + 1); }
        else { a.h.back() = std::max(a.h.back(), m.h[k]); a.l.back() = std::min(a.l.back(), m.l[k]); a.c.back() = m.c[k]; a.v.back() += m.v[k]; a.e.back() = k + 1; }
    }
    return a;
}

// ---- индикаторы по формулам MT5, причинные ----
typedef std::vector<double> Vd;
inline Vd i_sma(const Vd& x, int p) { Vd r(x.size(), NAN); for (int i = p - 1; i < (int)x.size(); ++i) { double s = 0; for (int j = i - p + 1; j <= i; ++j) s += x[j]; r[i] = s / p; } return r; }
inline Vd i_ema(const Vd& x, int p) { Vd r(x.size()); double a = 2.0 / (p + 1); for (size_t i = 0; i < x.size(); ++i) r[i] = i ? r[i - 1] + a * (x[i] - r[i - 1]) : x[0]; return r; }
inline Vd i_smma(const Vd& x, int p) { Vd r(x.size(), NAN); double s = 0; for (int i = 0; i < (int)x.size(); ++i) { if (i < p) { s += x[i]; if (i == p - 1) r[i] = s / p; } else r[i] = (r[i - 1] * (p - 1) + x[i]) / p; } return r; }
inline Vd i_tr(const Tf& b) { Vd r(b.n()); for (int i = 0; i < b.n(); ++i) { double v = b.h[i] - b.l[i]; if (i) v = std::max(v, std::max(std::fabs(b.h[i] - b.c[i - 1]), std::fabs(b.l[i] - b.c[i - 1]))); r[i] = v; } return r; }
inline Vd i_atr(const Tf& b, int p) { Vd tr = i_tr(b), r(b.n(), NAN); double s = 0; for (int i = 0; i < b.n(); ++i) { s += tr[i]; if (i >= p) s -= tr[i - p]; if (i + 1 >= p) r[i] = s / p; } return r; }
inline Vd i_adx(const Tf& b, int p) {
    int n = b.n(); Vd tr = i_tr(b), adx(n, 0); double a = 2.0 / (p + 1), pdi = 0, mdi = 0;
    for (int i = 1; i < n; ++i) {
        double up = b.h[i] - b.h[i - 1], dn = b.l[i - 1] - b.l[i]; if (up < 0) up = 0; if (dn < 0) dn = 0;
        if (up > dn) dn = 0; else if (up < dn) up = 0; else up = dn = 0;
        double pd = tr[i] != 0 ? 100 * up / tr[i] : 0, nd = tr[i] != 0 ? 100 * dn / tr[i] : 0;
        pdi += a * (pd - pdi); mdi += a * (nd - mdi);
        double dx = pdi + mdi != 0 ? 100 * std::fabs(pdi - mdi) / (pdi + mdi) : 0;
        adx[i] = adx[i - 1] + a * (dx - adx[i - 1]);
    }
    return adx;
}
inline Vd i_rsi(const Vd& c, int p) {
    int n = (int)c.size(); Vd r(n, NAN); double g = 0, l = 0;
    for (int i = 1; i < n; ++i) {
        double d = c[i] - c[i - 1], u = d > 0 ? d : 0, w = d < 0 ? -d : 0;
        if (i <= p) { g += u / p; l += w / p; if (i < p) continue; }
        else { g = (g * (p - 1) + u) / p; l = (l * (p - 1) + w) / p; }
        r[i] = l != 0 ? 100 - 100 / (1 + g / l) : (g != 0 ? 100 : 50);
    }
    return r;
}

struct Pos { int dir; double entry, sl, tp, risk; int i_sig, i_in, k_in; int tag = 0, level = -1; bool be = false; };
struct Rec { int dir; double entry, exit, sl0, tp, pnl; int i_sig, i_in; int k_in, k_out; int64_t t_bar; std::string why; };

struct Engine;
struct Strategy {
    virtual ~Strategy() {}
    virtual void init(Engine&) {}
    virtual void on_bar(Engine&, int) {}                 // открытие бара i: доступны только бары < i
    virtual void on_open(Engine&, int, int) {}           // открытие минутки k бара i
    virtual void manage(Engine&, int, int, size_t) {}    // сопровождение позиции внутри минутки (после стопа, до цели)
    virtual void on_close(Engine&, int, int) {}          // минутка k закрылась
    virtual void on_closed(Engine&, const Pos&, const Rec&) {}
};

struct Engine {
    const Bars* m; Tf b; double comm; bool by_price; Strategy* st;
    std::vector<Pos> pos; std::vector<Rec> out;
    double sp(int k) const { return m->spread[k] * m->point; }
    double point() const { return m->point; }
    // вход по открытию минутки k; sl/tp задаются после (через ссылку)
    double entry_price(int dir, int k) const { return dir > 0 ? m->o[k] + sp(k) : m->o[k]; }
    Pos& open(int dir, int k, int i_sig, int i_in, double sl, double tp) {
        Pos p; p.dir = dir; p.entry = entry_price(dir, k); p.sl = sl; p.tp = tp; p.risk = sl > 0 ? std::fabs(p.entry - sl) : 0; p.i_sig = i_sig; p.i_in = i_in; p.k_in = k;
        pos.push_back(p); return pos.back();
    }
    std::vector<double> sl0_;   // начальные стопы позиций (для отчёта)
    void close(size_t j, int k, double px, const char* why) {
        Pos p = pos[j]; pos.erase(pos.begin() + j);
        Rec r; r.dir = p.dir; r.entry = p.entry; r.exit = px; r.sl0 = p.dir > 0 ? (p.risk > 0 ? p.entry - p.risk : 0) : (p.risk > 0 ? p.entry + p.risk : 0); r.tp = p.tp;
        r.pnl = (p.dir > 0 ? px - p.entry : p.entry - px) - comm * (by_price ? p.entry : 1.0);
        r.i_sig = p.i_sig; r.i_in = p.i_in; r.k_in = p.k_in; r.k_out = k; r.t_bar = b.t[p.i_in]; r.why = why; out.push_back(r);
        st->on_closed(*this, p, out.back());
    }
    // выход по открытию минутки (по правилу)
    void close_open(size_t j, int k, const char* why) { close(j, k, pos[j].dir > 0 ? m->o[k] : m->o[k] + sp(k), why); }

    void gap_check(int k) {
        for (size_t j = 0; j < pos.size();) {
            const Pos& p = pos[j]; if (k <= p.k_in) { ++j; continue; }
            double px = p.dir > 0 ? m->o[k] : m->o[k] + sp(k);
            if (p.sl > 0 && (p.dir > 0 ? px <= p.sl : px >= p.sl)) close(j, k, px, "sl_gap");
            else if (p.tp > 0 && (p.dir > 0 ? px >= p.tp : px <= p.tp)) close(j, k, px, "tp_gap");
            else ++j;
        }
    }
    void run() {
        st->init(*this);
        for (int i = 0; i < b.n(); ++i) {
            const int k0 = b.s[i];
            gap_check(k0);
            st->on_bar(*this, i);
            for (int k = k0; k < b.e[i]; ++k) {
                if (k > k0) gap_check(k);
                st->on_open(*this, i, k);
                for (size_t j = 0; j < pos.size();) {           // стоп
                    const Pos& p = pos[j];
                    if (p.sl > 0 && (p.dir > 0 ? m->l[k] <= p.sl : m->h[k] + sp(k) >= p.sl)) close(j, k, p.sl, "sl"); else ++j;
                }
                for (size_t j = 0; j < pos.size();) { size_t before = pos.size(); st->manage(*this, i, k, j); if (pos.size() == before) ++j; }
                for (size_t j = 0; j < pos.size();) {           // цель
                    const Pos& p = pos[j];
                    if (p.tp > 0 && (p.dir > 0 ? m->h[k] >= p.tp : m->l[k] + sp(k) <= p.tp)) close(j, k, p.tp, "tp"); else ++j;
                }
                st->on_close(*this, i, k);
            }
        }
        int last = (int)m->size() - 1;
        while (!pos.empty()) close(0, last, pos[0].dir > 0 ? m->c[last] : m->c[last] + sp(last), "end");
    }
};
