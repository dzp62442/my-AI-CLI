---
name: env-setup
description: 复现开源代码仓库时自动配置 Python/C++/PyTorch/CUDA/MMCV 等技术栈的 conda 环境，先产出 requirements.txt 和安装方案，再通过 tmux 串行执行 conda/pip/编译命令，适用于视觉、三维重建、自动驾驶等仓库。
---

# env-setup：开源仓库环境配置技能

适用于自动驾驶、视觉感知、三维重建等开源仓库复现，技术栈涵盖 Python、C++、PyTorch、CUDA、MMCV 等。

## 工作流程总览

```text
阶段 1：方案设计与依赖整理 → 用户审批 → 阶段 2：tmux 中执行安装 → 阶段 3：验证与汇报
```

原则：
- 不盲信 README，必须交叉验证源码导入、依赖文件和实际安装结果。
- 方案设计阶段就产出可执行的 `requirements.txt`，不要等到安装阶段再临时拼。
- 所有下载安装、编译命令、`conda` 命令都在 `tmux` 中运行，日志落到 `/tmp/`，不要在前台直接跑长命令，不要在 Codex 前台/沙箱里直接跑 `conda info`、`conda env list`、`conda install`。
- 默认不配置代理。用户已使用 TUN 模式时，不再添加 `http_proxy/https_proxy`。

---

## 阶段 1：方案设计与依赖整理

### 1.1 信息收集

按优先级依次读取以下文件：

```text
README.md / README.rst
requirements.txt / requirements*.txt
setup.py / setup.cfg / pyproject.toml
environment.yml / conda.yaml
docs/install.md / INSTALL.md
任何 setup.sh / install.sh 脚本
```

同时扫描源码中的关键导入，交叉验证依赖声明：

```bash
rg -n "^(import|from) " --glob '*.py' .
rg -n "torch\.|mmcv|mmdet|mmseg|mmdet3d" --glob '*.py' .
```

### 1.2 版本分析原则

重点检查：
- Python 版本是否与 wheel 生态兼容。
- CUDA 版本来自系统还是环境内。
- torch / torchvision / torchaudio 是否匹配同一 CUDA 后缀。
- numpy 是否会被其他包升到 2.x；旧 torch / mmcv / 扩展通常不适合 numpy 2.x。
- setuptools 是否过新；`torch.utils.cpp_extension` 仍可能依赖 `pkg_resources`，必要时使用 `setuptools<81`。

常用兼容判断：
- 若项目明确要求 `cu118`，优先使用系统 `/usr/local/cuda-11.8`。
- 若项目含 MMCV 生态，必须额外核对官方兼容矩阵，不可只看 README。

### 1.3 CUDA 版本决策

系统全局 CUDA 为 **11.8**（`/usr/local/cuda-11.8`）：
- 若项目也需要 11.8，直接使用系统 CUDA：

```bash
export CUDA_HOME=/usr/local/cuda-11.8
export PATH=$CUDA_HOME/bin:$PATH
export LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH
```

- 若项目需要其他 CUDA 版本，再通过 conda 安装环境内 toolkit，并把 `CUDA_HOME=$CONDA_PREFIX`。

### 1.4 编写 requirements.txt

若仓库根目录没有合适的 `requirements.txt`，或现有文件明显缺失/混乱，则在方案设计阶段直接生成或更新根目录 `requirements.txt`，来源包括：
- 根 `environment.yml` 中的 pip 依赖
- 子模块已有 `requirements*.txt`
- 源码实际导入但依赖文件未声明的第三方包
- 需要剔除或修正的错误 pin

生成后要在方案里明确说明：
- 这个 `requirements.txt` 是新建还是修订
- 哪些包是补上的
- 哪些版本被改写以及原因

### 1.5 安装顺序规划

默认顺序：

```text
Step 1: 创建 conda 环境
Step 2: [若需要] 安装环境内 CUDA toolkit
Step 3: 安装 numpy
Step 4: 安装 torch / torchvision / torchaudio
Step 5: 调整 setuptools 版本
Step 6: [若使用 MMCV 生态] 安装 openmim，通过 mim 安装 mmcv/mmdet/mmseg/mmdet3d
Step 7: 安装其余 Python 依赖（requirements.txt）
Step 8: 编译 CUDA / C++ 扩展
Step 9: 安装其他库（如有）
Step 10: 验证环境
```

