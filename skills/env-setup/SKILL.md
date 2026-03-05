---
name: env-setup
description: 复现开源代码仓库时自动配置 Python/C++/PyTorch/CUDA/MMCV 等技术栈的 conda 环境
---

# env-setup：开源仓库环境配置技能

适用于自动驾驶、视觉感知、三维重建等领域的开源仓库复现，技术栈涵盖 Python、C++、PyTorch、CUDA、MMCV 等。

## 工作流程总览

```
阶段 1：方案设计  →  用户审批  →  阶段 2：执行配置  →  阶段 3：验证汇报
```

---

## 阶段 1：方案设计

### 1.1 信息收集

按优先级依次读取以下文件（存在则读取）：

```
README.md / README.rst
requirements.txt / requirements*.txt
setup.py / setup.cfg / pyproject.toml
environment.yml / conda.yaml
docs/install.md / INSTALL.md
任何 setup.sh / install.sh 脚本
```

同时扫描源码中的关键导入，交叉验证文档中的版本声明：

```bash
grep -r "torch\." --include="*.py" -l | head -5
grep -r "mmcv\|mmdet\|mmseg\|mmdet3d" --include="*.py" -l | head -5
```

### 1.2 版本分析原则

**不可盲目信任文档**，需交叉验证：

| 检查项 | 方法 |
|--------|------|
| CUDA 版本 | 查看 requirements.txt 中 torch 的 --index-url（cu118/cu121 等） |
| torch 版本 | 与 MMCV 兼容矩阵交叉验证 |
| numpy 版本 | numpy 2.x 与旧版 torch/mmcv 不兼容，通常需 numpy<2 |
| setuptools | MMCV 编译常需降级至 setuptools==59.5.0 |

**MMCV ↔ PyTorch 兼容矩阵（常用）**：

| mmcv-full | torch | CUDA |
|-----------|-------|------|
| 1.6.x | 1.9 ~ 1.13 | 10.2 / 11.x |
| 1.7.x | 1.13 ~ 2.0 | 11.x / 12.x |
| 2.x (mmcv) | 2.0+ | 11.8 / 12.x |

若文档指定 mmcv-full==1.6.0 但 torch==2.1.0，版本冲突！需降级 torch 或升级 mmcv。

### 1.3 CUDA 版本决策

系统全局 CUDA 为 **11.8**（`/usr/local/cuda-11.8`）。

判断逻辑：
- 若项目所需 CUDA == 11.8 → 直接使用系统 CUDA，设置 `CUDA_HOME=/usr/local/cuda-11.8`
- 若项目所需 CUDA != 11.8 → **通过 conda 在环境内安装专属 CUDA**，不影响系统和其他环境：

```bash
# 示例：项目需要 CUDA 12.1
conda install -n <env_name> -c nvidia cuda-toolkit=12.1 -y
# 编译时指向 conda 环境内的 cuda
export CUDA_HOME=$CONDA_PREFIX
```

在方案文档中明确标注所用 CUDA 来源（系统 or conda 内置）。

### 1.4 安装顺序规划

严格按以下顺序规划，**不可颠倒**：

```
Step 1: 创建 conda 环境（python 版本由 README 指定）
Step 2: [若需要] conda 安装专属 CUDA toolkit
Step 3: 安装 numpy（指定版本，避免后续冲突）
Step 4: 安装 torch / torchvision / torchaudio（指定版本 + CUDA 后缀）
Step 5: 安装 setuptools（若需要降级）
Step 6: 安装 openmim，通过 mim 安装 mmcv/mmdet/mmseg/mmdet3d
Step 7: pip install 通用依赖（跳过已安装的核心库）
Step 8: 编译 CUDA 扩展（models/csrc、lib/pointops 等）
Step 9: 安装可选加速库（pyturbojpeg 等，需 sudo 的告知用户）
```

### 1.5 数据与模型准备（仅梳理，不执行）

汇总 README 中涉及的数据集下载、预训练模型下载、数据预处理步骤，以列表形式呈现，**不执行任何下载操作**。

### 1.6 输出方案文档

将方案以 Markdown 格式写入项目的 **`docs/env-setup-plan.md`**（若 docs/ 不存在则创建），同时在对话中展示给用户。

文档结构：

```markdown
# 环境配置方案 — <项目名>

## 基本信息
- conda 环境名、Python 版本、CUDA 来源（系统/conda）及版本、PyTorch 版本

## 版本冲突分析
- 列出发现的冲突及解决方案

## 安装步骤
- 按顺序列出每一步完整命令

## 需要 sudo 的步骤（用户手动执行）
- 列出需要 sudo 的命令

## 数据与模型准备（供参考，不执行）
- 数据集、模型下载步骤清单
```

**等待用户审批后再进入阶段 2。**

---

## 阶段 2：执行配置

### 2.1 环境准备

```bash
# 读取 .bashrc，加载 conda 等环境变量
grep -E "conda|cuda|PATH" ~/.bashrc | head -30
source ~/.bashrc 2>/dev/null || true
which conda && conda --version
# 确认系统 CUDA
ls /usr/local/cuda*/version.txt 2>/dev/null || nvcc --version 2>/dev/null
```

### 2.2 创建 conda 环境

```bash
conda create -n <env_name> python=<version> -y

# 使用完整路径，避免 activate 失效问题
CONDA_PREFIX=/home/dzp62442/miniconda3/envs/<env_name>
PIP=$CONDA_PREFIX/bin/pip
PYTHON=$CONDA_PREFIX/bin/python
```

