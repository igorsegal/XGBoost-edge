// control.cpp - контроль случайными входами для вариантов с PF >= 1,1 и >= 100 сделок (только разработка, до 2025-01-01).
// Сборка: g++ -O2 -std=c++17 -o control control.cpp      Запуск: control <папка BAZA> <файл результата .csv>
// Два способа, по 500 прогонов, то же число лонгов и шортов по каждой паре:
//   hold - случайный бар, то же направление, тот же стоп в ATR, та же цель в R, то же время удержания, что у парной сделки;
//   rule - случайный бар, где выход ещё не наступил, и выход по правилу самой идеи.
// Перед этим программа проверяет себя: выход по правилу, посчитанный для настоящих входов, обязан совпасть с настоящим.
#include "strategies.h"
#include <random>
#include <functional>

static int64_t utc(int y, int mo, int d) {
    y -= mo <= 2; int64_t era = y / 400, yoe = y - era * 400, doy = (153 * (mo > 2 ? mo - 3 : mo + 9) + 2) / 5 + d - 1, doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    return (era * 146097 + doe - 719468) * 86400;
}
static const int64_t DEV_CUT = utc(2025, 1, 1);
static const int RUNS = 500;

enum Kind { RASCHKE, CTC, ENVG, ZS, SEY };
struct Var { const char* id; const char* name; Kind kind; bool anti, hg; int tf; std::vector<std::string> pairs; };

struct RaschkeT : Raschke { std::vector<int> tags; using Raschke::Raschke;
    void on_closed(Engine& E, const Pos& p, const Rec& r) override { tags.push_back(p.tag); Raschke::on_closed(E, p, r); } };

struct Real { int dir, tag, i_in, k_in, k_out, hold; bool by_open; double pnl, sl_atr, tpR; };
struct Ctx { Bars m; Tf b; double comm; bool by_price; Vd atr, atr20, fast, sig, ema, adx, f, s, z; std::vector<int> bar_of; std::vector<Real> real; std::vector<Rec> rec; };

static double sp(const Ctx& c, int k) { return c.m.spread[k] * c.m.point; }
static double pnl_of(const Ctx& c, int d, double en, double px) { return d * (px - en) - c.comm * (c.by_price ? en : 1.0); }
// Выход: стоп/цель по минуткам (разрыв - по открытию) до минутки lim; иначе по открытию lim (at_open) или по закрытию lim-1.
static double leave(const Ctx& c, int d, int k0, double en, double sl, double tp, int lim, bool at_open) {
    const Bars& m = c.m; int n = (int)m.size(); int end = std::min(lim, n);
    for (int k = k0; k < end; ++k) {
        double s = sp(c, k);
        if (k > k0) { double op = d > 0 ? m.o[k] : m.o[k] + s;
            if ((sl > 0 && d * (op - sl) <= 0) || (tp > 0 && d * (op - tp) >= 0)) return pnl_of(c, d, en, op); }
        if (sl > 0 && (d > 0 ? m.l[k] <= sl : m.h[k] + s >= sl)) return pnl_of(c, d, en, sl);
        if (tp > 0 && (d > 0 ? m.h[k] >= tp : m.l[k] + s <= tp)) return pnl_of(c, d, en, tp);
    }
    if (lim >= n) { int k = n - 1; return pnl_of(c, d, en, d > 0 ? m.c[k] : m.c[k] + sp(c, k)); }
    if (at_open) return pnl_of(c, d, en, d > 0 ? m.o[lim] : m.o[lim] + sp(c, lim));
    return pnl_of(c, d, en, d > 0 ? m.c[lim - 1] : m.c[lim - 1] + sp(c, lim - 1));
}
// первый бар j > i, на открытии которого срабатывает выход по правилу идеи; n() - не срабатывает
static int rule_bar(const Ctx& c, const Var& v, int tag, int d, int i) {
    int n = c.b.n();
    for (int j = i + 1; j < n; ++j) { int x = j - 1;
        if (v.kind == ZS) { if (d > 0 ? c.z[x] >= 0 : c.z[x] <= 0) return j; }
        else if (v.kind == SEY) { if (d * (c.f[x] - c.s[x]) < 0) return j; }
        else if (v.kind == RASCHKE) {
            if (tag == 1) { double fp = c.fast[x - 1], f = c.fast[x], pp = c.sig[x - 1], s = c.sig[x]; if (d > 0 ? (fp >= pp && f < s) : (fp <= pp && f > s)) return j; }
            else if (c.adx[x] < 20 || d * (c.b.c[x] - c.ema[x]) < 0) return j;
        }
    }
    return n;
}
static double rule_exit(const Ctx& c, const Var& v, int tag, int d, int i, int k, double en, double sl, double tp) {
    if (v.kind == CTC) return leave(c, d, k, en, sl, tp, (int)c.m.size(), false);
    if (v.kind == ENVG) { int j = i + 23; return leave(c, d, k, en, sl, tp, j < c.b.n() ? c.b.e[j] : (int)c.m.size(), false); }
    int j = rule_bar(c, v, tag, d, i); return leave(c, d, k, en, sl, tp, j < c.b.n() ? c.b.s[j] : (int)c.m.size(), true);
}
static bool eligible(const Ctx& c, const Var& v, int tag, int d, int i) {
    int x = i - 1;
    switch (v.kind) {
        case ZS: return x >= 20 && d * c.z[x] < 0;
        case SEY: return x >= 200 && d * (c.f[x] - c.s[x]) > 0;
        case ENVG: return x >= 20 && i + 23 < c.b.n() && c.atr[x] > 0;
        case CTC: return x >= 14;
        case RASCHKE: if (i < 60) return false; return tag == 1 ? d * (c.fast[x] - c.sig[x]) > 0 : (c.adx[x] >= 20 && d * (c.b.c[x] - c.ema[x]) > 0);
    }
    return false;
}
static const Vd& atr_of(const Ctx& c, const Var& v) { return v.kind == SEY ? c.atr20 : c.atr; }

