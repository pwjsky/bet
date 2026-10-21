# -*- coding: utf-8 -*-
"""
titan007 数据采集器
====================
数据来源:
  1. 比分页  https://bf.titan007.com/football/Over_YYYYMMDD.htm
      -> 当天全部完赛比赛: sId / 联赛 / 主客队 / 全场比分 / 半场比分
  2. 分析页  https://zq.titan007.com/analysis/{sId}sb.htm
      -> 亚盘 Vs_hOdds (多公司初盘/即时盘口+水位)
      -> 欧赔 Vs_eOdds (多公司初盘/即时)
      -> 相同盘路 TeamPk_letGoal_* (同盘口赢盘率)
  3. 直播页  https://live.titan007.com/detail/{sId}sb.htm  (可选, 赛后数据)
      -> 场地/天气/技术统计/首发阵容/身价
      注意: 技术统计是赛后数据, 只能用于分析, 不能作为赛前预测特征。

用法:
  py titan007_collector.py --date 20261015 --limit 30
  py titan007_collector.py --range 20261014 20261016
  py titan007_collector.py --match 3018834 --detail
"""
import argparse
import ast
import json
import math
import os
import random
import re
import ssl
import sys
import time
import urllib.request
from collections import Counter
from statistics import median

BASE = r"g:\bet"
DATA_DIR = os.path.join(BASE, "titan_data")

HDRS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": "https://bf.titan007.com/",
}
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


# ============================================================
# 基础工具
# ============================================================
def fetch(url, encoding="utf-8", retries=2):
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=HDRS)
            with urllib.request.urlopen(req, timeout=60, context=CTX) as resp:
                raw = resp.read()
            for enc in (encoding, "utf-8", "gbk", "gb18030"):
                try:
                    return raw.decode(enc)
                except Exception:
                    continue
            return raw.decode("utf-8", errors="ignore")
        except Exception as e:
            last = e
            time.sleep(1.0 + attempt * 1.5)
    raise last


def clean_text(s):
    s = re.sub(r"<[^>]+>", "", s or "")
    s = s.replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", s).strip()


def extract_js_array(html, name):
    m = re.search(r"var\s+%s\s*=\s*(\[\[.*?\]\])\s*;" % name, html, re.S)
    if not m:
        return []
    try:
        return ast.literal_eval(m.group(1))
    except Exception:
        return []


def to_float(x):
    try:
        return float(x)
    except Exception:
        return None


def parse_score(s):
    nums = re.findall(r"\d+", str(s))
    if len(nums) < 2:
        return None
    return int(nums[0]), int(nums[1])


# ============================================================
# 一、比分页: 当天完赛列表
# ============================================================
def parse_over_day(date_str):
    url = f"https://bf.titan007.com/football/Over_{date_str}.htm"
    html = fetch(url, encoding="gbk")
    rows = re.findall(r"(<tr[^>]*sId='\d+'[^>]*>.*?</tr>)", html, re.S)
    out = []
    for row in rows:
        sid_m = re.search(r"sId='(\d+)'", row)
        if not sid_m:
            continue
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if len(tds) < 9:
            continue
        fields = [clean_text(t) for t in tds]
        status = fields[2]
        if status != "完":
            continue
        score = parse_score(fields[4])
        half = parse_score(fields[6])
        if not score:
            continue
        # 盘口数值优先取 hdp_xxx 的 val 属性(比文字可靠):
        # 实测 corr(val, 净胜球)=+0.53, 即 val 为正表示主队让球。
        hdp_val = None
        mv = re.search(r"<td id='hdp_\d+' val='([^']*)'", row)
        if mv and mv.group(1).strip():
            try:
                hdp_val = float(mv.group(1))
            except ValueError:
                hdp_val = None
        out.append({
            "id": sid_m.group(1),
            "date": date_str,
            "league": fields[0],
            "time": fields[1],
            "home": re.sub(r"\[\d+\]", "", fields[3]).strip(),
            "away": re.sub(r"\[\d+\]", "", fields[5]).strip(),
            "home_rank": (re.search(r"\[(\d+)\]", fields[3]) or [None, None])[1],
            "away_rank": (re.search(r"\[(\d+)\]", fields[5]) or [None, None])[1],
            "score": f"{score[0]}-{score[1]}",
            "half": f"{half[0]}-{half[1]}" if half else None,
            "hdp_listed": fields[7],
            "hdp_val": hdp_val,
            # 统一主队视角: 负=主队让球, 正=主队受让
            "hcp_listed": -hdp_val if hdp_val is not None else None,
            "total_listed": fields[8],
        })
    return out


