// ideas8.cpp - прогон восьми идей сканера только на разработке (бары до 2025-01-01).
// Сборка: g++ -O2 -std=c++17 -o ideas8 ideas8.cpp
// Запуск: ideas8 <папка BAZA> <папка результатов> [--selftest] [--only=ID]
// Экзамен с 2025 года эта программа открыть не может: бары после начала экзамена отрезаются при загрузке.
#include "strategies.h"
#include <functional>
#include <set>

static int64_t utc(int y, int mo, int d) {
    y -= mo <= 2; int64_t era = y / 400, yoe = y - era * 400, doy = (153 * (mo > 2 ? mo - 3 : mo + 9) + 2) / 5 + d - 1, doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    return (era * 146097 + doe - 719468) * 86400;
}
static const int64_t DEV_CUT = utc(2025, 1, 1);

struct Variant { std::string id, name; bool primary; std::vector<std::string> pairs; int tf; std::function<Strategy*()> make; };

static std::vector<Variant> variants() {
    std::vector<Variant> v;
    auto add = [&](const char* id, const std::string& name, bool prim, std::vector<std::string> pairs, int tf, std::function<Strategy*()> f) { v.push_back({id, name, prim, pairs, tf, f}); };
    const int M5 = 300, M15 = 900, H1 = 3600, H4 = 14400, D1 = 86400;
    const std::vector<std::string> FX = {"EURUSD", "GBPUSD", "USDJPY", "AUDUSD"}, ALL = {"EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD"};
    // 1
    add("VOLCHG_01", "GBPUSD_H1_demo", true, {"GBPUSD"}, H1, [] { return new VolChg(0.3, 500, 300, 1); });
    add("VOLCHG_01", "GBPUSD_H1_tp1000", false, {"GBPUSD"}, H1, [] { return new VolChg(0.3, 1000, 600, 1); });
    add("VOLCHG_01", "GBPUSD_H1_both", false, {"GBPUSD"}, H1, [] { return new VolChg(0.3, 500, 300, 0); });
    add("VOLCHG_01", "GBPUSD_H1_negative", false, {"GBPUSD"}, H1, [] { return new VolChg(0.3, 500, 300, -1); });
    for (std::string p : {"EURUSD", "USDJPY", "AUDUSD"}) add("VOLCHG_01", p + "_H1_demo", false, {p}, H1, [] { return new VolChg(0.3, 500, 300, 1); });
    // 2
    add("RASCHKE_01", "EURUSD_H4_both", true, {"EURUSD"}, H4, [] { return new Raschke(true, true); });
    for (std::string p : ALL) for (int tf : {H4, H1}) {
        std::string t = tf == H4 ? "_H4" : "_H1";
        if (!(p == "EURUSD" && tf == H4)) add("RASCHKE_01", p + t + "_both", false, {p}, tf, [] { return new Raschke(true, true); });
        add("RASCHKE_01", p + t + "_anti", false, {p}, tf, [] { return new Raschke(true, false); });
        add("RASCHKE_01", p + t + "_grail", false, {p}, tf, [] { return new Raschke(false, true); });
    }
    // 3
    add("CTC_P11_01", "EURUSD_D1M1", true, {"EURUSD"}, D1, [] { return new Ctc(); });
    for (std::string p : {"GBPUSD", "USDJPY", "AUDUSD"}) add("CTC_P11_01", p + "_D1M1", false, {p}, D1, [] { return new Ctc(); });
    add("CTC_P11_01", "EURUSD_H4M1", false, {"EURUSD"}, H4, [] { return new Ctc(); });
    // 4
    add("GRAPH_ER_01", "XAUUSD_M15", true, {"XAUUSD"}, M15, [] { return new Graph(0); });
    add("GRAPH_ER_01", "XAUUSD_M15_bias2", false, {"XAUUSD"}, M15, [] { return new Graph(1); });
    add("GRAPH_ER_01", "XAUUSD_M15_author", false, {"XAUUSD"}, M15, [] { return new Graph(2); });
    add("GRAPH_ER_01", "EURUSD_M15", false, {"EURUSD"}, M15, [] { return new Graph(0); });
    add("GRAPH_ER_01", "EURUSD_H1", false, {"EURUSD"}, H1, [] { return new Graph(0); });
    // 5
    add("ENVGATOR_01", "EURUSD_H1", true, {"EURUSD"}, H1, [] { return new EnvGator(); });
    for (std::string p : ALL) for (int tf : {M15, H1, H4}) {
        if (p == "EURUSD" && tf == H1) continue; std::string t = tf == H4 ? "_H4" : (tf == H1 ? "_H1" : "_M15");
        add("ENVGATOR_01", p + t, false, {p}, tf, [] { return new EnvGator(); });
    }
    // 6
    add("ZSCORE_01", "XAUUSD_M15", true, {"XAUUSD"}, M15, [] { return new ZScore(); });
    add("ZSCORE_01", "XAUUSD_H4", false, {"XAUUSD"}, H4, [] { return new ZScore(); });
    for (std::string p : FX) for (int tf : {M15, H4}) add("ZSCORE_01", p + (tf == H4 ? "_H4" : "_M15"), false, {p}, tf, [] { return new ZScore(); });
    // 7
    add("DTB_01", "XAUUSD_M5_best", true, {"XAUUSD"}, M5, [] { return new Dtb(0); });
    add("DTB_01", "XAUUSD_M5_worst", true, {"XAUUSD"}, M5, [] { return new Dtb(1); });
    add("DTB_01", "XAUUSD_M5_notrail", false, {"XAUUSD"}, M5, [] { return new Dtb(2); });
    for (std::string p : {"XAUUSD", "EURUSD", "GBPUSD"}) for (int tf : {M5, M15, H1}) {
        if (p == "XAUUSD" && tf == M5) continue; if (p != "XAUUSD" && tf == M15) continue;
        std::string t = tf == M5 ? "_M5" : (tf == M15 ? "_M15" : "_H1");
        add("DTB_01", p + t + "_best", false, {p}, tf, [] { return new Dtb(0); });
        add("DTB_01", p + t + "_worst", false, {p}, tf, [] { return new Dtb(1); });
        add("DTB_01", p + t + "_notrail", false, {p}, tf, [] { return new Dtb(2); });
    }
    // 8
    add("SEYKOTA_01", "PORTFOLIO_D1", true, FX, D1, [] { return new Seykota(); });
    for (std::string p : ALL) add("SEYKOTA_01", p + "_D1", false, {p}, D1, [] { return new Seykota(); });
    add("SEYKOTA_01", "PORTFOLIO_H4", false, FX, H4, [] { return new Seykota(); });
    return v;
}

