#include <cmath>
#include <iostream>
#include <fstream>
#include <vector>
#include <string>
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <iomanip>
#include <ctime>
#include <map>
#include <deque>
#include <omp.h>
static const int NUM_QFEATS = 23;
static const int NUM_FLAGS  = 9;
inline bool is_scale_invariant(int feat_idx) {
    return feat_idx != 17;
}
#pragma pack(push, 1)
struct V3SliceEntry {
    char timeframe[8];
    uint64_t start_row;
    uint32_t num_rows;
};
struct V3QuantHeader {
    char magic[8];
    uint32_t num_slices;
    uint32_t num_qfeats;
    uint32_t num_flags;
    uint64_t total_rows;
    uint64_t index_offset;
    float bin_edges[NUM_QFEATS][256];
};
struct TickFileHeader {
    char magic[8];
    float point;
    uint32_t num_days;
    uint64_t total_ticks;
};
struct TickDayIndex {
    uint32_t day_ts;
    uint64_t start_tick_idx;
    uint32_t num_ticks;
};
struct TickRecord {
    uint32_t ts_sec;
    float bid;
    uint16_t spread_pts;
};
#pragma pack(pop)
struct Rule {
    int dir;
    int trend_mode;
    int f1, f2;
    uint8_t b1, b2;
    bool gt1, gt2;
    double score;
};
struct Signal {
    uint32_t bar_close_utc;
    int tf_hours;
    int dir;
    float atr14;
};
struct OptResult {
    std::string tf_mode;
    double sl_mult;
    double tp_mult;
    int trades;
    double wr;
    double pf;
    double balance;
    double max_dd;
    double fitness;
};
int get_broker_offset_sec(uint32_t utc_ts) {
    std::time_t t = static_cast<std::time_t>(utc_ts);
    std::tm* g = std::gmtime(&t);
    if (!g) return 7200;
    int m = g->tm_mon + 1;
    int d = g->tm_mday;
    int wday = g->tm_wday;
    if (m > 3 && m < 10) return 10800;
    if (m == 3) {
        int last_sun = 31 - ((wday + 31 - d) % 7);
        if (d > last_sun || (d == last_sun && g->tm_hour >= 1)) return 10800;
    }
    if (m == 10) {
        int last_sun = 31 - ((wday + 31 - d) % 7);
        if (d < last_sun || (d == last_sun && g->tm_hour < 1)) return 10800;
    }
    return 7200;
}
int get_broker_hour(uint32_t utc_ts) {
    int off_h = get_broker_offset_sec(utc_ts) / 3600;
    std::time_t t = static_cast<std::time_t>(utc_ts);
    std::tm* g = std::gmtime(&t);
    return g ? ((g->tm_hour + off_h) % 24) : 0;
}
int main() {
    auto t0 = std::chrono::high_resolution_clock::now();
    std::ifstream tf("data/cache/EURUSD_ticks.bin", std::ios::binary);
    if (!tf) { std::cerr << "Cannot open EURUSD_ticks.bin\n"; return 1; }
    TickFileHeader thdr{};
    tf.read(reinterpret_cast<char*>(&thdr), sizeof(thdr));
    std::vector<TickDayIndex> day_idx(thdr.num_days);
    tf.read(reinterpret_cast<char*>(day_idx.data()), thdr.num_days * sizeof(TickDayIndex));
    std::vector<TickRecord> ticks(thdr.total_ticks);
    tf.read(reinterpret_cast<char*>(ticks.data()), thdr.total_ticks * sizeof(TickRecord));
    tf.close();
    struct HourBar { float open; float close; };
    std::map<uint32_t, HourBar> tick_h1;
    for (size_t i = 0; i < ticks.size(); ) {
        uint32_t h_ts = (ticks[i].ts_sec / 3600U) * 3600U;
        float op = ticks[i].bid;
        float cl = ticks[i].bid;
        size_t j = i + 1;
        while (j < ticks.size() && (ticks[j].ts_sec / 3600U) * 3600U == h_ts) {
            cl = ticks[j].bid;
            j++;
        }
        tick_h1[h_ts] = {op, cl};
        i = j;
    }
    std::ifstream qf("data/cache/v3_quant_HTF.bin", std::ios::binary);
    if (!qf) { std::cerr << "Cannot open v3_quant_HTF.bin\n"; return 1; }
    V3QuantHeader qhdr{};
    qf.read(reinterpret_cast<char*>(&qhdr), sizeof(qhdr));
    qf.seekg(qhdr.index_offset);
    std::vector<V3SliceEntry> slices(qhdr.num_slices);
    qf.read(reinterpret_cast<char*>(slices.data()), qhdr.num_slices * sizeof(V3SliceEntry));
    uint64_t N = qhdr.total_rows;
    uint64_t base_sym  = sizeof(V3QuantHeader);
    uint64_t base_time = base_sym + N;
    uint64_t base_q    = base_time + N * 4ULL;
    uint64_t base_flg  = base_q + NUM_QFEATS * N;
    uint64_t base_tup  = base_flg + NUM_FLAGS * N;
    uint64_t base_trr  = base_tup + N;
    // 1. Находим точный SymbolID и часовой сдвиг (проверяем сдвиги от -4 до +4 часов)
    int eurusd_id = 0;
    int best_shift_sec = -7200;
    double best_match = 0.0;
    for (const auto& s : slices) {
        if (std::string(s.timeframe) != "H1") continue;
        uint64_t st = s.start_row;
        uint32_t M  = s.num_rows;
        std::vector<uint8_t> sym(M), tup(M);
        std::vector<uint32_t> ts(M);
        qf.seekg(base_sym + st);      qf.read(reinterpret_cast<char*>(sym.data()), M);
        qf.seekg(base_time + st * 4); qf.read(reinterpret_cast<char*>(ts.data()), M * 4);
        qf.seekg(base_tup + st);      qf.read(reinterpret_cast<char*>(tup.data()), M);
        for (int shift_h = -4; shift_h <= 4; ++shift_h) {
            int shift_s = shift_h * 3600;
            std::vector<int> m_cnt(256, 0), t_cnt(256, 0);
            for (uint32_t i = 0; i < M; ++i) {
                uint32_t utc_h = static_cast<uint32_t>(static_cast<int64_t>(ts[i]) + 3600 + shift_s);
                auto it = tick_h1.find(utc_h);
                if (it != tick_h1.end() && it->second.close != it->second.open) {
                    uint8_t real_up = (it->second.close > it->second.open) ? 1 : 0;
                    t_cnt[sym[i]]++;
                    if (real_up == tup[i]) m_cnt[sym[i]]++;
                }
            }
            for (int id = 0; id < 256; ++id) {
                if (t_cnt[id] > 300) {
                    double pct = 100.0 * m_cnt[id] / t_cnt[id];
                    if (pct > best_match) {
                        best_match = pct;
                        eurusd_id = id;
                        best_shift_sec = shift_s;
                    }
                }
            }
        }
        break;
    }
    uint8_t bin_ema5_8_zero = 0;
    for (int b = 0; b < 256; ++b) {
        if (qhdr.bin_edges[3][b] >= 0.0f) { bin_ema5_8_zero = (uint8_t)b; break; }
    }
    // 2. Один проход Walk-Forward (9м Train -> 3м OOS) для генерации всех OOS-сигналов EURUSD
    const uint32_t SEC_9M = 274U * 86400U;
    const uint32_t SEC_3M = 91U * 86400U;
    const int trend_modes[3] = {1, -1, 0};
    std::vector<Signal> all_wf_signals;
    for (const auto& s : slices) {
        std::string tf_name(s.timeframe);
        if (tf_name != "H4" && tf_name != "H1") continue;
        int tf_h = (tf_name == "H4") ? 4 : 1;
        uint64_t st = s.start_row;
        uint32_t M  = s.num_rows;
        std::vector<uint8_t> sym(M), trr(M);
        std::vector<uint32_t> ts(M);
        std::vector<std::vector<uint8_t>> q(NUM_QFEATS, std::vector<uint8_t>(M));
        std::vector<int8_t> triple(M);
        qf.seekg(base_sym + st);      qf.read(reinterpret_cast<char*>(sym.data()), M);
        qf.seekg(base_time + st * 4); qf.read(reinterpret_cast<char*>(ts.data()), M * 4);
        for (int f = 0; f < NUM_QFEATS; ++f) {
            qf.seekg(base_q + f * N + st);
            qf.read(reinterpret_cast<char*>(q[f].data()), M);
        }
        qf.seekg(base_flg + 8ULL * N + st); qf.read(reinterpret_cast<char*>(triple.data()), M);
        qf.seekg(base_trr + st);            qf.read(reinterpret_cast<char*>(trr.data()), M);
        std::vector<uint32_t> eu_idx;
        for (uint32_t i = 0; i < M; ++i) if (sym[i] == eurusd_id) eu_idx.push_back(i);
        if (eu_idx.empty()) continue;
        uint32_t oos_start = 1577836800U;
        uint32_t max_ts = ts[eu_idx.back()];
        while (oos_start + 15 * 86400U < max_ts) {
            uint32_t train_start = oos_start - SEC_9M;
            uint32_t oos_end     = std::min(max_ts, oos_start + SEC_3M);
            std::vector<uint32_t> tr_i, oos_i;
            for (uint32_t idx : eu_idx) {
                if (ts[idx] >= train_start && ts[idx] < oos_start) tr_i.push_back(idx);
                else if (ts[idx] >= oos_start && ts[idx] < oos_end) oos_i.push_back(idx);
            }
            if (tr_i.size() >= 100 && !oos_i.empty()) {
                std::vector<Rule> cand;
                #pragma omp parallel
                {
                    std::vector<Rule> loc;
                    for (int tm : trend_modes) {
                        for (int f1 = 0; f1 < NUM_QFEATS; ++f1) {
                            if (!is_scale_invariant(f1)) continue;
                            #pragma omp for schedule(dynamic, 1) nowait
                            for (int f2 = f1 + 1; f2 < NUM_QFEATS; ++f2) {
                                if (!is_scale_invariant(f2)) continue;
                                for (int b1 = 48; b1 <= 208; b1 += 40) {
                                    for (int b2 = 48; b2 <= 208; b2 += 40) {
                                        for (int gt1 = 0; gt1 <= 1; ++gt1) {
                                            for (int gt2 = 0; gt2 <= 1; ++gt2) {
                                                int nb = 0, bw = 0, ns = 0, sw = 0;
                                                for (uint32_t idx : tr_i) {
                                                    if (tm != 0 && triple[idx] != tm) continue;
                                                    bool c1 = gt1 ? (q[f1][idx] >= b1) : (q[f1][idx] <= b1);
                                                    if (!c1) continue;
                                                    bool c2 = gt2 ? (q[f2][idx] >= b2) : (q[f2][idx] <= b2);
                                                    if (!c2) continue;
                                                    if (q[3][idx] >= bin_ema5_8_zero) {
                                                        nb++; if (trr[idx] == 1) bw++;
                                                    } else {
                                                        ns++; if (trr[idx] == 1) sw++;
                                                    }
                                                }
                                                int min_tr = (tf_h == 4) ? 10 : 25;
                                                if (nb >= min_tr) {
                                                    double b_wr = (double)bw / nb;
                                                    double b_pf = (b_wr * 1.28) / std::max(0.01, 1.0 - b_wr);
                                                    if (b_pf >= 1.25) {
                                                        loc.push_back({1, tm, f1, f2, (uint8_t)b1, (uint8_t)b2, (bool)gt1, (bool)gt2,
                                                                       (b_pf - 1.0) * std::sqrt((double)nb)});
                                                    }
                                                }
                                                if (ns >= min_tr) {
                                                    double s_wr = (double)sw / ns;
                                                    double s_pf = (s_wr * 1.28) / std::max(0.01, 1.0 - s_wr);
                                                    if (s_pf >= 1.25) {
                                                        loc.push_back({-1, tm, f1, f2, (uint8_t)b1, (uint8_t)b2, (bool)gt1, (bool)gt2,
                                                                       (s_pf - 1.0) * std::sqrt((double)ns)});
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    #pragma omp critical
                    cand.insert(cand.end(), loc.begin(), loc.end());
                }
                std::sort(cand.begin(), cand.end(), [](const Rule& a, const Rule& b) { return a.score > b.score; });
                std::vector<Rule> best_r;
                for (const auto& r : cand) {
                    bool dup = false;
                    for (const auto& b : best_r) {
                        if (b.dir == r.dir && (b.f1 == r.f1 || b.f2 == r.f2)) { dup = true; break; }
                    }
                    if (!dup) best_r.push_back(r);
                    if (best_r.size() >= 3) break;
                }
                for (uint32_t idx : oos_i) {
                    int eta_dir = (q[3][idx] >= bin_ema5_8_zero) ? 1 : -1;
                    int sig = 0;
                    for (const auto& r : best_r) {
                        if (r.dir != eta_dir) continue;
                        if (r.trend_mode != 0 && triple[idx] != r.trend_mode) continue;
                        bool c1 = r.gt1 ? (q[r.f1][idx] >= r.b1) : (q[r.f1][idx] <= r.b1);
                        if (!c1) continue;
                        bool c2 = r.gt2 ? (q[r.f2][idx] >= r.b2) : (q[r.f2][idx] <= r.b2);
                        if (!c2) continue;
                        sig = r.dir;
                        break;
                    }
                    if (sig != 0) {
                        uint32_t close_utc = static_cast<uint32_t>(static_cast<int64_t>(ts[idx]) + tf_h * 3600 + best_shift_sec);
                        float atr = qhdr.bin_edges[17][q[17][idx]];
                        all_wf_signals.push_back({close_utc, tf_h, sig, atr});
                    }
                }
            }
            oos_start += SEC_3M;
        }
    }
    std::sort(all_wf_signals.begin(), all_wf_signals.end(), [](const Signal& a, const Signal& b) {
        if (a.bar_close_utc != b.bar_close_utc) return a.bar_close_utc < b.bar_close_utc;
        return a.tf_hours > b.tf_hours;
    });
    // 3. Сверхбыстрый прогон сетки параметров (SL 1.0..2.2 x TP 1.4..3.0 x режимы ТФ) на 41.7 млн тиков
    struct Task { int tf_filter; std::string name; double sl; double tp; };
    std::vector<Task> tasks;
    for (int tf_f : {4, 1, 0}) {
        std::string tname = (tf_f == 4) ? "H4" : ((tf_f == 1) ? "H1" : "H4+H1");
        for (int sl_i = 10; sl_i <= 22; ++sl_i) {
            for (int tp_i = 14; tp_i <= 30; ++tp_i) {
                double sl = sl_i / 10.0;
                double tp = tp_i / 10.0;
                if (tp >= sl + 0.2) tasks.push_back({tf_f, tname, sl, tp});
            }
        }
    }
    std::vector<OptResult> results(tasks.size());
    const int max_spread = 25;
    #pragma omp parallel for schedule(dynamic, 1)
    for (int k = 0; k < (int)tasks.size(); ++k) {
        int tf_f = tasks[k].tf_filter;
        double sl_mult = tasks[k].sl;
        double tp_mult = tasks[k].tp;
        double balance = 1000.0, peak = 1000.0, max_dd = 0.0;
        int trades = 0, wins = 0;
        double gp = 0.0, gl = 0.0;
        uint32_t busy_until = 0;
        std::deque<double> hist;
        for (const auto& sig : all_wf_signals) {
            if (tf_f != 0 && sig.tf_hours != tf_f) continue;
            if (sig.bar_close_utc < busy_until) continue;
            int brk_hour = get_broker_hour(sig.bar_close_utc);
            if (brk_hour == 23 || brk_hour == 0 || brk_hour == 1) continue;
            auto it = std::lower_bound(ticks.begin(), ticks.end(), sig.bar_close_utc,
                [](const TickRecord& tr, uint32_t t) { return tr.ts_sec < t; });
            if (it == ticks.end() || it->ts_sec - sig.bar_close_utc > 1800) continue;
            if (it->spread_pts > max_spread) continue;
            double spread_price = it->spread_pts * 1e-5;
            double sl_dist = std::max(0.0005, (double)sig.atr14 * sl_mult);
            double tp_dist = std::max(0.0007, (double)sig.atr14 * tp_mult);
            uint32_t max_hold_sec = (uint32_t)(sig.tf_hours * 50U * 3600U);
            double entry_price = (sig.dir == 1) ? (it->bid + spread_price) : it->bid;
            double sl_price    = (sig.dir == 1) ? (entry_price - sl_dist) : (entry_price + sl_dist);
            double tp_price    = (sig.dir == 1) ? (entry_price + tp_dist) : (entry_price - tp_dist);
            double exit_price = entry_price;
            uint32_t close_ts = it->ts_sec;
            bool closed = false;
            for (auto cur = it + 1; cur != ticks.end(); ++cur) {
                double cur_sp = cur->spread_pts * 1e-5;
                if (cur->ts_sec - it->ts_sec >= max_hold_sec) {
                    exit_price = (sig.dir == 1) ? cur->bid : (cur->bid + cur_sp);
                    close_ts = cur->ts_sec;
                    closed = true;
                    break;
                }
                if (sig.dir == 1) {
                    if (cur->bid <= sl_price) { exit_price = sl_price; close_ts = cur->ts_sec; closed = true; break; }
                    if (cur->bid >= tp_price) { exit_price = tp_price; close_ts = cur->ts_sec; closed = true; break; }
                } else {
                    double ask = cur->bid + cur_sp;
                    if (ask >= sl_price) { exit_price = sl_price; close_ts = cur->ts_sec; closed = true; break; }
                    if (ask <= tp_price) { exit_price = tp_price; close_ts = cur->ts_sec; closed = true; break; }
                }
            }
            if (!closed) continue;
            busy_until = close_ts;
            double r_mult = (sig.dir == 1)
                ? ((exit_price - entry_price) / sl_dist)
                : ((entry_price - exit_price) / sl_dist);
            double risk_pct = 0.01;
            if (hist.size() >= 8) {
                double gp_h = 0.0, gl_h = 0.0;
                for (double v : hist) { if (v > 0) gp_h += v; else gl_h += std::abs(v); }
                if (gl_h > 0.0 && (gp_h / gl_h) < 1.0) risk_pct = 0.0025;
            }
            hist.push_back(r_mult);
            if (hist.size() > 12) hist.pop_front();
            double pnl = (balance * risk_pct) * r_mult;
            balance += pnl;
            trades++;
            if (pnl > 0) { wins++; gp += pnl; }
            else         { gl += std::abs(pnl); }
            if (balance > peak) peak = balance;
            double dd = (peak - balance) / peak * 100.0;
            if (dd > max_dd) max_dd = dd;
        }
        double pf = (gl > 0.0) ? (gp / gl) : 0.0;
        double wr = (trades > 0) ? (100.0 * wins / trades) : 0.0;
        double fit = (trades >= 30) ? (pf * std::sqrt((double)trades) / std::max(5.0, max_dd)) : -1.0;
        results[k] = {tasks[k].name, sl_mult, tp_mult, trades, wr, pf, balance, max_dd, fit};
    }
    std::sort(results.begin(), results.end(), [](const OptResult& a, const OptResult& b) {
        return a.fitness > b.fitness;
    });
    std::ofstream out("rules/tick_opt_results.txt");
    auto print_both = [&](const std::string& line) {
        std::cout << line << "\n";
        out << line << "\n";
    };
    print_both("==========================================================================================");
    print_both("  GITHUB CLOUD OPTIMIZATION: 41.7 МЛН ТИКОВ DUKASCOPY EURUSD (ЗАПРЕТ РОЛЛОВЕРА 23:00-02:00)");
    print_both("  EURUSD SymbolID=" + std::to_string(eurusd_id) + " | Shift=" + std::to_string(best_shift_sec/3600)
               + "h | Совпадение свечей: " + std::to_string(best_match).substr(0,5) + "%");
    print_both("==========================================================================================");
    print_both("   TF   | SL_ATR | TP_ATR || Trades | WinRate |   PF   |  Balance ($)  |  MaxDD (%)");
    print_both("--------+--------+--------++--------+---------+--------+---------------+------------");
    for (const auto& r : results) {
        char buf[160];
        std::snprintf(buf, sizeof(buf),
            "  %-5s |  %4.1f  |  %4.1f  ||  %4d  |  %5.1f%% |  %5.2f |  $%10.2f  |   %6.2f%%",
            r.tf_mode.c_str(), r.sl_mult, r.tp_mult, r.trades, r.wr, r.pf, r.balance, r.max_dd);
        print_both(buf);
    }
    auto t1 = std::chrono::high_resolution_clock::now();
    print_both("==========================================================================================");
    print_both("Время расчёта (" + std::to_string(tasks.size()) + " комбинаций) на сервере: "
               + std::to_string(std::chrono::duration<double>(t1 - t0).count()).substr(0,5) + " сек.");
    return 0;
}