### 1.6 数据与模型准备（仅梳理，不执行）

把 README 中提到的数据集、权重、预处理步骤列成清单。

### 1.7 输出方案文档

将方案写入项目内 `docs/env-setup-plan.md`，同时在对话里展示摘要。

文档至少包含：

```markdown
# 环境配置方案 — <项目名>

## 基本信息
- conda 环境名
- Python 版本
- CUDA 来源与版本
- torch 版本

## 版本冲突分析
- 冲突项
- 解决方式

## requirements.txt 设计
- 新建或修订说明
- 关键包来源与版本调整

## 安装步骤
- 按顺序列出完整命令

## 数据与模型准备
- 仅清单，不执行
```

**等待用户审批后再进入阶段 2。**

---

## 阶段 2：tmux 中执行安装

### 2.1 统一规则：所有安装命令都在 tmux 中运行

所有会修改环境、联网下载、编译扩展的命令，都必须在 `tmux` 会话中执行。

标准做法：
- 新建专用会话，例如 `env_install`、`repo_env_install`
- `conda` 相关命令一律在该会话的宿主机 shell 中执行
- 把每一段命令通过 `tmux send-keys` 发进去
- 日志统一写到 `/tmp/<repo>_env_install.log`
- 通过 `tmux capture-pane` 和 `tail` 轮询进度
- 不要把长命令直接阻塞在前台 shell

推荐模式：

```bash
tmux new-session -d -s <session>
tmux send-keys -t <session> "cd <repo> && <command> |& tee -a /tmp/<log>.log" C-m
tmux capture-pane -t <session> -p | tail -n 40
tail -n 40 /tmp/<log>.log
```

### 2.2 tmux 实战经验

在实际安装中，优先遵循以下经验：
- 会话名固定，避免重复创建多个安装会话。
- 会话启动后先 `source ~/.bashrc`，确保宿主 shell 能正确拿到 `conda` 初始化。
- 每一段命令前打印阶段标题和时间戳，便于回看日志。
- 同一会话内串行发送命令；只有确认 shell 返回 prompt 后再发下一段。
- `tmux capture-pane` 能看到实时状态，但 `tee`/pip 有时会缓冲；必要时同时检查 `/tmp/*.log` 和进程状态。
- 若要确认会话是否空闲，可向 tmux 发送一个空回车，再抓 pane 输出。
- 长下载阶段不要误判为卡死；结合临时文件大小、`ps`、日志一起判断。
- 环境状态优先用环境目录和 `$PYTHON` 做验证，不要依赖前台 `conda info` / `conda env list`。

### 2.3 环境准备

```bash
source ~/.bashrc 2>/dev/null || true
which conda && conda --version
ls /usr/local/cuda*/version.txt 2>/dev/null || nvcc --version 2>/dev/null
```

### 2.4 创建 conda 环境

```bash
conda create -n <env_name> python=<version> pip -y
```

若 conda 因插件、虚拟包或求解器报错，优先尝试：

```bash
export CONDA_NO_PLUGINS=true
conda create --solver=classic -n <env_name> python=<version> pip -y
```

创建后统一使用绝对路径：

```bash
CONDA_PREFIX=/home/dzp62442/miniconda3/envs/<env_name>
PYTHON=$CONDA_PREFIX/bin/python
PIP="$PYTHON -m pip"
```

### 2.5 核心库安装

优先使用环境内 Python 直接调用 pip，不要默认用 `conda run -n ... pip` 跑大下载任务。

```bash
$PIP install --upgrade pip wheel
$PIP install "numpy==<version>"
$PIP install torch==<version> torchvision==<version> torchaudio==<version> \
  --index-url https://download.pytorch.org/whl/cu<cuda_suffix>
```

若项目后续编译扩展，且 torch 的 C++ 扩展需要 `pkg_resources`，则在扩展编译前先执行：

```bash
$PIP install 'setuptools<81'
```

### 2.6 安装其余 Python 依赖

```bash
$PIP install -r requirements.txt
```

安装后需要重新核对以下核心版本是否被覆盖：
- numpy
- setuptools
- pillow
- requests

