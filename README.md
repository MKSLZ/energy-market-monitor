# 能源电力市场监控日报（Energy Market Monitor）

面向电力交易员的自动化情报系统：**每 3 小时**抓取油气煤电相关的政治事件、政策与新闻，
基于内置的**历史事件→价格传导矩阵**，分析其对 **原油 / 天然气 / 煤炭 / 电力**（中国 + 欧洲市场）
的可能影响，自动生成中文 Markdown 日报并提交到本仓库。

- 最新一期：[`reports/latest.md`](reports/latest.md)
- 历史归档：[`reports/index.md`](reports/index.md)
- 运行状态：见仓库 **Actions** 标签页（workflow: `energy-market-monitor`）

---

## 一、监控什么（影响因子体系）

| 类别 | 因子（示例） | 主要作用品种 |
|---|---|---|
| 地缘政治 | 中东冲突/霍尔木兹通航、对俄制裁、俄乌波及油气设施、红海航运 | 油 ＞ 气 ＞ 煤 ＞ 电 |
| 供给端 | OPEC+ 减产/增产、LNG 设施停产、欧洲储气率、国内安监限产、印尼出口政策（HBA/RKAB）、核电停机 | 油 / 气 / 煤 / 电 |
| 库存数据 | EIA 原油库存、三大机构月报平衡、欧洲 AGSI 储气率 | 油 / 气 |
| 天气需求 | 寒潮、热浪、来水丰枯 | 气 / 电 / 煤 |
| 宏观金融 | 美联储利率、美元指数、经济与能源需求预期 | 油 ＞ 气 ＞ 煤 |
| 政策监管（中国） | 现货市场扩围、容量电价、成本监审/反内卷、负电价下限、煤电联动、长协电价、新能源消纳 | 电力（结构性） |
| 结构性变化 | 新能源大发/弃风弃光、碳价、储能政策 | 电力时段价格、气煤需求 |

每个因子在 `config/impact_matrix.json` 中配置了：触发词（中/英）、反转词（如"停火""增产"）、
对四品种的**方向、强度（1–5）、传导链条与时滞**，全部标注了历史经验依据
（2021–22 欧洲能源危机、2022 俄乌、2019 Abqaiq、2021 国内电荒、2025–26 美伊冲突等）。

## 二、数据源（全部免费、无需 Key）

- **新闻**：Google News RSS（11 组中英文关键词：布伦特/OPEC/TTF/LNG/动力煤/电力现货/霍尔木兹…）+ OilPrice、EIA Today in Energy、BBC、Guardian 直连 RSS
- **行情**：Yahoo Finance（Brent `BZ=F`、WTI `CL=F`、Henry Hub `NG=F`、美元指数 `^DXY`），Stooq 兜底
- **区域现货**：TTF、秦皇岛 Q5500、纽卡斯尔煤、印尼 HBA、欧洲批发电价——从当期新闻文本自动正则提取并附原文出处
- 单源失败自动跳过并在日报页脚登记，不阻断整体运行

## 三、日报内容

1. 四品种影响速览（方向箭头 + 量化评分 + 多空事件数）
2. 行情快照（期货自动抓取 + 区域现货新闻提取）
3. 本期重大事件（按影响因子分组、附原文链接与时间、多空方向标注）
4. 事件→价格传导推演（驱动、传导逻辑、时滞；含中国/欧洲市场差异化注记）
5. 综合研判与基准/上行/下行情景、关注日历（EIA 库存、IEA/OPEC 月报、FOMC 等）
6. 运行信息与免责声明

**评分口径**：评分 = Σ（因子权重 × 历史影响强度 × 方向），同一因子只计一次、证据条数仅表示热度；
衡量本期新增事件的**边际压力方向与集中度**，不是点位预测。

## 四、本地运行

```bash
pip install -r requirements.txt
python -m src.monitor
# 产物：reports/latest.md、reports/archive/YYYY-MM-DD/HHMM.md、reports/index.md
```

首次运行会把 `data/seed_events.json` 中的人工核验基线并入事件池（之后只处理增量新闻）；
去重状态保存在 `data/state.json`（删除即可重置）。

## 五、部署到 GitHub（每 3 小时自动运行）

1. 在 GitHub 上 **Fork 本仓库**（或 Push 到你自己的新仓库）。
2. 进入仓库 **Settings → Actions → General → Workflow permissions**，选择 **Read and write permissions** 并保存（允许 Actions 提交日报）。
3. 打开 **Actions** 标签页，启用 `energy-market-monitor` workflow。
4. 定时计划 `15 */3 * * *`（UTC）即刻生效；GitHub 调度高峰可能有数分钟延迟，也可随时用 **Run workflow** 手动触发。
5. 每期报告会自动 commit 到 `reports/`，在仓库里直接阅读，或结合 GitHub Pages/Obsidian 等展示。

### 可选：启用 LLM 综合研判

在仓库 **Settings → Secrets and variables → Actions** 中添加任一 OpenAI 兼容接口：

| Secret | 说明 |
|---|---|
| `LLM_API_KEY` | API Key（不配置则使用纯规则引擎，报告其他部分不受影响） |
| `LLM_BASE_URL` | 接口地址，默认 `https://api.openai.com/v1` |
| `LLM_MODEL` | 模型名，默认 `gpt-4o-mini` |

## 六、自定义

- 加/改新闻关键词与 RSS：`config/sources.json`
- 加/改影响因子、传导强度与逻辑：`config/impact_matrix.json`
- 改监控频率：`.github/workflows/monitor.yml` 的 cron（如每小时 `7 * * * *`）
- 更新人工基线：`data/seed_events.json`

## 七、目录结构

```
├── config/
│   ├── sources.json          # 新闻关键词/RSS/行情代码/现货提取正则
│   └── impact_matrix.json    # 事件→价格传导矩阵（20 个因子的历史经验知识库）
├── src/
│   ├── prices.py             # 行情抓取（Yahoo/Stooq，多级容错）
│   ├── news.py               # 新闻聚合与去重（状态持久化）
│   ├── analyze.py            # 事件分类、方向判定、评分、现货提取、可选 LLM
│   ├── report.py             # Markdown 日报渲染与归档
│   └── monitor.py            # 主入口
├── data/                     # 基线事件、去重状态、运行快照
├── reports/                  # latest.md + 按日归档 + index
└── .github/workflows/monitor.yml
```

## 免责声明

本项目由监控程序基于公开信息与预设的历史传导规则自动生成，仅供交易研究参考，
**不构成任何投资建议**。历史规律不代表未来表现，单次事件的实际价格反应受预期差、仓位、
政策干预与流动性影响，可能显著偏离规则判断，请结合实时盘口独立决策。
