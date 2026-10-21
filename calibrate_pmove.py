# -*- coding: utf-8 -*-
"""
亚盘赢盘模型概率校准
====================
问题: 单特征逻辑回归输出过自信 (实测给过 21% / 71%), 直接算 EV 不可信。

做法:
  1. 按日期分组做 5 折交叉, 每场拿到"模型没见过它"的原始概率 p_raw
  2. 用 p_raw 拟合 Platt 校准: p_cal = sigmoid(a * logit(p_raw) + c)
  3. 对比校准前后的 Brier、分档命中率、EV 过滤效果
  4. 校准参数写入 titan_data/calibration.json, 供 today_picks 使用

用法:
  py calibrate_pmove.py
"""
import json
import math
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from asian_handicap_model_v3 import (  # noqa: E402
    fit_logreg, sigmoid, standardize_fit, transform,
)
from verify_water_roi import build, payout, settle_units  # noqa: E402

DATA = os.path.join(BASE, "titan_data")
OUT = os.path.join(DATA, "calibration.json")
CACHE = os.path.join(DATA, "oof_pmove.json")


def logit(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def fit_single(rows):
    X = [[r["p_move"]] for r in rows]
    mu, sd = standardize_fit(X)
    w, b = fit_logreg(transform(X, mu, sd), [r["y"] for r in rows],
                      l2=3.0, lr=0.1, epochs=1200)
    return w[0], b, mu[0], sd[0]


def predict(params, pmove):
    w, b, mu, sd = params
    return sigmoid(b + w * (pmove - mu) / sd)


def oof_probs(rows, k=5):
    """按日期分组交叉, 返回每场的样本外原始概率。"""
    dates = sorted(set(r["date"] for r in rows))
    buckets = [[] for _ in range(k)]
    for i, d in enumerate(dates):
        buckets[i * k // len(dates)].append(d)
    ps = [None] * len(rows)
    for b in range(k):
        test_dates = set(buckets[b])
        tr = [r for r in rows if r["date"] not in test_dates]
        te_idx = [i for i, r in enumerate(rows) if r["date"] in test_dates]
        params = fit_single(tr)
        for i in te_idx:
            ps[i] = predict(params, rows[i]["p_move"])
    return ps


def brier(ps, ys):
    return sum((p - y) ** 2 for p, y in zip(ps, ys)) / len(ps)


def report(rows, ps, label):
    ys = [r["y"] for r in rows]
    print("\n== %s ==  n=%d  Brier %.5f" % (label, len(ps), brier(ps, ys)))
    bins = [(0.0, 0.35), (0.35, 0.45), (0.45, 0.50), (0.50, 0.55),
            (0.55, 0.65), (0.65, 0.75), (0.75, 1.01)]
    print("  %-12s %6s %8s %8s" % ("概率区间", "场次", "预测均值", "实际命中"))
    for lo, hi in bins:
        idx = [i for i, p in enumerate(ps) if lo <= p < hi]
        if len(idx) < 20:
            continue
        print("  %.2f~%.2f    %6d %8.1f%% %8.1f%%"
              % (lo, hi, len(idx), 100 * sum(ps[i] for i in idx) / len(idx),
                 100 * sum(ys[i] for i in idx) / len(idx)))


def pav(ps, ys, min_block=80):
    """保序回归(Pool Adjacent Violators), 返回 (p_lo, p_hi, 命中率, 样本数) 表。"""
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    blocks = []
    for i in order:
        blocks.append([1.0, float(ys[i]), 1])
        while len(blocks) > 1 and blocks[-2][1] / blocks[-2][0] > blocks[-1][1] / blocks[-1][0]:
            b = blocks.pop()
            blocks[-1][0] += b[0]
            blocks[-1][1] += b[1]
            blocks[-1][2] += b[2]
    merged = []
    for b in blocks:
        if merged and (merged[-1][2] < min_block or b[2] < min_block):
            merged[-1][0] += b[0]
            merged[-1][1] += b[1]
            merged[-1][2] += b[2]
        else:
            merged.append(list(b))
    edges = []
    idx = 0
    for b in merged:
        edges.append((ps[order[idx]], ps[order[idx + b[2] - 1]],
                      b[1] / b[0], b[2]))
        idx += b[2]
    return edges


def apply_iso(edges, p):
    for lo, hi, v, _ in edges:
        if p <= hi:
            return v
    return edges[-1][2]


def main():
    rows = build("crown")
    rows = [r for r in rows if abs((r["hg"] - r["ag"]) - r["h"]) > 1e-9]
    for r in rows:
        r["y"] = 1 if ((r["hg"] - r["ag"]) - r["h"]) > 0 else 0
    print("样本 %d 场  %s ~ %s" % (len(rows), rows[0]["date"], rows[-1]["date"]))

    if os.path.exists(CACHE):
        ps = json.load(open(CACHE, encoding="utf-8"))
        print("复用样本外概率缓存")
    else:
        ps = oof_probs(rows, 5)
        json.dump(ps, open(CACHE, "w", encoding="utf-8"))
    report(rows, ps, "校准前 (5 折样本外)")

    # Platt: 对 logit(p) 再做一维逻辑回归
    X = [[logit(p)] for p in ps]
    mu, sd = standardize_fit(X)
    w, b = fit_logreg(transform(X, mu, sd), [r["y"] for r in rows],
                      l2=0.5, lr=0.05, epochs=3000)
    a = w[0] / sd[0]
    c = b - w[0] * mu[0] / sd[0]
    pcal = [sigmoid(a * logit(p) + c) for p in ps]
    print("\nPlatt 参数: a=%+.4f  c=%+.4f  (a<1 表示原始概率过分散)" % (a, c))
    report(rows, pcal, "Platt 校准后")

    # 保序回归
    edges = pav(ps, [r["y"] for r in rows], min_block=80)
    piso = [apply_iso(edges, p) for p in ps]
    print("\n保序回归映射 (%d 段):" % len(edges))
    for lo, hi, v, n in edges:
        print("  p %.3f~%.3f -> %.1f%%  (n=%d)" % (lo, hi, 100 * v, n))
    report(rows, piso, "保序回归后")

    ys = [r["y"] for r in rows]
    print("\nBrier: 原始 %.5f  Platt %.5f  保序 %.5f"
          % (brier(ps, ys), brier(pcal, ys), brier(piso, ys)))

    # EV 过滤效果: EV = p*(1+水位)-1
    print("\n按 EV 过滤 (含水位, 四分之一盘精确结算):")
    for label, arr in (("原始", ps), ("Platt", pcal), ("保序", piso)):
        for thr in (0.0, 0.05, 0.10):
            n = profit = wins = 0
            for r, p in zip(rows, arr):
                d = 1 if p >= 0.5 else -1
                wd = r["wo_h"] if d == 1 else r["wo_a"]
                p_side = p if d == 1 else 1 - p
                ev = p_side * (1 + wd) - 1
                if ev < thr:
                    continue
                u = settle_units(r["h"], r["hg"], r["ag"])
                u = u if d == 1 else -u
                n += 1
                profit += payout(u, wd) - 1.0
                if u > 0:
                    wins += 1
            if n:
                print("  %-6s EV>=%.2f  n=%-5d 命中 %5.1f%%  ROI %+6.2f%%"
                      % (label, thr, n, 100.0 * wins / n, 100.0 * profit / n))

    json.dump({"type": "isotonic", "platt": {"a": a, "c": c},
               "iso_edges": [[lo, hi, v] for lo, hi, v, _ in edges],
               "n": len(rows), "brier_raw": brier(ps, ys),
               "brier_platt": brier(pcal, ys), "brier_iso": brier(piso, ys)},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n已保存 %s" % OUT)


if __name__ == "__main__":
    main()
