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
// Индексы признаков в v3_quant_HTF.bin:
// 0:L_c_Norm, 1:L_prev_Norm, 2:Ratio_L, 3:Ema5_8_Diff_Norm, 4:Ema8_21_Diff_Norm,
// 5:MACD_Hist_Norm, 6:MACD_Delta_Norm, 7:Stoch_K, 8:Stoch_D, 9:RSI5, 10:RSI8,
// 11:CCI5, 12:CCI8, 13:VolRatio, 14:OBV_Slope_Norm, 15:FigureID, 16:PenaltyScore,
// 17:ATR14, 18:ATR_Ratio, 19:HTF_EMA21_Slope_Norm, 20:Price_vs_HTF_EMA21_Norm,
// 21:Impulse_Age, 22:Wick_Reject_Ratio
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
struct Signal {
    uint32_t bar_close_utc;
    int sym_id;
    int dir;
    float atr14;
    uint8_t hit_trr;
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
inline float val_of(const V3QuantHeader& qhdr, int feat, uint8_t bin) {
    return qhdr.bin_edges[feat][bin];
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
    uint64_t st_h4 = 0; uint32_t M_h4 = 0;
    for (const auto& s : slices) {
        if (std::string(s.timeframe) == "H4") { st_h4 = s.start_row; M_h4 = s.num_rows; break; }
    }
    std::vector<uint8_t> sym(M_h4), trr(M_h4);
    std::vector<uint32_t> ts(M_h4);
    std::vector<std::vector<uint8_t>> q(NUM_QFEATS, std::vector<uint8_t>(M_h4));
    std::vector<std::vector<int8_t>> flg(NUM_FLAGS, std::vector<int8_t>(M_h4));
    qf.seekg(base_sym + st_h4);      qf.read((char*)sym.data(), M_h4);
    qf.seekg(base_time + st_h4 * 4); qf.read((char*)ts.data(), M_h4 * 4);
    for (int f = 0; f < NUM_QFEATS; ++f) {
        qf.seekg(base_q + f * N + st_h4);
        qf.read((char*)q[f].data(), M_h4);
    }
    for (int g = 0; g < NUM_FLAGS; ++g) {
        qf.seekg(base_flg + g * N + st_h4);
        qf.read((char*)flg[g].data(), M_h4);
    }
    qf.seekg(base_trr + st_h4); qf.read((char*)trr.data(), M_h4);
    auto to_h4_close_utc = [&](uint32_t bar_ts) -> uint32_t {
        uint32_t close_brk = bar_ts + 4 * 3600U;
        return close_brk - get_broker_offset_sec(close_brk - 7200U);
    };
    std::ofstream out("rules/tick_opt_results.txt");
    auto log = [&](const std::string& line) {
        std::cout << line << "\n";
        out << line << "\n";
    };
    log("==========================================================================================");
    log("  ПРОВЕРКА СТРУКТУРНЫХ ПРАВИЛ БЕЛЯЕВА V3 (БЕЗ ПЕРЕОБУЧЕНИЯ И ПОДГОНКИ ПОРОГОВ)");
    log("  Фильтры: PenaltyScore <= 1.0 | Свежий импульс Impulse_Age <= 5 | FigureID > 0");
    log("==========================================================================================");
    // 1. Сначала проверим каждый FigureID Беляева по всем 6 парам (на H4, SL=1.5 ATR, TP=2.0 ATR)
    struct FigStat { int tr = 0, w = 0; };
    std::map<int, FigStat> fig_stats;
    for (uint32_t i = 0; i < M_h4; ++i) {
        if (ts[i] < 1577836800U) continue; // 2020-2026 OOS период
        float fig = val_of(qhdr, 15, q[15][i]);
        float pen = val_of(qhdr, 16, q[16][i]);
        float age = val_of(qhdr, 21, q[21][i]);
        int fig_id = (int)std::round(fig);
        if (fig_id == 0) continue;
        if (pen <= 1.0f && age <= 5.0f) {
            fig_stats[fig_id].tr++;
            if (trr[i] == 1) fig_stats[fig_id].w++;
        }
    }
    log("\n--- 1. СТАТИСТИКА ПО ФИГУРАМ БЕЛЯЕВА (FigureID, 2020-2026, 6 ПАР H4) ---");
    for (auto& kv : fig_stats) {
        double wr = kv.second.tr > 0 ? (100.0 * kv.second.w / kv.second.tr) : 0.0;
        double pf = (wr / 100.0 * 1.25) / std::max(0.01, (1.0 - wr / 100.0) * 1.08);
        char buf[140];
        std::snprintf(buf, sizeof(buf), "  FigureID=%3d | Сделок=%4d | WinRate=%5.1f%% | Ожид. PF (с учётом спреда)=%4.2f",
                      kv.first, kv.second.tr, wr, pf);
        log(buf);
    }
    // 2. Тестируем 3 чистых, фиксированных (непереобучаемых) режима Беляева на EURUSD (41.7 млн тиков) и на 6 парах
    struct StrategyDef {
        std::string name;
        int mode;
    };
    std::vector<StrategyDef> modes = {
        {"Модель A: Фигуры Беляева (Penalty<=1, Age<=4, L_c>=0.35)", 1},
        {"Модель B: Импульс по тренду (Triple=+-1, MACD_Delta>0, Age<=3)", 2},
        {"Модель C: Отбой от HTF_EMA21 с длинным хвостом (Wick>=0.45, Penalty<=1)", 3}
    };
    for (const auto& m : modes) {
        std::vector<Signal> sigs;
        for (uint32_t i = 0; i < M_h4; ++i) {
            if (ts[i] < 1577836800U) continue;
            float lc      = val_of(qhdr, 0,  q[0][i]);
            float ema5_8  = val_of(qhdr, 3,  q[3][i]);
            float macd_d  = val_of(qhdr, 6,  q[6][i]);
            float fig     = val_of(qhdr, 15, q[15][i]);
            float pen     = val_of(qhdr, 16, q[16][i]);
            float p_htf   = val_of(qhdr, 20, q[20][i]);
            float age     = val_of(qhdr, 21, q[21][i]);
            float wick    = val_of(qhdr, 22, q[22][i]);
            int triple    = flg[8][i];
            int dir = (ema5_8 >= 0.0f) ? 1 : -1;
            bool ok = false;
            if (m.mode == 1) {
                ok = ((int)std::round(fig) != 0 && pen <= 1.0f && age <= 4.0f && lc >= 0.35f);
            } else if (m.mode == 2) {
                ok = (triple == dir && pen <= 1.5f && age <= 3.0f &&
                      ((dir == 1 && macd_d > 0.0f) || (dir == -1 && macd_d < 0.0f)));
            } else if (m.mode == 3) {
                ok = (pen <= 1.0f && wick >= 0.45f && age <= 5.0f &&
                      ((dir == 1 && p_htf <= 0.15f) || (dir == -1 && p_htf >= -0.15f)));
            }
            if (ok) {
                sigs.push_back({to_h4_close_utc(ts[i]), sym[i], dir, mid_atr(qhdr, q[17][i]), trr[i]});
            }
        }
        std::sort(sigs.begin(), sigs.end(), [](const Signal& a, const Signal& b) {
            return a.bar_close_utc < b.bar_close_utc;
        });
        log("\n==========================================================================================");
        log("  " + m.name);
        log("==========================================================================================");
        // Прогон на 41.7 млн тиков EURUSD (SL=2.0 ATR, TP=2.6 ATR)
        {
            double bal = 1000.0, peak = 1000.0, max_dd = 0.0, gp = 0.0, gl = 0.0;
            int tr = 0, w = 0;
            uint32_t busy = 0;
            std::map<int, std::pair<int, double>> by_year;
            for (const auto& s : sigs) {
                if (s.sym_id != 1) continue;
                if (s.bar_close_utc < busy) continue;
                int bh = get_broker_hour(s.bar_close_utc);
                if (bh == 23 || bh == 0 || bh == 1) continue;
                auto it = std::lower_bound(ticks.begin(), ticks.end(), s.bar_close_utc,
                    [](const TickRecord& trk, uint32_t t) { return trk.ts_sec < t; });
                if (it == ticks.end() || it->ts_sec - s.bar_close_utc > 60) continue;
                if (it->spread_pts > 25) continue;
                double sp = it->spread_pts * 1e-5;
                double sl_d = std::max(0.0005, (double)s.atr14 * 2.0);
                double tp_d = std::max(0.0007, (double)s.atr14 * 2.6);
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
                double pnl = (bal * 0.01) * r_mult;
                bal += pnl; tr++;
                if (pnl > 0) { w++; gp += pnl; } else { gl += std::abs(pnl); }
                if (bal > peak) peak = bal;
                double dd = (peak - bal) / peak * 100.0;
                if (dd > max_dd) max_dd = dd;
                int yr = parse_utc(it->ts_sec).year;
                by_year[yr].first++;
                by_year[yr].second = bal;
            }
            char b1[180];
            std::snprintf(b1, sizeof(b1),
                "[EURUSD ТИКИ H4 | SL=2.0 | TP=2.6] Сделок=%3d | WR=%5.1f%% | PF=%4.2f | Баланс=$%8.2f | MaxDD=%5.2f%%",
                tr, tr > 0 ? (100.0 * w / tr) : 0.0, gl > 0 ? (gp / gl) : 0.0, bal, max_dd);
            log(b1);
            for (auto& kv : by_year) {
                char yb[120];
                std::snprintf(yb, sizeof(yb), "    EURUSD %d г.: Сделок=%2d | Баланс=$%8.2f", kv.first, kv.second.first, kv.second.second);
                log(yb);
            }
        }
        // Прогон на всех 6 парах (H4, SL=1.5, TP=2.0)
        {
            double bal = 1000.0, peak = 1000.0, max_dd = 0.0, gp = 0.0, gl = 0.0;
            int tr = 0, w = 0;
            std::map<int, uint32_t> sym_busy;
            std::map<int, std::pair<int, double>> by_year;
            for (const auto& s : sigs) {
                int bh = get_broker_hour(s.bar_close_utc);
                if (bh == 23 || bh == 0 || bh == 1) continue;
                if (s.bar_close_utc < sym_busy[s.sym_id]) continue;
                sym_busy[s.sym_id] = s.bar_close_utc + 16 * 3600U;
                double r_mult = (s.hit_trr == 1) ? 1.25 : -1.08;
                double pnl = (bal * 0.005) * r_mult;
                bal += pnl; tr++;
                if (pnl > 0) { w++; gp += pnl; } else { gl += std::abs(pnl); }
                if (bal > peak) peak = bal;
                double dd = (peak - bal) / peak * 100.0;
                if (dd > max_dd) max_dd = dd;
                int yr = parse_utc(s.bar_close_utc).year;
                by_year[yr].first++;
                by_year[yr].second = bal;
            }
            char b2[180];
            std::snprintf(b2, sizeof(b2),
                "[ПОРТФЕЛЬ 6 ПАР H4 | SL=1.5 | TP=2.0] Сделок=%4d | WR=%5.1f%% | PF=%4.2f | Баланс=$%8.2f | MaxDD=%5.2f%%",
                tr, tr > 0 ? (100.0 * w / tr) : 0.0, gl > 0 ? (gp / gl) : 0.0, bal, max_dd);
            log(b2);
            for (auto& kv : by_year) {
                char yb[120];
                std::snprintf(yb, sizeof(yb), "    6 Пар %d г.: Сделок=%3d | Баланс=$%8.2f", kv.first, kv.second.first, kv.second.second);
                log(yb);
            }
        }
    }
    auto t1 = std::chrono::high_resolution_clock::now();
    log("\nВремя расчёта в облаке: " + std::to_string(std::chrono::duration<double>(t1 - t0).count()).substr(0, 5) + " сек.");
    return 0;
}