### 2.3 conda 内安装专属 CUDA（仅当项目所需 CUDA ≠ 系统 11.8 时）

```bash
conda install -n <env_name> -c nvidia cuda-toolkit=<x.y.z> -y  # 必须用完整三段版本号，如 12.1.0，否则 conda 会安装最新版
# 后续编译时使用：
export CUDA_HOME=$CONDA_PREFIX
export PATH=$CUDA_HOME/bin:$PATH
export LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH
```

若项目所需 CUDA == 11.8，则直接使用系统路径：

```bash
export CUDA_HOME=/usr/local/cuda-11.8
export PATH=$CUDA_HOME/bin:$PATH
export LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH
```

### 2.4 代理配置

**始终在脚本开头设置代理环境变量**（pip/mim/conda 均通过环境变量继承，不要用 --proxy 参数，mim 不支持）：

```bash
export http_proxy=http://127.0.0.1:7890
export https_proxy=http://127.0.0.1:7890
export HTTP_PROXY=http://127.0.0.1:7890
export HTTPS_PROXY=http://127.0.0.1:7890
# 定义 PROXY 变量供 pip 备用（conda/mim 只认环境变量）
PROXY="--proxy http://127.0.0.1:7890"
```

### 2.5 核心库安装

```bash
$PIP install "numpy==<version>" $PROXY
$PIP install torch==<version> torchvision==<version> torchaudio==<version> \
    --index-url https://download.pytorch.org/whl/cu<cuda_suffix> $PROXY
$PIP install "setuptools==59.5.0" $PROXY
```

### 2.6 MMCV 生态安装

mim 不支持 --proxy 参数，**必须通过 2.4 节的环境变量传代理**，否则依赖包走直连会超时。

```bash
$PIP install openmim $PROXY
# mim 继承环境变量中的代理，无需额外参数
$CONDA_PREFIX/bin/mim install mmcv-full==<version>
$CONDA_PREFIX/bin/mim install mmdet==<version>
$CONDA_PREFIX/bin/mim install mmsegmentation==<version>
$CONDA_PREFIX/bin/mim install mmdet3d==<version>
```

### 2.7 通用依赖安装

```bash
$PIP install -r requirements.txt \
    --ignore-installed torch torchvision torchaudio numpy setuptools
```

### 2.8 CUDA 扩展编译

确保 CUDA_HOME 已按 2.3 节设置，然后：

```bash
cd models/csrc && $PYTHON setup.py build_ext --inplace && cd ../..
cd lib/pointops && $PIP install . && cd ../..
```

### 2.9 需要 sudo 的步骤

遇到需要 sudo 的命令，停止执行，告知用户：

```
⚠️ 以下步骤需要 sudo 权限，请在终端手动执行：
  sudo apt-get update
  sudo apt-get install -y libturbojpeg
执行完成后告知我，我将继续后续步骤。
```

### 2.10 耗时任务处理

预计耗时 > 2 分钟的任务（torch 下载、CUDA 扩展编译等），使用 `run_in_background=true` 的 Bash 工具执行，日志写到 /tmp/ 文件，完成后通知。
**不要用 subagent**——subagent 的 Bash 权限受限，无法执行安装命令。

---

## 阶段 3：验证与汇报

### 3.1 环境验证

```bash
conda run -n <env_name> python - << 'EOF'
import sys
print(f"Python: {sys.version}")
import numpy as np; print(f"NumPy: {np.__version__}")
import torch
print(f"PyTorch: {torch.__version__}")
print(f"CUDA available: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"CUDA version: {torch.version.cuda}")
    print(f"GPU: {torch.cuda.get_device_name(0)}")
for pkg in ['mmcv', 'mmdet', 'mmseg', 'mmdet3d']:
    try:
        m = __import__(pkg); print(f"{pkg}: {m.__version__}")
    except ImportError as e: print(f"{pkg}: FAILED - {e}")
for ext in ['_msmv_sampling_cuda', 'pointops']:
    try:
        __import__(ext); print(f"{ext}: OK")
    except ImportError as e: print(f"{ext}: FAILED - {e}")
EOF
```

### 3.2 汇报格式

输出包含：
- 版本对比表（期望版本 vs 实际版本 vs 状态）
- CUDA 来源说明（系统 or conda 内置）
- conda activate 命令
- 踩坑记录（问题 → 解决方案）
- 待用户手动完成的事项清单

---

## 常见问题速查

| 问题 | 原因 | 解决方案 |
|------|------|---------| 
| mmcv 与 torch 版本不兼容 | 文档版本冲突 | 查 mmcv 官方兼容矩阵，降级 torch |
| numpy 导入报错 | numpy 2.x 不兼容 | pip install "numpy<2" |
| CUDA 扩展编译失败 | CUDA_HOME 未设置 | 按 2.3 节设置 CUDA_HOME |
| setuptools 编译报错 | 版本过高 | pip install setuptools==59.5.0 |
| pip 下载极慢 | 网络问题 | 启用 clash 代理（7890 端口） |
| mim install 找不到包 | openmim 未安装 | 先 pip install openmim |
| conda activate 无效 | 环境变量未加载 | 先 source ~/.bashrc |
| conda cuda 与系统 cuda 冲突 | PATH 顺序问题 | 确保 $CONDA_PREFIX/bin 在 /usr/local/cuda-11.8/bin 之前 |
| mim install 依赖下载超时 | mim 不支持 --proxy | 用环境变量 export http_proxy=... 传代理 |
| conda cuda 装了错误版本 | 版本号不精确 | 用完整三段版本号如 cuda-toolkit=12.1.0 |
