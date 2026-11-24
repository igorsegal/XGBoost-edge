// tester.cpp - тестер правил из реестра на истории XFBAR001.
// Запуск: tester <config.json> [--selftest]
// Реестр даёт значения параметров по умолчанию; конфиг теста включает правила и переопределяет параметры.
#include "json_mini.h"
#include "bars.h"
#include "expr_rule.h"
#include "rules/hedge.h"
#include <cstdio>
#include <set>
#include <algorithm>
#include <iostream>

static const char* VERSION = "tester 1.1";

// ---- таблица реализованных правил: id реестра -> фабрика ----
static std::map<std::string, RuleFactory> factories() {
    return { {"HEDGE_ENS_01", make_hedge} };
}

struct Trade { int i_sig, i_in, i_out; int dir; double pnl, R; int64_t t_in; };

// Дата по Unix-времени без gmtime_r (переносимо на MinGW).
static void civil(int64_t t, int& y, int& m, int& d) {
    int64_t z = t / 86400 + 719468; if (t < 0 && t % 86400) z -= 1;
    int64_t era = (z >= 0 ? z : z - 146096) / 146097; int64_t doe = z - era * 146097;
    int64_t yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365; int64_t yy = yoe + era * 400;
    int64_t doy = doe - (365 * yoe + yoe / 4 - yoe / 100); int64_t mp = (5 * doy + 2) / 153;
    d = (int)(doy - (153 * mp + 2) / 5 + 1); m = (int)(mp < 10 ? mp + 3 : mp - 9); y = (int)(yy + (m <= 2));
}
static std::string ymd(int64_t t) { int y, m, d; civil(t, y, m, d); char b[32]; snprintf(b, sizeof b, "%04d-%02d-%02d", y % 10000, m, d); return b; }
static std::string quarter(int64_t t) { int y, m, d; civil(t, y, m, d); char b[32]; snprintf(b, sizeof b, "%04dQ%d", y % 10000, (m - 1) / 3 + 1); return b; }

struct Seg { std::string name; int64_t t0, t1; };   // [t0, t1)
struct Metrics { int n = 0, wins = 0, longs = 0, shorts = 0; double net = 0, gw = 0, gl = 0, sumR = 0, maxdd = 0; int posQ = 0, totQ = 0; };

static Metrics calc(const std::vector<Trade>& tr, const Seg& s, double point) {
    Metrics m; double eq = 0, peak = 0; std::map<std::string, double> q;
    for (const auto& t : tr) {
        if (t.t_in < s.t0 || t.t_in >= s.t1) continue;
        m.n++; double p = t.pnl / (10 * point);   // в пипсах (5-значная котировка)
        m.net += p; (p > 0 ? m.gw : m.gl) += (p > 0 ? p : -p); if (p > 0) m.wins++;
        (t.dir > 0 ? m.longs : m.shorts)++; m.sumR += t.R;
        eq += p; peak = std::max(peak, eq); m.maxdd = std::max(m.maxdd, peak - eq); q[quarter(t.t_in)] += p;
    }
    m.totQ = (int)q.size(); for (auto& kv : q) if (kv.second > 0) m.posQ++;
    return m;
}
static double pf(const Metrics& m) { return m.gl > 0 ? m.gw / m.gl : (m.gw > 0 ? 999 : 0); }

// ATR (простое среднее TR за period), причинный
static std::vector<double> atr(const Bars& b, int p) {
    size_t n = b.size(); std::vector<double> tr(n), a(n, NAN);
    for (size_t i = 0; i < n; ++i) {
        double r = b.h[i] - b.l[i];
        if (i) r = std::max(r, std::max(std::fabs(b.h[i] - b.c[i - 1]), std::fabs(b.l[i] - b.c[i - 1])));
        tr[i] = r;
    }
    double s = 0; for (size_t i = 0; i < n; ++i) { s += tr[i]; if (i >= (size_t)p) s -= tr[i - p]; if (i + 1 >= (size_t)p) a[i] = s / p; }
    return a;
}

struct ExitCfg { int hold; double stopMult; int atrP; double comm; };