int main(int argc, char** argv) {
    try {
        if (argc < 3) { fprintf(stderr, "control <BAZA> <out.csv>\n"); return 2; }
        const std::string base = argv[1];
        const int M = 0; (void)M; const int H1 = 3600, H4 = 14400;
        std::vector<Var> V = {
            {"RASCHKE_01", "EURUSD_H4_both", RASCHKE, true, true, H4, {"EURUSD"}}, {"RASCHKE_01", "GBPUSD_H1_anti", RASCHKE, true, false, H1, {"GBPUSD"}},
            {"RASCHKE_01", "USDJPY_H1_both", RASCHKE, true, true, H1, {"USDJPY"}}, {"RASCHKE_01", "USDJPY_H1_anti", RASCHKE, true, false, H1, {"USDJPY"}},
            {"RASCHKE_01", "USDJPY_H1_grail", RASCHKE, false, true, H1, {"USDJPY"}}, {"RASCHKE_01", "XAUUSD_H4_both", RASCHKE, true, true, H4, {"XAUUSD"}},
            {"CTC_P11_01", "EURUSD_H4M1", CTC, false, false, H4, {"EURUSD"}}, {"ENVGATOR_01", "XAUUSD_H4", ENVG, false, false, H4, {"XAUUSD"}},
            {"ZSCORE_01", "EURUSD_H4", ZS, false, false, H4, {"EURUSD"}}, {"ZSCORE_01", "GBPUSD_H4", ZS, false, false, H4, {"GBPUSD"}},
            {"ZSCORE_01", "AUDUSD_H4", ZS, false, false, H4, {"AUDUSD"}}, {"SEYKOTA_01", "PORTFOLIO_H4", SEY, false, false, H4, {"EURUSD", "GBPUSD", "USDJPY", "AUDUSD"}}};
        FILE* out = fopen(argv[2], "wb"); if (!out) throw std::runtime_error("не записать результат");
        fprintf(out, "id,variant,trades,net_pips,pf,method,runs,random_median_net,random_p95_net,random_median_pf,random_p95_pf,share_net_ge_real,share_pf_ge_real,share_pass_bar\n");
        long wrong = 0;
        for (const Var& v : V) {
            std::vector<Ctx> C(v.pairs.size()); double rnet = 0, rgw = 0, rgl = 0; int rn = 0;
            for (size_t p = 0; p < v.pairs.size(); ++p) {
                Ctx& c = C[p]; const std::string& pair = v.pairs[p];
                c.m = load_xfbar(base + "/" + pair + "/" + pair + "_M1.bin"); cut_bars(c.m, DEV_CUT); c.m.symbol = pair;
                c.comm = 7.0 / (pair == "XAUUSD" ? 100.0 : 100000.0); c.by_price = pair.substr(3) != "USD";
                Engine E; E.m = &c.m; E.b = aggregate(c.m, v.tf); E.comm = c.comm; E.by_price = c.by_price;
                std::unique_ptr<Strategy> st; RaschkeT* rt = nullptr;
                if (v.kind == RASCHKE) { rt = new RaschkeT(v.anti, v.hg); st.reset(rt); } else if (v.kind == CTC) st.reset(new Ctc()); else if (v.kind == ENVG) st.reset(new EnvGator()); else if (v.kind == ZS) st.reset(new ZScore()); else st.reset(new Seykota());
                E.st = st.get(); E.run(); c.b = E.b; c.rec = E.out;
                c.atr = i_atr(c.b, 14); c.atr20 = i_atr(c.b, 20);
                if (v.kind == RASCHKE) { Raschke r(true, true); r.init(E); c.fast = r.fast; c.sig = r.sig; c.ema = r.ema; c.adx = r.adx; }
                if (v.kind == SEY) { c.f = i_ema(c.b.c, 20); c.s = i_ema(c.b.c, 200); }
                if (v.kind == ZS) { ZScore q; q.init(E); c.z = q.z; }
                c.bar_of.assign(c.m.size(), 0); for (int i = 0; i < c.b.n(); ++i) for (int k = c.b.s[i]; k < c.b.e[i]; ++k) c.bar_of[k] = i;
                const int64_t from = pair == "AUDUSD" ? utc(2020, 11, 1) : utc(2020, 7, 1);
                for (size_t q = 0; q < c.rec.size(); ++q) {
                    const Rec& r = c.rec[q]; if (!(r.t_bar >= from && r.t_bar < DEV_CUT)) continue;
                    Real t; t.dir = r.dir; t.tag = rt ? rt->tags[q] : 0; t.i_in = r.i_in; t.k_in = r.k_in; t.k_out = r.k_out; t.pnl = r.pnl;
                    t.hold = c.bar_of[r.k_out] - r.i_in; t.by_open = r.why == "mean" || r.why == "cross" || r.why == "anti_cross" || r.why == "hg_adx" || r.why == "hg_ema";
                    const double a = atr_of(c, v)[r.i_in - 1], risk = r.sl0 > 0 ? std::fabs(r.entry - r.sl0) : 0;
                    t.sl_atr = risk > 0 ? risk / a : 0; t.tpR = (r.tp > 0 && risk > 0) ? std::fabs(r.tp - r.entry) / risk : 0;
                    c.real.push_back(t);
                    // самопроверка: тот же вход, тот же стоп - выход обязан дать ту же прибыль
                    double again = rule_exit(c, v, t.tag, r.dir, r.i_in, r.k_in, r.entry, r.sl0, r.tp);
                    if (std::fabs(again - r.pnl) > 1e-9) { ++wrong; if (wrong < 6) fprintf(stderr, "самопроверка: %s %s %s k=%d %s было %.6f стало %.6f\n", v.id, v.name, pair.c_str(), r.k_in, r.why.c_str(), r.pnl, again); }
                    double pips = r.pnl / (10 * c.m.point); rnet += pips; if (pips > 0) rgw += pips; else rgl -= pips; ++rn;
                }
            }
            const double rpf = rgl > 0 ? rgw / rgl : 999;
            for (int method = 0; method < 2; ++method) {
                std::mt19937_64 g(20261128 + method);
                // подходящие бары: по паре, виду сделки и направлению
                std::vector<std::map<int, std::vector<int>>> pool(C.size());
                std::vector<double> nets, pfs; int ge_net = 0, ge_pf = 0, pass = 0;
                for (int run = 0; run < RUNS; ++run) {
                    double net = 0, gw = 0, gl = 0;
                    for (size_t p = 0; p < C.size(); ++p) {
                        Ctx& c = C[p]; const int64_t from = v.pairs[p] == "AUDUSD" ? utc(2020, 11, 1) : utc(2020, 7, 1);
                        for (const Real& t : c.real) {
                            const int key = method ? t.tag * 4 + (t.dir > 0 ? 1 : 2) : 0;
                            std::vector<int>& P = pool[p][key];
                            if (P.empty()) { for (int i = 61; i < c.b.n(); ++i) if (c.b.t[i] >= from && c.b.t[i] < DEV_CUT && (!method || eligible(c, v, t.tag, t.dir, i))) P.push_back(i);
                                if (P.empty()) throw std::runtime_error("нет подходящих баров"); }
                            int i = 0, k = 0;
                            for (int tries = 0;; ++tries) {
                                if (tries > 100000) throw std::runtime_error("не найти случайный вход");
                                i = P[g() % P.size()]; k = c.b.s[i];
                                if (v.kind == CTC) { k = c.b.s[i] + (int)(g() % (uint64_t)(c.b.e[i] - c.b.s[i])); if (c.m.spread[k] > 50) continue; }
                                break;
                            }
                            const int d = t.dir; const double en = d > 0 ? c.m.o[k] + sp(c, k) : c.m.o[k];
                            double sl = 0, tp = 0;
                            if (t.sl_atr > 0) {
                                const double dist = t.sl_atr * atr_of(c, v)[i - 1];
                                // у SEYKOTA стоп отложен от своей стороны котировки, как в самой идее (это и есть цена входа)
                                sl = en - d * dist; if (t.tpR > 0) tp = en + d * t.tpR * dist;
                            }
                            double pn;
                            if (method) pn = rule_exit(c, v, t.tag, d, i, k, en, sl, tp);
                            else { const int j = i + t.hold;
                                if (j >= c.b.n()) pn = leave(c, d, k, en, sl, tp, (int)c.m.size(), false);
                                else if (t.by_open) pn = leave(c, d, k, en, sl, tp, c.b.s[j], true);
                                else pn = leave(c, d, k, en, sl, tp, c.b.e[j], false); }
                            const double pips = pn / (10 * c.m.point); net += pips; if (pips > 0) gw += pips; else gl -= pips;
                        }
                    }
                    const double pf = gl > 0 ? gw / gl : 999; nets.push_back(net); pfs.push_back(pf);
                    if (net >= rnet) ++ge_net; if (pf >= rpf) ++ge_pf; if (net > 0 && pf >= 1.3 && rn >= 100) ++pass;
                }
                std::sort(nets.begin(), nets.end()); std::sort(pfs.begin(), pfs.end());
                fprintf(out, "%s,%s,%d,%.1f,%.3f,%s,%d,%.1f,%.1f,%.3f,%.3f,%.3f,%.3f,%.3f\n", v.id, v.name, rn, rnet, rpf, method ? "rule" : "hold", RUNS,
                        nets[RUNS / 2], nets[(int)(RUNS * 0.95)], pfs[RUNS / 2], pfs[(int)(RUNS * 0.95)], (double)ge_net / RUNS, (double)ge_pf / RUNS, (double)pass / RUNS);
                printf("%-11s %-15s %-4s настоящий PF %.3f нетто %9.1f | случайные: PF медиана %.3f, 95%% %.3f | не хуже по нетто %5.1f%%, по PF %5.1f%% | прошли планку %.1f%%\n", v.id, v.name, method ? "rule" : "hold", rpf, rnet,
                       pfs[RUNS / 2], pfs[(int)(RUNS * 0.95)], 100.0 * ge_net / RUNS, 100.0 * ge_pf / RUNS, 100.0 * pass / RUNS); fflush(stdout);
            }
        }
        fclose(out);
        printf("самопроверка выходов на настоящих входах: расхождений %ld\n", wrong);
        return wrong ? 4 : 0;
    } catch (const std::exception& e) { fprintf(stderr, "ОШИБКА: %s\n", e.what()); return 1; }
}
