---
name: volc-ml-task
description: 火山引擎机器学习平台 Volc CLI 的自定义训练任务管理技能。用于查看、筛选、诊断、导出、提交火山机器学习平台 ml_task 训练任务，尤其是用户以 dzp 开头创建的任务；也适用于解释或生成 volc ml_task submit/list/get/logs/export/instance 命令和训练 YAML 配置。对创建、取消、停止、删除等会改变线上任务状态的操作必须谨慎处理。
---

# Volc ML Task

使用火山引擎机器学习平台 CLI 管理自定义训练任务时遵循本技能。

完整官网导出文档在 [references/full-cli-doc.md](references/full-cli-doc.md)。只有当本技能正文不足以回答问题、需要查询模型仓库/推理服务/完整字段含义/边缘参数时，才读取完整文档。优先用 `rg` 定位章节，例如：

```bash
rg -n "^### submit|^### logs|ResourceQueue|SidecarMemoryRatio" references/full-cli-doc.md
```

## 边界

- 不接管 `volc` 的安装、升级、`volc configure`、AK/SK/Region 配置。这些由用户手动完成。
- 默认认为用户已经完成凭证配置，配置文件位于 `$HOME/.volc/config` 和 `$HOME/.volc/credentials`。
- 在非交互 shell 中调用 `volc` 前，先加载最小环境文件 `$HOME/.volc_env`，不要为了 `volc` 加载完整 `$HOME/.shell_env`。
- 优先关注 `ml_task` 自定义训练任务。`ml_model`、`ml_service` 只在用户明确询问时再查完整文档。
- 官网文档中有些示例使用 `mlp`，但 `ml_task` 常规命令优先写成 `volc ml_task ...`。若本机只有 `mlp` 可用，再改用 `mlp`。

## 命令执行约定

Agent 通常在非交互 shell 中执行命令。运行任何 `volc` 命令前，先显式加载环境：

```bash
. "$HOME/.volc_env"
```

自动化读取任务信息时，优先使用机器可读输出：

- `list`、`get`、`instance list` 支持 `--output json`，Agent 默认加上。
- `submit` 支持 `--output json`，但提交任务必须先二次确认。
- `logs` 输出日志文本，按需使用 `--lines`、`--content`、`--reverse`、`-f`。
- `upload`、`export`、`cancel` 按文档没有通用 `--output json`，不要强行添加未知参数。

不加 `--output json` 时，`list`、`get`、`instance list` 可能进入面向人工的交互/格式化输出，不适合作为 Agent 默认模式。已验证 `volc ml_task list -n dzp` 会进入交互式 `TaskList` 界面，在非 TTY 场景下可能以 `exit status 255` 结束。

## 安全规则

- 用户创建的任务名称都以 `dzp` 开头。列任务、查任务时优先加 `-n dzp` 或 `--name dzp`，过滤大量无关任务。
- 任何任务创建操作，包括 `volc ml_task submit`，执行前必须向用户二次确认，并展示将要执行的命令和关键配置摘要。
- 原则上不要替用户取消、停止、删除任务。除非用户强烈要求，并且在二次确认中明确给出任务 ID 与操作类型。
- 执行取消/停止/删除前，必须先用 `get` 或 `list` 核对任务 ID、任务名、状态、创建者/可见范围等可获得信息，避免误操作。
- 不要在未经用户确认时修改线上任务状态；只读命令如 `list/get/logs/export/instance list` 可以直接执行。

## 状态解读

- 火山机器学习平台可能因自动调度、闲时资源抢占、自动重试等机制改变任务状态。
- 可抢占任务可能出现旧任务变为 `Killed`，随后平台自动复制/创建一个同名的新任务继续排队或运行。这通常不代表用户手动停止。
- 代码或环境存在 bug 时，任务可能 `Failed` 后自动重试，直到达到配置的重试上限。用户当前常见上限为 5 次。
- 遇到同名任务一旧一新、旧任务 `Killed` 或 `Failed`、新任务继续 `Running/Queue/Staging` 时，优先解释为平台重调度/重试现象；需要确认原因时再查看任务详情和日志。
- 任务日志时间可能与本地/平台展示时间差 8 小时。如果日志内容连续且与任务运行阶段吻合，优先判断为日志时区错位，而不是日志陈旧；用户后续可能修复该问题。

## 用户调用方式

### 看当前状态

用户说“看一下现在的状态”“现在任务怎么样了”等类似描述时：

1. 先列出近 10 条、全部常见状态的 `dzp` 任务，使用精简字段输出。
2. 找出 `Running/Queue/Staging` 任务，优先关注 `Running`。
3. 对正在运行的任务查看最新 100 条日志，概括训练/验证进度、最近指标、是否有明显错误。
4. 若出现同名旧任务 `Killed/Failed` 后新任务继续运行，按平台重调度/抢占/重试现象解释，除非日志或详情显示明确异常。