static std::vector<Trade> simulate(IRule& rule, const Bars& b, const std::vector<double>& A, int start_idx, const ExitCfg& X, std::vector<int>* sigs) {
    std::vector<Trade> out; int n = (int)b.size(); int free_from = 0;
    if (sigs) sigs->assign(n, 0);
    for (int x = 0; x < n - 1; ++x) {
        int sg = rule.signal(x);
        if (sigs) (*sigs)[x] = sg;
        if (sg == 0 || x < start_idx - 1 || x < free_from || std::isnan(A[x]) || A[x] <= 0) continue;
        int e = x + 1; if (e + X.hold - 1 >= n) break;
        double dist = X.stopMult * A[x], sp = b.spread[e] * b.point;
        double entry = sg > 0 ? b.o[e] + sp : b.o[e];
        double stop = sg > 0 ? entry - dist : entry + dist;
        int k = e; double exitp = 0; bool done = false;
        for (k = e; k <= e + X.hold - 1; ++k) {
            if (sg > 0) {
                if (k > e && b.o[k] <= stop) { exitp = b.o[k]; done = true; break; }
                if (b.l[k] <= stop) { exitp = stop; done = true; break; }
            } else {
                double ask_o = b.o[k] + b.spread[k] * b.point, ask_h = b.h[k] + b.spread[k] * b.point;
                if (k > e && ask_o >= stop) { exitp = ask_o; done = true; break; }
                if (ask_h >= stop) { exitp = stop; done = true; break; }
            }
        }
        if (!done) { k = e + X.hold - 1; exitp = sg > 0 ? b.c[k] : b.c[k] + b.spread[k] * b.point; }
        double pnl = (sg > 0 ? exitp - entry : entry - exitp) - X.comm;
        out.push_back({x, e, k, sg, pnl, pnl / dist, b.t[e]});
        free_from = k;
    }
    return out;
}

// Режим проверки индикатора: tester --dump <файл баров> <ИНДИКАТОР> <выход> <источник> [имя=значение ...]
// Печатает по одному значению на бар (nan до прогрева). Нужен для независимой сверки с Python.
static int dump_indicator(int argc, char** argv) {
    if (argc < 6) { std::cerr << "Использование: tester --dump <файл баров> <ИНДИКАТОР> <выход> <источник> [имя=значение ...]\n"; return 2; }
    Bars b = load_xfbar(argv[2]); Params p;
    for (int i = 6; i < argc; ++i) { std::string a = argv[i]; size_t e = a.find('='); if (e == std::string::npos) throw std::runtime_error("параметр должен быть имя=значение: " + a); p[a.substr(0, e)] = atof(a.c_str() + e + 1); }
    IndOut r = compute_indicator(argv[3], p, b, argv[5]);
    if (!r.count(argv[4])) throw std::runtime_error(std::string("нет выхода ") + argv[4]);
    const Vec& v = r[argv[4]];
    for (size_t i = 0; i < v.size(); ++i) { if (std::isnan(v[i])) printf("%lld nan\n", (long long)b.t[i]); else printf("%lld %.15g\n", (long long)b.t[i], v[i]); }
    return 0;
}

// Порча баров после точки среза (для проверки причинности): бар j портится, если он закрывается позже cut_t.
static void scramble(Bars& b, int64_t cut_t) {
    for (size_t i = 0; i < b.size(); ++i) if (b.t[i] + b.period_sec > cut_t) { b.o[i] *= 1.37; b.h[i] *= 1.41; b.l[i] *= 0.63; b.c[i] = b.c[i] * 0.77 + 0.1; }
}

