# -*- coding: utf-8 -*-
"""
亚盘赢盘预测模型 v2
====================
目标: 预测「亚盘让球赢盘方向」(主/客), 不是胜平负。
针对旧模型的问题做了以下约束:

1. 目标与结算统一: 用终盘让球数精确结算, 四分之一盘按半赢半输处理。
2. 不用手工加减分: 用带 L2 正则的逻辑回归输出概率。
3. 不做信号重复计分: 只保留「市场移动」类特征, 并剔除高度共线的原始变量。
4. 不再用「主胜概率」当「赢盘概率」: 欧赔只以变化量形式进入, 不直接判断方向。
5. 缺失值中性化: 同盘口赢盘率缺失时填 0(不提供信息), 不降低评分上限参与比较。
6. 同盘口极端值收缩: 0%/100% 向 50% 收缩, 避免小样本极值主导。
7. 评估只用样本外预测: 重复分层 K 折 + 跨批次验证, 不在全样本上报告命中率。
8. 如实报告: 若交叉验证没有超过基准, 直接说明「没有可靠 edge」。

特征(全部为初盘→终盘的变化量或初盘控制变量):
    hcp_move        盘口变化(终盘 - 初盘, 负=升盘)
    p_move          亚盘水位隐含主队赢盘概率的变化
    odds_edge_move  欧赔去水后(主胜-客胜)概率差的变化
    same_diff       相同盘口赢盘率差(收缩后, 主-客)
    hcp_depth       初盘深度 |h|
    p_open          初盘水位隐含主队赢盘概率(控制变量)
"""
import json
import math
import random
import re
import sys
from collections import defaultdict

BASE = r"g:\bet"

# ============================================================
# 一、盘口解析与结算(统一口径)
# ============================================================
HCP_MAP = {
    "平手": 0.0, "平/半": 0.25, "半球": 0.5, "半/一": 0.75,
    "一球": 1.0, "一/球半": 1.25, "球半": 1.5, "球半/两": 1.75,
    "两球": 2.0, "两/两球半": 2.25, "两球半": 2.5, "两球半/三": 2.75,
    "三球": 3.0, "三/三球半": 3.25, "三球半": 3.5, "三球半/四": 3.75,
    "四球": 4.0, "四/四球半": 4.25, "四球半": 4.5,
}


def hcp_to_num(text):
    """盘口文字 -> 主队视角让球数. 负=主队让球, 正=主队受让("*"开头)."""
    if not text:
        return None
    t = text.strip()
    receiving = t.startswith("*")
    if receiving:
        t = t[1:]
    if t in HCP_MAP:
        v = HCP_MAP[t]
    elif "/" in t:
        try:
            a, b = t.split("/")
            v = (float(a) + float(b)) / 2
        except Exception:
            return None
    else:
        try:
            v = float(t)
        except Exception:
            return None
    return v if receiving else -v


def settle(side, h, hg, ag, water_home, water_away):
    """精确亚盘结算. 返回单位收益(赢=水位, 输=-1, 走水=0, 四分之一盘各半)."""
    if side == "主":
        hh, water = h, water_home
        margin = (hg - ag) + hh
    else:
        hh, water = -h, water_away
        margin = (ag - hg) + hh
    x2 = hh * 2
    if abs(x2 - round(x2)) < 1e-9:
        subs = [hh]
    else:
        lo = math.floor(x2) / 2
        subs = [lo, lo + 0.5]
    total = 0.0
    for sub in subs:
        mm = margin + (sub - hh)
        if mm > 1e-9:
            total += water
        elif mm < -1e-9:
            total -= 1.0
    return total / len(subs)


def result_side(h, hg, ag):
    """真实赢盘方向: 主/客/走水."""
    m = (hg - ag) + h
    if m > 1e-9:
        return "主"
    if m < -1e-9:
        return "客"
    return "走水"


# ============================================================
# 二、数据加载
# ============================================================
def parse_score(s):
    nums = re.findall(r"\d+", str(s))
    if len(nums) < 2:
        return None
    return int(nums[0]), int(nums[1])


