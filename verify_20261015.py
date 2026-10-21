# -*- coding: utf-8 -*-
"""
亚盘模型泛化验证 — 基于 Over_20261015.htm 的 55 场主流联赛完赛比赛
数据来源: zq.titan007.com/analysis/{id}sb.htm 的 Crow* 公司盘口
模型: 复用 asian_handicap_verify_all.py 的 predict_asian / handicap_to_num / calc_handicap_result
"""
import json
import sys

sys.path.insert(0, "/workspace")
from asian_handicap_verify_all import (
    predict_asian, handicap_to_num, calc_handicap_result,
)


def load_data():
    with open("/workspace/match_list_20261015.json", "r", encoding="utf-8") as f:
        matches = json.load(f)
    with open("/workspace/scraped_data.json", "r", encoding="utf-8") as f:
        scraped = json.load(f)
    scraped_map = {s["id"]: s for s in scraped}
    merged = []
    for m in matches:
        s = scraped_map.get(m["id"])
        if not s:
            continue
        merged.append({
            "id": m["id"],
            "league": m["league"],
            "home": m["home"],
            "away": m["away"],
            "score": m["score"],
            "half": m["half"],
            "hcp_listed": m["hcp"],
            "odds_chu": s.get("odds_chu"),
            "asian_chu": tuple(s["asian_chu"]) if s.get("asian_chu") else None,
            "odds_zhong": s.get("odds_zhong"),
            "asian_zhong": tuple(s["asian_zhong"]) if s.get("asian_zhong") else None,
            "same_home_wr": s.get("same_home_wr"),
            "same_away_wr": s.get("same_away_wr"),
        })
    return merged


