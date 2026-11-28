// savgol.h - SAVGOL_01: знаки скорости и ускорения по параболе на последних N закрытиях (статья 25137).
// Правила и допущения: registry/specs/SAVGOL_01.md. Знаки считаются в целых числах.
#pragma once
#include "tokyo_break.h"

inline OwnResult sg_run(const Params& P, const Bars& m, int start_idx, double comm, bool by_price) {
    auto par = [&](const char* k) { auto it = P.find(k); if (it == P.end()) throw std::runtime_error(std::string("SAVGOL_01: нет параметра ") + k); return it->second; };
    const int N = (int)par("window"); const double slPts = par("sl_points"), tpPts = par("tp_points"), goldPt = par("gold_point");
    const int n = (int)m.size(); const double pt = m.point, rulePt = m.symbol.rfind("XAU", 0) == 0 ? goldPt : pt;
    OwnResult R; R.sigs.assign(n, 0);
    typedef __int128 W;
    W S[5] = {0, 0, 0, 0, 0};
    for (int i = 0; i < N; ++i) { const W x = i - (N - 1); W p = 1; for (int q = 0; q < 5; ++q) { S[q] += p; p *= x; } }
    // алгебраические дополнения симметричной матрицы 3x3 для строк наклона и изгиба; определитель положителен
    const W a1[3] = {-(S[1] * S[4] - S[2] * S[3]), S[0] * S[4] - S[2] * S[2], -(S[0] * S[3] - S[1] * S[2])};
    const W a2[3] = {S[1] * S[3] - S[2] * S[2], -(S[0] * S[3] - S[1] * S[2]), S[0] * S[2] - S[1] * S[1]};
    std::vector<long long> y(n); for (int i = 0; i < n; ++i) y[i] = std::llround(m.c[i] / pt);
    long cEntry = 0, cSl = 0, cTp = 0, cSig = 0;
    bool pos = false; LtTrade T{}; int prevAcc = 0;
    auto close_pos = [&](int i, double px, const char* why) {
        T.i_out = i; T.exit = px; T.why = why;
        T.pnl = (T.dir > 0 ? px - T.entry : T.entry - px) - comm * (by_price ? T.entry : 1.0);
        T.R = T.pnl / std::fabs(T.entry - T.sl);
        if (T.i_in >= start_idx) { if (T.why == "SL") ++cSl; else if (T.why == "TP") ++cTp; else ++cSig; }
        R.trades.push_back(T); pos = false;
    };
    for (int i = 0; i < n; ++i) {
        if (pos) {
            const double sp = m.spread[i] * pt;
            if (T.dir > 0) {
                if (i > T.i_in && m.o[i] <= T.sl) close_pos(i, m.o[i], "SL");
                else if (m.l[i] <= T.sl) close_pos(i, T.sl, "SL");
                else if (m.h[i] >= T.tp) close_pos(i, T.tp, "TP");
            } else {
                if (i > T.i_in && m.o[i] + sp >= T.sl) close_pos(i, m.o[i] + sp, "SL");
                else if (m.h[i] + sp >= T.sl) close_pos(i, T.sl, "SL");
                else if (m.l[i] + sp <= T.tp) close_pos(i, T.tp, "TP");
            }
        }
        if (i < N - 1) continue;
        W T0 = 0, T1 = 0, T2 = 0;
        for (int j = 0; j < N; ++j) { const W x = j - (N - 1), v = y[i - (N - 1) + j] - y[i]; T0 += v; T1 += x * v; T2 += x * x * v; }
        const W v1 = a1[0] * T0 + a1[1] * T1 + a1[2] * T2, v2 = a2[0] * T0 + a2[1] * T1 + a2[2] * T2;
        const int vel = v1 > 0 ? 1 : v1 < 0 ? -1 : 0, acc = v2 > 0 ? 1 : v2 < 0 ? -1 : 0;
        const bool next = i + 1 < n;
        if (!pos) {
            int d = 0;
            if (vel > 0 && acc > 0 && prevAcc <= 0) d = 1; else if (vel < 0 && acc < 0 && prevAcc >= 0) d = -1;
            if (d) {
                R.sigs[i] = d;
                if (next) {
                    const double entry = d > 0 ? m.o[i + 1] + m.spread[i + 1] * pt : m.o[i + 1];
                    pos = true; T = LtTrade{i, i + 1, -1, d, entry, 0, entry - d * slPts * rulePt, entry + d * tpPts * rulePt, 0, 0, 0, ""};
                    if (i + 1 >= start_idx) ++cEntry;
                }
            }
        } else if (T.dir > 0 ? (acc < 0 || vel <= 0) : (acc > 0 || vel >= 0)) {
            if (next) close_pos(i + 1, T.dir > 0 ? m.o[i + 1] : m.o[i + 1] + m.spread[i + 1] * pt, "SIGNAL");
        }
        prevAcc = acc;
    }
    if (pos) close_pos(n - 1, T.dir > 0 ? m.c[n - 1] : m.c[n - 1] + m.spread[n - 1] * pt, "END");
    R.f = {{"entries", cEntry}, {"exit_stop", cSl}, {"exit_target", cTp}, {"exit_signal", cSig}};
    return R;
}