def build_sample(mid, league, home, away, score, oc, ac, oz, az, sh, sa, batch):
    sg = parse_score(score)
    if not sg or not ac or not az or not oc or not oz:
        return None
    h_open = hcp_to_num(ac[1])
    h_close = hcp_to_num(az[1])
    if h_open is None or h_close is None:
        return None
    return {
        "id": str(mid), "league": league, "home": home, "away": away,
        "hg": sg[0], "ag": sg[1], "batch": batch,
        "h_open": h_open, "h_close": h_close,
        "wo_h": float(ac[0]), "wo_a": float(ac[2]),
        "wc_h": float(az[0]), "wc_a": float(az[2]),
        "odds_open": list(oc), "odds_close": list(oz),
        "same_home_wr": sh, "same_away_wr": sa,
    }


def load_samples():
    sys.path.insert(0, BASE)
    from asian_handicap_verify_all import MATCHES as OLD37

    out = []
    for (mid, league, home, away, score, half, oc, ac, oz, az, sh, sa) in OLD37:
        s = build_sample(mid, league, home, away, score, oc, ac, oz, az, sh, sa, "old37")
        if s:
            out.append(s)

    with open(BASE + r"\match_list_20261015.json", encoding="utf-8") as f:
        matches = json.load(f)
    with open(BASE + r"\scraped_data.json", encoding="utf-8") as f:
        scraped = json.load(f)
    smap = {x["id"]: x for x in scraped}
    for m in matches:
        d = smap.get(m["id"])
        if not d:
            continue
        s = build_sample(m["id"], m["league"], m["home"], m["away"], m["score"],
                         d.get("odds_chu"), d.get("asian_chu"), d.get("odds_zhong"),
                         d.get("asian_zhong"), d.get("same_home_wr"), d.get("same_away_wr"),
                         "new55")
        if s:
            out.append(s)

    # 去重(两批理论上无重叠)
    seen = set()
    uniq = []
    for s in out:
        if s["id"] in seen:
            continue
        seen.add(s["id"])
        uniq.append(s)
    return uniq


# ============================================================
# 三、特征工程
# ============================================================
def odds_edge(o):
    """欧赔去水后的(主胜概率 - 客胜概率)."""
    ph, pd, pa = 1.0 / o[0], 1.0 / o[1], 1.0 / o[2]
    t = ph + pd + pa
    return ph / t - pa / t


def water_prob(home_water, away_water):
    """亚盘水位隐含主队赢盘概率(低水方概率更高)."""
    return away_water / (home_water + away_water)


def shrink_same_diff(sh, sa):
    """同盘口赢盘率差: 0/100 向 50 收缩, 缺失填 0."""
    if sh is None or sa is None:
        return 0.0
    sh = 0.5 + (sh / 100.0 - 0.5) * 0.8
    sa = 0.5 + (sa / 100.0 - 0.5) * 0.8
    return sh - sa


# odds_edge_move 与 hcp_move 相关系数约 -0.85, 二者描述同一件事(欧亚盘同步移动),
# 只保留与赢盘直接相关的亚盘移动 hcp_move, 避免重复计分。
FEATURES = ["hcp_move", "p_move", "same_diff", "hcp_depth", "p_open"]


def make_features(s):
    p_open = water_prob(s["wo_h"], s["wo_a"])
    p_close = water_prob(s["wc_h"], s["wc_a"])
    return {
        "hcp_move": s["h_close"] - s["h_open"],
        "p_move": p_close - p_open,
        "odds_edge_move": odds_edge(s["odds_close"]) - odds_edge(s["odds_open"]),
        "same_diff": shrink_same_diff(s["same_home_wr"], s["same_away_wr"]),
        "hcp_depth": abs(s["h_open"]),
        "p_open": p_open,
    }


def prepare(samples):
    X, y, meta = [], [], []
    for s in samples:
        actual = result_side(s["h_close"], s["hg"], s["ag"])
        if actual == "走水":
            continue
        f = make_features(s)
        X.append([f[k] for k in FEATURES])
        y.append(1 if actual == "主" else 0)
        meta.append({"sample": s, "actual": actual, "raw": f})
    return X, y, meta