# ============================================================
# 二、分析页: 亚盘 / 欧赔 / 相同盘路
# ============================================================
def _consensus_handicap(entries, how="mode"):
    """
    entries: [(home_water, hcp_value, away_water), ...] 来自不同公司
    titan007 盘口符号约定: 正数=主队让球, 负数=主队受让, 0=平手。
    用多数公司符号确定方向, 再在"同向"公司里确定深度:
      median: 中位数(会系统性偏深约 0.35 球, 已实测)
      mode  : 0.25 粒度众数(偏差约 -0.13, 默认)
      p25   : 25 分位(偏差约 -0.03, 最接近比分页主盘)
    返回值 h 统一为主队视角: 负=让球, 正=受让。
    """
    entries = [e for e in entries if e[1] is not None and e[0] is not None and e[2] is not None]
    if not entries:
        return None, None, None, 0

    nonzero = [e for e in entries if abs(e[1]) > 1e-9]
    if not nonzero:
        return 0.0, median(e[0] for e in entries), median(e[2] for e in entries), len(entries)

    neg = sum(1 for e in nonzero if e[1] < 0)
    pos = len(nonzero) - neg
    home_gives = pos >= neg  # 多数公司为正 -> 主队让球
    selected = [e for e in entries if (e[1] > 0) == home_gives]
    if not selected:
        selected = entries
    abs_vals = sorted(abs(e[1]) for e in selected)
    if how == "median":
        depth = median(abs_vals)
    elif how == "p25":
        depth = abs_vals[max(0, int(len(abs_vals) * 0.25) - 1)]
    else:
        cnt = Counter(round(v * 4) / 4 for v in abs_vals)
        top = cnt.most_common()
        depth = median(abs_vals) if len(top) > 1 and top[0][1] == top[1][1] else top[0][0]
    h = -depth if home_gives else depth
    return h, median(e[0] for e in selected), median(e[2] for e in selected), len(selected)


