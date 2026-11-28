// iso_pnn.h - ISO_PNN_01: вероятность направления по RSI и стохастику (статья 24194), режим сигнала 0.
// Правила и допущения: registry/specs/ISO_PNN_01.md. Выход и стоп - общие правила тестера.
#pragma once
#include "../bars.h"
#include <algorithm>
#include <array>

struct IsoPnnRule : IRule {
    const Bars* B = nullptr;
    int rsiP, kP, dP, slow, look, calW, H, pnnN, mode, n = 0;
    double entryP, gate, sigma, weight;
    std::vector<double> rsi, K, D, raw;
    static double clamp(double v, double a, double b) { return v < a ? a : v > b ? b : v; }
    void init(const Params& P, const Bars& b) override {
        auto par = [&](const char* k) { auto it = P.find(k); if (it == P.end()) throw std::runtime_error(std::string("ISO_PNN_01: нет параметра ") + k); return it->second; };
        rsiP = (int)par("rsi_period"); kP = (int)par("stoch_k"); dP = (int)par("stoch_d"); slow = (int)par("stoch_slowing"); look = (int)par("pattern_lookback");
        calW = (int)par("calibration_window"); H = (int)par("forecast_horizon"); pnnN = (int)par("pnn_samples"); mode = (int)par("model_mode");
        entryP = par("entry_probability"); gate = par("raw_gate"); sigma = par("pnn_sigma"); weight = par("pnn_weight");
        B = &b; n = (int)b.size(); rsi.assign(n, NAN); K.assign(n, NAN); D.assign(n, NAN); raw.assign(n, NAN);
        double ag = 0, al = 0;
        for (int i = 1; i < n; ++i) {
            const double ch = b.c[i] - b.c[i - 1], g = ch > 0 ? ch : 0, l = ch < 0 ? -ch : 0;
            if (i <= rsiP) { ag += g; al += l; if (i == rsiP) { ag /= rsiP; al /= rsiP; } }
            else { ag = (ag * (rsiP - 1) + g) / rsiP; al = (al * (rsiP - 1) + l) / rsiP; }
            if (i >= rsiP) rsi[i] = al == 0 ? 100.0 : 100.0 - 100.0 / (1.0 + ag / al);
        }
        std::vector<double> lo(n, NAN), hi(n, NAN);
        for (int i = kP - 1; i < n; ++i) { double a = b.l[i], z = b.h[i]; for (int j = 1; j < kP; ++j) { a = std::min(a, b.l[i - j]); z = std::max(z, b.h[i - j]); } lo[i] = a; hi[i] = z; }
        for (int i = kP + slow - 2; i < n; ++i) { double su = 0, sd = 0; for (int j = 0; j < slow; ++j) { su += b.c[i - j] - lo[i - j]; sd += hi[i - j] - lo[i - j]; } K[i] = sd == 0 ? 100.0 : 100.0 * su / sd; }
        for (int i = kP + slow + dP - 3; i < n; ++i) { double s = 0; for (int j = 0; j < dP; ++j) s += K[i - j]; D[i] = s / dP; }
        for (int i = 1; i < n; ++i) {
            if (std::isnan(rsi[i - 1]) || std::isnan(K[i - 1]) || std::isnan(D[i])) continue;
            const double lr = clamp((rsi[i] - 50) / 35, -1, 1), lk = clamp((K[i] - 50) / 40, -1, 1), sr = clamp((rsi[i] - rsi[i - 1]) / 10, -1, 1),
                         sk = clamp((K[i] - K[i - 1]) / 15, -1, 1), kd = clamp((K[i] - D[i]) / 15, -1, 1);
            raw[i] = clamp(0.5 + 0.5 * (0.28 * lr + 0.22 * lk + 0.20 * sr + 0.15 * sk + 0.15 * kd), 0, 1);
        }
    }
    int warmup() const override { return 100 + calW + H + look; }
    double isotonic(int i) const {
        std::vector<std::pair<double, double>> v;
        for (int j = i - H; j > i - H - calW; --j) v.push_back({raw[j], B->c[j + H] > B->c[j] ? 1.0 : 0.0});
        if (v.size() < 30) return 0.5;
        std::sort(v.begin(), v.end());
        std::vector<double> gx, gy, gw;
        for (auto& p : v) {
            if (gx.empty() || std::fabs(p.first - gx.back()) > 1e-9) { gx.push_back(p.first); gy.push_back(p.second); gw.push_back(1); }
            else { const double w = gw.back() + 1; gy.back() = (gy.back() * gw.back() + p.second) / w; gw.back() = w; }
        }
        const int g = (int)gx.size(); std::vector<double> bm, bw; std::vector<int> be;
        for (int q = 0; q < g; ++q) {
            bm.push_back(gy[q]); bw.push_back(gw[q]); be.push_back(q);
            while (bm.size() >= 2 && bm[bm.size() - 2] > bm.back()) {
                const size_t a = bm.size() - 2; const double w = bw[a] + bw[a + 1];
                bm[a] = (bm[a] * bw[a] + bm[a + 1] * bw[a + 1]) / w; bw[a] = w; be[a] = be[a + 1]; bm.pop_back(); bw.pop_back(); be.pop_back();
            }
        }
        std::vector<double> fit(g); int s = 0; for (size_t a = 0; a < bm.size(); ++a) { for (int q = s; q <= be[a]; ++q) fit[q] = bm[a]; s = be[a] + 1; }
        const double x = raw[i];
        if (x <= gx[0]) return clamp(fit[0], 0.01, 0.99);
        if (x >= gx[g - 1]) return clamp(fit[g - 1], 0.01, 0.99);
        for (int q = 0; q < g - 1; ++q) if (x >= gx[q] && x <= gx[q + 1]) {
            const double dx = gx[q + 1] - gx[q]; if (dx <= 1e-12) return clamp(fit[q], 0.01, 0.99);
            return clamp(fit[q] + (x - gx[q]) / dx * (fit[q + 1] - fit[q]), 0.01, 0.99);
        }
        return 0.5;
    }
    std::array<double, 6> feat(int i) const {
        const Bars& b = *B; const double rg = b.h[i] - b.l[i];
        const double loc = rg <= b.point ? 0.5 : clamp((b.c[i] - b.l[i]) / rg, 0, 1);
        double hh = b.h[i], ll = b.l[i]; for (int j = 1; j <= look; ++j) { hh = std::max(hh, b.h[i - j]); ll = std::min(ll, b.l[i - j]); }
        const double mom = hh - ll <= b.point ? 0.5 : clamp(0.5 + 0.5 * (b.c[i] - b.c[i - look]) / (hh - ll), 0, 1);
        return {clamp(rsi[i] / 100, 0, 1), clamp(K[i] / 100, 0, 1), clamp(D[i] / 100, 0, 1), loc, mom, raw[i]};
    }
    double pnn(int i) const {
        const auto q = feat(i); double up = 0, dn = 0; int nu = 0, nd = 0; const double den = 2 * sigma * sigma; const int m = std::min(pnnN, calW);
        for (int j = i - H; j > i - H - m; --j) {
            const auto s = feat(j); double d2 = 0; for (int a = 0; a < 6; ++a) { const double z = q[a] - s[a]; d2 += z * z; }
            const double k = std::exp(-d2 / den);
            if (B->c[j + H] > B->c[j]) { up += k; ++nu; } else { dn += k; ++nd; }
        }
        if (nu < 5 || nd < 5) return 0.5;
        up /= nu; dn /= nd; if (up + dn <= 1e-15) return 0.5;
        return clamp(up / (up + dn), 0.01, 0.99);
    }
    int signal(int i) override {
        if (i < warmup()) return 0;
        const double x = raw[i];
        const bool longSide = x >= 0.5 + gate, shortSide = x <= 0.5 - gate;
        if (!longSide && !shortSide) return 0;
        double p = isotonic(i); if (mode == 1) p = (1 - weight) * p + weight * pnn(i);
        p = clamp(p, 0.01, 0.99);
        // порог включительно: допуск только на ошибку округления (вероятность часто равна порогу точно, например 11/20)
        if (longSide && p >= entryP - 1e-9) return 1;
        if (shortSide && 1 - p >= entryP - 1e-9) return -1;
        return 0;
    }
};
inline std::unique_ptr<IRule> make_iso_pnn() { return std::unique_ptr<IRule>(new IsoPnnRule()); }
