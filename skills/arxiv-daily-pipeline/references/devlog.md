# arxiv-daily-pipeline — 开发与排障记录（devlog）

> 历史与迭代记录（实验数据、事故复盘、决策原因）。操作内容以主文档 SKILL.md 为准。

## 2026-07-01：代码补丁（有意保留）

- arxiv_retriever.py：trafilatura.fetch_url → requests.get（trafilatura 不读代理 env）；API 重试 10 次/10s → 5 次/60s。未提交，勿误清。

## 2026-09-23 ~ 09-24：网络故障与 406 排障

- 背景：TUN 代理关闭后两级失败（API 406 / HTML 下载超时）。
- 对照实验：直连大面积 406；走 7890 间歇性 406（约 10% 请求级）；mitmproxy 中转 0 失败——方案被用户否决（「不要随意增加网络中间件」），全部回滚、零残留。
- 修复：HTML 下载改 requests 走代理；launch 弃用 `NO_PROXY=export.arxiv.org`（406 崩溃根因之一），API 改走 7890；加 CA 残留防御段（REQUESTS_CA_BUNDLE 指向已删 CA 曾造成预检 8 连败假故障）。
- launch 预检上线：小请求（1706.03762v7）失败 30s 重试 ≤8 次，输出 `[precheck]`。

## 2026-09-25：缓存命中机制确认 → 预热方案落地

- 发现：406 来自 CDN 层「缓存未命中→回源」，且针对 Python 客户端特征；缓存命中响应不查客户端。
- 两次独立对照实验（08:18 / 21:00）：Python 406（`MISS`）→ curl 预热 → 同 URL Python 200（`HIT` + `Age`）。
- 装机（用户批准）：arxiv-warmup.py → ~/.hermes/scripts/；launch.sh 集成预热段；备份 `.bak-20260925`；技能模板同步。
- 实测：预热 17/17 → 预检第 1 次通过。

## 2026-09-26：生产首日

- 预热 17/17 + 预检一次通过；主程序 27 分钟跑完；全自动到飞书归档。

## 2026-09-28：强风控窗口（记录）

- 06:04-07:12 连续 18 次请求全 406（预检 8 + 复核 10；代理/直连、curl/Python、换 UA 均中招，`MISS`）→ 极端窗口连 curl 未命中请求也被拦、预热无法灌缓存。
- 当日无新论文无实际影响；处置：照常汇报、等窗口缓解，不加组件。

## 固化结论（已进主文档）

- 红线：不加网络中间件 / 不动 clash / 不改项目代码 / 先诊断后动手。
- 预热必须紧贴主程序启动（feed 日间更新）。

## 2026-10-13：技能迁入 my-AI-CLI（v2.0.0 → v3.0.0 分层调整）

- 背景：流水线知识散在三处——Hermes 本地技能（运维视角）、汇总 job 的 4189 字符 prompt（后处理规范）、`hermes-cron-patterns` 里的重复文档（且已过时）。目标：单一真身、定时任务侧只留简短描述词。
- 动作：
  - 技能整体迁到 `my-AI-CLI/skills/arxiv-daily-pipeline/`，由 cc-switch 分发（分发前的 Hermes 本地副本 `~/.hermes/skills/research/arxiv-daily-pipeline/` 已删除——同名技能同层重复会被判 ambiguous 拒绝）。
  - 新增 `references/postprocess.md`：把汇总后处理规范从 job prompt 搬进技能（篇幅口径定为 **≤500 字/篇**）。
  - launch 脚本真身移入 `scripts/`，`~/.hermes/scripts/arxiv-daily-launch.sh` 改为 exec wrapper（Hermes cron 的 `script` 字段被限制在 `~/.hermes/scripts/` 内，绝对路径/软链都会被拒）；warmup 路径改为技能相对，预热清单默认落 `${TMPDIR:-/tmp}`。
  - `hermes-cron-patterns` 里的 arxiv 专用文件搬走留指针；其中过时内容（`NO_PROXY=export.arxiv.org`、分次 `content-update --append`）未迁移。
- 删除决策：原 `references/gateway-quirks.md`（微信断路器 / QQ `is_reconnect` bug）内容已被 `hermes-cron-patterns` 与 `hermes-platforms` 覆盖，属薄重复，未迁移。

## 2026-10-13（同日）：v3.0.0 —— 按「平台无关」重新分层

- 用户要求：**技能只放所有 AI Agent 通用的内容**，Hermes 专有的（调度时刻、投递目标、交付约定、脚本落位约束）留在 Hermes 侧。
- 判定依据：飞书归档走 `feishu-cli`（通用 CLI，不是 Hermes 机制）→ **留在技能内**；job ID/时刻/`deliver`/「最终回复即投递」/验证 nudge 规则 → **移出技能**（进 cron job prompt 与 `hermes-cron-patterns`）。
- 具体：SKILL.md 去掉 job 表、投递地址、wrapper 说明、「07:00 cron 照做」措辞；troubleshooting 去掉验证 nudge 劫持、job `unknown` 卡状态、模型流中断（平台侧故障，归 `hermes-cron-patterns`）；启动脚本路径全部环境变量可覆盖（`ARXIV_DAILY_*` / `CONDA_SH`），不再依赖 `~/.hermes/`。
- 仍未平台无关的一项：代理依赖 clash@7890（本机网络事实），保留在技能内并标了红线。
- Hermes 侧接线（job ID、脚本 wrapper 约束、交付约定）记在 `hermes-cron-patterns` 技能，不进本技能。


