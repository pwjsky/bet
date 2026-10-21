# -*- coding: utf-8 -*-
"""展示命中的18场比赛明细 + 模型推荐逻辑说明"""
from asian_handicap_verify_all import (
    MATCHES, predict_asian, handicap_to_num, calc_handicap_result
)


def run():
    print("=" * 120)
    print("  命中场次明细（18场）—— 模型推荐与实际赛果一致")
    print("=" * 120)

    hit_matches = []
    for (mid, league, home, away, score, half,
         odds_chu, asian_chu, odds_zhong, asian_zhong,
         same_home_wr, same_away_wr) in MATCHES:

        if not asian_zhong:
            continue
        hcp_num = handicap_to_num(asian_zhong[1])
        if hcp_num is None:
            continue
        sg = score.split("-")
        hg, ag = int(sg[0]), int(sg[1])
        pred, score_val, reasons = predict_asian(
            odds_chu, asian_chu, odds_zhong, asian_zhong, same_home_wr, same_away_wr
        )
        actual = calc_handicap_result(hg, ag, hcp_num)
        if pred in ("主", "客") and pred == actual:
            hit_matches.append({
                "league": league, "home": home, "away": away, "score": score,
                "handicap": asian_zhong[1], "pred": pred, "actual": actual,
                "score_val": score_val, "reasons": reasons,
                "odds_chu": odds_chu, "asian_chu": asian_chu,
                "odds_zhong": odds_zhong, "asian_zhong": asian_zhong,
                "same_home_wr": same_home_wr, "same_away_wr": same_away_wr,
            })

    # 按评分绝对值排序（信心强度）
    hit_matches.sort(key=lambda x: -abs(x["score_val"]))

    for i, r in enumerate(hit_matches, 1):
        print(f"\n{'─'*120}")
        print(f"  【{i:>2}】 {r['league']}  {r['home']} vs {r['away']}  比分 {r['score']}")
        print(f"       终盘亚盘: 主水 {r['asian_zhong'][0]:.2f} | 盘口 {r['handicap']} | 客水 {r['asian_zhong'][2]:.2f}")
        print(f"       终盘欧赔: 主 {r['odds_zhong'][0]:.2f} | 平 {r['odds_zhong'][1]:.2f} | 客 {r['odds_zhong'][2]:.2f}")
        # 欧赔隐含概率
        ph = 1/r['odds_zhong'][0]; pd = 1/r['odds_zhong'][1]; pa = 1/r['odds_zhong'][2]
        tot = ph+pd+pa
        print(f"       隐含概率: 主 {ph/tot*100:.1f}% | 平 {pd/tot*100:.1f}% | 客 {pa/tot*100:.1f}%")
        # 水位变化
        dh = r['asian_zhong'][0] - r['asian_chu'][0]
        da = r['asian_zhong'][2] - r['asian_chu'][2]
        print(f"       水位变化: 主水 {dh:+.3f} | 客水 {da:+.3f}")
        # 盘口变化
        print(f"       盘口变化: {r['asian_chu'][1]} → {r['asian_zhong'][1]}")
        # 相同盘口
        if r['same_home_wr'] is not None and r['same_away_wr'] is not None:
            print(f"       相同盘口: 主队主场赢盘率 {r['same_home_wr']:.1f}% | 客队客场赢盘率 {r['same_away_wr']:.1f}%")
        # 推荐
        direction = r['pred']
        team = r['home'] if direction == "主" else r['away']
        hcp_text = r['handicap']
        if direction == "主":
            rec = f"主队 {r['home']} 让 {hcp_text}（上盘）"
        else:
            # 客队方向：若主队受让(*)，则客队让球；否则客队受让
            if hcp_text.startswith("*"):
                rec = f"客队 {r['away']} 让 {hcp_text[1:]}（上盘）"
            else:
                rec = f"客队 {r['away']} 受让 {hcp_text}（下盘）"
        confidence = "高" if abs(r['score_val']) >= 2 else ("中" if abs(r['score_val']) >= 1 else "低")
        print(f"       ★ 模型推荐: {rec}")
        print(f"       综合评分: {r['score_val']:+.1f}  |  信心: {confidence}")
        print(f"       信号明细:")
        for reason in r['reasons']:
            print(f"         · {reason}")

    print(f"\n{'='*120}")
    print(f"  共 {len(hit_matches)} 场命中")
    print(f"{'='*120}")

    # 推荐逻辑总结
    print(f"\n{'='*120}")
    print("  模型推荐逻辑说明")
    print(f"{'='*120}")
    print("""
  推荐方向由 4 个信号综合打分得出（得分 >= +1 → 主推主队；<= -1 → 主推客队；介于两者 → 中性不推荐）：

  1. 水位变化（权重最高）
     - 主水下降 → 市场资金流入主队，机构降低赔付 → 利好主队
     - 主水上升 → 市场资金流入客队 → 利好客队
     - 阈值：>|0.05| 记 ±1.0，|0.01~0.05| 记 ±0.5

  2. 盘口升降
     - 升盘（终盘让球更深，如 半球→半/一）→ 机构增强主队信心 → 利好主队
     - 降盘（终盘让球变浅，如 半/一→半球）→ 机构减弱主队信心 → 利好客队
     - 记 ±1.0

  3. 欧赔隐含概率（终盘）
     - 主胜概率比客胜高 >20% → 利好主队 +1.0；高 10~20% → +0.5
     - 客胜概率比主胜高 >20% → 利好客队 -1.0；高 10~20% → -0.5

  4. 相同盘口历史赢盘率
     - 主队主场赢盘率 比 客队客场赢盘率 高 >15% → +1.0；高 5~15% → +0.5
     - 反之亦然

  信心分级：|评分| ≥ 2 高信心，1~2 中信心，< 1 低信心（实际低信心场次多归入中性不推荐）

  输出格式：[联赛] 主队 vs 客队 → 推荐方向（让球/受让说明）+ 信心等级 + 支撑信号
""")
    print(f"{'='*120}")


if __name__ == "__main__":
    run()
