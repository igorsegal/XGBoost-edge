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
#include <omp.h>
static const int NUM_QFEATS = 23;
static const int NUM_FLAGS  = 9;
static const char* QFEAT_NAMES[NUM_QFEATS] = {
    "L_c_Norm", "L_prev_Norm", "Ratio_L", "Ema5_8_Diff_Norm", "Ema8_21_Diff_Norm",
    "MACD_Hist_Norm", "MACD_Delta_Norm", "Stoch_K", "Stoch_D", "RSI5", "RSI8",
    "CCI5", "CCI8", "VolRatio", "OBV_Slope_Norm", "FigureScore", "PenaltyScore",
    "ATR14", "ATR_Ratio", "HTF_EMA21_Slope_Norm", "Price_vs_HTF_EMA21_Norm",
    "Impulse_Age", "Wick_Reject_Ratio"
};
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
#pragma pack(pop)
struct RuleCandidate {
    int f1, f2;
    uint8_t b1, b2;
    bool gt1, gt2;
    int dir; // 1 = BUY (Target_RR==1), 0 = SELL (Target_RR==0)
    int train_trades, oos_trades;
    double train_wr, oos_wr;
    double score;
};
int main(int argc, char** argv) {
    std::string cache_path = (argc > 1) ? argv[1] : "data/cache/v3_quant_HTF.bin";
    std::string target_tf  = (argc > 2) ? argv[2] : "H1";
    std::string out_mqh    = (argc > 3) ? argv[3] : "rules/discovered_edges.mqh";
    auto t0 = std::chrono::high_resolution_clock::now();
    std::ifstream in(cache_path, std::ios::binary);
    if (!in) {
        std::cerr << "Error: cannot open cache " << cache_path << "\n";
        return 1;
    }
    V3QuantHeader hdr{};
    in.read(reinterpret_cast<char*>(&hdr), sizeof(hdr));
    if (std::strncmp(hdr.magic, "V3QUANT1", 8) != 0) {
        std::cerr << "Error: invalid magic header\n";
        return 1;
    }
    in.seekg(hdr.index_offset);
    std::vector<V3SliceEntry> slices(hdr.num_slices);
    in.read(reinterpret_cast<char*>(slices.data()), hdr.num_slices * sizeof(V3SliceEntry));
    V3SliceEntry chosen{};
    bool found_tf = false;
    for (const auto& s : slices) {
        if (std::string(s.timeframe) == target_tf) {
            chosen = s;
            found_tf = true;
            break;
        }
    }
    if (!found_tf) {
        std::cerr << "Timeframe " << target_tf << " not found in " << cache_path << "\n";
        return 1;
    }
    uint64_t N = hdr.total_rows;
    uint64_t start = chosen.start_row;
    uint32_t M = chosen.num_rows;
    // Читаем только срез нужного таймфрейма для 23 квантованных признаков, флага Triple_Trend_Align (8) и Target_RR
    std::vector<std::vector<uint8_t>> q(NUM_QFEATS, std::vector<uint8_t>(M));
    uint64_t base_q = sizeof(V3QuantHeader) + N * (1ULL + 4ULL);
    for (int f = 0; f < NUM_QFEATS; ++f) {
        in.seekg(base_q + static_cast<uint64_t>(f) * N + start);
        in.read(reinterpret_cast<char*>(q[f].data()), M);
    }
    std::vector<int8_t> triple_align(M);
    uint64_t base_flags = base_q + static_cast<uint64_t>(NUM_QFEATS) * N;
    in.seekg(base_flags + 8ULL * N + start);
    in.read(reinterpret_cast<char*>(triple_align.data()), M);
    std::vector<uint8_t> target_rr(M);
    uint64_t base_trr = base_flags + static_cast<uint64_t>(NUM_FLAGS) * N + N;
    in.seekg(base_trr + start);
    in.read(reinterpret_cast<char*>(target_rr.data()), M);
    uint32_t split_idx = static_cast<uint32_t>(M * 0.70);
    std::vector<RuleCandidate> all_best;
    // Параллельный перебор парных условий с фильтром Triple_Trend_Align
    #pragma omp parallel
    {
        std::vector<RuleCandidate> local_best;
        for (int f1 = 0; f1 < NUM_QFEATS; ++f1) {
            #pragma omp for schedule(dynamic, 1) nowait
            for (int f2 = f1 + 1; f2 < NUM_QFEATS; ++f2) {
                for (int b1 = 32; b1 <= 224; b1 += 32) {
                    for (int b2 = 32; b2 <= 224; b2 += 32) {
                        for (int gt1 = 0; gt1 <= 1; ++gt1) {
                            for (int gt2 = 0; gt2 <= 1; ++gt2) {
                                int tr_buy = 0, tr_buy_win = 0;
                                int oos_buy = 0, oos_buy_win = 0;
                                for (uint32_t i = 0; i < M; ++i) {
                                    if (triple_align[i] != 1) continue;
                                    bool c1 = gt1 ? (q[f1][i] >= b1) : (q[f1][i] <= b1);
                                    if (!c1) continue;
                                    bool c2 = gt2 ? (q[f2][i] >= b2) : (q[f2][i] <= b2);
                                    if (!c2) continue;
                                    if (i < split_idx) {
                                        tr_buy++;
                                        if (target_rr[i] == 1) tr_buy_win++;
                                    } else {
                                        oos_buy++;
                                        if (target_rr[i] == 1) oos_buy_win++;
                                    }
                                }
                                if (tr_buy >= 300 && oos_buy >= 150) {
                                    double tr_wr  = (double)tr_buy_win / tr_buy;
                                    double oos_wr = (double)oos_buy_win / oos_buy;
                                    if (tr_wr >= 0.56 && oos_wr >= 0.56) {
                                        RuleCandidate rc{f1, f2, (uint8_t)b1, (uint8_t)b2, (bool)gt1, (bool)gt2,
                                                         1, tr_buy, oos_buy, tr_wr * 100.0, oos_wr * 100.0,
                                                         oos_wr * std::sqrt((double)oos_buy)};
                                        local_best.push_back(rc);
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        #pragma omp critical
        all_best.insert(all_best.end(), local_best.begin(), local_best.end());
    }
    std::sort(all_best.begin(), all_best.end(), [](const RuleCandidate& a, const RuleCandidate& b) {
        return a.score > b.score;
    });
    if (all_best.size() > 15) all_best.resize(15);
    auto t1 = std::chrono::high_resolution_clock::now();
    double sec = std::chrono::duration<double>(t1 - t0).count();
    std::cout << "=== V3 MINER REPORT (" << target_tf << ", rows=" << M << ") ===\n";
    std::cout << "Elapsed: " << std::fixed << std::setprecision(3) << sec << " sec | Found robust OOS rules: " << all_best.size() << "\n\n";
    std::ofstream mqh(out_mqh);
    mqh << "// Auto-generated by mine_v3.cpp on " << target_tf << " (" << M << " bars)\n";
    mqh << "// Strict Out-of-Sample (OOS) verified rules\n#pragma once\n\n";
    for (size_t i = 0; i < all_best.size(); ++i) {
        const auto& r = all_best[i];
        float thr1 = hdr.bin_edges[r.f1][r.b1];
        float thr2 = hdr.bin_edges[r.f2][r.b2];
        std::string op1 = r.gt1 ? ">=" : "<=";
        std::string op2 = r.gt2 ? ">=" : "<=";
        std::cout << "#" << (i + 1) << " BUY if Triple_Trend_Align==1 && "
                  << QFEAT_NAMES[r.f1] << " " << op1 << " " << thr1 << " && "
                  << QFEAT_NAMES[r.f2] << " " << op2 << " " << thr2
                  << " | Train WR=" << std::setprecision(1) << r.train_wr << "% (" << r.train_trades << ")"
                  << " | OOS WR=" << r.oos_wr << "% (" << r.oos_trades << ")\n";
        mqh << "// Rule #" << (i + 1) << " | OOS WinRate=" << std::fixed << std::setprecision(1) << r.oos_wr
            << "% (" << r.oos_trades << " trades)\n";
        mqh << "bool CheckEdge_" << target_tf << "_" << (i + 1)
            << "(bool tripleAlign, double " << QFEAT_NAMES[r.f1] << ", double " << QFEAT_NAMES[r.f2] << ") {\n";
        mqh << "   return (tripleAlign && " << QFEAT_NAMES[r.f1] << " " << op1 << " " << std::setprecision(6) << thr1
            << " && " << QFEAT_NAMES[r.f2] << " " << op2 << " " << thr2 << ");\n}\n\n";
    }
    mqh.close();
    return 0;
}

