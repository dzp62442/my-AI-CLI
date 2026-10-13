# 故障模式 → 处理

平台侧（调度/投递/超时/状态机）的故障不在这里，见 Hermes 的 `hermes-cron-patterns` 技能。本文件只收流水线本身的故障。

## 406 风控（元数据抓取 / API）

**症状**：主程序卡在 `Retrieving arxiv papers...`；`main.log` 出现 `HTTP 406` 或对 `arxiv.org:80` 的 `ConnectTimeoutError`；tmux 会话存活但无进度；当日 `daily-arxiv-{date}.md` 未生成。

**根因**：arXiv 对 Python 客户端的「CDN 缓存未命中→回源」请求间歇性返 406（`X-Cache: MISS`）；curl 可穿过并填充缓存，命中路径（`HIT`）不查客户端。

**处理**：

1. 等几分钟重试，或让预检跳过坏窗口
2. 持续大面积 406 → 手动预热后重跑
3. **强风控窗口**（连 curl 未命中请求也被拦）：无法灌缓存，照常汇报、等窗口缓解，**不加组件**

### 手动预热（恢复用）

```bash
# 前提：unset CA 残留变量 → export 7890 代理 → conda activate zotero-arxiv-daily
SKILL_DIR=~/Libraries/my-AI-CLI/skills/arxiv-daily-pipeline
python "$SKILL_DIR/scripts/arxiv-warmup.py" /tmp/warm_urls.txt
n=0; ok=0
while IFS= read -r u; do
  [ -z "$u" ] && continue
  n=$((n+1))
  code=$(curl -x http://127.0.0.1:7890 -sS -m 25 -o /dev/null -w '%{http_code}' "$u")
  if [ "$code" != "200" ]; then sleep 2; code=$(curl -x http://127.0.0.1:7890 -sS -m 25 -o /dev/null -w '%{http_code}' "$u"); fi
  if [ "$code" = "200" ]; then ok=$((ok+1)); else echo "warm fail($code): ${u:0:100}"; fi
done < /tmp/warm_urls.txt
echo "warm: $ok/$n"   # 期望全 200（典型 13-16 批 + 1 预检）
```

验证预热生效：arXiv 库请求清单第 1 批（20 ID）<1s 返回 = 命中。然后重跑 `scripts/arxiv-daily-launch.sh`。

### 自测风控是否生效中

取清单任一 URL，把 `max_results=100` 改成 `99`（同形状冷 URL）：Python 406 说明风控生效中；curl 预热后 200 说明预热起效。

---

## 代理未就绪 → 主程序静默崩溃（**假阴性**）

**场景**：主机开机后、用户登录前，clash party / mihomo 的 core 由 GUI 在登录时 autostart 拉起 → 这段时间 7890 不可用。此时任何自动补跑的流水线都会崩。

**症状**：

- 启动脚本输出「✅ 已在 tmux 后台启动」，但 tmux 会话 1 秒内 ENDED
- Hydra 运行目录存在（`outputs/{date}/HH-MM-SS/`）但 `main.log` **为空**（日志初始化前就崩，无报错）
- 后处理环节因读不到输出文件误报「今日没有新论文」（实际可能有 10 篇）
- 需要联网的后续步骤报 `ProxyError('Unable to connect to proxy', ConnectionRefusedError(111))`

**诊断**：`ss -tlnp | grep 7890`（代理是否就绪）→ 看 tmux 会话与 `main.log` → 看当日输出文件是否存在。

**恢复**（代理恢复后）：手动跑 launch → 45s 后确认 `tmux has-session` → 挂监控等结束 → 有产出则补后处理，无产出则补报「今日无新论文」。

**根治**：GNOME 自动登录（GDM `AutomaticLoginEnable=True`），把登录并入开机流程，clash 就绪时间固定为开机后 30-60s。启动脚本自带的预热段与预检失败重试（8 × 30s）本身也能吃掉部分竞争窗口。

---

## 周末假阳性

周六周日 `daily-arxiv-{date}.md` 正常生成（约 181 字节，「No Papers Today」），周一失败——arXiv 周末不发新论文，周末跳过下载环节把网络问题掩盖了。

**周末两天正常 ≠ 流水线健康**。周一先看 `main.log` 有没有实际错误。

---

## 主程序还在跑：正常还是卡死

`tmux has-session` 为真只说明进程活着，不代表健康。

- **正常**：`main.log` 在滚动（下载/解析进度）
- **卡死**：卡在 HTML 下载循环（每篇 30s 超时 × 数百篇 = 数小时），`main.log` 反复 `ConnectTimeoutError`；或 429 限流反复重试

处理：确认启动时的代理 env 是否生效（`ConnectTimeoutError` = HTML 下载没走代理），必要时 kill 后重跑。

---

## 飞书文档缺少筛选解读（split delivery）

**根因**：归档步骤只做了 `doc import`（原始 md）+ `wiki move-docs`，步骤 1-2 生成的筛选/解读只存在于 Agent 回复里，没进文档。

**修复**：按 `postprocess.md`「组装」把解读与原始输出合并后**一次性导入**；或对已上传文档补：

```bash
feishu-cli doc content-update <doc_token> --mode append --markdown-file /tmp/feishu-append-<date>.md
feishu-cli doc export <doc_token> --output /tmp/verify.md && grep -c "批判性思考" /tmp/verify.md
```

---

## 代码补丁状态（勿误清）

`src/zotero_arxiv_daily/retriever/arxiv_retriever.py` 有**有意保留**的未提交修改（`git status` 显示 ` M` 属正常）：

- `trafilatura.fetch_url` → `requests.get(timeout=30)`（trafilatura 不读代理 env）
- API 重试 10 次/10s → 5 次/60s

**勿被 `git checkout` / `clean` / `reset` 清掉**——清了 HTML 下载就失去代理支持。

---

## 手动恢复流程（网络/代理故障后）

```bash
# 1. 确认 clash 代理在
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:7890   # 应非 000

# 2. 带预热+预检启动
bash ~/Libraries/my-AI-CLI/skills/arxiv-daily-pipeline/scripts/arxiv-daily-launch.sh
tmux has-session -t arxiv-daily && echo OK

# 3. 等 30-60 分钟，观察 tmux 结束与 outputs/daily-arxiv-{date}.md

# 4. 有产出 → 走 postprocess.md；无产出 → 补报「今日无新论文」
```

## Verification

```bash
cd ~/Libraries/zotero-arxiv-daily
conda activate zotero-arxiv-daily
PYTHONPATH=src python -m pytest tests/retriever/test_arxiv_retriever.py -m "not slow"
# 预期：3 passed, 1 error（Hydra 配置解析，既有问题）
```
