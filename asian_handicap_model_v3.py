# -*- coding: utf-8 -*-
"""
亚盘赢盘模型 v3
================
数据源(全部为赛前可得):
  1. titan_data/listings.json  比分页终盘让球盘(hdp_val), 单位为主队视角: 负=主队让球
  2. titan_data/euro.json      本场百家欧赔初盘/即时(1x2d.titan007.com/{sid}.js)

特征:
  hcp            终盘让球深度(主队视角)
  abs_hcp        |终盘让球|
  p_open         欧赔初盘去水主胜概率
  p_close        欧赔即时去水主胜概率
  p_move         p_close - p_open
  pd_open        初盘去水平局概率
  pd_close       即时去水平局概率
  p_std          即时主胜概率的公司间标准差(分歧度)
  rebate         即时返还率中位数
  log_n_euro     开盘公司数的对数

用法:
  py asian_handicap_model_v3.py --train
  py asian_handicap_model_v3.py --eval
  py asian_handicap_model_v3.py --predict 3018834
  py asian_handicap_model_v3.py --predict-date 20261016
"""
import argparse
import json
import math
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from asian_handicap_model_v2 import fit_logreg  # noqa: E402

LISTINGS = os.path.join(BASE, "titan_data", "listings.json")
EURO = os.path.join(BASE, "titan_data", "euro.json")
MODEL_PATH = os.path.join(BASE, "titan_data", "model_v3.json")

FEATURES = ["hcp", "abs_hcp", "p_open", "p_close", "p_move",
            "pd_open", "pd_close", "p_std", "rebate", "log_n_euro"]


def devig(odds):
    inv = [1.0 / v for v in odds]
    s = sum(inv)
    return [v / s for v in inv]


def make_features(rec, euro):
    """rec: 比分页记录; euro: 欧赔记录。返回特征向量。"""
    po = devig(euro["odds_open"])
    pc = devig(euro["odds_close"])
    h = rec["hcp_listed"]
    return [
        h, abs(h),
        po[0], pc[0], pc[0] - po[0],
        po[1], pc[1],
        euro["p_std_close"],
        euro["rebate_close"],
        math.log(max(euro["n_euro"], 1)),
    ]


def load_samples():
    listings = json.load(open(LISTINGS, encoding="utf-8"))
    euro = json.load(open(EURO, encoding="utf-8"))
    rows = []
    for sid, e in euro.items():
        rec = listings.get(sid)
        if not e or not rec or rec.get("hcp_listed") is None:
            continue
        try:
            hg, ag = [int(x) for x in rec["score"].split("-")]
        except Exception:
            continue
        h = rec["hcp_listed"]
        m = (hg - ag) + h
        if abs(m) < 1e-9:          # 走水剔除
            continue
        rows.append({"sid": sid, "date": rec["date"], "league": rec.get("league"),
                     "rec": rec, "euro": e, "x": make_features(rec, e),
                     "y": 1 if m > 0 else 0})
    rows.sort(key=lambda r: r["date"])
    return rows


def standardize_fit(X):
    d = len(X[0])
    mu = [sum(x[i] for x in X) / len(X) for i in range(d)]
    sd = [(sum((x[i] - mu[i]) ** 2 for x in X) / len(X)) ** 0.5 or 1.0 for i in range(d)]
    return mu, sd


def transform(X, mu, sd):
    return [[(x[i] - mu[i]) / sd[i] for i in range(len(mu))] for x in X]


def sigmoid(x):
    return 1 / (1 + math.exp(-max(-30, min(30, x))))


def train(rows):
    X = [r["x"] for r in rows]
    y = [r["y"] for r in rows]
    mu, sd = standardize_fit(X)
    w, b = fit_logreg(transform(X, mu, sd), y, l2=3.0, lr=0.1, epochs=2000)
    return {"features": FEATURES, "w": w, "b": b, "mu": mu, "sd": sd}


def predict(model, rec, euro):
    x = make_features(rec, euro)
    z = model["b"] + sum(wi * (xi - mi) / si
                         for wi, xi, mi, si in zip(model["w"], x, model["mu"], model["sd"]))
    return sigmoid(z)


