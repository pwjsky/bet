# -*- coding: utf-8 -*-
"""
今日亚盘推荐
============
流程:
  1. 抓 https://bf.titan007.com/football/Next_YYYYMMDD.htm  当天赛程(含已开赛)
  2. 逐场抓 http://1x2d.titan007.com/{sid}.js               初盘/即时欧赔
  3. p_move = 即时去水主胜概率 - 初盘去水主胜概率
  4. 用 titan_data 历史样本训练"单特征 p_move"逻辑回归, 再用保序回归表校准概率
  5. 抓赛前真实亚盘水位, 算 EV = 押注方赢盘率 x (1+水位) - 1
  6. 阈值制出单: |p_raw-0.5| >= --min-sig(默认 0.12) 即出单, 不再取前 N 名
     - 好处: 中午买过的单不会被晚上的更强信号挤掉, 达标即锁定
     - 门槛 0.12 是按现网训练参数(lr=0.1/1500 步)在 2026-01~10 全量数据上校准的:
       1072 注 / 259 天, 命中 64.3%, ROI +19.82%, 日均 4.14 注, 最大回撤 -5.78U
     - 对照: 0.13 = 798 注 / ROI +22.62%; 0.14 = 600 注 / ROI +25.62%
     - 注意: 回测脚本用 lr=0.3/2500 步, |p-0.5| 尺度更宽, 那边的 0.12 约等于这里的 0.15
  7. 方差加权: 用历史 euro.json 算 |p_move| 上 1/3 档的 p_std 中位数,
     排序分改为 sig * (std/med)^0.5, 只影响展示顺序, 不剔除任何场次
  8. 盘口偏离加权: 用欧赔 1x2 反推预期净胜球(理论让球), 与实际皇冠盘口比较,
     排序分再乘 (|dev|/med)^0.5, dev = 理论让球 - 实际让球

为什么按信号强度排序, 而不是按 EV 排序:
  逐日 Top10 实测(样本外 24 天) 按 |p-0.5| 排序 67.5% 命中 ROI +23.48%,
  按 EV 排序只有 60.8% / +18.23%。EV 排序会优先挑高水位场次(水位 0.978 vs 0.864),
  那些多是小联赛, 模型并不更准; 信号强度才对应模型真正确定的方向。
  EV 的正确用法是过滤(剔除水位太差的场), 不是排序。

用法:
  py today_picks.py
  py today_picks.py --date 20261018
  py today_picks.py --min-sig 0.16 --min-n 50
  py today_picks.py --top 5          # 只要前 5 注(临时收窄)
  py today_picks.py --min-ev 0.0     # 只保留 EV 为正的

为什么只用 p_move:
  未开赛页面不返回亚盘数值, 实时接口拿到的是走地盘残留。
  单特征模型不需要盘口, 样本外 Top5 74% / Top10 66.5%, 与全特征相当。
"""
import argparse
import ast
import json
import math
import os
import re
import ssl
import statistics
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from asian_handicap_model_v3 import (  # noqa: E402
    devig, fit_logreg, load_samples, standardize_fit, transform,
)

DATA_DIR = os.path.join(BASE, "titan_data")
CALIB_PATH = os.path.join(DATA_DIR, "calibration.json")
EURO_PATH = os.path.join(DATA_DIR, "euro.json")
WATER_PATH = os.path.join(DATA_DIR, "water.json")
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
HDR = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": "https://bf.titan007.com/",
}


def fetch(url, retries=3):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HDR)
            with urllib.request.urlopen(req, timeout=20, context=CTX) as r:
                raw = r.read()
            for enc in ("gbk", "utf-8", "gb18030"):
                try:
                    return raw.decode(enc)
                except Exception:
                    continue
            return raw.decode("utf-8", errors="ignore")
        except Exception as e:
            last = e
            if attempt < retries - 1:
                import time
                time.sleep(0.8 * (attempt + 1))
    raise last


def strip_tags(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s).replace("&nbsp;", " ")).strip()