# ============================================================
# 四、逻辑回归(L2) 与标准化
# ============================================================
def sigmoid(z):
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def standardize_fit(X):
    n, d = len(X), len(X[0])
    mean = [sum(row[j] for row in X) / n for j in range(d)]
    std = []
    for j in range(d):
        v = sum((row[j] - mean[j]) ** 2 for row in X) / n
        std.append(math.sqrt(v) if v > 1e-12 else 1.0)
    return mean, std


def transform(X, mean, std):
    return [[(row[j] - mean[j]) / std[j] for j in range(len(row))] for row in X]


def fit_logreg(X, y, l2=1.0, lr=0.15, epochs=900):
    n, d = len(X), len(X[0])
    w = [0.0] * d
    b = 0.0
    for _ in range(epochs):
        gw = [0.0] * d
        gb = 0.0
        for row, target in zip(X, y):
            p = sigmoid(b + sum(w[j] * row[j] for j in range(d)))
            err = p - target
            for j in range(d):
                gw[j] += err * row[j]
            gb += err
        for j in range(d):
            w[j] -= lr * (gw[j] / n + l2 * w[j] / n)
        b -= lr * gb / n
    return w, b


def predict_proba(model, x):
    w, b, mean, std = model
    z = b + sum(w[j] * (x[j] - mean[j]) / std[j] for j in range(len(w)))
    return sigmoid(z)


def fit_model(X, y):
    mean, std = standardize_fit(X)
    Xs = transform(X, mean, std)
    w, b = fit_logreg(Xs, y)
    return (w, b, mean, std)


# ============================================================
# 五、评估
# ============================================================
def stratified_folds(y, k, rng):
    pos = [i for i, v in enumerate(y) if v == 1]
    neg = [i for i, v in enumerate(y) if v == 0]
    rng.shuffle(pos)
    rng.shuffle(neg)
    folds = [[] for _ in range(k)]
    for arr in (pos, neg):
        for j, i in enumerate(arr):
            folds[j % k].append(i)
    return folds


def metrics(y, probs, meta_excluded=None):
    n = len(y)
    brier = sum((p - t) ** 2 for p, t in zip(probs, y)) / n
    ll = 0.0
    for p, t in zip(probs, y):
        p = min(max(p, 1e-6), 1 - 1e-6)
        ll -= t * math.log(p) + (1 - t) * math.log(1 - p)
    ll /= n
    return {"n": n, "brier": brier, "logloss": ll}


def backtest(probs, meta, threshold=0.55):
    """按概率阈值下注, 返回命中率/下注数/ROI."""
    bets = 0
    hits = 0
    profit = 0.0
    profits = []
    for p, m in zip(probs, meta):
        s = m["sample"]
        if p >= threshold:
            side = "主"
        elif p <= 1 - threshold:
            side = "客"
        else:
            continue
        bets += 1
        if side == m["actual"]:
            hits += 1
        v = settle(side, s["h_close"], s["hg"], s["ag"], s["wc_h"], s["wc_a"])
        profit += v
        profits.append(v)
    return {"bets": bets, "hits": hits, "hit_rate": hits / bets if bets else 0.0,
            "roi": profit / bets if bets else 0.0, "profit": profit, "profits": profits}


def wilson_ci(k, n, z=1.96):
    """Wilson 命中率置信区间."""
    if n == 0:
        return 0.0, 0.0
    p = k / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, center - half), min(1.0, center + half)


def all_in_benchmark(meta, side_rule):
    hits = 0
    profit = 0.0
    n = 0
    for m in meta:
        s = m["sample"]
        side = side_rule(s)
        n += 1
        if side == m["actual"]:
            hits += 1
        profit += settle(side, s["h_close"], s["hg"], s["ag"], s["wc_h"], s["wc_a"])
    return {"n": n, "hit_rate": hits / n, "roi": profit / n}


