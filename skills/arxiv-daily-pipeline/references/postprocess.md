# 后处理规范：筛选 → 解读 → 组装 → 飞书归档

从 zotero-arxiv-daily 的原始输出出发，产出「原始论文列表 + 主题筛选 + 论文解读」的单一文档并归档到飞书知识库。平台无关流程；用哪个 Agent 跑都可以。

## 约束

- **不修改 zotero-arxiv-daily 项目代码**
- 论文原文用 Agent 自带的抓取/读文件工具获取（`web_extract` / `web_fetch` / `read_file`），**不要**在 `/tmp` 下写一次性 Python 脚本做提取
- **飞书文档一次性上传完整内容**：原始论文列表 + 主题筛选 + 论文解读，一个文档、一次导入

## 1. 主题筛选

匹配口径（结合标题、摘要、TLDR 与研究内容综合判断，**不要机械关键词匹配**）：

| 级别 | 关键词 |
|------|--------|
| 核心 | 前馈重建（feed-forward / feedforward reconstruction）、占据预测（occupancy prediction / 3D occupancy / BEV occupancy / semantic occupancy）、环视（surround-view） |
| 相关 | 可泛化 3DGS、稀疏视图重建、高斯表示、驾驶场景重建、轻量化实时推理 |
| 不相关 | 纯图像匹配、通用分类/检测/分割（与重建/占据无关）、非驾驶场景的独立任务 |

只要与上述任一方向有实质性关联即可入选。

产出格式：

```markdown
## 主题筛选结果

> 主题口径：前馈重建 / 占据预测。今日共 N 篇论文，M 篇符合主题。

| # | 论文 | arXiv | 相关性判断 |
|---|------|-------|-----------|
| 1 | **标题** | [ID](链接) | 一句话说明为何相关 |

**未入选简述：**
- 论文A（原因）
- 论文B（原因）
```

## 2. 论文解读

对每篇入选论文通过 arXiv 链接取原文（优先 HTML 版 `arxiv.org/html/XXXX`）。7 个维度，**每篇 ≤500 字**：

1. **任务定义** — 要解决什么问题
2. **一句话总结** — 核心方法
3. **问题与创新** — 现有方法不足 & 本文创新点
4. **架构概述** — 系统流程（分步）
5. **核心模块** — 关键技术实现细节
6. **实验概述** — 训练数据、评测基准、对比方法、核心结果
7. **批判性思考** — 亮点、局限、对课题（环视前馈高斯重建/占据预测）的启发

优先级规则：

- ≤5 篇入选 → 全部详细解读
- \>5 篇 → Top 5 详细解读，其余列标题 + 链接 + 一句话摘要
- 与「环视 + 前馈 + 占据」直接撞车的标 ⭐ **必须精读**

产出格式：

```markdown
## 论文解读

### 1. 论文标题 ⭐
**链接：** https://arxiv.org/abs/XXXX
**机构：** 第一单位

**任务定义：** …
**一句话总结：** …
**问题与创新：** …
**架构概述：** …
**核心模块：** …
**实验概述：** …
**批判性思考：** …
```

## 3. 组装

原始输出与解读合并成**一个** markdown（块间留 `---` 分隔线）：

```bash
DATE=$(date +%F)
RAW_FILE="~/Libraries/zotero-arxiv-daily/outputs/daily-arxiv-${DATE}.md"   # 展开为绝对路径
INTERP="/tmp/daily-interpretation-${DATE}.md"   # 步骤 1-2 的产出，开头带 `---`
COMBINED="/tmp/daily-push-${DATE}.md"

cat "$RAW_FILE" "$INTERP" > "$COMBINED"
wc -l < "$COMBINED"
```

最终文档结构：

```text
# Zotero arXiv Daily - YYYY-MM-DD
（原始 N 篇论文 TLDR）
---
## 主题筛选结果
## 论文解读
### 1. …
```

## 4. 飞书归档（feishu-cli）

```bash
DATE=$(date +%F)
SPACE_ID=7621015102212295908
PARENT_NODE=D67vwKFYyiZr0gk080dcr89tnyb     # 文献阅读 → 每日推送（C54KwvndwibrEqkf2zvcHSCfnte 是父目录，不要停留）

# A. 导入合并文档
feishu-cli doc import "/tmp/daily-push-${DATE}.md" --title "每日文献推送 ${DATE}" --output json
# → 记下 document_id

# B. 移到每日推送节点
feishu-cli wiki move-docs <document_id> --space-id "$SPACE_ID" \
  --parent-node "$PARENT_NODE" --obj-type docx --output json

# C. 取链接
feishu-cli doc get <document_id> --output json
```

**回读校验**（不要跳过）：

```bash
feishu-cli doc export <document_id> --output /tmp/verify-${DATE}.md
grep -c "批判性思考" /tmp/verify-${DATE}.md      # 应 = 入选篇数
grep -c "^| " /tmp/verify-${DATE}.md             # 筛选表
feishu-cli wiki nodes "$SPACE_ID" --parent "$PARENT_NODE" --output json | grep "$DATE"
```

move 可能提交异步任务，等 3-5s 再验证；出现重复节点用 `echo y | feishu-cli wiki delete <node_token>` 删旧的。

**补充已有文档**（原文档只传了原始输出时）：

```bash
feishu-cli doc content-update <doc_token> --mode append --markdown-file /tmp/feishu-append-${DATE}.md
```

doc_token 查询：`feishu-cli wiki nodes "$SPACE_ID" --parent "$PARENT_NODE" --output json`。

## 5. 汇报文本

```text
📚 每日文献推送
📅 YYYY-MM-DD
📊 总论文数：N 篇 | 符合主题：M 篇
📎 飞书文档：每日文献推送 YYYY-MM-DD（附链接）

（如有特别值得关注的论文，1-2 句点出）
```

无新论文时：

```text
📚 每日文献推送
📅 YYYY-MM-DD
今日没有新论文。
```

（怎么把这段文本送达用户由各平台自己的投递机制决定，见平台侧配置。）