def parse_analysis(sid):
    html = fetch(f"https://zq.titan007.com/analysis/{sid}sb.htm", encoding="utf-8")
    result = {"id": sid}

    # ---- Vs_hOdds: 注意这不是本场盘口 ----
    # 实测该数组的字段0 是"比赛ID", 且 76 场里 42 场出现在主队近 47 场战绩(h_data)中,
    # 本场 sid 反而不在其中。即它是"多场历史比赛"的盘口集合, 不是本场亚盘。
    # 因此聚合结果没有意义(实测让球方赢盘率 40%、全押 ROI -21%)。
    # 本场盘口请用比分页的 hcp_listed / hdp_val。
    hodds = extract_js_array(html, "Vs_hOdds")
    rows = [r for r in hodds if len(r) >= 8]

    open_entries, close_entries = [], []
    for r in rows:
        oh, ohcp, oa = to_float(r[2]), to_float(r[3]), to_float(r[4])
        ch, chcp, ca = to_float(r[5]), to_float(r[6]), to_float(r[7])
        if None not in (oh, ohcp, oa) and abs(ohcp) <= 5:
            open_entries.append((oh, ohcp, oa))
        if None not in (ch, chcp, ca) and abs(chcp) <= 5:
            close_entries.append((ch, chcp, ca))

    h_open, wo_h, wo_a, n_open = _consensus_handicap(open_entries, "mode")
    h_close, wc_h, wc_a, n_close = _consensus_handicap(close_entries, "mode")
    result.update({
        "hodds_open": h_open, "wo_h": wo_h, "wo_a": wo_a, "n_open_company": n_open,
        "hodds_close": h_close, "wc_h": wc_h, "wc_a": wc_a, "n_close_company": n_close,
    })
    for how in ("median", "p25"):
        result[f"hodds_open_{how}"] = _consensus_handicap(open_entries, how)[0]
        result[f"hodds_close_{how}"] = _consensus_handicap(close_entries, how)[0]

    # ---- 欧赔: 各公司初盘/即时中位数 ----
    eodds = extract_js_array(html, "Vs_eOdds")
    e_open, e_close = [], []
    for r in eodds:
        if len(r) < 8:
            continue
        o = [to_float(r[2]), to_float(r[3]), to_float(r[4])]
        c = [to_float(r[5]), to_float(r[6]), to_float(r[7])]
        if None not in o:
            e_open.append(o)
        if None not in c:
            e_close.append(c)
    result["odds_open"] = [median(x[i] for x in e_open) for i in range(3)] if e_open else None
    result["odds_close"] = [median(x[i] for x in e_close) for i in range(3)] if e_close else None
    result["n_odds_company"] = len(e_open)

    # ---- 相同盘路 ----
    sh, sa = None, None
    for side, target in (("h", "主"), ("g", "客")):
        m = re.search(r"id='TeamPk_letGoal_%s'(.*?)</TABLE>" % side, html, re.S | re.I)
        if not m:
            continue
        block = re.sub(r"\s+", "", m.group(1))
        mm = re.search(r"<td>%s</td><td>(\d+)</td><td>(\d+)</td><td>(\d+)</td><td>([\d.]+)%%</td>"
                       % target, block)
        if mm:
            if side == "h":
                sh = float(mm.group(4))
            else:
                sa = float(mm.group(4))
    result["same_home_wr"] = sh
    result["same_away_wr"] = sa

    # ---- 同盘路的初盘文字(校验用) ----
    m = re.search(r"id='TeamPk_letGoal_h'.*?初盘:([^<]+)</td", html, re.S)
    result["same_hcp_text"] = clean_text(m.group(1)) if m else None
    return result


# ============================================================
# 三、直播页: 赛前/赛后附加信息(可选)
# ============================================================
def parse_detail(sid):
    """
    直播详情页(live.titan007.com/detail/{sid}sb.htm)。
    注意: 技术统计、事件、xG 都是赛后数据, 只能用于复盘分析, 不能进入赛前预测特征。
    赛前可用的只有: 场地 / 天气 / 温度 / 首发阵容(若已公布)。
    """
    html = fetch(f"https://live.titan007.com/detail/{sid}sb.htm", encoding="utf-8")
    out = {"id": sid}

    # ---- 场地 / 天气 / 温度 ----
    m = re.search(r"<label>场地：<a[^>]*>([^<]+)</a></label>", html)
    out["venue"] = m.group(1).strip() if m else None
    m = re.search(r"<label>天气：([^<]+)</label>", html)
    out["weather"] = m.group(1).strip() if m else None
    m = re.search(r"<label>温度：([^<]+)</label>", html)
    out["temperature"] = m.group(1).strip() if m else None

    # ---- 技术统计(赛后) ----
    stats = {}
    for val_h, name, val_a in re.findall(
            r"<div class='data'><span[^>]*>([^<]*)</span><span>([^<]+)</span>"
            r"<span[^>]*>([^<]*)</span></div>", html):
        name = clean_text(name)
        if not name:
            continue
        try:
            stats[name] = [_num(val_h), _num(val_a)]
        except Exception:
            continue
    out["match_stats_postgame"] = stats

    # ---- 首发阵容 + 替补: 按球员链接中的球队 id 分组 ----
    i = html.find("首发阵容")
    block = html[i:i + 40000] if i >= 0 else ""
    home_id = away_id = None
    m = re.search(r"<div class=\"homeN\">(.*?)</div>", block, re.S)
    if m:
        t = re.search(r"team/Summary/(\d+)\.html", m.group(1))
        home_id = t.group(1) if t else None
    m = re.search(r"<div class=\"guestN\">(.*?)</div>", block, re.S)
    if m:
        t = re.search(r"team/Summary/(\d+)\.html", m.group(1))
        away_id = t.group(1) if t else None

    players_h, players_a = [], []
    for team_id, name, _birth, value in re.findall(
            r"player/(\d+)/\d+\.html'[^>]*>([^<]+)</a>.*?姓名：([^<]+)</li>.*?"
            r"身价：(\d+)\(万欧元\)", block, re.S):
        item = {"name": clean_text(name), "value_wan": int(value)}
        if team_id == home_id:
            players_h.append(item)
        elif team_id == away_id:
            players_a.append(item)
    # 页面顺序: 每队前 11 人为首发, 后 9 人为替补
    out["lineup"] = {
        "home_start": players_h[:11], "home_bench": players_h[11:],
        "away_start": players_a[:11], "away_bench": players_a[11:],
        "home_value_wan": sum(p["value_wan"] for p in players_h),
        "away_value_wan": sum(p["value_wan"] for p in players_a),
    }

    return out


