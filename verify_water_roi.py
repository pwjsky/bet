# -*- coding: utf-8 -*-
"""
真实水位下的亚盘赢盘 ROI 验证
============================
水位来源: titan_data/water.json (Crown/Bet365 赛前封盘水位, jsData sOdds[9..11])
欧赔来源: titan_data/euro.json   (p_move 特征)
结算:    用与水位同一快照的盘口 (crown.hcp_close), 四分之一盘精确结算

水位是净赔率: 押 1 赢 0.90 -> 总回报 1.90
ROI = 平均(总回报 - 1)

用法:
  py verify_water_roi.py
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from asian_handicap_model_v3 import (  # noqa: E402
    devig, fit_logreg, load_samples, standardize_fit, transform, sigmoid,
)

DATA = os.path.join(BASE, "titan_data")
L = json.load(open(os.path.join(DATA, "listings.json"), encoding="utf-8"))
W = json.load(open(os.path.join(DATA, "water.json"), encoding="utf-8"))


def settle_units(h, hg, ag):
    """h 为主队让球数(正=主让)。返回主队赢盘档位 +1/+0.5/0/-0.5/-1。"""
    k = round(((hg - ag) - h) * 4)
    if k >= 2:
        return 1.0
    if k == 1:
        return 0.5
    if k == 0:
        return 0.0
    if k == -1:
        return -0.5
    return -1.0


def payout(unit, w):
    """unit: 押注方赢盘档位; w: 押注方净水位。返回总回报(含本金)。"""
    if unit == 1.0:
        return 1.0 + w
    if unit == 0.5:
        return 1.0 + w / 2.0
    if unit == 0.0:
        return 1.0
    if unit == -0.5:
        return 0.5
    return 0.0


def apply_calib(edges, p):
    """保序回归表 -> 分段线性插值(保持单调)。"""
    if not edges:
        return p
    xs = [(a + b) / 2 for a, b, _ in edges]
    ys = [c for _, _, c in edges]
    if p <= xs[0]:
        return ys[0]
    if p >= xs[-1]:
        return ys[-1]
    for i in range(1, len(xs)):
        if p <= xs[i]:
            t = (p - xs[i - 1]) / max(xs[i] - xs[i - 1], 1e-9)
            return ys[i - 1] + t * (ys[i] - ys[i - 1])
    return ys[-1]


def build(book="crown"):
    rows = []
    for sid, e in json.load(open(os.path.join(DATA, "euro.json"), encoding="utf-8")).items():
        if e.get("p_move") is None:
            continue
        w = W.get(sid, {}).get(book)
        l = L.get(sid)
        if not w or not l:
            continue
        try:
            hg, ag = [int(x) for x in l["score"].split("-")]
        except Exception:
            continue
        h = w["hcp_close"]
        if h is None:
            continue
        rows.append({"sid": sid, "date": l["date"], "p_move": e["p_move"],
                     "h": h, "hg": hg, "ag": ag,
                     "h_listed": l.get("hcp_listed"),
                     "wo_h": w["wo_h_close"], "wo_a": w["wo_a_close"]})
    rows.sort(key=lambda r: r["date"])
    return rows


def fit_pmove(rows):
    X = [[r["p_move"]] for r in rows]
    mu, sd = standardize_fit(X)
    w, b = fit_logreg(transform(X, mu, sd), [r["y"] for r in rows],
                      l2=3.0, lr=0.1, epochs=1500)
    return w[0], b


def evaluate(rows, w, b, mu, sd, label):
    print("\n== %s ==  n=%d" % (label, len(rows)))
    bands = [(0.0, "全下"), (0.05, "|sig|>=0.05"), (0.08, "|sig|>=0.08"),
             (0.10, "|sig|>=0.10"), (0.15, "|sig|>=0.15")]
    for thr, name in bands:
        n = profit = wins = 0
        odds_sum = 0.0
        for r in rows:
            p = sigmoid(b + w * (r["p_move"] - mu) / sd)
            sig = abs(p - 0.5)
            if sig < thr:
                continue
            r["y"] = 1 if ((r["hg"] - r["ag"]) - r["h"]) > 0 else 0
            d = 1 if p >= 0.5 else -1
            u = settle_units(r["h"], r["hg"], r["ag"])
            u = u if d == 1 else -u
            wd = r["wo_h"] if d == 1 else r["wo_a"]
            n += 1
            profit += payout(u, wd) - 1.0
            odds_sum += wd
            if u > 0:
                wins += 1
        if n:
            print("  %-13s n=%-5d 命中 %5.1f%%  平均水位 %.3f  ROI %+6.2f%%"
                  % (name, n, 100.0 * wins / n, odds_sum / n, 100.0 * profit / n))


def main():
    book = sys.argv[1] if len(sys.argv) > 1 else "crown"
    fast = "--fast" in sys.argv
    rows = build(book)
    # 剔除走水，与模型训练口径一致（四分之一盘约 12% 场次走水）
    rows = [r for r in rows if abs((r["hg"] - r["ag"]) - r["h"]) > 1e-9]
    for r in rows:
        r["y"] = 1 if ((r["hg"] - r["ag"]) - r["h"]) > 0 else 0
    print("样本 %d 场  %s ~ %s" % (len(rows), rows[0]["date"], rows[-1]["date"]))
    ws = sorted(r["wo_h"] for r in rows)
    print("主水 中位 %.3f 均值 %.4f P5 %.3f P95 %.3f  <0.85占%.1f%%"
          % (ws[len(ws) // 2], sum(ws) / len(ws), ws[int(len(ws) * .05)],
             ws[int(len(ws) * .95)], 100.0 * sum(1 for x in ws if x < 0.85) / len(ws)))
    pair = [r["wo_h"] + r["wo_a"] for r in rows]
    print("主水+客水 均值 %.3f (正常 1.80~1.95)" % (sum(pair) / len(pair)))

    # 1) 样本内拟合
    X = [[r["p_move"]] for r in rows]
    mu, sd = standardize_fit(X)
    w, b = fit_logreg(transform(X, mu, sd), [r["y"] for r in rows],
                      l2=3.0, lr=0.1, epochs=1500)
    print("\n单特征 p_move: w=%+.4f b=%+.4f" % (w[0], b))
    evaluate(rows, w[0], b, mu[0], sd[0], "%s 盘口 + %s 水位 (样本内)" % (book, book))

    if fast:
        return

    # 2) 滚动样本外: 每天用之前所有日期训练
    dates = sorted(set(r["date"] for r in rows))
    oos = []
    for i in range(5, len(dates)):
        d = dates[i]
        tr = [r for r in rows if r["date"] < d]
        te = [r for r in rows if r["date"] == d]
        if len(tr) < 300 or not te:
            continue
        Xt = [[r["p_move"]] for r in tr]
        m, s = standardize_fit(Xt)
        ww, bb = fit_logreg(transform(Xt, m, s), [r["y"] for r in tr],
                            l2=3.0, lr=0.1, epochs=800)
        for r in te:
            p = sigmoid(bb + ww[0] * (r["p_move"] - m[0]) / s[0])
            oos.append(dict(r, p=p))
    if oos:
        print("\n滚动样本外 %d 场  %s ~ %s" % (len(oos), oos[0]["date"], oos[-1]["date"]))
        for thr, name in [(0.0, "全下"), (0.05, "|sig|>=0.05"), (0.08, "|sig|>=0.08"),
                          (0.10, "|sig|>=0.10"), (0.15, "|sig|>=0.15")]:
            n = profit = wins = 0
            odds_sum = 0.0
            for r in oos:
                if abs(r["p"] - 0.5) < thr:
                    continue
                d = 1 if r["p"] >= 0.5 else -1
                u = settle_units(r["h"], r["hg"], r["ag"])
                u = u if d == 1 else -u
                wd = r["wo_h"] if d == 1 else r["wo_a"]
                n += 1
                profit += payout(u, wd) - 1.0
                odds_sum += wd
                if u > 0:
                    wins += 1
            if n:
                print("  %-13s n=%-5d 命中 %5.1f%%  平均水位 %.3f  ROI %+6.2f%%"
                      % (name, n, 100.0 * wins / n, odds_sum / n, 100.0 * profit / n))

        # 口径对照: 同一模型、同一方向, 只换结算盘口
        print("\n  口径对照 (同一模型方向, 只换结算盘口):")
        for key, sign, label in (("h", 1, "皇冠盘口"), ("h_listed", -1, "比分页盘口")):
            n = wins = 0
            for r in oos:
                h = r[key]
                if h is None:
                    continue
                d = 1 if r["p"] >= 0.5 else -1
                u = settle_units(sign * h, r["hg"], r["ag"])
                u = u if d == 1 else -u
                n += 1
                if u > 0:
                    wins += 1
            if n:
                print("    %-10s n=%-4d 命中 %5.1f%%" % (label, n, 100.0 * wins / n))

        # 逐日 TopN
        print("\n  逐日选强 (每天按 |p-0.5| 取前 N 场):")
        for topn in (1, 3, 5, 10):
            n = profit = wins = 0
            odds_sum = 0.0
            days = {}
            for r in oos:
                days.setdefault(r["date"], []).append(r)
            for d, arr in days.items():
                arr.sort(key=lambda x: -abs(x["p"] - 0.5))
                for r in arr[:topn]:
                    dd = 1 if r["p"] >= 0.5 else -1
                    u = settle_units(r["h"], r["hg"], r["ag"])
                    u = u if dd == 1 else -u
                    wd = r["wo_h"] if dd == 1 else r["wo_a"]
                    n += 1
                    profit += payout(u, wd) - 1.0
                    odds_sum += wd
                    if u > 0:
                        wins += 1
            if n:
                print("    Top%-2d n=%-4d 命中 %5.1f%%  平均水位 %.3f  ROI %+6.2f%%"
                      % (topn, n, 100.0 * wins / n, odds_sum / n, 100.0 * profit / n))

        # 逐日 TopN (按校准后 EV 排序, 与 today_picks.py 同口径)
        calib = os.path.join(DATA, "calibration.json")
        edges = []
        if os.path.exists(calib):
            edges = [tuple(x) for x in
                     json.load(open(calib, encoding="utf-8"))["iso_edges"]]
        for r in oos:
            r["p_cal"] = apply_calib(edges, r["p"])
            d = 1 if r["p_cal"] >= 0.5 else -1
            p_side = r["p_cal"] if d == 1 else 1 - r["p_cal"]
            wd = r["wo_h"] if d == 1 else r["wo_a"]
            r["ev"] = p_side * (1 + wd) - 1
            r["side"] = d
        print("\n  逐日选强 (每天按校准后 EV 取前 N 场):")
        days = {}
        for r in oos:
            days.setdefault(r["date"], []).append(r)

        def day_eval(topn, sort_key, min_sig=0.0, min_ev=None, cal_sig=False):
            n = profit = wins = 0
            odds_sum = 0.0
            day_pnl = []
            for d, arr in days.items():
                pool = [r for r in arr
                        if abs((r["p_cal"] if cal_sig else r["p"]) - 0.5) >= min_sig
                        and (min_ev is None or r["ev"] >= min_ev)]
                if not pool:
                    continue
                pool.sort(key=sort_key)
                pnl = 0.0
                for r in (pool if topn is None else pool[:topn]):
                    u = settle_units(r["h"], r["hg"], r["ag"])
                    u = u if r["side"] == 1 else -u
                    wd = r["wo_h"] if r["side"] == 1 else r["wo_a"]
                    pay = payout(u, wd) - 1.0
                    n += 1
                    pnl += pay
                    profit += pay
                    odds_sum += wd
                    if u > 0:
                        wins += 1
                day_pnl.append(pnl)
            if not n:
                return "无场次"
            up = sum(1 for x in day_pnl if x > 0)
            return ("n=%-4d 日均%4.1f 命中 %5.1f%%  水位 %.3f  ROI %+6.2f%%"
                    "  盈利日 %d/%d  最好%+.2fU 最差%+.2fU"
                    % (n, 1.0 * n / len(day_pnl), 100.0 * wins / n,
                       odds_sum / n, 100.0 * profit / n, up, len(day_pnl),
                       max(day_pnl), min(day_pnl)))

        print("    %-24s %s" % ("EV排序 Top10", day_eval(10, lambda r: -r["ev"])))
        print("    %-24s %s" % ("EV排序 Top5", day_eval(5, lambda r: -r["ev"])))
        sig_key = lambda r: -abs(r["p"] - 0.5)          # noqa: E731
        print("\n  Top10 排序口径对比:")
        for label, kw in (
            ("原始sig排序", dict(sort_key=sig_key)),
            ("原始sig + EV>=0", dict(sort_key=sig_key, min_ev=0.0)),
            ("原始sig + EV>=0.05", dict(sort_key=sig_key, min_ev=0.05)),
            ("原始sig>=0.08 + EV排序",
             dict(sort_key=lambda r: -r["ev"], min_sig=0.08)),
            ("校准sig排序", dict(sort_key=sig_key, cal_sig=True)),
        ):
            kw.setdefault("topn", 10)
            print("    %-24s %s" % (label, day_eval(**kw)))

        print("\n  逐日强信号 (当天满足阈值的全部场次, 不限数量):")
        for thr in (0.05, 0.08, 0.10, 0.15):
            print("    %-24s %s" % ("sig>=%.2f" % thr,
                                    day_eval(None, sig_key, min_sig=thr)))
        print("\n  逐日 Top10 且强信号 (先按阈值过滤, 再取前 10):")
        for thr in (0.05, 0.08, 0.10, 0.12, 0.15):
            print("    %-24s %s" % ("Top10 & sig>=%.2f" % thr,
                                    day_eval(10, sig_key, min_sig=thr)))
        tenth = []
        for d, arr in days.items():
            arr2 = sorted(arr, key=sig_key)
            if len(arr2) >= 10:
                tenth.append(abs(arr2[9]["p"] - 0.5))
        if tenth:
            tenth.sort()
            print("\n  每天第 10 名的信号强度: 最小 %.3f  P25 %.3f  中位 %.3f  P75 %.3f"
                  % (tenth[0], tenth[len(tenth) // 4],
                     tenth[len(tenth) // 2], tenth[3 * len(tenth) // 4]))
        print("\n  逐日强信号 + EV 过滤:")
        for thr in (0.08, 0.10):
            for mev in (0.0, 0.05, 0.10):
                print("    %-24s %s" % ("sig>=%.2f EV>=%.2f" % (thr, mev),
                                        day_eval(None, sig_key, min_sig=thr,
                                                 min_ev=mev)))


if __name__ == "__main__":
    main()