def parse_schedule(day):
    """返回当天未开赛比赛列表。"""
    html = fetch("https://bf.titan007.com/football/Next_%s.htm" % day)
    rows = re.findall(r"(<tr[^>]*sId='\d+'[^>]*>.*?</tr>)", html, re.S)
    out = []
    for row in rows:
        sid = re.search(r"sId='(\d+)'", row).group(1)
        tds = [strip_tags(t) for t in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(tds) < 6:
            continue
        league, tm, status, home, score, away = tds[:6]
        if status in ("取消", "推迟", "腰斩"):   # 只排除确定不打的
            continue
        # 已开赛/有比分也保留: 一天多次运行时候选池保持一致, 不会每次换一批
        out.append({"sid": sid, "league": league, "time": tm,
                    "home": home, "away": away, "score": score})
    return out


def grab_odds(g):
    txt = fetch("http://1x2d.titan007.com/%s.js" % g["sid"])
    m = re.search(r"var\s+game\s*=\s*Array\((.*?)\)\s*;", txt, re.S)
    if not m:
        return None
    opens, closes = [], []
    for it in re.findall(r'"([^"]*)"', m.group(1)):
        f = it.split("|")
        if len(f) < 17:
            continue
        try:
            o = [float(f[3]), float(f[4]), float(f[5])]
            c = [float(f[10]), float(f[11]), float(f[12])]
        except ValueError:
            continue
        if min(o) > 1 and min(c) > 1:
            opens.append(o)
            closes.append(c)
    if not opens or not closes:
        return None
    mo = [statistics.median(x[i] for x in opens) for i in range(3)]
    mc = [statistics.median(x[i] for x in closes) for i in range(3)]
    g["odds_open"] = [round(x, 3) for x in mo]
    g["odds_close"] = [round(x, 3) for x in mc]
    g["p_close"] = devig(mc)[0]
    g["p_move"] = devig(mc)[0] - devig(mo)[0]
    g["p_std"] = statistics.pstdev([devig(x)[0] for x in closes]) if len(closes) > 1 else 0.0
    g["n_company"] = len(closes)
    return g


def sigmoid(x):
    return 1 / (1 + math.exp(-max(-30, min(30, x))))


def load_calib():
    """加载保序回归校准表 [(p_lo, p_hi, 实际命中率), ...]"""
    if not os.path.exists(CALIB_PATH):
        return None
    try:
        d = json.load(open(CALIB_PATH, encoding="utf-8"))
        return [tuple(x) for x in d.get("iso_edges", [])]
    except Exception:
        return None


def apply_calib(edges, p):
    """分段线性插值, 保持单调, 避免阶梯化丢失排序。"""
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


def find_array(txt, name):
    i = txt.find("var " + name)
    if i < 0:
        return None
    j = txt.find("[", i)
    if j < 0:
        return None
    depth = 0
    for k in range(j, len(txt)):
        if txt[k] == "[":
            depth += 1
        elif txt[k] == "]":
            depth -= 1
            if depth == 0:
                return txt[j:k + 1]
    return None


def parse_rows(txt, name):
    s = find_array(txt, name)
    if not s:
        return []
    while ",," in s:                 # JS 稀疏数组 [,,] 补空位
        s = s.replace(",,", ",''")
    try:
        return ast.literal_eval(s)
    except Exception:
        return []


def as_float(v, lo, hi):
    try:
        x = float(v)
    except Exception:
        return None
    return x if lo <= x <= hi else None


def grab_water(sid):
    """抓赛前真实亚盘: 盘口 + 主/客水位。返回 {'crown': {...}, 'bet365': {...}}"""
    url = "https://live.titan007.com/jsData/%s/%s/%s.js" % (sid[:2], sid[2:4], sid)
    req = urllib.request.Request(url, headers={
        "User-Agent": HDR["User-Agent"],
        "Referer": "https://zq.titan007.com/analysis/%s.htm" % sid,
    })
    with urllib.request.urlopen(req, timeout=20, context=CTX) as r:
        txt = r.read().decode("utf-8", "ignore")
    out = {}
    for name, key in (("sOdds", "crown"), ("sOdds8", "bet365")):
        rows = parse_rows(txt, name)
        pre = [r for r in rows if len(r) > 14 and r[0] in ("早餐", "未开场")]
        if not pre:
            continue
        last = pre[-1]
        hcp = as_float(last[10], -10, 10)
        wh = as_float(last[9], 0.5, 1.5)
        wa = as_float(last[11], 0.5, 1.5)
        if hcp is None or wh is None or wa is None:
            continue
        out[key] = {"hcp": hcp, "wo_h": wh, "wo_a": wa}
    return out


def train_pmove():
    rows = load_samples()
    X = [[r["x"][4]] for r in rows]          # 索引 4 = p_move
    mu, sd = standardize_fit(X)
    w, b = fit_logreg(transform(X, mu, sd), [r["y"] for r in rows],
                      l2=3.0, lr=0.1, epochs=1500)
    return rows, w[0], b, mu[0], sd[0]


_GRID = None


def poisson_grid():
    """(λh, λa, P主胜, P平, P客胜) 网格, 用于由 1x2 概率反推预期净胜球"""
    global _GRID
    if _GRID is not None:
        return _GRID
    import numpy as np
    k = np.arange(0, 13)
    fact = np.array([math.factorial(int(x)) for x in k], float)
    lams = np.round(np.arange(0.15, 4.01, 0.05), 2)
    pmf = {l: np.exp(-l) * l ** k / fact for l in lams}
    rows = []
    for lh in lams:
        for la in lams:
            m = np.outer(pmf[lh], pmf[la])
            rows.append((lh, la, np.tril(m, -1).sum(), np.trace(m), np.triu(m, 1).sum()))
    _GRID = np.array(rows)
    return _GRID


def implied_margin(probs, chunk=2000):
    """[(p主,p平,p客), ...] -> [预期净胜球 λh-λa, ...]"""
    import numpy as np
    g = poisson_grid()
    out = []
    for i in range(0, len(probs), chunk):
        p = np.asarray(probs[i:i + chunk], float)
        d = ((g[None, :, 2] - p[:, None, 0]) ** 2
             + (g[None, :, 3] - p[:, None, 1]) ** 2
             + (g[None, :, 4] - p[:, None, 2]) ** 2)
        idx = d.argmin(1)
        out.extend((g[idx, 0] - g[idx, 1]).tolist())
    return out


def var_threshold(day, min_hist=1000):
    """历史(day 之前)的 |p_move| 上 1/3 分位, 以及该档的 p_std / |理论盘-实际盘| 中位数。

    强信号里只有即时分歧高于这个中位数的场次才有超额收益;
    欧赔隐含让球与实际让球偏离越大, 命中率越高。
    """
    if not (os.path.exists(EURO_PATH) and os.path.exists(WATER_PATH)):
        return None
    day = str(day)
    try:
        euro = json.load(open(EURO_PATH, encoding="utf-8"))
        water = json.load(open(WATER_PATH, encoding="utf-8"))
    except Exception:
        return None
    pm, std, items = [], [], []
    for sid, r in euro.items():
        if (r.get("date") or "") >= day:
            continue
        if r.get("p_move") is None or r.get("p_std_close") is None:
            continue
        pm.append(abs(r["p_move"]))
        std.append(r["p_std_close"])
        w = (water.get(sid) or {}).get("crown")
        if w and w.get("hcp_close") is not None and r.get("odds_close"):
            items.append((abs(r["p_move"]), r["odds_close"], w["hcp_close"]))
    if len(pm) < min_hist:
        return None
    s = sorted(pm)
    q67 = s[int(len(s) * 2 / 3)]
    top = [v for p, v in zip(pm, std) if p >= q67]
    out = {"q67": q67, "med_std": statistics.median(top),
           "n": len(pm), "n_top": len(top), "med_dev": None}
    strong = [x for x in items if x[0] >= q67]
    if len(strong) >= 300:
        devs = [abs(m - h) for m, (_, _, h) in
                zip(implied_margin([devig(x[1]) for x in strong]), strong)]
        out["med_dev"] = statistics.median(devs) or 1e-9
        out["n_dev"] = len(strong)
    return out


def parse_kickoff(time_str, day):
    """'10-17 18:30' + '20261017' -> datetime"""
    m = re.match(r"(\d{2})-(\d{2})\s+(\d{2}):(\d{2})", time_str.strip())
    if not m:
        return None
    mo, dd, hh, mi = (int(x) for x in m.groups())
    return datetime(int(day[:4]), mo, dd, hh, mi)


def brief_pick(g):
    return {"sid": g["sid"], "match": g["home"] + " vs " + g["away"],
            "league": g.get("league"), "kickoff": g.get("kickoff"),
            "side": "主" if g["side"] == 1 else "客",
            "hcp": g.get("hcp"), "odds": g.get("odds"),
            "ev": round(g["ev"], 4) if g.get("ev") is not None else None}


def brief_full(g):
    d = brief_pick(g)
    d["p"] = round(g["p"], 4) if g.get("p") is not None else None
    d["sig_cal"] = round(g["sig_cal"], 4) if g.get("sig_cal") is not None else None
    d["dev"] = round(g["dev"], 3) if g.get("dev") is not None else None
    d["std"] = round(g["p_std"], 4) if g.get("p_std") is not None else None
    return d


def log_change(day, prev, cur):
    """top5 有变动时追加记录到 top5_changes.json"""
    o = {g["sid"]: g for g in prev}
    n = {g["sid"]: g for g in cur}
    kept = [s for s in n if s in o and n[s]["side"] == o[s]["side"]
            and n[s].get("hcp") == o[s].get("hcp")]
    removed = [s for s in o if s not in n]
    added = [s for s in n if s not in o]
    if not removed and not added and len(kept) == len(n):
        return
    path = os.path.join(DATA_DIR, "top5_changes.json")
    hist = []
    if os.path.exists(path):
        try:
            hist = json.load(open(path, encoding="utf-8"))
        except Exception:
            hist = []
    hist.append({"date": day, "run_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 "kept": [brief_pick(n[s]) for s in kept],
                 "removed": [brief_pick(o[s]) for s in removed],
                 "added": [brief_pick(n[s]) for s in added]})
    json.dump(hist, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    spath = os.path.join(DATA_DIR, "top5_snapshots.json")
    snaps = []
    if os.path.exists(spath):
        try:
            snaps = json.load(open(spath, encoding="utf-8"))
        except Exception:
            snaps = []
    snaps.append({"date": day, "run_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                  "picks": [brief_full(g) for g in cur]})
    json.dump(snaps, open(spath, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("top5 变动: 保留 %d, 移除 %d, 新增 %d -> %s"
          % (len(kept), len(removed), len(added), path))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now().strftime("%Y%m%d"))
    ap.add_argument("--top", type=int, default=0,
                    help="最多出几注, 0=不限制(达标全出, 默认)")
    ap.add_argument("--min-n", type=int, default=30, help="最少欧赔公司数")
    ap.add_argument("--min-sig", type=float, default=0.12,
                    help="最小 |p_raw-0.5|, 默认 0.12(日均约 4.1 注, ROI +19.8%%)")
    ap.add_argument("--min-ev", type=float, default=None,
                    help="最小 EV 过滤, 如 0.0; 不填则不过滤")
    ap.add_argument("--no-var-filter", action="store_true",
                    help="关闭方差加权(默认开启)")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()

    now = datetime.now()
    games = parse_schedule(a.date)
    if not games:
        print("没有取到 %s 的赛程(页面可能未生成)" % a.date)
        return
    print("%s 赛程 %d 场(含已开赛)" % (a.date, len(games)))

    done = []
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(grab_odds, dict(g)): g for g in games}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                r = f.result()
                if r:
                    done.append(r)
            except Exception:
                pass
            if i % 300 == 0:
                print("  抓取 [%d/%d] 有欧赔 %d" % (i, len(games), len(done)))
    print("有欧赔 %d 场" % len(done))

    rows, w, b, mu, sd = train_pmove()
    edges = load_calib()
    print("模型 w=%+.4f b=%+.4f 训练 %d 场%s"
          % (w, b, len(rows), "" if edges else " (无校准表)"))

    picks = []
    for g in done:
        if g["n_company"] < a.min_n:
            continue
        g["p_raw"] = sigmoid(b + w * (g["p_move"] - mu) / sd)
        g["p"] = apply_calib(edges, g["p_raw"])
        g["sig"] = abs(g["p_raw"] - 0.5)      # 排序/过滤用原始概率, 保留区分度
        g["sig_cal"] = abs(g["p"] - 0.5)      # 强度标签用校准概率
        if g["sig"] < a.min_sig:
            continue
        ko = parse_kickoff(g["time"], a.date)
        g["kickoff"] = ko.strftime("%m-%d %H:%M") if ko else g["time"]
        today = now.strftime("%Y%m%d")
        g["started"] = bool(ko <= now) if ko else bool(a.date < today)
        picks.append(g)

    wmed = dmed = None
    vt = None if a.no_var_filter else var_threshold(a.date)
    if vt:
        wmed = vt["med_std"] or 1e-9
        dmed = vt.get("med_dev")
        # 方差加权: score = sig * (std/med)^0.5, 不剔除任何场次
        picks.sort(key=lambda g: -(g["sig"] * (g["p_std"] / wmed) ** 0.5))
        print("方差加权(历史 %d 场, 强档 std 中位 %.4f%s), 候选 %d 场"
              % (vt["n"], vt["med_std"],
                 "" if not dmed else ", 理论盘偏离中位 %.3f" % dmed, len(picks)))
    else:
        picks.sort(key=lambda g: -g["sig"])
        print("方差加权: 历史样本不足或未启用")

    cand = picks if a.top <= 0 else picks[:a.top * 10]

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(grab_water, g["sid"]): g for g in cand}
        for f in as_completed(futs):
            g = futs[f]
            try:
                g["water"] = f.result()
            except Exception:
                g["water"] = {}

    for g in cand:
        g["side"] = 1 if g["p"] >= 0.5 else -1
        book = g["water"].get("crown") or g["water"].get("bet365")
        g["book"] = "皇冠" if g["water"].get("crown") else "365"
        if book:
            g["hcp"] = book["hcp"]
            g["odds"] = book["wo_h"] if g["side"] == 1 else book["wo_a"]
            p_side = g["p"] if g["side"] == 1 else 1 - g["p"]
            g["ev"] = p_side * (1 + g["odds"]) - 1
        else:
            g["hcp"] = g["odds"] = g["ev"] = None

    subs = []
    for g in cand:
        g["dev"] = None
        bk = g["water"].get("crown") or g["water"].get("bet365")
        if bk and g.get("odds_close"):
            subs.append((g, bk["hcp"]))
    if subs and dmed:
        for (g, h), m in zip(subs, implied_margin([devig(x["odds_close"]) for x, _ in subs])):
            g["dev"] = m - h

    def rank_score(g):
        s = g["sig"] * (g["p_std"] / wmed) ** 0.5 if wmed else g["sig"]
        if dmed and g["dev"] is not None:
            s *= (abs(g["dev"]) / dmed) ** 0.5
        return s

    cand.sort(key=lambda g: -rank_score(g))
    if a.min_ev is None:
        picks = cand
    else:
        picks = [g for g in cand if g["ev"] is not None and g["ev"] >= a.min_ev]
    if a.top > 0:
        picks = picks[:a.top]

    out = os.path.join(DATA_DIR, "today_picks_%s.json" % a.date)
    prev = []
    if os.path.exists(out):
        try:
            prev = json.load(open(out, encoding="utf-8"))
        except Exception:
            prev = []

    # 只增不减: 当天此前已出的单, 即使重算后跌破门槛也保留
    # 这样中午买过的单不会被晚上的新单挤掉, 是阈值制相对 top5 的核心差别
    cur_sids = {g["sid"] for g in picks}
    locked = []
    for g in prev:
        if g["sid"] in cur_sids:
            continue
        g = dict(g, locked=True)
        ko = parse_kickoff(g.get("time") or "", a.date)
        g["started"] = bool(ko <= now) if ko else bool(a.date < now.strftime("%Y%m%d"))
        locked.append(g)
    if locked:
        picks = locked + picks

    if not picks:
        print("\n今天没有达标场次(门槛 |p_raw-0.5| >= %.2f), 空仓。" % a.min_sig)
        json.dump(picks, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        return
    if locked:
        print("\n锁定保留 %d 注(重算后已跌破 %.2f, 按只增不减不下调)" % (len(locked), a.min_sig))

    print("\n%-3s %-11s %-9s %-22s %-4s %-4s %-4s %6s %6s %7s %5s %7s %6s %6s %4s"
          % ("#", "开赛", "联赛", "对阵", "状态", "方向", "来源", "校准", "原始",
             "盘口", "水位", "EV", "std", "dev", "强度"))
    for i, g in enumerate(picks, 1):
        level = "强" if g["sig_cal"] >= 0.15 else ("中" if g["sig_cal"] >= 0.10 else "弱")
        hcp = "-" if g["hcp"] is None else ("%+.2f" % g["hcp"])
        odds = "-" if g["odds"] is None else "%.2f" % g["odds"]
        ev = "-" if g["ev"] is None else "%+.1f%%" % (100 * g["ev"])
        std_s = "-" if g.get("p_std") is None else "%.3f" % g["p_std"]
        dev_s = "-" if g.get("dev") is None else "%+.2f" % g["dev"]
        state = "已开" if g.get("started") else "未开"
        src = "锁" if g.get("locked") else "新"
        print("%-3d %-11s %-9s %-22s %-4s %-4s %-4s %5.1f%% %5.1f%% %7s %5s %7s %6s %6s %4s"
              % (i, g["kickoff"], g["league"][:8],
                 (g["home"] + " vs " + g["away"])[:22], state,
                 "主" if g["side"] == 1 else "客", src, g["p"] * 100,
                 g["p_raw"] * 100, hcp, odds, ev, std_s, dev_s, level))

    print("\n盘口为主队视角(正=主让); 水位为净水位, 押1赢0.89则总回报1.89")
    print("EV = 赢盘率 x (1+水位) - 1; 已按信号强度排序, EV 用于判断水位是否值得打")
    print("dev = 欧赔隐含净胜球 - 皇冠实际让球; |dev| 越大盘口越偏离, 排序权重越高")
    print("来源: 新=本轮达标; 锁=此前已出单, 本轮重算跌破门槛仍保留")

    json.dump(picks, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if prev:
        log_change(a.date, prev, picks)
    print("\n已保存 %s" % out)
    print("提醒: 达标即出, 不需要抢时点; 已出的单不会被后续重算撤掉。")


if __name__ == "__main__":
    main()