def _num(x):
    x = str(x).strip()
    if x.endswith("%"):
        return float(x[:-1])
    try:
        return int(x)
    except ValueError:
        return float(x)


# ============================================================
# 四、采集与缓存
# ============================================================
def load_cache():
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, "matches.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, "matches.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def is_usable(rec):
    return (rec.get("hcp_open") is not None and rec.get("hcp_close") is not None
            and rec.get("odds_open") and rec.get("odds_close")
            and rec.get("wo_h") and rec.get("wc_h"))


def collect_day(date_str, limit=None, sleep=0.6, detail=False, refresh=False):
    cache = load_cache()
    listing = parse_over_day(date_str)
    print(f"[{date_str}] 完赛场次 {len(listing)}")
    if limit:
        listing = listing[:limit]

    ok = fail = skip = 0
    for i, item in enumerate(listing, 1):
        sid = item["id"]
        if not refresh and sid in cache and is_usable(cache[sid]):
            skip += 1
            continue
        try:
            rec = dict(item)
            rec.update(parse_analysis(sid))
            if detail:
                try:
                    rec.update(parse_detail(sid))
                except Exception as e:
                    rec["detail_error"] = str(e)
            if not is_usable(rec):
                fail += 1
                print(f"  [{i}/{len(listing)}] {sid} 解析不完整 "
                      f"hcp={rec.get('hcp_open')} odds={bool(rec.get('odds_open'))}")
            else:
                ok += 1
            cache[sid] = rec
            if i % 20 == 0:
                save_cache(cache)
                print(f"  [{i}/{len(listing)}] 已采集 ok={ok} fail={fail} skip={skip}")
            time.sleep(sleep + random.random() * 0.4)
        except Exception as e:
            fail += 1
            print(f"  [{i}/{len(listing)}] {sid} 失败: {e}")
            time.sleep(1.5)
    save_cache(cache)
    print(f"[{date_str}] 完成: ok={ok} fail={fail} skip={skip}, 缓存总数={len(cache)}")
    return ok, fail


def collect_range(start, end, limit_per_day=None, sleep=0.6, detail=False, refresh=False):
    from datetime import datetime, timedelta
    d = datetime.strptime(start, "%Y%m%d")
    stop = datetime.strptime(end, "%Y%m%d")
    while d <= stop:
        collect_day(d.strftime("%Y%m%d"), limit=limit_per_day, sleep=sleep,
                    detail=detail, refresh=refresh)
        d += timedelta(days=1)


def show_one(sid, detail=False):
    rec = parse_analysis(sid)
    if detail:
        rec.update(parse_detail(sid))
    print(json.dumps(rec, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="单个日期 YYYYMMDD")
    ap.add_argument("--range", nargs=2, metavar=("START", "END"))
    ap.add_argument("--match", help="只抓单场 id")
    ap.add_argument("--limit", type=int, default=None, help="每天最多抓多少场")
    ap.add_argument("--sleep", type=float, default=0.6)
    ap.add_argument("--detail", action="store_true", help="同时抓直播页附加信息(赛后)")
    ap.add_argument("--refresh", action="store_true", help="忽略已有缓存, 重新抓取")
    args = ap.parse_args()

    if args.match:
        show_one(args.match, detail=args.detail)
    elif args.range:
        collect_range(args.range[0], args.range[1], args.limit, args.sleep,
                      args.detail, args.refresh)
    elif args.date:
        collect_day(args.date, args.limit, args.sleep, args.detail, args.refresh)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