def rolling_eval(rows, folds=5):
    dates = sorted(set(r["date"] for r in rows))
    chunks = []
    for k in range(folds):
        lo, hi = len(dates) * k // folds, len(dates) * (k + 1) // folds
        ds = set(dates[lo:hi])
        chunks.append([r for r in rows if r["date"] in ds])

    oot = []
    for k in range(1, folds):
        tr = [r for j in range(k) for r in chunks[j]]
        te = chunks[k]
        model = train(tr)
        for r in te:
            oot.append((r, predict(model, r["rec"], r["euro"])))
        hit = sum(1 for r in te if (predict(model, r["rec"], r["euro"]) >= 0.5) == (r["y"] == 1)) / len(te)
        fav = sum(1 for r in te if (r["rec"]["hcp_listed"] < 0) == (r["y"] == 1)) / len(te)
        print(f"  折{k}: 测试 {len(te):<4} 模型 {hit*100:5.2f}%  押让球方 {fav*100:5.2f}%")

    n = len(oot)
    ys = [r["y"] for r, _ in oot]
    ps = [p for _, p in oot]
    brier = sum((p - y) ** 2 for p, y in zip(ps, ys)) / n
    hit = sum(1 for (r, p), y in zip(oot, ys) if (p >= 0.5) == (y == 1)) / n
    fav = sum(1 for r, _ in oot if (r["rec"]["hcp_listed"] < 0) == (r["y"] == 1)) / n
    print(f"\n样本外 n={n}: Brier {brier:.4f} 模型命中 {hit*100:.2f}% 押让球方 {fav*100:.2f}%")

    print("\n校准(预测概率5等分):")
    order = sorted(range(n), key=lambda i: ps[i])
    for b in range(5):
        idx = order[n * b // 5:n * (b + 1) // 5]
        pp = sum(ps[i] for i in idx) / len(idx)
        yy = sum(ys[i] for i in idx) / len(idx)
        print(f"  桶{b+1}: n={len(idx):<4} 预测 {pp*100:5.1f}%  实际 {yy*100:5.1f}%")

    print("\n选择性下注:")
    for th in (0.05, 0.08, 0.10, 0.12):
        sel = [(r, p) for r, p in oot if p >= 0.5 + th or p <= 0.5 - th]
        if not sel:
            continue
        h2 = sum(1 for r, p in sel if (p >= 0.5) == (r["y"] == 1)) / len(sel)
        f2 = sum(1 for r, _ in sel if (r["rec"]["hcp_listed"] < 0) == (r["y"] == 1)) / len(sel)
        print(f"  |p-0.5|>={th:.2f}: n={len(sel):<4} 模型 {h2*100:5.2f}% "
              f"(ROI≈{(h2*1.925-1)*100:+.1f}% 按水位0.925)  押让球方 {f2*100:5.2f}%")


def cmd_train():
    rows = load_samples()
    model = train(rows)
    json.dump(model, open(MODEL_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"用 {len(rows)} 场训练, 模型已保存: {MODEL_PATH}")
    for name, wi in zip(FEATURES, model["w"]):
        print(f"  {name:<12} {wi:+.4f}")


def cmd_eval():
    rows = load_samples()
    print(f"样本 {len(rows)}  日期 {rows[0]['date']}~{rows[-1]['date']}")
    rolling_eval(rows)


def cmd_predict(sid):
    model = json.load(open(MODEL_PATH, encoding="utf-8"))
    listings = json.load(open(LISTINGS, encoding="utf-8"))
    euro = json.load(open(EURO, encoding="utf-8"))
    rec, e = listings.get(sid), euro.get(sid)
    if not rec or not e:
        print("缺少该场数据(需 listings + euro 均已采集)")
        return
    p = predict(model, rec, e)
    side = "主队" if p >= 0.5 else "客队"
    strength = "强" if abs(p - 0.5) >= 0.10 else ("弱" if abs(p - 0.5) >= 0.05 else "无")
    print(f"{sid} {rec.get('league')} {rec.get('home')} vs {rec.get('away')}")
    print(f"  终盘盘口(主队视角) {rec['hcp_listed']:+.2f}  欧赔即时主胜 {e['p_close']*100:.1f}%")
    print(f"  主队赢盘概率 {p*100:.1f}%  ->  {side}  信号强度: {strength}")
    if "score" in rec:
        print(f"  实际比分 {rec['score']} (仅供核对)")


def cmd_predict_date(date):
    model = json.load(open(MODEL_PATH, encoding="utf-8"))
    listings = json.load(open(LISTINGS, encoding="utf-8"))
    euro = json.load(open(EURO, encoding="utf-8"))
    out = []
    for sid, rec in listings.items():
        if rec.get("date") != date or rec.get("hcp_listed") is None:
            continue
        e = euro.get(sid)
        if not e:
            continue
        p = predict(model, rec, e)
        out.append((abs(p - 0.5), sid, rec, e, p))
    out.sort(reverse=True)
    print(f"{date}: 共 {len(out)} 场可预测, 按信号强度排序")
    for _, sid, rec, e, p in out:
        side = "主" if p >= 0.5 else "客"
        print(f"  {sid} {rec.get('league','')[:6]:<6} hcp={rec['hcp_listed']:+5.2f} "
              f"p={p*100:5.1f}% -> {side}  ({rec.get('home','')} vs {rec.get('away','')})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", action="store_true")
    ap.add_argument("--eval", action="store_true")
    ap.add_argument("--predict")
    ap.add_argument("--predict-date")
    a = ap.parse_args()
    if a.train:
        cmd_train()
    elif a.eval:
        cmd_eval()
    elif a.predict:
        cmd_predict(a.predict)
    elif a.predict_date:
        cmd_predict_date(a.predict_date)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