def main():
    matches = load_data()
    print("=" * 115)
    print(f"  亚盘模型泛化验证  |  数据源: Over_20261015.htm + Crow* 公司盘口  |  共 {len(matches)} 场主流联赛完赛比赛")
    print("=" * 115)
    header = f"{'联赛':<8}{'主队':<14}{'客队':<14}{'比分':<6}{'终盘':<10}{'预测':<5}{'实际':<6}{'命中':<6}{'评分':<7}  信号"
    print(header)
    print("-" * 115)

    total = hit = miss = push = neutral = skipped = 0
    results_detail = []

    for m in matches:
        if not m["asian_zhong"]:
            print(f"{m['league']:<8}{m['home']:<14}{m['away']:<14}{m['score']:<6}{'无终盘':<10}")
            skipped += 1
            continue

        hcp = m["asian_zhong"][1]
        hcp_num = handicap_to_num(hcp)
        if hcp_num is None:
            print(f"{m['league']:<8}{m['home']:<14}{m['away']:<14}{m['score']:<6}{hcp:<10}{'盘口解析失败'}")
            skipped += 1
            continue

        sg = m["score"].split("-")
        hg, ag = int(sg[0]), int(sg[1])

        pred, score_val, reasons = predict_asian(
            m["odds_chu"], m["asian_chu"], m["odds_zhong"], m["asian_zhong"],
            m["same_home_wr"], m["same_away_wr"],
        )
        actual = calc_handicap_result(hg, ag, hcp_num)

        if actual == "走水":
            is_hit = "走水"; push += 1
        elif pred == "中":
            is_hit = "中性"; neutral += 1
        elif pred == actual:
            is_hit = "√"; hit += 1
        else:
            is_hit = "×"; miss += 1

        total += 1
        reason_str = "; ".join(reasons) if reasons else "无"
        print(f"{m['league']:<8}{m['home']:<14}{m['away']:<14}{m['score']:<6}{hcp:<10}{pred:<5}{actual:<6}{is_hit:<6}{score_val:>+5.1f}  {reason_str}")
        results_detail.append({
            "league": m["league"], "home": m["home"], "away": m["away"],
            "score": m["score"], "handicap": hcp, "pred": pred, "actual": actual,
            "hit": is_hit, "score_val": score_val, "reasons": reasons,
        })

    # ---- 总体统计 ----
    print("-" * 115)
    valid = hit + miss
    print(f"\n  总场次: {total}  |  命中: {hit}  |  未中: {miss}  |  走水: {push}  |  中性: {neutral}  |  跳过: {skipped}")
    if valid > 0:
        print(f"  ★ 胜率(不含走水/中性): {hit}/{valid} = {hit/valid*100:.1f}%")
        print(f"  ★ 胜率(含走水/中性为未中): {hit}/{total} = {hit/total*100:.1f}%")

    # ---- 按联赛统计 ----
    print(f"\n  {'='*62}")
    print(f"  按联赛统计:")
    print(f"  {'联赛':<10}{'场次':>6}{'命中':>6}{'未中':>6}{'走水':>6}{'中性':>6}{'胜率':>10}")
    print(f"  {'-'*52}")
    by_league = {}
    for r in results_detail:
        lg = r["league"]
        if lg not in by_league:
            by_league[lg] = {"t": 0, "h": 0, "m": 0, "p": 0, "n": 0}
        by_league[lg]["t"] += 1
        if r["hit"] == "√": by_league[lg]["h"] += 1
        elif r["hit"] == "×": by_league[lg]["m"] += 1
        elif r["hit"] == "走水": by_league[lg]["p"] += 1
        elif r["hit"] == "中性": by_league[lg]["n"] += 1
    for lg in sorted(by_league.keys(), key=lambda x: -by_league[x]["t"]):
        s = by_league[lg]
        v = s["h"] + s["m"]
        wr = s["h"] / v * 100 if v else 0
        print(f"  {lg:<10}{s['t']:>6}{s['h']:>6}{s['m']:>6}{s['p']:>6}{s['n']:>6}{wr:>9.0f}%")

    # ---- 错误案例分析 ----
    print(f"\n  {'='*62}")
    print(f"  未命中案例分析:")
    for r in results_detail:
        if r["hit"] == "×":
            reason_str = "; ".join(r["reasons"]) if r["reasons"] else "无"
            print(f"  {r['league']} {r['home']} vs {r['away']} {r['score']} | "
                  f"盘口{r['handicap']} 预测{r['pred']} 实际{r['actual']} | "
                  f"评分{r['score_val']:+.1f} | 信号: {reason_str}")

    # ---- 信号有效性分析 ----
    print(f"\n  {'='*62}")
    print(f"  各信号命中统计 (仅计算有明确方向的场次):")
    signal_hits = {}
    for r in results_detail:
        if r["hit"] not in ("√", "×"):
            continue
        for reason in r["reasons"]:
            if "主水" in reason:
                sig = "水位变化"
            elif "升盘" in reason or "降盘" in reason:
                sig = "盘口升降"
            elif "欧赔" in reason:
                sig = "欧赔概率"
            elif "同盘" in reason:
                sig = "相同盘口"
            else:
                sig = reason.split("(")[0].strip()
            if sig not in signal_hits:
                signal_hits[sig] = {"h": 0, "m": 0}
            if r["hit"] == "√":
                signal_hits[sig]["h"] += 1
            else:
                signal_hits[sig]["m"] += 1
    for sig, s in sorted(signal_hits.items(), key=lambda x: -(x[1]["h"] + x[1]["m"])):
        v = s["h"] + s["m"]
        wr = s["h"] / v * 100 if v else 0
        print(f"    {sig:<12} 出现{v:>3}次  命中{s['h']:>3}  未中{s['m']:>3}  胜率{wr:>5.1f}%")

    # ---- 与前 37 场对比 ----
    print(f"\n  {'='*62}")
    print(f"  与前 37 场验证结果对比:")
    print(f"    前 37 场: 命中 18/23 = 78.3% (有明确方向)")
    if valid > 0:
        print(f"    本批 {total} 场: 命中 {hit}/{valid} = {hit/valid*100:.1f}% (有明确方向)")
        combined_h = 18 + hit
        combined_v = 23 + valid
        print(f"    合并 {37+total} 场: 命中 {combined_h}/{combined_v} = {combined_h/combined_v*100:.1f}% (有明确方向)")

    print("\n" + "=" * 115)
    print("  注: 以上为基于盘口数据的模型预测验证, 仅供研究参考, 不构成投注建议。")
    print("=" * 115)


if __name__ == "__main__":
    main()