def repeated_cv(X, y, meta, k=5, repeats=10, seed=42, l2=1.0):
    rng = random.Random(seed)
    agg = defaultdict(list)
    oof_store = []
    for rep in range(repeats):
        folds = stratified_folds(y, k, rng)
        oof = [None] * len(y)
        for fi in range(k):
            test_idx = set(folds[fi])
            train_idx = [i for i in range(len(y)) if i not in test_idx]
            Xtr = [X[i] for i in train_idx]
            ytr = [y[i] for i in train_idx]
            model = fit_model(Xtr, ytr)
            for i in sorted(test_idx):
                oof[i] = predict_proba(model, X[i])
        probs = [p if p is not None else 0.5 for p in oof]
        oof_store.append(probs)
        mt = metrics(y, probs)
        for key, val in mt.items():
            agg[key].append(val)
        for th in (0.5, 0.55, 0.60):
            bt = backtest(probs, meta, threshold=th)
            agg[f"hit_{th}"].append(bt["hit_rate"])
            agg[f"bets_{th}"].append(bt["bets"])
            agg[f"roi_{th}"].append(bt["roi"])
    return agg, oof_store


def summarize(agg, key):
    vals = agg[key]
    if not vals:
        return 0.0, 0.0
    m = sum(vals) / len(vals)
    if len(vals) < 2:
        return m, 0.0
    sd = math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))
    return m, sd


