# -*- coding: utf-8 -*-
"""大小球特征单变量诊断: 哪个变量能预测大球"""
import os
import statistics
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from ou_model import build  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")


def corr(xs, ys):
    mx, my = statistics.mean(xs), statistics.mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    return num / (dx * dy) if dx and dy else 0.0


rows = build()
print("样本", len(rows))

feats = ["p_over_move", "line_move", "line", "p_over_close", "euro_pmove",
         "hcp", "league_avg", "line_dev", "league_bias", "home_bias", "away_bias"]
print("\n相关系数 (与 y=大球):")
for f in feats:
    pairs = [(r[f], r["y"]) for r in rows if r.get(f) is not None]
    if len(pairs) < 100:
        print("  %-14s 样本不足" % f)
        continue
    c = corr([p[0] for p in pairs], [p[1] for p in pairs])
    print("  %-14s n=%-6d corr=%+.4f" % (f, len(pairs), c))

for f in feats:
    pairs = [r for r in rows if r.get(f) is not None]
    if len(pairs) < 500:
        continue
    pairs.sort(key=lambda r: r[f])
    print("\n== %s (按值分 10 组) ==" % f)
    print("  %-16s %5s %7s %8s %8s %7s" % ("区间", "场次", "大球率", "平均水位", "盈亏线", "差值"))
    q = len(pairs) // 10
    for i in range(10):
        seg = pairs[i * q:(i + 1) * q] if i < 9 else pairs[9 * q:]
        if not seg:
            continue
        hit = sum(r["y"] for r in seg) / len(seg)
        w = statistics.mean(r["over_water"] for r in seg)
        be = 1.0 / (1.0 + w)
        print("  %6.3f~%6.3f  %5d %6.1f%% %7.3f %7.1f%% %+6.1f%%"
              % (seg[0][f], seg[-1][f], len(seg), 100 * hit, w, 100 * be, 100 * (hit - be)))
