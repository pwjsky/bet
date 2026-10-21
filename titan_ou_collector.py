# -*- coding: utf-8 -*-
"""
大小球水位采集器
================
数据源: https://live.titan007.com/jsData/{sid前2位}/{sid第3-4位}/{sid}.js

全场大小球字段 (scoreOdds.js: 半场 h2=15, 全场 f2=21, 每组 6 个值 = 开盘3 + 即时3):
  [21]大水 [22]盘口 [23]小水   <- 全场开盘
  [24]大水 [25]盘口 [26]小水   <- 全场即时
  注意: 行长度会随末尾空字段变化 (46/43/40/37), 但前 27 位含义恒定;
  len<27 的行(如 34 位)没有全场大小球, 必须跳过。
  早期按 len>=46 / len>=21 二分是错的: 40/43 位行会取到 [15:21] 的半场盘。

输出 titan_data/ou.json:
  {sid: {"crown": {line_open, over_open, under_open, line_close, over_close, under_close},
         "bet365": {...}}}

用法:
  py titan_ou_collector.py --limit 200
  py titan_ou_collector.py --workers 10
"""
import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from titan007_collector import fetch  # noqa: E402
from titan_water_collector import parse_rows, num  # noqa: E402

DATA = os.path.join(BASE, "titan_data")
LISTINGS = os.path.join(DATA, "listings.json")
OUT = os.path.join(DATA, "ou.json")

_lock = threading.Lock()


def wv(v):
    x = num(v)
    return x if x is not None and 0.3 <= x <= 1.6 else None


def ln(v):
    x = num(v)
    return x if x is not None and 0.5 <= x <= 8 else None


def parse_ou(row):
    if len(row) < 27:
        return None
    vals = [wv(row[21]), ln(row[22]), wv(row[23]), wv(row[24]), ln(row[25]), wv(row[26])]
    if None in vals:
        return None
    return {"over_open": vals[0], "line_open": vals[1], "under_open": vals[2],
            "over_close": vals[3], "line_close": vals[4], "under_close": vals[5]}


def one(sid):
    url = "https://live.titan007.com/jsData/%s/%s/%s.js" % (sid[:2], sid[2:4], sid)
    txt = fetch(url, "utf-8")
    rec = {}
    for name, key in (("sOdds", "crown"), ("sOdds8", "bet365")):
        parsed = [parse_ou(r) for r in parse_rows(txt, name)
                  if r and r[0] in ("早餐", "未开场")]
        parsed = [p for p in parsed if p]
        if not parsed:
            continue
        first, last = parsed[0], parsed[-1]
        if abs(last["line_close"] - first["line_open"]) > 2.5:   # 盘口异常跳变, 丢弃
            continue
        rec[key] = last
        rec[key]["line_open"] = first["line_open"]
        rec[key]["over_open"] = first["over_open"]
        rec[key]["under_open"] = first["under_open"]
    return {"sid": sid, **rec} if rec else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--rebuild", action="store_true", help="忽略已有记录, 全量重采")
    a = ap.parse_args()

    raw = json.load(open(LISTINGS, encoding="utf-8"))
    ids = sorted(r["id"] for r in raw.values() if r.get("total_listed"))
    if a.limit:
        ids = ids[:a.limit]

    old = {}
    if os.path.exists(OUT) and not a.rebuild:
        try:
            old = json.load(open(OUT, encoding="utf-8"))
        except Exception:
            old = {}
    todo = [i for i in ids if i not in old]
    print("目标 %d 场, 已有 %d, 待采 %d" % (len(ids), len(old), len(todo)), flush=True)

    t0 = time.time()
    ok = fail = 0
    done = 0
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(one, i): i for i in todo}
        for f in as_completed(futs):
            done += 1
            try:
                r = f.result()
                if r:
                    with _lock:
                        old[r["sid"]] = r
                    ok += 1
                else:
                    fail += 1
            except Exception:
                fail += 1
            if done % 500 == 0:
                rate = done / max(time.time() - t0, 1e-6)
                print("  [%d/%d] ok=%d fail=%d %.1f/s 剩余%.0f秒"
                      % (done, len(todo), ok, fail, rate, (len(todo) - done) / max(rate, 1e-6)),
                      flush=True)
                json.dump(old, open(OUT + ".tmp", "w", encoding="utf-8"), ensure_ascii=False)
                os.replace(OUT + ".tmp", OUT)

    json.dump(old, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print("完成 ok=%d fail=%d 总记录 %d, 用时 %.1f 分"
          % (ok, fail, len(old), (time.time() - t0) / 60), flush=True)


if __name__ == "__main__":
    main()