若与方案不符，要记录并决定是否回钉。

### 2.7 MMCV 生态

仅在项目实际使用 MMCV 生态时安装：

```bash
$PIP install openmim
$CONDA_PREFIX/bin/mim install mmcv-full==<version>
$CONDA_PREFIX/bin/mim install mmdet==<version>
$CONDA_PREFIX/bin/mim install mmsegmentation==<version>
$CONDA_PREFIX/bin/mim install mmdet3d==<version>
```

### 2.8 常见 CUDA 扩展编译经验

编译前先设置：

```bash
export CUDA_HOME=/usr/local/cuda-11.8
export PATH=$CUDA_HOME/bin:$PATH
export LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH
```

统一经验：
- 先装 torch，再编译本地 CUDA 扩展。
- 本地扩展默认优先尝试 `--no-build-isolation`，避免隔离环境看不到 torch。
- `simple-knn` 和 `diff-gaussian-rasterization` 可直接用同一模式安装：

```bash
$PIP install -v --no-build-isolation submodules/simple-knn
$PIP install -v --no-build-isolation submodules/diff-gaussian-rasterization
```

- 若同时存在 `croco/models/curope` 和 `dust3r/croco/models/curope`，要按实际导入路径编译；很多仓库实际走 `dust3r/croco`，此时不能只编根目录副本：

```bash
cd croco/models/curope && $PYTHON setup.py build_ext --inplace
cd <repo_root>
cd dust3r/croco/models/curope && $PYTHON setup.py build_ext --inplace
```

---

## 阶段 3：验证与汇报

### 3.1 基础验证

优先使用环境内 Python 验证，不直接依赖 `conda info` / `conda env list`。

优先验证：

```bash
$PYTHON - <<'EOF'
import torch
print('torch', torch.__version__)
print('cuda', torch.version.cuda)
print('cuda_available', torch.cuda.is_available())
EOF
```

### 3.2 扩展与业务验证

若直接导入自定义扩展报 `libc10.so` / `libtorch*.so` 找不到，先显式 `import torch`，必要时补：

```bash
export LD_LIBRARY_PATH=$CONDA_PREFIX/lib/python3.11/site-packages/torch/lib:$CUDA_HOME/lib64:$LD_LIBRARY_PATH
```

验证时按“通用扩展 → 项目入口”两层做：

```bash
$PYTHON - <<'EOF'
import torch
import simple_knn._C
import diff_gaussian_rasterization
print('gaussian extensions ok')
EOF
```

然后补充项目实际入口导入，例如 `from mast3r.model import AsymmetricMASt3R`、`import mmcv`、`import pointops`。若不再出现 `Warning, cannot find cuda-compiled version of RoPE2D`，说明对应 `curope` 已编译到实际导入路径。

### 3.3 汇报格式

汇报必须包含：
- 最终环境名与激活命令
- 关键版本：Python / torch / CUDA / numpy
- `requirements.txt` 是否新建或修订
- 已安装并验证通过的扩展
- 踩坑记录：问题 → 原因 → 解决方式
- 尚未完成的项

---

## 常见问题速查

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| conda 因插件或虚拟包报错 | 插件环境异常 | `export CONDA_NO_PLUGINS=true`，必要时加 `--solver=classic` |
| torch / 本地 CUDA 扩展编译异常 | torch 未先安装，或 build isolation 隔离了 torch | 先装 torch，再用 `pip install --no-build-isolation <local_pkg>` |
| `torch.utils.cpp_extension` 报 `pkg_resources` 缺失 | setuptools 过新 | `pip install 'setuptools<81'` |
| 直接导入自定义扩展时报 `libc10.so` 缺失 | torch 动态库未预加载 | 先 `import torch`，或补 `LD_LIBRARY_PATH` |
| 只编了根目录 `curope` 仍出现 RoPE 警告 | 实际导入走的是 `dust3r/croco` | 再编 `dust3r/croco/models/curope` |
| pip 大轮子下载时日志不动 | 输出缓冲，不一定卡死 | 同时检查 tmux pane、日志、进程和临时文件大小 |
| `conda run -n ... pip` 表现异常 | 包装层额外引入问题 | 优先用 `$CONDA_PREFIX/bin/python -m pip` |