static std::map<std::string, Bars> CACHE; static std::string BDIR;
static const Bars& m1(const std::string& pair) {
    auto it = CACHE.find(pair); if (it != CACHE.end()) return it->second;
    Bars b = load_xfbar(BDIR + "/" + pair + "/" + pair + "_M1.bin"); cut_bars(b, DEV_CUT); b.symbol = pair;
    return CACHE.emplace(pair, std::move(b)).first->second;
}

static std::vector<Rec> run_one(const Bars& m, const Variant& v, const std::string& pair) {
    Engine E; E.m = &m; E.b = aggregate(m, v.tf);
    double lot = pair == "XAUUSD" ? 100.0 : 100000.0; E.comm = 7.0 / lot; E.by_price = pair.substr(3) != "USD";
    std::unique_ptr<Strategy> s(v.make()); E.st = s.get(); E.run(); return E.out;
}

struct T { int64_t t; double pips; int dir; };

int main(int argc, char** argv) {
    try {
        if (argc < 3) { fprintf(stderr, "ideas8 <BAZA> <out> [--selftest] [--only=ID]\n"); return 2; }
        BDIR = argv[1]; std::string out = argv[2]; bool self = false; std::string only;
        for (int i = 3; i < argc; ++i) { std::string a = argv[i]; if (a == "--selftest") self = true; else if (a.rfind("--only=", 0) == 0) only = a.substr(7); else throw std::runtime_error("неизвестный ключ " + a); }
        FILE* res = self ? nullptr : fopen((out + "/results" + (only.empty() ? "" : "_" + only) + ".csv").c_str(), "wb");
        if (res) fprintf(res, "id,variant,primary,trades,longs,shorts,win_pct,net_pips,pf,max_dd_pips,pos_windows,y2020h2,y2021,y2022,y2023,y2024,verdict\n");
        int bad = 0;
        for (const auto& v : variants()) {
            if (!only.empty() && v.id != only) continue;
            std::vector<T> all; long checked = 0, diff = 0;
            for (const auto& pair : v.pairs) {
                const Bars& m = m1(pair);
                std::vector<Rec> r = run_one(m, v, pair);
                if (self) {
                    // портим все минутки, закрывающиеся после точки среза: всё, что случилось до среза, не должно измениться
                    for (double f : {0.35, 0.6, 0.85}) {
                        size_t cut = (size_t)(m.size() * f); const int64_t cutT = m.t[cut];
                        Bars x = m; for (size_t i = cut; i < x.size(); ++i) { x.o[i] *= 1.37; x.h[i] *= 1.41; x.l[i] *= 0.63; x.c[i] = x.c[i] * 0.77 + 0.1; x.spread[i] = x.spread[i] * 3 + 7; x.v[i] = x.v[i] * 5 + 3; }
                        std::vector<Rec> r2 = run_one(x, v, pair);
                        auto key = [](const Rec& a) { return std::make_tuple(a.k_in, a.dir, a.k_out, a.entry); };
                        auto before = [&](const std::vector<Rec>& q) { std::vector<Rec> o; for (const auto& a : q) if (m.t[a.k_in] + 60 <= cutT) o.push_back(a);
                            std::sort(o.begin(), o.end(), [&](const Rec& a, const Rec& b) { return std::make_tuple(a.k_in, a.i_sig, a.dir, a.entry) < std::make_tuple(b.k_in, b.i_sig, b.dir, b.entry); }); return o; };
                        std::vector<Rec> a = before(r), b = before(r2);
                        if (a.size() != b.size()) { ++diff; continue; }
                        for (size_t k = 0; k < a.size(); ++k) {
                            ++checked; const Rec &p = a[k], &q = b[k];
                            if (p.k_in != q.k_in || p.dir != q.dir || p.entry != q.entry || p.sl0 != q.sl0 || p.tp != q.tp) ++diff;
                            else if ((m.t[p.k_out] + 60 <= cutT || m.t[q.k_out] + 60 <= cutT) && (p.k_out != q.k_out || p.exit != q.exit)) ++diff;
                        }
                    }
                    continue;
                }
                std::sort(r.begin(), r.end(), [](const Rec& a, const Rec& b) { return std::make_tuple(a.k_in, a.i_sig, a.dir, a.entry) < std::make_tuple(b.k_in, b.i_sig, b.dir, b.entry); });
                const int64_t from = pair == "AUDUSD" ? utc(2020, 11, 1) : utc(2020, 7, 1);
                FILE* tf = fopen((out + "/trades/" + v.id + "__" + v.name + "__" + pair + ".csv").c_str(), "wb");
                if (!tf) throw std::runtime_error("не записать сделки");
                fprintf(tf, "signal_time,entry_time,exit_time,dir,entry,exit,sl,tp,pnl,why,counted\n");
                Tf b = aggregate(m, v.tf);
                for (const auto& a : r) {
                    bool c = a.t_bar >= from && a.t_bar < DEV_CUT;
                    fprintf(tf, "%lld,%lld,%lld,%d,%.10g,%.10g,%.10g,%.10g,%.10g,%s,%d\n", (long long)b.t[a.i_sig], (long long)m.t[a.k_in], (long long)m.t[a.k_out], a.dir, a.entry, a.exit, a.sl0, a.tp, a.pnl, a.why.c_str(), c ? 1 : 0);
                    if (c) all.push_back({a.t_bar, a.pnl / (10 * m.point), a.dir});
                }
                fclose(tf);
            }
            if (self) { printf("%-12s %-22s проверено сделок %ld, расхождений %ld -> %s\n", v.id.c_str(), v.name.c_str(), checked, diff, diff ? "ЗАГЛЯДЫВАНИЕ" : "OK"); fflush(stdout); if (diff) ++bad; continue; }
            std::stable_sort(all.begin(), all.end(), [](const T& a, const T& b) { return a.t < b.t; });
            int n = 0, w = 0, lg = 0; double net = 0, gw = 0, gl = 0, eq = 0, pk = 0, dd = 0, yr[5] = {0};
            for (const auto& t : all) { ++n; net += t.pips; if (t.pips > 0) { ++w; gw += t.pips; } else gl -= t.pips; if (t.dir > 0) ++lg; eq += t.pips; pk = std::max(pk, eq); dd = std::max(dd, pk - eq);
                int y = 0; for (int k = 1; k < 5; ++k) if (t.t >= utc(2020 + k, 1, 1)) y = k; yr[y] += t.pips; }
            int pos = 0; for (int s = 0; s < 27; ++s) { int mo = 6 + 2 * s; int64_t a = utc(2020 + mo / 12, mo % 12 + 1, 1), z = utc(2020 + (mo + 2) / 12, (mo + 2) % 12 + 1, 1); double q = 0; for (const auto& t : all) if (t.t >= a && t.t < z) q += t.pips; if (q > 0) ++pos; }
            double pf = gl > 0 ? gw / gl : (gw > 0 ? 999 : 0); bool ok = n >= 100 && net > 0 && pf >= 1.3;
            fprintf(res, "%s,%s,%d,%d,%d,%d,%.1f,%.1f,%.3f,%.1f,%d,%.1f,%.1f,%.1f,%.1f,%.1f,%s\n", v.id.c_str(), v.name.c_str(), v.primary ? 1 : 0, n, lg, n - lg, n ? 100.0 * w / n : 0, net, pf, dd, pos, yr[0], yr[1], yr[2], yr[3], yr[4], ok ? "PASS" : "FAIL");
            printf("%-12s %-22s %s сделок %5d  нетто %10.1f пп  PF %.3f  %s\n", v.id.c_str(), v.name.c_str(), v.primary ? "О" : "Д", n, net, pf, ok ? "ПРОШЛО" : "не прошло"); fflush(stdout);
        }
        if (res) fclose(res);
        return bad ? 4 : 0;
    } catch (const std::exception& e) { fprintf(stderr, "ОШИБКА: %s\n", e.what()); return 1; }
}
