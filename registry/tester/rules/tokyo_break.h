// tokyo_break.h - TOKYO_BREAK_01: пробой токийского диапазона (статья 24936).
// Правила и допущения: registry/specs/TOKYO_BREAK_01.md. Решения только по закрытым свечам, исполнение по открытию следующей.
#pragma once
#include "classic_trace.h"

struct OwnResult { std::vector<LtTrade> trades; std::vector<int> sigs; std::vector<std::pair<const char*, long>> f; };

// Сдвиг серверного времени: летом США (второе воскресенье марта .. первое воскресенье ноября) больше на час.
inline int64_t tk_days_civil(int y, int m, int d) {
    y -= m <= 2; const int64_t era = y / 400, yoe = y - era * 400, doy = (153 * (m > 2 ? m - 3 : m + 9) + 2) / 5 + d - 1, doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    return era * 146097 + doe - 719468;
}
inline bool tk_us_dst(int64_t t) {
    const int64_t day = t / 86400; int y = 1970 + (int)(day / 365.2425);
    while (tk_days_civil(y, 1, 1) > day) --y;
    while (tk_days_civil(y + 1, 1, 1) <= day) ++y;
    auto nth_sunday = [&](int m, int n) { int64_t d = tk_days_civil(y, m, 1); const int wd = (int)((d + 4) % 7); return d + (7 - wd) % 7 + 7 * (n - 1); };  // 0 = воскресенье
    return day >= nth_sunday(3, 2) && day < nth_sunday(11, 1);
}