int main(int argc, char** argv) {
    try {
        if (argc >= 2 && std::string(argv[1]) == "--dump") return dump_indicator(argc, argv);
        if (argc < 2) { std::cerr << "Использование: tester <config.json> [--selftest]\n"; return 2; }
        bool selftest = argc > 2 && std::string(argv[2]) == "--selftest";
        std::string cfgPath = argv[1];
        JV cfg = json_load(cfgPath);
        std::string dir = cfgPath.substr(0, cfgPath.find_last_of("/\\") == std::string::npos ? 0 : cfgPath.find_last_of("/\\") + 1);
        std::string regPath = cfg.has("registry") ? cfg.at("registry").str() : dir + "../rules_registry.json";
        if (!cfg.has("registry") && dir.empty()) regPath = "../rules_registry.json";
        JV reg = json_load(regPath);
        std::string regDir = regPath.substr(0, regPath.find_last_of("/\\") == std::string::npos ? 0 : regPath.find_last_of("/\\") + 1);
        JV catJ = json_load(cfg.has("catalog") ? cfg.at("catalog").str() : regDir + "indicators_catalog.json");
        std::map<std::string, JV> catalog; for (const auto& ij : catJ.at("indicators").a) catalog[ij.at("id").str()] = ij;

        const JV& d = cfg.at("data");
        std::string pair = d.at("pair").str(), tf = d.at("timeframe").str(), bdir = d.at("bars_dir").str();
        char sep = bdir.find('\\') != std::string::npos ? '\\' : '/';
        Bars b = load_xfbar(bdir + sep + pair + sep + pair + "_" + tf + ".bin");
        BarCache cache; cache.dir = bdir; cache.pair = pair;

        const JV& per = cfg.at("period");
        double yrs = per.at("years").num(5), ty = per.at("train_years").num(3), vy = per.at("val_years").num(1);
        int64_t endT = per.has("end") && per.at("end").t == JV::NUM ? (int64_t)per.at("end").n : b.t.back() + b.period_sec;
        const int64_t Y = 365LL * 86400;
        int64_t s0 = endT - (int64_t)(yrs * Y), s1 = s0 + (int64_t)(ty * Y), s2 = s1 + (int64_t)(vy * Y);
        std::vector<Seg> segs = { {"train", s0, s1}, {"validation", s1, s2}, {"clean", s2, endT + 1} };
        int start_idx = 0; while (start_idx < (int)b.size() && b.t[start_idx] < s0) ++start_idx;

        const JV& cs = cfg.at("costs"), &ex = cfg.at("exits");
        ExitCfg X; X.hold = (int)ex.at("hold_bars").num(24); X.stopMult = ex.at("stop_atr_mult").num(2.0); X.atrP = (int)ex.at("atr_period").num(14);
        X.comm = cs.at("commission_per_lot_usd").num(7) / cs.at("lot_units").num(100000);
        const JV& cr = cfg.at("criteria");
        int minTrades = (int)cr.at("min_trades").num(100); double minPF = cr.at("min_profit_factor").num(1.3);

        auto fac = factories();
        std::vector<double> A = atr(b, X.atrP);
        std::string testName = cfg.at("test_name").str();
        std::string out = "{\n \"tester\":\"" + std::string(VERSION) + "\",\n \"test_name\":\"" + testName + "\",\n \"pair\":\"" + pair + "\", \"timeframe\":\"" + tf + "\",\n";
        out += " \"role\":\"" + (cfg.has("role") ? cfg.at("role").str() : std::string("primary")) + "\",\n";
        out += " \"bars\":" + std::to_string(b.size()) + ", \"history\":\"" + ymd(b.t.front()) + " .. " + ymd(b.t.back()) + "\",\n";
        out += " \"period\":\"" + ymd(s0) + " .. " + ymd(endT) + "\",\n \"costs\":{\"commission_price\":" + std::to_string(X.comm) + ", \"spread\":\"по бару из файла\"},\n";
        out += " \"exits\":{\"hold_bars\":" + std::to_string(X.hold) + ",\"stop_atr_mult\":" + std::to_string(X.stopMult) + "},\n \"rules\":[\n";
        bool firstRule = true; int exitCode = 0;

        for (const auto& rj : reg.at("rules").a) {
            std::string id = rj.at("id").str();
            if (!cfg.at("rules").has(id)) continue;
            const JV& rc = cfg.at("rules").at(id);
            if (!rc.at("enabled").boolean(false)) { printf("[%s] выключено в конфиге\n", id.c_str()); continue; }
            bool isExpr = rj.has("implementation") && rj.at("implementation").t == JV::OBJ && rj.at("implementation").has("kind") && rj.at("implementation").at("kind").str() == "expr";
            if (!isExpr && !fac.count(id)) { printf("[%s] ВКЛЮЧЕНО, но реализации в тестере нет\n", id.c_str()); exitCode = 3; continue; }
            Params P;
            for (const auto& kv : rj.at("params").o) P[kv.first] = kv.second.at("default").num(0);
            std::string over;
            if (rc.has("params")) for (const auto& kv : rc.at("params").o) {
                if (!rj.at("params").has(kv.first)) throw std::runtime_error("[" + id + "] параметра '" + kv.first + "' нет в реестре");
                const JV& pd = rj.at("params").at(kv.first); double v = kv.second.num(0);
                if (pd.has("min") && v < pd.at("min").num(-1e300)) throw std::runtime_error("[" + id + "] параметр " + kv.first + " меньше минимума");
                if (pd.has("max") && v > pd.at("max").num(1e300)) throw std::runtime_error("[" + id + "] параметр " + kv.first + " больше максимума");
                P[kv.first] = v; over += kv.first + "=" + std::to_string(v) + " ";
            }
            std::unique_ptr<IRule> rule;
            if (isExpr) rule.reset(new ExprRule(rj, P, b, cache, catalog)); else { rule = fac[id](); rule->init(P, b); }
            std::vector<int> sigs;
            std::vector<Trade> tr = simulate(*rule, b, A, start_idx, X, &sigs);

            if (selftest) {
                // Проверка на заглядывание в будущее: для нескольких точек среза портим все бары, закрывающиеся после среза,
                // и сравниваем всё, что правило видит до среза: сигналы, а у правил-условий ещё и значения всех индикаторов на каждом баре.
                int totalDiff = 0, totalSer = 0; const double fr[] = {0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9};
                for (double f : fr) {
                    int cut = (int)(b.size() * f); Bars b2 = b;
                    scramble(b2, b.t[cut]); for (size_t i = cut; i < b2.size(); ++i) { b2.o[i] = b.o[i] * 1.37; b2.h[i] = b.h[i] * 1.41; b2.l[i] = b.l[i] * 0.63; b2.c[i] = b.c[i] * 0.77 + 0.1; }
                    for (size_t i = 0; i < (size_t)cut; ++i) { b2.o[i] = b.o[i]; b2.h[i] = b.h[i]; b2.l[i] = b.l[i]; b2.c[i] = b.c[i]; }
                    BarCache cache2 = cache; for (auto& kv : cache2.m) scramble(kv.second, b.t[cut]);
                    std::unique_ptr<IRule> r2;
                    if (isExpr) r2.reset(new ExprRule(rj, P, b2, cache2, catalog)); else { r2 = fac[id](); r2->init(P, b2); }
                    for (int i = 0; i < cut; ++i) if (r2->signal(i) != sigs[i]) ++totalDiff;
                    if (isExpr) totalSer += static_cast<ExprRule*>(r2.get())->series_diff(*static_cast<ExprRule*>(rule.get()), cut);
                }
                printf("[%s] SELFTEST причинности (8 точек среза): расхождений сигналов %d, расхождений рядов индикаторов %d -> %s\n", id.c_str(), totalDiff, totalSer, (totalDiff + totalSer) == 0 ? "OK" : "ЕСТЬ ЗАГЛЯДЫВАНИЕ");
                if (totalDiff + totalSer) exitCode = 4;
            }

            printf("\n[%s] %s %s  параметры: %s\n", id.c_str(), pair.c_str(), tf.c_str(), over.empty() ? "по умолчанию" : over.c_str());
            if (!firstRule) { out += ",\n"; }
            firstRule = false;
            out += "  {\"id\":\"" + id + "\", \"overrides\":\"" + over + "\", \"signals_total\":" + std::to_string(std::count_if(sigs.begin(), sigs.end(), [](int s) { return s != 0; })) + ", \"segments\":[";
            Metrics cleanM; bool fs = true;
            for (const auto& s : segs) {
                Metrics m = calc(tr, s, b.point); if (s.name == "clean") cleanM = m;
                printf("  %-10s %s..%s  сделок %4d (лонг %d, шорт %d)  побед %4.1f%%  нетто %8.1f пп  PF %5.2f  ср.R %6.3f  макс.просадка %7.1f пп  плюсовых кварталов %d/%d\n",
                       s.name.c_str(), ymd(s.t0).c_str(), ymd(s.t1 - 1).c_str(), m.n, m.longs, m.shorts, m.n ? 100.0 * m.wins / m.n : 0.0, m.net, pf(m), m.n ? m.sumR / m.n : 0.0, m.maxdd, m.posQ, m.totQ);
                char buf[400]; snprintf(buf, sizeof buf, "%s{\"segment\":\"%s\",\"trades\":%d,\"win_pct\":%.2f,\"net_pips\":%.1f,\"profit_factor\":%.3f,\"avg_R\":%.4f,\"max_dd_pips\":%.1f,\"pos_quarters\":\"%d/%d\"}",
                         fs ? "" : ",", s.name.c_str(), m.n, m.n ? 100.0 * m.wins / m.n : 0.0, m.net, pf(m), m.n ? m.sumR / m.n : 0.0, m.maxdd, m.posQ, m.totQ);
                out += buf; fs = false;
            }
            bool ok = cleanM.n >= minTrades && cleanM.net > 0 && pf(cleanM) >= minPF;
            printf("  ВЕРДИКТ по чистому отрезку: %s (нужно: сделок >= %d, нетто > 0, PF >= %.2f; есть: сделок %d, нетто %.1f пп, PF %.2f)\n",
                   ok ? "ПРОШЛО" : "НЕ ПРОШЛО", minTrades, minPF, cleanM.n, cleanM.net, pf(cleanM));
            out += std::string("], \"verdict\":\"") + (ok ? "PASS" : "FAIL") + "\"}";
        }
        out += "\n ]\n}\n";
        std::string outPath = cfg.has("output") ? cfg.at("output").str() : dir + "../results/" + testName + ".json";
        FILE* f = fopen(outPath.c_str(), "wb"); if (f) { fwrite(out.data(), 1, out.size(), f); fclose(f); printf("\nРезультат записан: %s\n", outPath.c_str()); }
        else printf("\nНе удалось записать результат: %s\n", outPath.c_str());
        return exitCode;
    } catch (const std::exception& e) { std::cerr << "ОШИБКА: " << e.what() << "\n"; return 1; }
}