```bash
. "$HOME/.volc_env"
volc ml_task list -n dzp \
  --status Initialized,Queue,Staging,Running,Killing,Success,Failed,Killed,Exception \
  --limit 10 \
  --offset 0 \
  --output json \
  --format=JobId,JobName,Status,Start,End
```

对每个需要查看进度的运行中任务：

```bash
volc ml_task logs -t <task-id> -i worker_0 --lines 100
```

若用户要求“查看更多”“历史任务”等，再列出近 25 条任务；超过 25 条时再增大 `--limit` 或用 `--offset` 翻页。

## 常用命令

### 列出用户相关任务

列出近 10 条、全部常见状态的 `dzp` 任务：

```bash
. "$HOME/.volc_env"
volc ml_task list -n dzp \
  --status Initialized,Queue,Staging,Running,Killing,Success,Failed,Killed,Exception \
  --limit 10 \
  --offset 0 \
  --output json \
  --format=JobId,JobName,Status,Start,End
```

列出近 25 条、全部常见状态的 `dzp` 任务：

```bash
volc ml_task list -n dzp \
  --status Initialized,Queue,Staging,Running,Killing,Success,Failed,Killed,Exception \
  --limit 25 \
  --offset 0 \
  --output json \
  --format=JobId,JobName,Status,Start,End
```

`--output json` 下默认只返回 10 条。需要超过 25 条时，再显式增大 `--limit` 或使用 `--offset` 翻页：

```bash
volc ml_task list -n dzp \
  --status Initialized,Queue,Staging,Running,Killing,Success,Failed,Killed,Exception \
  --limit 100 \
  --offset 0 \
  --output json \
  --format=JobId,JobName,Status,Start,End
```

按状态筛选：

```bash
volc ml_task list -n dzp --status Queue,Staging,Running --limit 10 --output json
volc ml_task list -n dzp --status Success,Failed,Killed,Exception --limit 25 --output json
```

需要限定输出字段时，先查询支持的字段：

```bash
volc ml_task list --helpformat
volc ml_task list -n dzp \
  --status Initialized,Queue,Staging,Running,Killing,Success,Failed,Killed,Exception \
  --limit 100 \
  --offset 0 \
  --output json \
  --format=JobId,JobName,Status,Start,End
```

### 查看任务详情

```bash
. "$HOME/.volc_env"
volc ml_task get --id t-xxxxxxxxxxxxxxxxxxxxx
volc ml_task get --id t-xxxxxxxxxxxxxxxxxxxxx --output json
```

用途：
- 核对任务名称、状态、资源队列、镜像、入口命令、参数、实例规格、存储挂载。
- 在任何危险操作前确认目标任务。
- 从线上任务还原配置时，结合 `export` 使用。

### 查看实例列表

```bash
. "$HOME/.volc_env"
volc ml_task instance list --id t-xxxxxxxxxxxxxxxxxxxxx
volc ml_task instance list --id t-xxxxxxxxxxxxxxxxxxxxx --output json
```

实例列表可能返回完整实例名，例如 `t-xxxxxxxx-worker-0`。日志命令通常使用角色实例短名，例如 `worker_0`，不要直接把完整实例名传给 `logs -i`。

### 查看日志

查看某个任务的最新 100 条日志：

```bash
. "$HOME/.volc_env"
volc ml_task logs -t t-xxxxxxxxxxxxxxxxxxxxx -i worker_0 --lines 100
```

其他常用日志查询：

```bash
volc ml_task logs --task t-xxxxxxxxxxxxxxxxxxxxx --instance worker_0
volc ml_task logs -t t-xxxxxxxxxxxxxxxxxxxxx -i worker_0 --lines 200
volc ml_task logs -t t-xxxxxxxxxxxxxxxxxxxxx -i worker_0 --content error --lines 200
volc ml_task logs -t t-xxxxxxxxxxxxxxxxxxxxx -i worker_0 -f
```

要点：
- `--content` 支持 Lucene 检索语法。
- 不加 `--reverse` 时，默认从当前时间向前取最新 `--lines` 条日志；这是查看当前进度的正确方式。
- `--reverse` 会从任务启动时间开始取最早的 `--lines` 条日志，不适合查看最新进度。
- `--lines` 默认 500；常规进度查询优先用 `--lines 100`，避免占用过多上下文。
- `-f` 持续滚动日志；长时间跟随日志时应避免阻塞当前工作，必要时放入 tmux。
- 如果日志时间与平台/本地时间刚好相差 8 小时，大概率是日志时区错位；结合任务状态和日志内容判断，不要直接认为日志停滞。

### 导出任务配置或代码

```bash
. "$HOME/.volc_env"
volc ml_task export --task t-xxxxxxxxxxxxxxxxxxxxx --config
volc ml_task export --task t-xxxxxxxxxxxxxxxxxxxxx --code
volc ml_task export --task t-xxxxxxxxxxxxxxxxxxxxx --config --code
```

用途：
- 从已有任务导出 YAML 配置，作为新任务模板。
- 下载任务代码进行排查。

### 上传训练代码