inline OwnResult tk_run(const Params& P, const Bars& m, int start_idx, double comm, bool by_price) {
    auto par = [&](const char* k) { auto it = P.find(k); if (it == P.end()) throw std::runtime_error(std::string("TOKYO_BREAK_01: нет параметра ") + k); return it->second; };
    const int wStart = (int)par("range_start_min"), wEnd = (int)par("range_end_min"), minBars = (int)par("min_range_bars"), atrP = (int)par("atr_period"),
              brkWin = (int)par("break_window"), maxTr = (int)par("max_trades_per_range"), trailStart = (int)par("trail_start"), maxBars = (int)par("max_bars"),
              sessEnd = (int)par("session_end_min"), shW = (int)par("server_winter_h"), shS = (int)par("server_summer_h");
    const double distMax = par("dist_prev_max_pts"), bodyMin = par("body_ratio_min"), buf = par("buffer_atr"), slUp = par("sl_r_up"), slDn = par("sl_r_down"),
                 flAtr = par("sl_floor_atr"), flSp = par("sl_spread_mult"), tpUp = par("tp_r_up"), tpDn = par("tp_r_down"), dead = par("dead_man_r"), trAtr = par("trail_atr");
    if (m.period_sec != 900) throw std::runtime_error("TOKYO_BREAK_01 работает на M15");
    const int n = (int)m.size(); const double pt = m.point;
    OwnResult R; R.sigs.assign(n, 0);
    const std::vector<double> A = lt_atr(m, atrP);
    long cRanges = 0, cBreak = 0, rDist = 0, rBody = 0, rStop = 0, rTarget = 0, entries = 0;

    struct Rng { bool valid = false; double hi = 0, lo = 0, size = 0, atr = 0; int bars = 0, since = 0, trades = 0; bool up = false, dn = false; } G;
    double wHi = 0, wLo = 0; int wBars = 0; bool prevIn = false;
    int64_t curDay = -1; double dHi = 0, dLo = 0, pHi = 0, pLo = 0; bool havePrev = false;
    bool pos = false; LtTrade T{}; double stop = 0, boundary = 0, rUnit = 0, atrT = 0; int k = 0; bool trailed = false;

    auto close_pos = [&](int i, double px, const std::string& why) {
        char w[64]; snprintf(w, sizeof w, "%s|w=%.2f", why.c_str(), T.be / 100.0);
        T.i_out = i; T.exit = px; T.why = w;
        T.pnl = (T.dir > 0 ? px - T.entry : T.entry - px) - comm * (by_price ? T.entry : 1.0);
        T.R = T.pnl / std::fabs(T.entry - T.sl); T.be = 0;
        R.trades.push_back(T); pos = false;
    };

    for (int i = 0; i < n; ++i) {
        const bool inTest = i >= start_idx;
        // 1. стоп и цель внутри свечи i
        if (pos) {
            const double sp = m.spread[i] * pt; const char* lbl = trailed ? "TRAIL" : "SL";
            if (T.dir > 0) {
                if (i > T.i_in && m.o[i] <= stop) close_pos(i, m.o[i], lbl);
                else if (m.l[i] <= stop) close_pos(i, stop, lbl);
                else if (m.h[i] >= T.tp) close_pos(i, T.tp, "TP");
            } else {
                if (i > T.i_in && m.o[i] + sp >= stop) close_pos(i, m.o[i] + sp, lbl);
                else if (m.h[i] + sp >= stop) close_pos(i, stop, lbl);
                else if (m.l[i] + sp <= T.tp) close_pos(i, T.tp, "TP");
            }
        }
        const int64_t t = m.t[i], st = t + 3600 * (tk_us_dst(t) ? shS : shW), sday = st / 86400; const int mod = (int)((st % 86400) / 60);
        if (sday != curDay) { if (curDay >= 0) { pHi = dHi; pLo = dLo; havePrev = true; } curDay = sday; dHi = m.h[i]; dLo = m.l[i]; }
        else { dHi = std::max(dHi, m.h[i]); dLo = std::min(dLo, m.l[i]); }
        const bool next = i + 1 < n;
        // 2. сопровождение позиции по закрытой свече i
        if (pos) {
            ++k;
            const double c = m.c[i];
            const bool inside = T.dir > 0 ? c < boundary - dead * rUnit : c > boundary + dead * rUnit;
            const char* why = inside ? "BACK" : mod >= sessEnd ? "DAY" : k >= maxBars ? "TIME" : nullptr;
            if (why) { if (next) close_pos(i + 1, T.dir > 0 ? m.o[i + 1] : m.o[i + 1] + m.spread[i + 1] * pt, why); }
            else if (k >= trailStart && next) {
                const double ns = T.dir > 0 ? c - trAtr * atrT : c + trAtr * atrT;
                const bool better = T.dir > 0 ? ns > stop : ns < stop;
                const bool safe = T.dir > 0 ? ns < m.o[i + 1] : ns > m.o[i + 1] + m.spread[i + 1] * pt;
                if (better && safe) { stop = ns; trailed = true; }
            }
        }
        // 3. окно диапазона
        const bool in = mod >= wStart && mod < wEnd;
        if (in && !prevIn) { G = Rng{}; wHi = m.h[i]; wLo = m.l[i]; wBars = 1; prevIn = true; continue; }
        if (in) { wHi = std::max(wHi, m.h[i]); wLo = std::min(wLo, m.l[i]); ++wBars; prevIn = true; continue; }
        if (prevIn) {
            G = Rng{}; G.hi = wHi; G.lo = wLo; G.size = wHi - wLo; G.bars = wBars; G.atr = A[i];
            G.valid = wBars >= minBars && G.size > 0 && !std::isnan(A[i]) && A[i] > 0;
            if (G.valid && inTest) ++cRanges;
        }
        prevIn = false;
        if (!G.valid) continue;
        ++G.since;
        // 4. пробой
        if (G.since > brkWin || G.trades >= maxTr || pos) continue;
        const double c = m.c[i]; int dir = 0;
        if (!G.up && c > G.hi + buf * G.atr) dir = 1; else if (!G.dn && c < G.lo - buf * G.atr) dir = -1;
        if (!dir) continue;
        if (dir > 0) G.up = true; else G.dn = true;
        if (i < start_idx - 1) { /* до проверочного отрезка сделки тоже ведутся, чтобы состояние было как у советника */ }
        if (inTest) ++cBreak;
        if (!havePrev) continue;
        const double dist = (dir > 0 ? pHi - G.hi : G.lo - pLo) / pt;
        if (dist > distMax + 1e-6) { if (inTest) ++rDist; continue; }
        const double candle = m.h[i] - m.l[i];
        if (candle <= 0 || std::fabs(c - m.o[i]) / candle < bodyMin - 1e-9) { if (inTest) ++rBody; continue; }
        const double w = (G.since <= 2 ? 0.6 : G.since <= 6 ? 1.0 : G.since <= 14 ? 0.4 : 0.6) * (dir < 0 ? 0.6 : 1.0);
        const double edge = dir > 0 ? G.hi : G.lo;
        double sd = (dir > 0 ? slUp : slDn) * G.size;
        sd = std::max(sd, flAtr * G.atr); sd = std::max(sd, flSp * m.spread[i] * pt);
        const double sl = dir > 0 ? edge - sd : edge + sd, td = (dir > 0 ? tpUp : tpDn) * G.size, tp = dir > 0 ? c + td : c - td;
        R.sigs[i] = dir;
        if (!next) continue;
        const double entry = dir > 0 ? m.o[i + 1] + m.spread[i + 1] * pt : m.o[i + 1];
        if (dir > 0 ? entry <= sl : entry >= sl) { if (inTest) ++rStop; continue; }
        if (dir > 0 ? tp <= entry : tp >= entry) { if (inTest) ++rTarget; continue; }
        pos = true; T = LtTrade{i, i + 1, -1, dir, entry, 0, sl, tp, 0, 0, (int)std::lround(w * 100), ""};
        stop = sl; boundary = edge; rUnit = G.size; atrT = G.atr; k = 0; trailed = false; ++G.trades; if (inTest) ++entries;
    }
    if (pos) close_pos(n - 1, T.dir > 0 ? m.c[n - 1] : m.c[n - 1] + m.spread[n - 1] * pt, "END");
    R.f = {{"ranges", cRanges}, {"breakouts", cBreak}, {"rej_location", rDist}, {"rej_body", rBody}, {"rej_stop_passed", rStop}, {"rej_target_reached", rTarget}, {"entries", entries}};
    return R;
}
