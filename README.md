# 能源电力市场监控日报（Energy Market Monitor）

面向电力交易员的自动化情报系统：**每 3 小时**抓取油气煤电相关的政治事件、政策与新闻，
基于内置的**历史事件→价格传导矩阵**，分析其对 **原油 / 天然气 / 煤炭 / 电价**（中国 + 欧洲市场）
的可能影响，自动生成**中文日报（HTML 网页版 + Markdown 版）**并提交到本仓库。

- 🌐 **网页版日报（推荐，每日滚动更新）**：<https://mkslz.github.io/energy-market-monitor/>
- 历史日报（按日）：<https://mkslz.github.io/energy-market-monitor/archive/>
- 仓库内最新一期：[`reports/latest.md`](reports/latest.md) / [`reports/latest.html`](reports/latest.html)
- 运行状态：见仓库 **Actions** 标签页（workflow: `energy-market-monitor`）

> 网页版为**当日一份日报、日内滚动更新**（每 3 小时刷新同一份），按日归档；Markdown 版保留每次运行的高频快照。

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

- **新闻**：Google News RSS（多组中英文关键词：布伦特/OPEC/TTF/LNG/动力煤/电力现货/年度长协/容量电价/秦皇岛煤价/CECI/来水…，Google 限流时自动切 Bing 镜像）+ OilPrice、EIA Today in Energy、MarketWatch、BBC、Guardian 直连 RSS
- **国际期货行情**：CNBC 报价接口为主（WTI `@CL.1`、Brent `@LCO.1`、Henry Hub `@NG.1`、美元指数 `.DXY`），Yahoo Finance 为备
- **区域现货（确定性接口）**：**国内动力煤——CCTD 中国煤炭市场网官方价（环渤海动力煤现货价 / 秦皇岛综合交易价 / 年度长协价，5500K，元/吨，GBK 首页解析）**、纽卡斯尔国际煤价（Trading Economics）、德国日前现货电价（energy-charts / SMARD，取近 24 小时均值）
- **区域现货（新闻提取）**：TTF、印尼 HBA 等从当期新闻文本正则提取并附原文（秦港 Q5500 已由 CCTD 确定性接口提供，确定性源优先）；提取到的报价写入 `data/spot_state.json`，TTL（10 天）内跨期沿用并标注日期，避免某 3 小时窗口无报价时量化归零
- 单源失败自动跳过并在日报页脚登记，不阻断整体运行

## 三、日报内容

1. 四品种影响速览（方向箭头 + 量化评分 + 多空事件数）
2. 行情快照（期货自动抓取 + 区域现货确定性取数/新闻提取）
3. 本期重大事件（按影响因子分组、附原文链接与时间、多空方向标注）
4. 事件→价格传导推演（驱动、传导逻辑、时滞；含中国/欧洲市场差异化注记）
5. **国内电价专项推演**：把油价 / 气价 / 煤价与事件量化映射到中国电价
   - 传导权重：原油≈不传导（油电占比约 0.1%）、天然气仅推沿海尖峰（气电约 3.5%）、煤炭为定价主体（煤电约 59%）
   - 煤价→度电燃料成本：以 CCTD 环渤海动力煤现货价 5500K 为锚（实测），供电煤耗约 300 克/度、长协煤约 80% 对冲，分别测边际煤机成本与综合上网电量成本推力（分/千瓦时），并给「长协锚 / 当前现货 / 再涨 100」实测情景；仅当 CCTD 与国际煤价均不可得时才回落为假设档位（不伪造实测价）
   - 分时间尺度（日前/实时现货 → 月度中长期 → 次年年度长协 → 终端代理购电）、分区域（沿海 / 煤电基地 / 水电省），并叠加容量电价、136 号文、现货扩围等结构性机制
6. 综合研判与基准/上行/下行情景、关注日历（EIA 库存、IEA/OPEC 月报、FOMC 等）
7. 运行信息与免责声明

> 国内电价相关参数见 `config/cn_power.json`（发电结构、度电煤耗、长协比例、分环节传导率、分区域敏感度等，均为公开行业经验近似，可调）。所有“分/千瓦时”均为成本端推力、非电价预测点位。

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
5. 每期报告会自动 commit：Markdown 快照到 `reports/`，HTML 网页到 `site/`，并自动部署到 GitHub Pages。

### 网页版（GitHub Pages）

工作流的 `deploy-pages` 作业会把 `site/` 目录发布为静态网站，固定网址：
**`https://<你的用户名>.github.io/energy-market-monitor/`**

一次性启用（本仓库已用 API 自动完成；Fork 到新仓库时需手动做一次）：

1. 仓库 **Settings → Pages → Build and deployment → Source** 选择 **GitHub Actions**。
2. 保证仓库为 **Public**（免费账户即可；私有仓库使用 Pages 需 GitHub Pro）。
3. 手动 Run 一次 workflow，访问上面的固定网址即可；此后每 3 小时自动刷新。

> 网页版为**当日一份日报、日内滚动更新至最新一期**，历史按日列于 `/archive/`。

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
│   ├── sources.json          # 新闻关键词/RSS/行情代码/确定性现货源/现货提取正则
│   ├── impact_matrix.json    # 事件→价格传导矩阵（20 个因子的历史经验知识库）
│   └── cn_power.json         # 国内电价推演参数（发电结构/煤耗/长协对冲/传导率/分区域）
├── src/
│   ├── prices.py             # 行情抓取（CNBC 主、Yahoo 备 + TE/energy-charts 确定性现货）
│   ├── news.py               # 新闻聚合与去重（Google/Bing + 直连 RSS）
│   ├── analyze.py            # 事件分类、方向判定、评分、现货提取、可选 LLM
│   ├── spot_store.py         # 现货报价跨期持久化（10 天 TTL 沿用）
│   ├── cn_power.py           # 国内电价专项推演（油/气/煤→中国电价，分时间/分区域量化）
│   ├── report.py             # Markdown 日报渲染与高频归档
│   ├── html_report.py        # HTML 网页日报渲染（终端风格、内联样式）
│   └── monitor.py            # 主入口
├── data/                     # 基线事件、去重状态、现货状态(spot_state.json)、运行快照
├── reports/                  # Markdown：latest + 每次运行高频快照
├── site/                     # HTML 站点：index.html（最新）+ archive/按日（GitHub Pages 发布目录）
└── .github/workflows/monitor.yml   # 每 3h 抓取分析 + 提交 + 部署 Pages
```

## 免责声明

本项目由监控程序基于公开信息与预设的历史传导规则自动生成，仅供交易研究参考，
**不构成任何投资建议**。历史规律不代表未来表现，单次事件的实际价格反应受预期差、仓位、
政策干预与流动性影响，可能显著偏离规则判断，请结合实时盘口独立决策。
