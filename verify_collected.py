# -*- coding: utf-8 -*-
"""
用 titan007 采集数据验证赢盘模型 v2
====================================
- 数据: titan_data/matches.json (由 titan007_collector.py 生成)
- 评估: 按日期做时间外推 (早日期训练, 晚日期测试) + 分日独立评估
- 指标: 命中率 / 精确结算 ROI / Brier / 校准
"""
import json
import sys
import math
from collections import Counter, defaultdict

sys.path.insert(0, r"g:\bet")
from asian_handicap_model_v2 import (
    FEATURES, make_features, fit_model, predict_proba,
    settle, result_side, backtest, wilson_ci, metrics, repeated_cv, summarize,
)

DATA = r"g:\bet\titan_data\matches.json"


def valid_water(x):
    return isinstance(x, (int, float)) and 0.3 < x < 2.0


def load_rows(min_date=None, max_date=None):
    data = json.load(open(DATA, encoding="utf-8"))
    rows = []
    skipped = Counter()
    for sid, rec in data.items():
        d = rec.get("date", "")
        if min_date and d < min_date:
            continue
        if max_date and d > max_date:
            continue
        try:
            hg, ag = [int(x) for x in rec["score"].split("-")]
        except Exception:
            skipped["比分缺失"] += 1
            continue
        h_open, h_close = rec.get("hcp_open"), rec.get("hcp_close")
        if h_open is None or h_close is None:
            skipped["盘口缺失"] += 1
            continue
        if abs(h_close) > 5 or abs(h_open) > 5:
            skipped["盘口异常"] += 1
            continue
        if not all(valid_water(rec.get(k)) for k in ("wo_h", "wo_a", "wc_h", "wc_a")):
            skipped["水位异常"] += 1
            continue
        if not rec.get("odds_open") or not rec.get("odds_close"):
            skipped["欧赔缺失"] += 1
            continue
        if min(rec["odds_open"]) < 1.01 or min(rec["odds_close"]) < 1.01:
            skipped["欧赔异常"] += 1
            continue
        actual = result_side(h_close, hg, ag)
        if actual == "走水":
            skipped["走水"] += 1
            continue
        s = {
            "h_open": h_open, "h_close": h_close,
            "wo_h": rec["wo_h"], "wo_a": rec["wo_a"],
            "wc_h": rec["wc_h"], "wc_a": rec["wc_a"],
            "odds_open": rec["odds_open"], "odds_close": rec["odds_close"],
            "same_home_wr": rec.get("same_home_wr"), "same_away_wr": rec.get("same_away_wr"),
            "hg": hg, "ag": ag, "date": d, "league": rec.get("league"),
            "home": rec.get("home"), "away": rec.get("away"), "id": sid,
        }
        f = make_features(s)
        rows.append({
            "sample": s, "raw": f, "actual": actual,
            "y": 1 if actual == "主" else 0,
            "x": [f[k] for k in FEATURES],
        })
    return rows, skipped


def report_split(name, train, test):
    print(f"\n--- {name}: 训练 {len(train)} 场 -> 测试 {len(test)} 场 ---")
    if len(train) < 30 or len(test) < 20:
        print("  样本不足, 跳过")
        return
    model = fit_model([r["x"] for r in train], [r["y"] for r in train])
    probs = [predict_proba(model, r["x"]) for r in test]
    ys = [r["y"] for r in test]
    mt = metrics(ys, probs)
    bt0 = backtest(probs, test, threshold=0.5)
    lo, hi = wilson_ci(bt0["hits"], bt0["bets"])
    print(f"  Brier {mt['brier']:.4f}  LogLoss {mt['logloss']:.4f}")
    print(f"  全出手: {bt0['hits']}/{bt0['bets']} = {bt0['hit_rate']*100:.1f}% "
          f"95%CI[{lo*100:.1f}, {hi*100:.1f}]  ROI {bt0['roi']*100:+.1f}%")
    for th in (0.55, 0.60):
        bt = backtest(probs, test, threshold=th)
        if bt["bets"]:
            print(f"  阈值{th:.2f}: 下注{bt['bets']:>3} 命中{bt['hits']:>3} "
                  f"{bt['hit_rate']*100:.1f}%  ROI {bt['roi']*100:+.1f}%")
    # 基准
    for label, rule in [("全押主", lambda s: "主"), ("全押客", lambda s: "客"),
                        ("全押上盘", lambda s: "主" if s["h_close"] < 0 else "客"),
                        ("全押下盘", lambda s: "客" if s["h_close"] < 0 else "主")]:
        hits = sum(1 for r in test if rule(r["sample"]) == r["actual"])
        prof = sum(settle(rule(r["sample"]), r["sample"]["h_close"], r["sample"]["hg"],
                          r["sample"]["ag"], r["sample"]["wc_h"], r["sample"]["wc_a"]) for r in test)
        print(f"    基准{label:<5} {hits/len(test)*100:>5.1f}%  ROI {prof/len(test)*100:>+6.1f}%")
    # 校准
    buckets = defaultdict(lambda: [0, 0])
    for p, r in zip(probs, test):
        b = min(4, max(0, int(p * 5)))
        buckets[b][0] += 1
        buckets[b][1] += r["y"]
    print("  校准(概率区间 -> 实际主赢盘率):")
    for b in sorted(buckets):
        n, k = buckets[b]
        print(f"    {b*20:>3}-{b*20+20:>3}%: {k}/{n} = {k/n*100:>5.1f}%")