可以在提交任务时上传代码，也可以提前上传以加速创建：

```bash
. "$HOME/.volc_env"
volc ml_task upload --local_code_path ./path/to/code --region cn-beijing
```

常用选项：
- `--local_diff on|off`：是否仅上传增量，默认 `on`。
- `--copy-links`：上传软链接指向的实际文件；当软链接是绝对路径或指向上传目录外文件时优先使用。
- `--links`：直接上传软链接；仅当容器内存在相同链接关系时使用。

### 提交训练任务

提交任务属于创建线上任务，必须二次确认后再执行。

```bash
. "$HOME/.volc_env"
volc ml_task submit -c task.yaml
```

常见覆盖参数：

```bash
volc ml_task submit \
  -c task.yaml \
  -n dzp-example-task \
  --entrypoint "python train.py" \
  --args "--config configs/train.yaml --epochs 10" \
  --image "image-url" \
  --resource_queue_id "q-xxxxxxxx" \
  --framework Custom \
  --output json
```

提交前检查：
- 任务名必须以 `dzp` 开头，除非用户明确要求其他命名。
- `UserCodePath` 与 `RemoteMountCodePath` 是否匹配。
- `Entrypoint` 和 `Args` 是否会被命令行参数覆盖。
- `ImageUrl` 是否正确，私有镜像是否需要 `ImageCredential`。
- `ResourceQueueID` 或 `ResourceQueueName` 是否正确；`ResourceQueueName` 优先级高于 `ResourceQueueID`。
- `Framework` 是否为支持值：`TensorFlowPS`、`PyTorchDDP`、`MXNet`、`BytePS`、`MPI`、`Custom`。
- `TaskRoleSpecs` 中 `RoleName`、`RoleReplicas`、`Flavor`、`GpuRate` 是否符合预期。
- `Storages` 中 TOS/NAS/vePFS 挂载路径、只读配置、缓存参数是否合理。
- 若挂载 TOS，注意 `SidecarMemoryRatio`。填写时建议 `SidecarMemoryRatio * 实例规格内存 >= 4GiB`，否则可能挂载失败或容器异常。
- `AccessType` 与 `AccessUsers` 是否会暴露给不该看到任务的人。
- `Preemptible`、`Priority`、`RetryOptions`、`DiagOptions` 是否符合用户意图。

`--entrypoint` 示例：

```bash
--entrypoint=./start.sh
--entrypoint="python main.py"
```

`--args` 示例，以下形式等价：

```bash
--args=--aaa=1 --args=--bbb=2 --args=--ccc=3
--args="--aaa=1 --bbb=2 --ccc=3"
--args='--aaa=1 --bbb=2' --args=--ccc=3
```

`--set` 可覆盖 YAML 中字段，但优先级低于其他显式 flag：

```bash
volc ml_task submit -c task.yaml --set Entrypoint="sleep 5s" --set Priority=4
```

### 取消任务

取消任务会改变线上任务状态。原则上不执行，除非用户强烈要求并完成二次确认。

```bash
. "$HOME/.volc_env"
volc ml_task cancel --id t-xxxxxxxxxxxxxxxxxxxxx
```

执行前必须先运行：

```bash
. "$HOME/.volc_env"
volc ml_task get --id t-xxxxxxxxxxxxxxxxxxxxx --output json
```

并向用户复述目标任务 ID、任务名、当前状态和即将执行的取消命令。

## 配置文件重点

`ml_task submit -c task.yaml` 的 YAML 常见字段：

- `TaskName`：任务名，用户任务默认以 `dzp` 开头。
- `Description`：任务描述。
- `Entrypoint`、`Args`：入口命令和参数。
- `UserCodePath`：本地代码路径。目录以 `/` 结尾时上传目录下内容；不以 `/` 结尾时上传目录本身及其内容。
- `RemoteMountCodePath`：容器内代码挂载路径。
- `Envs`：环境变量，`IsPrivate: true/false` 控制详情页可见性。
- `ImageUrl`、`ImageCredential`：镜像及私有镜像凭证。
- `ResourceQueueID`、`ResourceQueueName`：资源队列，名称优先级更高。
- `Framework`：训练框架。
- `TaskRoleSpecs`：角色、实例数、规格、GPU 切分。
- `ActiveDeadlineSeconds`、`DelayExitTimeSeconds`：最长运行时间和实例保留时长。
- `AccessType`、`AccessUsers`：可见范围和可见用户。
- `Preemptible`、`Priority`：可抢占与优先级。
- `RetryOptions`：自动重试。
- `DiagOptions`：任务诊断。
- `PrivateNetwork`：VPC/Subnet/安全组。
- `CustomServices`：自定义指标采集端口。
- `EnableTensorBoard`、`TensorBoardStorage`：TensorBoard。
- `SidecarMemoryRatio`、`Storages`：TOS/NAS/vePFS 数据盘挂载。

字段细节或完整样例不足时，读取 [references/full-cli-doc.md](references/full-cli-doc.md) 中 `ml_task submit` 章节。
