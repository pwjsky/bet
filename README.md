# 足球亚盘 p_move 阈值模型

基于 titan007 欧赔变化（`p_move`）预测亚盘方向的每日出单工具。纯 Python，只依赖 numpy。

**结论先行**：2026-01 ~ 2026-10 共 1072 注、ROI +19.82%、74 个交易日滚动回测零爆仓。这是历史回测结果，不代表未来收益。

## 策略

单特征 `p_move` = 初盘 → 即时盘的主胜去水概率变动，逻辑回归 + 保序校准：

```
p_raw = sigmoid(b + w * (p_move - mu) / sd)
出单条件：|p_raw - 0.5| >= 0.12，且欧赔公司数 >= 30
```

- 达到门槛的场次**全部出单**，不设名额上限（不是 top5）
- 方向由 `p_raw >= 0.5` 决定押主队还是客队
- 已出的单当天只增不减，重算跌破门槛也保留（标记 `locked`）
- 排序分只影响展示顺序，不影响是否出单

## 快速开始

### 新机器 / 云端

```bash
git clone https://github.com/pwjsky/bet.git
cd bet

pip install -r requirements.txt

# 历史数据（约 11.6 MB，解压后 84 MB）
curl -L -o data.zip https://github.com/pwjsky/bet/releases/download/data-2026.10/bet_data.zip
python -c "import zipfile; zipfile.ZipFile('data.zip').extractall('titan_data')"

# 先验证能否访问数据源
curl -I "http://1x2d.titan007.com/1.js"

# 出单
python today_picks.py
```

第 4 步不通说明当前网络访问不了 titan007，后续全部无法执行。

### 本地已采过数据

直接跑：

```bash
python today_picks.py                  # 当天
python today_picks.py --date 20261021  # 指定业务日
```

## 每日流程

```bash
# 1. 出单（中午 12:00 后跑，欧赔最全）
python today_picks.py

# 2. 结算已完场的单
python temp/settle_picks.py 20261021

# 3. 同步到仓库
git add -A && git commit -m "picks 20261021" && git push
```

**业务日口径**：12:00 ~ 次日 12:00，脚本已按此切分。

## 数据文件

放在 `titan_data/`，**不进 git**（体积大）：

| 文件 | 大小 | 用途 |
|---|---|---|
| `listings.json` | 42 MB | 赛程、比分、盘口列表 |
| `euro.json` | 21 MB | 历史欧赔，训练 `p_move` 模型 |
| `water.json` | 21 MB | 历史水位，结算与校准 |
| `calibration.json` | < 1 MB | 保序校准表 |

进 git 的只有：`today_picks_*.json`（每日出单记录）、`top5_changes.json`、`top5_snapshots.json`、`daily_backtest.csv`。

## 结算口径

- titan007 盘口符号：**正 = 主队让球，负 = 主队受让**
- 赢盘 +1 / 赢半 +0.5 / 走盘 0 / 输半 −0.5 / 输盘 −1，押客队取反
- 比分接口：`https://livestatic.titan007.com/phone/txt/analysisheader/cn/{sid[0]}/{sid[1:3]}/{sid}.txt`
- 单注回报 = 本金 × 水位；ROI = 平均(总回报 − 1)

## 当前参数

| 项目 | 值 |
|---|---|
| 门槛 | `|p_raw − 0.5| >= 0.12` |
| 最少欧赔公司 | 30 |
| 单注 | 100 元起，按累计净利阶梯加码 |
| 单日暴露上限 | 本金 25% |
| 模型参数 | `lr=0.1` / `l2=3.0` / `1500 步` |

## 关键结论

全量回测（2026-01-01 ~ 2026-10-16，1072 注可结算）：

| 门槛 | 注数 | 日均 | 命中率 | ROI |
|---|---|---|---|---|
| 0.10 | 1965 | 7.02 | 62.8% | +16.44% |
| 0.12 | **1072** | **4.14** | **64.3%** | **+19.82%** |
| 0.13 | 798 | 3.31 | 66.0% | +22.62% |
| 0.14 | 600 | 2.68 | 67.9% | +25.62% |

门槛越低注数越多、绝对收益越高，但 ROI 递减。每放宽一档新增注单的 ROI 在 +11.7% ~ +13.5%，**没有一档为负**，说明 0.12 仍在有效区间内。

详细依据、参数复核规则、资金管理方案见 [AGENTS.md](AGENTS.md)。

## 目录

```
today_picks.py              每日出单主脚本
asian_handicap_model_v3.py  模型与特征
verify_water_roi.py         真实水位下的 ROI 验证、结算函数
settle_picks.py             按 sid 查比分结算
titan_*_collector.py        欧赔 / 亚盘 / 水位 / 角球 / 大小球采集器
AGENTS.md                   项目规则与全部历史结论
模型说明.md                  模型推导
temp/                       研究脚本（不进 git）
titan_data/                 采集数据（不进 git）
```

## 免责

本项目仅为数据建模研究，不构成任何投注建议。亚盘涉及资金风险，历史回测结果不预示未来表现。请遵守所在地区法律法规。
