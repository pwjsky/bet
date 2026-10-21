# -*- coding: utf-8 -*-
"""
比分页名单采集器
================
从 https://bf.titan007.com/football/Over_YYYYMMDD.htm 抓当天完赛名单,
合并进 titan_data/listings.json (按 sid, 保留已有记录)。

用法:
  py titan_listings_collector.py --dates 20260713-20260831
"""
import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from titan007_collector import parse_over_day  # noqa: E402

DATA = os.path.join(BASE, "titan_data")
OUT = os.path.join(DATA, "listings.json")


def expand(spec):
    out = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            from datetime import date, timedelta
            a, b = part.split("-")
            d0 = date(int(a[:4]), int(a[4:6]), int(a[6:]))
            d1 = date(int(b[:4]), int(b[4:6]), int(b[6:]))
            while d0 <= d1:
                out.append(d0.strftime("%Y%m%d"))
                d0 += timedelta(days=1)
        elif part:
            out.append(part)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", required=True)
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()

    dates = expand(a.dates)
    data = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    have = set(v["date"] for v in data.values())
    dates = [d for d in dates if d not in have]
    if not dates:
        print("所有日期已存在, 无需采集")
        return
    before = len(data)
    print("已有 %d 场, 待抓 %d 天 (%s ~ %s)"
          % (before, len(dates), dates[0], dates[-1]))

    t0 = time.time()
    ok = empty = fail = 0

    def work(d):
        return d, parse_over_day(d)

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(work, d): d for d in dates}
        for i, fut in enumerate(as_completed(futs), 1):
            d = futs[fut]
            try:
                _, rows = fut.result()
                if not rows:
                    empty += 1
                for r in rows:
                    data[r["id"]] = r
                ok += 1
                print("[%d/%d] %s %d 场 (累计 %d)"
                      % (i, len(dates), d, len(rows), len(data)), flush=True)
            except Exception as e:
                fail += 1
                print("[%d/%d] %s 失败: %s" % (i, len(dates), d, e), flush=True)
            if i % 5 == 0:
                json.dump(data, open(OUT + ".tmp", "w", encoding="utf-8"),
                          ensure_ascii=False, indent=1)
                os.replace(OUT + ".tmp", OUT)

    json.dump(data, open(OUT + ".tmp", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    os.replace(OUT + ".tmp", OUT)
    print("完成: 成功 %d 天, 空 %d, 失败 %d, 新增 %d 场, 总计 %d, 用时 %.1f 分"
          % (ok, empty, fail, len(data) - before, len(data), (time.time() - t0) / 60))


if __name__ == "__main__":
    main()
