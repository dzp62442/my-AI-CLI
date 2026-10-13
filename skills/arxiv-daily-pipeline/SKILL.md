---
name: arxiv-daily-pipeline
description: "组织从 Zotero 兴趣推荐到飞书知识库归档的每日文献推送。用于启动 zotero-arxiv-daily、按研究主题筛选论文并标注五类标签、阅读原文生成简要解读、组装完整 Markdown 日报，以及排查这条流水线的运行与归档问题。"
metadata:
  version: "3.2.0"
  tags: [arxiv, pipeline, feishu, gaussian-occupancy]
---

# arXiv Daily 文献推送流水线

先由 zotero-arxiv-daily 自动生成「每日 arxiv 推送」，再由 AI Agent 逐篇筛选、打标签并解读相关论文，合成完整 Markdown 文档归档到飞书知识库。

**流程、项目代码与网络（代理、clash）都不随意改动；遇到问题先报告，等兰德专门处理。**

本技能只放与 AI Agent 平台无关的内容；调度时刻、投递目标、平台专有的运行约定留在各平台的定时任务配置里（Hermes 侧见 cron job「文献推送-启动 / 汇总」与 `hermes-cron-patterns` 技能）。

流水线两段：

| 段 | 做什么 | 耗时 |
|----|--------|------|
| 启动 | 缓存预热 → API 预检 → tmux 启动 zotero-arxiv-daily 主程序 | 30-60 分钟 |
| 后处理 | 读取原始 md → 主题筛选 → 论文标签 → 简要解读 → 组装 → 飞书归档（`feishu-cli`） | 随论文数量和原文获取情况变化 |

## 关键路径与参数

| 项 | 默认值（可用环境变量覆盖） |
|----|--------------------------|
| 项目目录 | `~/Libraries/zotero-arxiv-daily`（`ARXIV_DAILY_PROJECT`） |
| conda 环境 | `zotero-arxiv-daily`（`ARXIV_DAILY_CONDA_ENV`，conda.sh 用 `CONDA_SH`） |
| 输出文件 | `outputs/daily-arxiv-{YYYY-MM-DD}.md` |
| 预热清单 | `${TMPDIR:-/tmp}/arxiv-warm_urls.txt`（`ARXIV_DAILY_WARM_FILE`） |
| tmux 会话 | `arxiv-daily`（`ARXIV_DAILY_SESSION`） |
| 飞书知识空间 | `7621015102212295908` |
| 每日推送节点 | `D67vwKFYyiZr0gk080dcr89tnyb`（归档目标） |
| 文献阅读节点（父目录） | `C54KwvndwibrEqkf2zvcHSCfnte` |

## 场景导航

| 场景 | 去哪 |
|------|------|
| 正常跑一轮 | 下文「启动主程序」+「后处理」 |
| 主题筛选、标签标注、7 维解读、组装与归档 | 下文「后处理」中的必读规范与标签配置 |
| 报错、406、卡死、代理未就绪 | `references/troubleshooting.md` |
| 历史与决策原因 | `references/devlog.md` |

---

## 启动主程序

```bash
bash skills/arxiv-daily-pipeline/scripts/arxiv-daily-launch.sh
```

脚本依次做四件事：

1. 清理 CA 残留环境变量，设 7890 代理（大小写变量都设）
2. 预热：`scripts/arxiv-warmup.py` 构建批次 URL 清单 → curl 逐条预热（失败重试 1 次）
3. 预检：小请求探测 arXiv API 可用性，失败 30s 后重试，最多 8 次
4. `tmux new-session -d -s arxiv-daily` 启动主程序；结束时打印 `=== MAIN DONE ===`

正常日志：

```text
[warmup] 批次 URL 预热完成：N/N
[precheck] arXiv API 预检通过（第 1 次尝试）
```

### 代理策略（2026-09-24 起）

API 与 HTML/PDF 都走 7890；`NO_PROXY` 里不含 `export.arxiv.org`（旧写法是 406 崩溃的根因之一）。项目侧 HTML 下载用 `requests.get(timeout=30)`——`trafilatura.fetch_url` 不读代理 env。

### 406 与缓存预热机制

arXiv API 响应经 CDN 缓存；风控只拦「缓存未命中→回源」的 Python 请求（406），缓存命中不查客户端。所以先用 curl 灌满全部批次 URL，再让 Python 走命中路径。

- 预热清单要**紧贴**主程序启动构建（feed 日间会更新）
- 判读响应头：Python 406 时 `X-Cache: MISS`；curl 同 URL 200；预热后 Python 200 + `HIT`（带 `Age`）
- 强风控窗口（连 curl 未命中请求也被拦）：照常汇报、等窗口缓解
- 手动预热步骤见 `references/troubleshooting.md`

---

## 后处理

**进行后处理时，必须先完整阅读 [后处理规范](references/postprocess.md)，并读取 [论文标签配置](references/paper-tags.yaml) 中的五类标签、可选值与选取注意事项。** 组装时按 [汇总文档模板](templates/daily-push-report.md) 保持表格与解读格式一致。

输入是主程序已生成的 `outputs/daily-arxiv-{date}.md`。保留其中完整的「每日 arxiv 推送」，由 Agent 接续完成：

1. **主题筛选** — 按前馈重建 / 占据预测及相关方向，逐篇判断是否入选并说明理由。
2. **论文标签** — 为原始日报中的每篇论文选择研究领域、输入配置、平台、场景、技术特征五类标签；研究领域单选，其余按 YAML 规则多选或留无适用标记。信息不足时查阅原文，不凭标题猜测。
3. **简要解读** — 只对符合主题的论文进行解读；优先获取 arXiv HTML 原文，按 7 个维度撰写，单篇 ≤500 字，重点论文的安排遵循后处理规范。
4. **组装与归档** — 原始输出 + 含标签的主题筛选表 + 论文解读合为**一个** Markdown，用 `feishu-cli` 一次导入并移到「文献阅读 → 每日推送」，再回读核对。

**五类标签只出现在「主题筛选结果」表格中**，每篇论文一行，并注明入选或未入选；原始项目输出和后面的论文解读均不附加标签。完整筛选口径、标签填写方式、输出格式、飞书命令及回读校验以必读的后处理规范为准。

## 监控

```bash
tmux capture-pane -t arxiv-daily -p | tail -5
ls -la ~/Libraries/zotero-arxiv-daily/outputs/daily-arxiv-$(date +%F).md
ls ~/Libraries/zotero-arxiv-daily/outputs/$(date +%F)/*/main.log
```

## 手动补文档

某天文档缺失、或只上传了原始输出没带分析时，按 `references/postprocess.md` 的组装 + 导入 + 回读校验重做；已上传过原始 md 时用 `content-update --mode append` 补分析。

feishu-cli 的两个坑：stdout 会混入 `[自动刷新] Access Token...` 日志（解析 JSON 前先截断到首个 `{`/`[`）；偶发 `EOF`（网络抖动）重试 2-4 次、调用前 unset 代理变量。文档链接 = `https://feishu.cn/wiki/<node_token>`。

## 仅在需要时查阅的文档与脚本

- [故障排查](references/troubleshooting.md) — 出现 406、代理未就绪、卡死或归档内容不完整时查阅。
- [历史记录](references/devlog.md) — 需要了解既有方案的实验依据、事故复盘和决策原因时查阅。
- [启动脚本](scripts/arxiv-daily-launch.sh) — 需要检查启动过程与参数时阅读。
- [预热脚本](scripts/arxiv-warmup.py) — 需要排查批次 URL 清单生成时阅读。