def main():
    rows, skipped = load_rows()
    print("=" * 92)
    print("采集数据验证")
    print("=" * 92)
    print("原始记录:", len(json.load(open(DATA, encoding="utf-8"))))
    print("可用样本:", len(rows))
    print("过滤原因:", dict(skipped))
    print("日期分布:", dict(sorted(Counter(r["sample"]["date"] for r in rows).items())))
    print("联赛 TOP15:", dict(Counter(r["sample"]["league"] for r in rows).most_common(15)))

    # 无偏性检查: 让球方赢盘率应接近 50%, 明显偏离说明盘口聚合存在系统偏差
    eff = win = 0
    for r in rows:
        s = r["sample"]
        m = (s["hg"] - s["ag"]) + s["h_close"]
        if abs(m) < 1e-9:
            continue
        eff += 1
        if (m > 0) == (s["h_close"] < 0):
            win += 1
    if eff:
        print(f"让球方赢盘率: {win}/{eff} = {win/eff*100:.1f}%  (无偏预期约 50%)")

    dates = sorted(set(r["sample"]["date"] for r in rows))
    print("\n" + "=" * 92)
    print("分日独立评估(每天用其余日期训练)")
    print("=" * 92)
    for d in dates:
        train = [r for r in rows if r["sample"]["date"] != d]
        test = [r for r in rows if r["sample"]["date"] == d]
        report_split(f"{d} 留出", train, test)

    if len(dates) >= 2:
        print("\n" + "=" * 92)
        print("时间外推: 早期训练 -> 最后一天测试")
        print("=" * 92)
        last = dates[-1]
        train = [r for r in rows if r["sample"]["date"] < last]
        test = [r for r in rows if r["sample"]["date"] == last]
        report_split(f"<{last} -> {last}", train, test)

    print("\n" + "=" * 92)
    print("重复分层交叉验证(仅作对照, 存在同期泄漏)")
    print("=" * 92)
    X = [r["x"] for r in rows]
    y = [r["y"] for r in rows]
    meta = [{"sample": r["sample"], "actual": r["actual"]} for r in rows]
    agg, oofs = repeated_cv(X, y, meta, k=5, repeats=10, seed=42)
    all_probs = [sum(rep[i] for rep in oofs) / len(oofs) for i in range(len(y))]
    bt0 = backtest(all_probs, meta, threshold=0.5)
    lo, hi = wilson_ci(bt0["hits"], bt0["bets"])
    print(f"  Brier {summarize(agg,'brier')[0]:.4f}  "
          f"命中 {bt0['hits']}/{bt0['bets']} = {bt0['hit_rate']*100:.1f}% "
          f"95%CI[{lo*100:.1f}, {hi*100:.1f}]  ROI {bt0['roi']*100:+.1f}%")
    for th in (0.55, 0.60):
        bt = backtest(all_probs, meta, threshold=th)
        if bt["bets"]:
            print(f"  阈值{th:.2f}: 下注{bt['bets']} 命中{bt['hit_rate']*100:.1f}% ROI {bt['roi']*100:+.1f}%")

    print("\n" + "=" * 92)
    print("全量拟合系数(仅查看方向)")
    print("=" * 92)
    model = fit_model(X, y)
    w, b, mean, std = model
    print(f"截距 {b:+.4f}")
    for f, c in sorted(zip(FEATURES, w), key=lambda x: -abs(x[1])):
        print(f"  {f:<14} {c:+.4f}")


if __name__ == "__main__":
    main()