# ============================================================
# 六、输出
# ============================================================
def main():
    samples = load_samples()
    X, y, meta = prepare(samples)

    print("=" * 92)
    print("  亚盘赢盘模型 v2  |  目标: 让球赢盘方向  |  评估: 样本外预测")
    print("=" * 92)
    print(f"样本总数 {len(samples)} 场 | 有效(剔除走水) {len(y)} 场 | "
          f"主赢盘 {sum(y)} | 客赢盘 {len(y)-sum(y)}")
    from collections import Counter
    print("批次分布:", dict(Counter(m["sample"]["batch"] for m in meta)))

    # ---- 特征相关矩阵 ----
    print("\n" + "-" * 92)
    print("特征相关性(绝对值>0.7视为共线, 需关注)")
    print("-" * 92)
    d = len(FEATURES)
    print("            " + "".join(f"{f[:12]:>14}" for f in FEATURES))
    for i, fi in enumerate(FEATURES):
        row = []
        for j in range(d):
            xi = [m["raw"][fi] for m in meta]
            xj = [m["raw"][FEATURES[j]] for m in meta]
            mi = sum(xi) / len(xi)
            mj = sum(xj) / len(xj)
            cov = sum((a - mi) * (b - mj) for a, b in zip(xi, xj))
            si = math.sqrt(sum((a - mi) ** 2 for a in xi))
            sj = math.sqrt(sum((b - mj) ** 2 for b in xj))
            r = cov / (si * sj) if si * sj > 1e-12 else 0.0
            row.append(r)
        print(f"{fi:<12}" + "".join(f"{v:>14.2f}" for v in row))

    # ---- 单变量检验 ----
    print("\n" + "-" * 92)
    print("单变量与主队赢盘的相关性 / 三分组赢盘率")
    print("-" * 92)
    for f in FEATURES:
        vals = [m["raw"][f] for m in meta]
        mv = sum(vals) / len(vals)
        yv = sum(y) / len(y)
        cov = sum((a - mv) * (b - yv) for a, b in zip(vals, y))
        sv = math.sqrt(sum((a - mv) ** 2 for a in vals))
        sy = math.sqrt(sum((b - yv) ** 2 for b in y))
        r = cov / (sv * sy) if sv * sy > 1e-12 else 0.0
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        groups = []
        for gi in range(3):
            seg = order[gi * len(order) // 3:(gi + 1) * len(order) // 3]
            rate = sum(y[i] for i in seg) / len(seg)
            groups.append(rate)
        print(f"{f:<14} r={r:+.3f}   低/中/高三分组主赢盘率: "
              f"{groups[0]*100:.0f}% / {groups[1]*100:.0f}% / {groups[2]*100:.0f}%")

    # ---- 重复分层交叉验证 ----
    print("\n" + "=" * 92)
    print("重复分层 5 折交叉验证 (10 次重复, 全部为样本外预测)")
    print("=" * 92)
    agg, oofs = repeated_cv(X, y, meta, k=5, repeats=10, seed=42)

    brier_m, brier_sd = summarize(agg, "brier")
    ll_m, ll_sd = summarize(agg, "logloss")
    print(f"Brier {brier_m:.4f} ± {brier_sd:.4f}   (0.25=随机, 越低越好)")
    print(f"LogLoss {ll_m:.4f} ± {ll_sd:.4f}")

    # 全样本(无阈值)方向命中率: 用 OOF 概率
    all_probs = [sum(rep[i] for rep in oofs) / len(oofs) for i in range(len(y))]
    no_thresh = backtest(all_probs, meta, threshold=0.5)
    lo, hi = wilson_ci(no_thresh["hits"], no_thresh["bets"])
    profits = no_thresh["profits"]
    roi_se = 0.0
    if len(profits) > 1:
        pm = sum(profits) / len(profits)
        psd = math.sqrt(sum((v - pm) ** 2 for v in profits) / (len(profits) - 1))
        roi_se = psd / math.sqrt(len(profits))
    print(f"方向命中率(p>0.5押主, 全部出手): {no_thresh['hits']}/{no_thresh['bets']} = "
          f"{no_thresh['hit_rate']*100:.1f}%  95%CI[{lo*100:.1f}%, {hi*100:.1f}%]  "
          f"ROI {no_thresh['roi']*100:+.1f}% ± {roi_se*100:.1f}")

    sp = sorted(all_probs)
    def q(p):
        return sp[min(len(sp) - 1, int(p * len(sp)))]
    print(f"OOF概率分位 10/25/50/75/90%: {q(0.1):.3f} / {q(0.25):.3f} / "
          f"{q(0.5):.3f} / {q(0.75):.3f} / {q(0.9):.3f}")

    for th in (0.55, 0.60):
        h_m, h_sd = summarize(agg, f"hit_{th}")
        b_m, b_sd = summarize(agg, f"bets_{th}")
        r_m, r_sd = summarize(agg, f"roi_{th}")
        print(f"阈值{th:.2f}: 平均下注 {b_m:.1f} 场  命中率 {h_m*100:.1f}% ± {h_sd*100:.1f}  "
              f"ROI {r_m*100:+.1f}% ± {r_sd*100:.1f}")

    # ---- 基准 ----
    print("\n" + "-" * 92)
    print("同口径基准(全部出手, 不加过滤)")
    print("-" * 92)
    b_home = all_in_benchmark(meta, lambda s: "主")
    b_away = all_in_benchmark(meta, lambda s: "客")
    b_fav = all_in_benchmark(meta, lambda s: "主" if s["h_close"] < 0 else "客")
    b_dog = all_in_benchmark(meta, lambda s: "客" if s["h_close"] < 0 else "主")
    print(f"全押主   {b_home['hit_rate']*100:.1f}%  ROI {b_home['roi']*100:+.1f}%")
    print(f"全押客   {b_away['hit_rate']*100:.1f}%  ROI {b_away['roi']*100:+.1f}%")
    print(f"全押上盘 {b_fav['hit_rate']*100:.1f}%  ROI {b_fav['roi']*100:+.1f}%")
    print(f"全押下盘 {b_dog['hit_rate']*100:.1f}%  ROI {b_dog['roi']*100:+.1f}%")

    # ---- 跨批次验证 ----
    print("\n" + "-" * 92)
    print("跨批次验证(用一批训练, 另一批完全留出)")
    print("-" * 92)
    old_idx = [i for i, m in enumerate(meta) if m["sample"]["batch"] == "old37"]
    new_idx = [i for i, m in enumerate(meta) if m["sample"]["batch"] == "new55"]
    cross_results = []
    for train_name, train_idx, test_name, test_idx in [
        ("old37", old_idx, "new55", new_idx),
        ("new55", new_idx, "old37", old_idx),
    ]:
        if len(train_idx) < 20 or len(test_idx) < 10:
            continue
        model = fit_model([X[i] for i in train_idx], [y[i] for i in train_idx])
        probs = [predict_proba(model, X[i]) for i in test_idx]
        mt = metrics([y[i] for i in test_idx], probs)
        bt = backtest(probs, [meta[i] for i in test_idx], threshold=0.55)
        bt0 = backtest(probs, [meta[i] for i in test_idx], threshold=0.5)
        cross_results.append({"train": train_name, "test": test_name,
                              "roi": bt["roi"], "hit": bt["hit_rate"], "bets": bt["bets"],
                              "roi_all": bt0["roi"], "hit_all": bt0["hit_rate"]})
        print(f"训练 {train_name:<6} -> 测试 {test_name:<6}  "
              f"测试集 {len(test_idx):>2} 场  Brier {mt['brier']:.4f}  "
              f"全出手命中 {bt0['hit_rate']*100:.1f}% ROI {bt0['roi']*100:+.1f}%  |  "
              f"阈值0.55: 下注{bt['bets']} 命中{bt['hit_rate']*100:.1f}% ROI {bt['roi']*100:+.1f}%")

    # ---- 最终模型系数 ----
    print("\n" + "=" * 92)
    print("最终模型(全样本拟合, 仅用于查看方向; 其系数不代表样本外效果)")
    print("=" * 92)
    w, b, mean, std = fit_model(X, y)
    print(f"截距 {b:+.4f}")
    for f, coef in sorted(zip(FEATURES, w), key=lambda x: -abs(x[1])):
        print(f"  {f:<14} 标准化系数 {coef:+.4f}")
    print("\n系数为正 => 该特征增大时更倾向主队赢盘。")

    # ---- 结论 ----
    print("\n" + "=" * 92)
    print("结论")
    print("=" * 92)
    h55_m, _ = summarize(agg, "hit_0.55")
    r55_m, _ = summarize(agg, "roi_0.55")
    base_best = max(b_home["hit_rate"], b_away["hit_rate"], b_fav["hit_rate"], b_dog["hit_rate"])
    cross_rois = ", ".join(f"{x['roi']*100:+.1f}%" for x in cross_results)
    cross_pos = len(cross_results) == 2 and all(x["roi"] > 0 for x in cross_results)
    brier_ok = brier_m < 0.25

    print(f"  Brier {brier_m:.4f} 是否优于随机 0.25: {'是' if brier_ok else '否'}")
    print(f"  跨批次阈值0.55 ROI 是否同为正: {'是' if cross_pos else '否'} ({cross_rois})")
    print(f"  CV阈值0.55 命中 {h55_m*100:.1f}% / 基准最高 {base_best*100:.1f}% / ROI {r55_m*100:+.1f}%")

    if brier_ok and cross_pos and r55_m > 0 and h55_m > base_best:
        print("\n结论: 出现初步 edge 迹象, 但 85 场样本仍不足以确认, 只能小注验证。")
    else:
        print("\n结论: 当前 92 场数据上没有可靠 edge。")
        print("      概率输出可用于观察市场定价, 但不应据此真实下注。")
        print("      下一步应先补数据(至少数百场、覆盖多个时间窗), 再重跑本脚本。")


# ============================================================
# 七、对新比赛预测
# ============================================================
_MODEL_CACHE = None


def get_final_model():
    global _MODEL_CACHE
    if _MODEL_CACHE is None:
        samples = load_samples()
        X, y, _ = prepare(samples)
        _MODEL_CACHE = fit_model(X, y)
    return _MODEL_CACHE


def predict_win_prob(hcp_open, home_water_open, away_water_open,
                     hcp_close, home_water_close, away_water_close,
                     odds_open, odds_close,
                     same_home_wr=None, same_away_wr=None):
    """
    对新比赛返回 (主队赢盘概率, 客队赢盘概率)。

    参数:
        hcp_open / hcp_close   盘口文字, 如 "半球" / "*平/半"(受让)
        home_water_* / away_water_*  主/客水位
        odds_open / odds_close 欧赔 [主胜, 平, 客胜]
        same_home_wr / same_away_wr  相同盘口赢盘率(百分数, 可缺省)

    注意: 这是研究用概率输出, 当前样本量下未经验证, 不应直接用于下注。
    """
    s = {
        "h_open": hcp_to_num(hcp_open), "h_close": hcp_to_num(hcp_close),
        "wo_h": home_water_open, "wo_a": away_water_open,
        "wc_h": home_water_close, "wc_a": away_water_close,
        "odds_open": list(odds_open), "odds_close": list(odds_close),
        "same_home_wr": same_home_wr, "same_away_wr": same_away_wr,
    }
    if s["h_open"] is None or s["h_close"] is None:
        raise ValueError("盘口文字无法解析")
    f = make_features(s)
    p = predict_proba(get_final_model(), [f[k] for k in FEATURES])
    return p, 1.0 - p


if __name__ == "__main__":
    main()
