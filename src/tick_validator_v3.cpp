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
#include <map>
#include <omp.h>
static const int NUM_QFEATS = 23;
static const int NUM_FLAGS  = 9;
static const char* FEAT_NAMES[NUM_QFEATS] = {
    "L_c_Norm", "L_prev_Norm", "Ratio_L", "Ema5_8_Diff_Norm", "Ema8_21_Diff_Norm",
    "MACD_Hist_Norm", "MACD_Delta_Norm", "Stoch_K", "Stoch_D", "RSI5", "RSI8",
    "CCI5", "CCI8", "VolRatio", "OBV_Slope_Norm", "FigureID", "PenaltyScore",
    "ATR14", "ATR_Ratio", "HTF_EMA21_Slope_Norm", "Price_vs_HTF_EMA21_Norm",
    "Impulse_Age", "Wick_Reject_Ratio"
};
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
    int train_n;
    double train_wr;
};
struct Signal {
    uint32_t bar_close_utc;
    int sym_id;
    int dir;
    float atr14;
};
struct UtcParts {
    int year, month, day, hour, wday;
};
UtcParts parse_utc(uint32_t ts) {
    uint32_t days = ts / 86400U;
    uint32_t rem  = ts % 86400U;
    int hour = (int)(rem / 3600U);
    int wday = (int)((days + 4U) % 7U);
    int64_t z = (int64_t)days + 719468;
    int64_t era = (z >= 0 ? z : z - 146096) / 146097;
    uint32_t doe = (uint32_t)(z - era * 146097);
    uint32_t yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    int64_t y = (int64_t)yoe + era * 400;
    uint32_t doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    uint32_t mp = (5 * doy + 2) / 153;
    int day = (int)(doy - (153 * mp + 2) / 5 + 1);
    int month = (int)(mp < 10 ? mp + 3 : mp - 9);
    int year = (int)(y + (month <= 2 ? 1 : 0));
    return {year, month, day, hour, wday};
}
int get_broker_offset_sec(uint32_t utc_ts) {
    UtcParts g = parse_utc(utc_ts);
    if (g.month > 3 && g.month < 10) return 10800;
    if (g.month == 3) {
        int last_sun = 31 - ((g.wday + 31 - g.day) % 7);
        if (g.day > last_sun || (g.day == last_sun && g.hour >= 1)) return 10800;
    }
    if (g.month == 10) {
        int last_sun = 31 - ((g.wday + 31 - g.day) % 7);
        if (g.day < last_sun || (g.day == last_sun && g.hour < 1)) return 10800;
    }
    return 7200;
}
int get_broker_hour(uint32_t utc_ts) {
    int off_h = get_broker_offset_sec(utc_ts) / 3600;
    UtcParts g = parse_utc(utc_ts);
    return (g.hour + off_h) % 24;
}
uint32_t trading_elapsed_sec(uint32_t start_ts, uint32_t cur_ts) {
    if (cur_ts <= start_ts) return 0;
    uint32_t raw = cur_ts - start_ts;
    const uint32_t SAT_EPOCH = 172800U;
    const uint32_t WEEK_SEC  = 604800U;
    const uint32_t WKND_SEC  = 172800U;
    if (start_ts < SAT_EPOCH) return raw;
    uint32_t w_start = (start_ts - SAT_EPOCH) / WEEK_SEC;
    uint32_t w_cur   = (cur_ts   - SAT_EPOCH) / WEEK_SEC;
    uint32_t weekends = (w_cur > w_start) ? (w_cur - w_start) : 0;
    uint32_t sub = weekends * WKND_SEC;
    return (raw > sub) ? (raw - sub) : 0;
}
inline float mid_atr(const V3QuantHeader& qhdr, uint8_t bin) {
    if (bin >= 255) return qhdr.bin_edges[17][255];
    return 0.5f * (qhdr.bin_edges[17][bin] + qhdr.bin_edges[17][bin + 1]);
}
int main() {
    auto t0 = std::chrono::high_resolution_clock::now();
    std::ifstream tf("data/cache/EURUSD_ticks.bin", std::ios::binary);
    if (!tf) { std::cerr << "Cannot open EURUSD_ticks.bin\n"; return 1; }
    TickFileHeader thdr{};
    tf.read(reinterpret_cast<char*>(&thdr), sizeof(thdr));
    tf.seekg(sizeof(TickFileHeader) + thdr.num_days * sizeof(TickDayIndex));
    std::vector<TickRecord> ticks(thdr.total_ticks);
    tf.read(reinterpret_cast<char*>(ticks.data()), thdr.total_ticks * sizeof(TickRecord));
    tf.close();
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
    uint8_t bin_ema5_8_zero = 0;
    for (int b = 0; b < 256; ++b) {
        if (qhdr.bin_edges[3][b] >= 0.0f) { bin_ema5_8_zero = (uint8_t)b; break; }
    }
    uint64_t st_h4 = 0; uint32_t M_h4 = 0;
    for (const auto& s : slices) {
        if (std::string(s.timeframe) == "H4") { st_h4 = s.start_row; M_h4 = s.num_rows; break; }
    }
    std::vector<uint8_t> sym(M_h4), trr(M_h4);
    std::vector<uint32_t> ts(M_h4);
    std::vector<std::vector<uint8_t>> q(NUM_QFEATS, std::vector<uint8_t>(M_h4));
    std::vector<int8_t> triple(M_h4);
    qf.seekg(base_sym + st_h4);      qf.read((char*)sym.data(), M_h4);
    qf.seekg(base_time + st_h4 * 4); qf.read((char*)ts.data(), M_h4 * 4);
    for (int f = 0; f < NUM_QFEATS; ++f) {
        qf.seekg(base_q + f * N + st_h4);
        qf.read((char*)q[f].data(), M_h4);
    }
    qf.seekg(base_flg + 8ULL * N + st_h4); qf.read((char*)triple.data(), M_h4);
    qf.seekg(base_trr + st_h4);            qf.read((char*)trr.data(), M_h4);
    uint32_t max_ts = 0;
    for (uint32_t i = 0; i < M_h4; ++i) if (ts[i] > max_ts) max_ts = ts[i];
    const int eurusd_id = 1;
    auto to_h4_close_utc = [&](uint32_t bar_ts) -> uint32_t {
        uint32_t close_brk = bar_ts + 4 * 3600U;
        return close_brk - get_broker_offset_sec(close_brk - 7200U);
    };
    std::vector<std::string> sniper_rules_log;
    // Снайперский Walk-Forward отбор (strict_trend=true: BUY только при Triple==1, SELL только при Triple==-1)
    auto run_sniper_wf = [&](bool test_all_good_pairs, double min_pf, int top_k, bool save_log) {
        std::vector<Signal> sigs;
        std::vector<uint8_t> oos_trr;
        const uint32_t SEC_9M = 274U * 86400U;
        const uint32_t SEC_3M = 91U * 86400U;
        uint32_t oos_start = 1577836800U; // 2020-01-01
        while (oos_start + 15 * 86400U < max_ts) {
            uint32_t train_start = oos_start - SEC_9M;
            uint32_t oos_end     = std::min(max_ts, oos_start + SEC_3M);
            std::vector<uint32_t> tr_i, oos_i;
            for (uint32_t i = 0; i < M_h4; ++i) {
                // Исключаем слабые пары 5 и 6 из обучения и торговли
                if (sym[i] == 5 || sym[i] == 6) continue;
                if (ts[i] >= train_start && ts[i] < oos_start) {
                    tr_i.push_back(i);
                } else if (ts[i] >= oos_start && ts[i] < oos_end) {
                    if (test_all_good_pairs || sym[i] == eurusd_id) oos_i.push_back(i);
                }
            }
            if (tr_i.size() >= 100 && !oos_i.empty()) {
                std::vector<Rule> cand_b, cand_s;
                #pragma omp parallel
                {
                    std::vector<Rule> lb, ls;
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
                                                // Жёсткий фильтр тренда: BUY только по аптренду (1), SELL только по даунтренду (-1)
                                                if (triple[idx] == 0) continue;
                                                bool c1 = gt1 ? (q[f1][idx] >= b1) : (q[f1][idx] <= b1);
                                                if (!c1) continue;
                                                bool c2 = gt2 ? (q[f2][idx] >= b2) : (q[f2][idx] <= b2);
                                                if (!c2) continue;
                                                if (triple[idx] == 1 && q[3][idx] >= bin_ema5_8_zero) {
                                                    nb++; if (trr[idx] == 1) bw++;
                                                } else if (triple[idx] == -1 && q[3][idx] < bin_ema5_8_zero) {
                                                    ns++; if (trr[idx] == 1) sw++;
                                                }
                                            }
                                            if (nb >= 45) {
                                                double wr = (double)bw / nb;
                                                double pf = (wr * 1.28) / std::max(0.01, 1.0 - wr);
                                                if (pf >= min_pf) {
                                                    lb.push_back({1, 1, f1, f2, (uint8_t)b1, (uint8_t)b2, (bool)gt1, (bool)gt2,
                                                                  (pf - 1.0) * std::sqrt((double)nb), nb, wr * 100.0});
                                                }
                                            }
                                            if (ns >= 45) {
                                                double wr = (double)sw / ns;
                                                double pf = (wr * 1.28) / std::max(0.01, 1.0 - wr);
                                                if (pf >= min_pf) {
                                                    ls.push_back({-1, -1, f1, f2, (uint8_t)b1, (uint8_t)b2, (bool)gt1, (bool)gt2,
                                                                  (pf - 1.0) * std::sqrt((double)ns), ns, wr * 100.0});
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    #pragma omp critical
                    {
                        cand_b.insert(cand_b.end(), lb.begin(), lb.end());
                        cand_s.insert(cand_s.end(), ls.begin(), ls.end());
                    }
                }
                auto pick = [&](std::vector<Rule>& c) {
                    std::sort(c.begin(), c.end(), [](const Rule& a, const Rule& b) { return a.score > b.score; });
                    std::vector<Rule> r_out;
                    for (const auto& r : c) {
                        bool dup = false;
                        for (const auto& x : r_out) if (x.f1 == r.f1 || x.f2 == r.f2) { dup = true; break; }
                        if (!dup) r_out.push_back(r);
                        if ((int)r_out.size() >= top_k) break;
                    }
                    return r_out;
                };
                auto best = pick(cand_b);
                auto best_s = pick(cand_s);
                best.insert(best.end(), best_s.begin(), best_s.end());
                if (save_log && oos_start + SEC_3M >= max_ts) {
                    for (const auto& r : best) {
                        char rbuf[256];
                        std::snprintf(rbuf, sizeof(rbuf),
                            "  [H4 SNIPER] %s | Triple=%+d | %s %s %.4f AND %s %s %.4f (TrainN=%d, WR=%.1f%%)",
                            (r.dir == 1 ? "BUY " : "SELL"), r.trend_mode,
                            FEAT_NAMES[r.f1], (r.gt1 ? ">=" : "<="), qhdr.bin_edges[r.f1][r.b1],
                            FEAT_NAMES[r.f2], (r.gt2 ? ">=" : "<="), qhdr.bin_edges[r.f2][r.b2],
                            r.train_n, r.train_wr);
                        sniper_rules_log.push_back(rbuf);
                    }
                }
                for (uint32_t idx : oos_i) {
                    if (triple[idx] == 0) continue;
                    int eta_dir = (q[3][idx] >= bin_ema5_8_zero) ? 1 : -1;
                    int sig = 0;
                    for (const auto& r : best) {
                        if (r.dir != eta_dir || triple[idx] != r.trend_mode) continue;
                        bool c1 = r.gt1 ? (q[r.f1][idx] >= r.b1) : (q[r.f1][idx] <= r.b1);
                        if (!c1) continue;
                        bool c2 = r.gt2 ? (q[r.f2][idx] >= r.b2) : (q[r.f2][idx] <= r.b2);
                        if (!c2) continue;
                        sig = r.dir;
                        break;
                    }
                    if (sig != 0) {
                        sigs.push_back({to_h4_close_utc(ts[idx]), sym[idx], sig, mid_atr(qhdr, q[17][idx])});
                        oos_trr.push_back(trr[idx]);
                    }
                }
            }
            oos_start += SEC_3M;
        }
        return std::make_pair(sigs, oos_trr);
    };
    std::ofstream out("rules/tick_opt_results.txt");
    auto log = [&](const std::string& line) {
        std::cout << line << "\n";
        out << line << "\n";
    };
    log("==========================================================================================");
    log("  СНАЙПЕРСКАЯ ОПТИМИЗАЦИЯ V3 (СТРОГИЙ ТРЕНД TRIPLE=+-1, БЕЗ СЛАБЫХ ПАР 5 И 6)");
    log("==========================================================================================");
    // 1. Вариант 1: EURUSD H4 на 41.7 млн тиков Dukascopy
    auto [eu_sigs, eu_trr] = run_sniper_wf(false, 1.50, 1, true);
    std::sort(eu_sigs.begin(), eu_sigs.end(), [](const Signal& a, const Signal& b) { return a.bar_close_utc < b.bar_close_utc; });
    log("\n--- ВАРИАНТ 1: EURUSD H4 НА 41.7 МЛН ТИКОВ DUKASCOPY (КРИВАЯ БАЛАНСА ПО ГОДАМ) ---");
    for (auto [sl_m, tp_m] : std::vector<std::pair<double,double>>{{2.0, 2.6}, {2.2, 3.0}}) {
        double bal = 1000.0, peak = 1000.0, max_dd = 0.0, gp = 0.0, gl = 0.0;
        int tr = 0, w = 0;
        uint32_t busy = 0;
        std::map<int, std::pair<int, double>> by_year;
        for (const auto& s : eu_sigs) {
            if (s.bar_close_utc < busy) continue;
            int bh = get_broker_hour(s.bar_close_utc);
            if (bh == 23 || bh == 0 || bh == 1) continue;
            auto it = std::lower_bound(ticks.begin(), ticks.end(), s.bar_close_utc,
                [](const TickRecord& trk, uint32_t t) { return trk.ts_sec < t; });
            if (it == ticks.end() || it->ts_sec - s.bar_close_utc > 60) continue;
            if (it->spread_pts > 25) continue;
            double sp = it->spread_pts * 1e-5;
            double sl_d = std::max(0.0005, (double)s.atr14 * sl_m);
            double tp_d = std::max(0.0007, (double)s.atr14 * tp_m);
            double entry = (s.dir == 1) ? (it->bid + sp) : it->bid;
            double sl_p  = (s.dir == 1) ? (entry - sl_d) : (entry + sl_d);
            double tp_p  = (s.dir == 1) ? (entry + tp_d) : (entry - tp_d);
            double exit_p = entry;
            uint32_t close_t = it->ts_sec;
            bool closed = false;
            for (auto cur = it + 1; cur != ticks.end(); ++cur) {
                double csp = cur->spread_pts * 1e-5;
                if (trading_elapsed_sec(it->ts_sec, cur->ts_sec) >= 4U * 50U * 3600U) {
                    exit_p = (s.dir == 1) ? cur->bid : (cur->bid + csp);
                    close_t = cur->ts_sec; closed = true; break;
                }
                if (s.dir == 1) {
                    if (cur->bid <= sl_p) { exit_p = sl_p; close_t = cur->ts_sec; closed = true; break; }
                    if (cur->bid >= tp_p) { exit_p = tp_p; close_t = cur->ts_sec; closed = true; break; }
                } else {
                    double ask = cur->bid + csp;
                    if (ask >= sl_p) { exit_p = sl_p; close_t = cur->ts_sec; closed = true; break; }
                    if (ask <= tp_p) { exit_p = tp_p; close_t = cur->ts_sec; closed = true; break; }
                }
            }
            if (!closed) continue;
            busy = close_t;
            double r_mult = (s.dir == 1) ? ((exit_p - entry) / sl_d) : ((entry - exit_p) / sl_d);
            double pnl = (bal * 0.015) * r_mult; // 1.5% риск на снайперский сигнал
            bal += pnl; tr++;
            if (pnl > 0) { w++; gp += pnl; } else { gl += std::abs(pnl); }
            if (bal > peak) peak = bal;
            double dd = (peak - bal) / peak * 100.0;
            if (dd > max_dd) max_dd = dd;
            int yr = parse_utc(it->ts_sec).year;
            by_year[yr].first++;
            by_year[yr].second = bal;
        }
        char hdr_buf[180];
        std::snprintf(hdr_buf, sizeof(hdr_buf),
            "\n[EURUSD H4 SNIPER | SL=%.1f | TP=%.1f] Сделок=%d | WR=%.1f%% | PF=%.2f | Баланс=$%.2f | MaxDD=%.2f%%",
            sl_m, tp_m, tr, tr > 0 ? (100.0 * w / tr) : 0.0, gl > 0 ? (gp / gl) : 0.0, bal, max_dd);
        log(hdr_buf);
        for (auto& kv : by_year) {
            char ybuf[128];
            std::snprintf(ybuf, sizeof(ybuf), "  Конец %d г.: Сделок=%2d | Баланс=$%8.2f",
                          kv.first, kv.second.first, kv.second.second);
            log(ybuf);
        }
    }
    // 2. Вариант 2: Портфель из 4 лучших пар (SymbolID 1, 2, 3, 4) на H4
    log("\n--- ВАРИАНТ 2: ПОРТФЕЛЬ 4 ЛУЧШИХ ПАР (SymbolID 1..4, H4, СНАЙПЕРСКИЙ ТРЕНД) ---");
    auto [all_sigs, all_trr] = run_sniper_wf(true, 1.55, 1, false);
    std::vector<size_t> order(all_sigs.size());
    for (size_t i = 0; i < order.size(); ++i) order[i] = i;
    std::sort(order.begin(), order.end(), [&](size_t a, size_t b) {
        return all_sigs[a].bar_close_utc < all_sigs[b].bar_close_utc;
    });
    double p_bal = 1000.0, p_peak = 1000.0, p_dd = 0.0, p_gp = 0.0, p_gl = 0.0;
    int p_tr = 0, p_w = 0;
    std::map<int, uint32_t> sym_busy;
    std::map<int, std::pair<int, double>> p_by_year;
    std::map<int, std::pair<int, int>> p_by_sym;
    for (size_t idx : order) {
        const auto& s = all_sigs[idx];
        uint8_t hit_tp = all_trr[idx];
        int bh = get_broker_hour(s.bar_close_utc);
        if (bh == 23 || bh == 0 || bh == 1) continue;
        if (s.bar_close_utc < sym_busy[s.sym_id]) continue;
        sym_busy[s.sym_id] = s.bar_close_utc + 16 * 3600U;
        double r_mult = (hit_tp == 1) ? 1.25 : -1.08;
        double pnl = (p_bal * 0.01) * r_mult;
        p_bal += pnl; p_tr++;
        p_by_sym[s.sym_id].first++;
        if (pnl > 0) { p_w++; p_gp += pnl; p_by_sym[s.sym_id].second++; }
        else         { p_gl += std::abs(pnl); }
        if (p_bal > p_peak) p_peak = p_bal;
        double dd = (p_peak - p_bal) / p_peak * 100.0;
        if (dd > p_dd) p_dd = dd;
        int yr = parse_utc(s.bar_close_utc).year;
        p_by_year[yr].first++;
        p_by_year[yr].second = p_bal;
    }
    char pbuf[180];
    std::snprintf(pbuf, sizeof(pbuf),
        "\n[ПОРТФЕЛЬ 4 ПАР H4 SNIPER] Сделок=%d | WR=%.1f%% | PF=%.2f | Баланс ($1000 старт)=$%.2f | MaxDD=%.2f%%",
        p_tr, p_tr > 0 ? (100.0 * p_w / p_tr) : 0.0, p_gl > 0 ? (p_gp / p_gl) : 0.0, p_bal, p_dd);
    log(pbuf);
    log("\n--- Кривая баланса портфеля по годам (2020 - 2026) ---");
    for (auto& kv : p_by_year) {
        char ybuf[128];
        std::snprintf(ybuf, sizeof(ybuf), "  Конец %d г.: Сделок за год=%3d | Баланс=$%9.2f",
                      kv.first, kv.second.first, kv.second.second);
        log(ybuf);
    }
    log("\n--- Разбивка по 4 лучшим парам ---");
    for (auto& kv : p_by_sym) {
        char sbuf[128];
        std::snprintf(sbuf, sizeof(sbuf), "  SymbolID=%2d: Сделок=%3d | Побед=%3d | WinRate=%5.1f%%",
                      kv.first, kv.second.first, kv.second.second,
                      kv.second.first > 0 ? (100.0 * kv.second.second / kv.second.first) : 0.0);
        log(sbuf);
    }
    log("\n--- АКТУАЛЬНЫЕ СНАЙПЕРСКИЕ ПРАВИЛА ПОСЛЕДНЕГО КВАРТАЛА ---");
    for (const auto& rl : sniper_rules_log) log(rl);
    auto t1 = std::chrono::high_resolution_clock::now();
    log("\nВремя расчёта в облаке: " + std::to_string(std::chrono::duration<double>(t1 - t0).count()).substr(0, 5) + " сек.");
    return 0;
}
