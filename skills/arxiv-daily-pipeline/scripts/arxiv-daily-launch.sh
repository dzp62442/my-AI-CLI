#!/usr/bin/env bash
# arXiv Daily 启动脚本
#   预热批次 URL → arXiv API 预检 → tmux 后台启动 zotero-arxiv-daily 主程序
#
# 代理策略（2026-09-24 起）：API 也走代理；NO_PROXY 里绝不能含 export.arxiv.org
#   （旧写法是 406 崩溃根因之一，勿回退）。
#
# 路径可用环境变量覆盖（见 SKILL.md「关键路径与参数」）：
#   ARXIV_DAILY_PROJECT  ARXIV_DAILY_CONDA_ENV  CONDA_SH  ARXIV_DAILY_WARM_FILE  ARXIV_DAILY_SESSION
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${ARXIV_DAILY_PROJECT:-$HOME/Libraries/zotero-arxiv-daily}"
CONDA_ENV="${ARXIV_DAILY_CONDA_ENV:-zotero-arxiv-daily}"
CONDA_SH="${CONDA_SH:-$HOME/miniconda3/etc/profile.d/conda.sh}"
WARM_FILE="${ARXIV_DAILY_WARM_FILE:-${TMPDIR:-/tmp}/arxiv-warm_urls.txt}"
SESSION="${ARXIV_DAILY_SESSION:-arxiv-daily}"

PROXY=http://127.0.0.1:7890

# 防御：清理可能污染 TLS/CA 设置的外部残留环境变量（历史测试遗留等）
unset REQUESTS_CA_BUNDLE CURL_CA_BUNDLE SSL_CERT_FILE SSL_CERT_DIR 2>/dev/null || true

export HTTP_PROXY="$PROXY" HTTPS_PROXY="$PROXY" http_proxy="$PROXY" https_proxy="$PROXY"
export NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1

# 清理旧 session
tmux kill-session -t "$SESSION" 2>/dev/null || true

# shellcheck source=/dev/null
source "$CONDA_SH" && conda activate "$CONDA_ENV"

# ---- 缓存预热 ----
# 机制：arXiv 对 Python 客户端的「缓存未命中」请求间歇性 406；curl 可穿过风控层并填充 CDN 缓存；
# 预热后 Python 请求走「缓存命中」路径即可稳定通过。
# 步骤：构建批次 URL 清单（复刻主程序 RSS 解析逻辑，只读）→ 逐条 curl 预热（失败重试 1 次）。
# 容错：清单构建失败或个别 URL 预热失败均不阻断，继续「预检 → 启动」流程。
if python "$SCRIPT_DIR/arxiv-warmup.py" "$WARM_FILE"; then
  warm_total=0; warm_ok=0
  while IFS= read -r u || [ -n "$u" ]; do
    if [ -z "$u" ]; then continue; fi
    warm_total=$((warm_total+1))
    code=$(curl -x "$PROXY" -sS -m 25 -o /dev/null -w '%{http_code}' "$u" || true)
    if [ "$code" != "200" ]; then
      sleep 2
      code=$(curl -x "$PROXY" -sS -m 25 -o /dev/null -w '%{http_code}' "$u" || true)
    fi
    if [ "$code" = "200" ]; then
      warm_ok=$((warm_ok+1))
    else
      echo "[warmup] 预热失败(${code:-ERR}): ${u:0:110}..."
    fi
  done < "$WARM_FILE"
  echo "[warmup] 批次 URL 预热完成：$warm_ok/$warm_total"
else
  echo "[warmup] URL 清单构建失败（RSS 不可达 / 无 new id 等），跳过预热，继续原有流程"
fi

# ---- API 预检 ----
# 背景（2026-09-24）：arXiv 侧偶发 406 拒绝（短时间内成片出现），主程序对 406 无重试会直接崩溃。
# 用小请求探测窗口：失败则等待重试，尽量让主程序在可用窗口内启动。
# 注：预检 URL 已包含在预热清单中，正常情况下第 1 次即通过。
API_OK=0
for i in 1 2 3 4 5 6 7 8; do
  if python -c "import sys, arxiv; r=list(arxiv.Client(num_retries=1, delay_seconds=3).results(arxiv.Search(id_list=['1706.03762v7']))); sys.exit(0 if r else 1)" 2>/dev/null; then
    API_OK=1; echo "[precheck] arXiv API 预检通过（第 $i 次尝试）"; break
  fi
  if [ "$i" -lt 8 ]; then
    echo "[precheck] arXiv API 请求失败（尝试 $i/8），30s 后重试..."
    sleep 30
  fi
done
if [ "$API_OK" -ne 1 ]; then
  echo "[precheck] ⚠️ 预检 8 次均失败，仍启动主程序（兜底：后处理环节发现无产出时处理）"
fi

# ---- 启动主程序 ----
tmux new-session -d -s "$SESSION" -x 200 -y 50 \
  "export HTTP_PROXY=$PROXY HTTPS_PROXY=$PROXY http_proxy=$PROXY https_proxy=$PROXY NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1 && cd $PROJECT_DIR && set -a && source .env && set +a && source $CONDA_SH && conda activate $CONDA_ENV && PYTHONPATH=src python -m zotero_arxiv_daily.main 2>&1; echo '=== MAIN DONE ==='"

echo "✅ arxiv-daily 主程序已在 tmux 后台启动（已配置代理）"
echo "预计运行 30-60 分钟；结束后由后处理环节（references/postprocess.md）归档"
