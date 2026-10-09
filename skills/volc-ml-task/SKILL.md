---
name: volc-ml-task
description: 火山引擎机器学习平台 Volc CLI 自定义训练任务管理。用于查看、筛选、诊断、导出 dzp 任务，以及准备、校验和经用户授权提交训练 YAML；不接管凭证配置，不擅自创建、停止或删除任务。
---

# Volc ML Task

## 范围与调用环境

- 用户任务名称以 `dzp` 开头；查询列表时用 `-n dzp`，用户已指定任务 ID 时直接查询该任务。
- 不安装、升级 `volc`，不运行 `volc configure`，不改动 AK/SK、账号或 Region。沿用用户已有 API 密钥鉴权；不读取、回显或复制密钥到配置、日志、文档中。
- 每次在非交互 shell 调用 `volc` 前，先 `. "$HOME/.volc_env"`；不要加载完整 `.shell_env`。
- `list/get/instance list/submit` 默认加 `--output json`，避免交互界面。`logs/export/cancel` 不添加未经支持的输出参数。
- 常规命令使用 `volc ml_task`；只有本机确实仅有 `mlp` 时才替换命令名。

## 授权与监控边界

- 查看、分析、编写配置不代表获准提交。创建任务前展示配置摘要与命令，取得用户对本轮任务的明确确认；若用户已对同一份配置和提交次数作出明确授权，不重复索要同一确认。新改动或新增任务超出授权时重新确认。
- 提交授权不包含 commit、push、安装依赖、停止、取消或删除其他任务。项目 README / 本轮指令仍要求用户手动提交时，不能仅凭本技能改为自动提交。
- 取消、停止、删除必须由用户明确要求；操作前只读核验任务 ID、名称、状态和可获得的创建者信息，再确认具体目标与操作。
- **除非用户明确要求持续监控，否则只做一次状态检查；不等待排队结束、不持续轮询、不使用 `logs -f`。** 用户已有独立监控服务。
- 创建请求超时不等于创建失败；先查询是否已创建，无法确定时报告，不盲目重提。平台自动重试不等于授权 Agent 另建任务。

## 用户固定默认值

以下是用户明确指定的默认配置。**除非用户明确要求修改对应项，否则绝对不许改变，也不能为排队、报错或测试方便自行降级或替换。** 以 [ml-task-template.yaml](references/ml-task-template.yaml) 为配置基准：

| 项目 | 固定默认值 |
| --- | --- |
| 队列 | `c20250502`，ID `q-20251224110115-844wd` |
| 优先级与闲时资源 | `Priority: 9`，`Preemptible: true` |
| 计算资源 | 一个 worker 实例，`ml.pni2.14xlarge`，4 卡 Tesla A100-80G，`PyTorchDDP` |
| 镜像 | `cr-mlp-cn-beijing.cr.volces.com/public/haoce_dev_template_base:v1` |
| TOS | `c20250502` 桶根目录挂载到 `/c20250502`，Fuse，读写（`ReadOnly: false`） |
| vePFS | 模板中的两处挂载，均为读写；路径、子目录和文件系统 ID 不变 |
| 鉴权 | 沿用现有 API 密钥及平台权限，不更换身份或鉴权方式 |
| 自动重试 | 开启，间隔 120 秒，上限 10 次；触发条件为 Failed、MachineFailure、InstanceReclaimed，不保留重试资源 |
| 其他环境项 | 沿用模板的运行时限、缓存方式、关闭 TensorBoard 和诊断项等配置 |

另外两项硬要求：

- **绝对不填写任务名称下面的描述和标签。** YAML 保持 `Description: ""`、`Tags: []`；不得借用描述、标签记录 commit、方案摘要或提交追踪信息，也不得通过 CLI 参数覆写。
- **云端任务入口指令必须简洁。** 固定采用五行结构：进入工作树、激活平台 conda、加载项目环境、调用项目内 Git 同步脚本、执行 Goal 交付的单一实验指令。各行用普通换行分隔，不添加 `&&`。其他校验放入脚本，不能把长检查命令或内联程序塞进入口；不必压缩成两行。

TOS 可读写只代表挂载权限，不授权删除、移动、覆盖长期共享数据或缓存。项目既有数据保护约定仍然有效。

## 查看状态与日志

一次状态检查按需使用列表、详情和日志，不是只能调用一条命令。默认只列最近 10 条，用户要求更多历史时再取 25 条或翻页：

```bash
. "$HOME/.volc_env"
volc ml_task list -n dzp \
  --status Initialized,Queue,Staging,Running,Killing,Success,Failed,Killed,Exception \
  --limit 10 --offset 0 --output json \
  --format=JobId,JobName,Status,Start,End
volc ml_task get --id <task-id> --output json
volc ml_task logs -t <task-id> -i worker_0 --lines 100
```

- 优先查看 Running，其次 Queue/Staging；只读相应任务的必要日志。
- `get --output json` 默认字段有限，按需用 `get --helpformat` 后指定 `--format`。不要因为默认输出没有某字段就认定它未配置。
- `logs` 默认向前取最近日志；`--reverse` 取任务开始时的日志，不适合检查最新进度。按需用 `--content error` 筛选。
- `instance list --id <task-id> --output json` 返回的完整实例名不是日志参数；日志通常使用 `worker_0`。
- 日志与平台时间可能差 8 小时，应结合内容判断时区，不直接认为任务停滞。
- 同名旧任务 Killed/Failed、新任务继续运行时，可能是资源回收或自动重试；结合详情与日志判断，不武断认定用户停止或程序必然有 bug。重试上限读取当前任务配置，用户现默认是 10 次。

## 准备与提交任务

涉及准备 YAML、解释具体提交指令或实际提交时，必须阅读 [提交流程](references/submit-workflow.md)。它包含工作树与入口选择、默认值核验、提交前确认、防止重复创建和提交后的一次性回读。

- 默认只修改 `TaskName` 和 `Entrypoint`，其余保持模板配置。
- 命名为 `dzp_<project>_<worktree>_<experiment>`：依次是姓名、项目简称、工作树简称、实验简称；SV-Occ 的 `dev_semantic` 使用 `sem`。总长最多 **31 个字符**（含下划线），以 `dzp_svocc_sem_gauss_suppress_v1` 为上限示例。绝不使用 `smoke`，不加日期后缀，不展开冗长分支全名。实验名可含下划线，保留核心方法、用途或必要版本；参考已有名称作有意义的缩写，不机械截断。任务简称与真实输出目录分别记录，不要求字面一致，也不为命名修改实验目录。
- [本地配置校验器](scripts/validate_task_config.py) 仅解析配置、核对默认值，不联网、不提交；需要现有 Python 环境有 PyYAML。它不能证明用户已授权或云端环境已就绪。
- `cloud_sync.sh` 是 SV-Occ 项目专用脚本，由 SV-Occ 仓库维护在根目录，与 `haoce_activate.sh` 并列；本技能不保存或分发其副本。其他项目使用自身的同步脚本，不直接套用 SV-Occ 实现。首次上云仍需确认项目脚本已同步，见提交流程。
- 只读导出任务时，使用独立临时目录：`volc ml_task export --task <task-id> --config`。**导出不一定完整**：已验证的四个历史任务均启用 Preemptible，但导出 YAML 未保留此字段。必须结合 `get` 和固定模板复核，不能直接把导出文件原样提交。
- 当前工作流使用 vePFS 已有仓库和 Git 更新，`UserCodePath`、`RemoteMountCodePath` 留空。不要顺手上传代码包，更不要用 `--copy-links` 把数据、权重或 work_dirs 软链接目标整体上传。

## 危险操作

只有明确获准后才能执行。例如取消前先核对，再确认具体任务：

```bash
. "$HOME/.volc_env"
volc ml_task get --id <task-id> --output json
# 仅在具体取消操作得到确认后执行：
volc ml_task cancel --id <task-id>
```

## 进一步查询

[完整 CLI 文档](references/full-cli-doc.md) 是历史官网导出资料，仅在正文和提交流程不足时按需查阅。通用示例不能覆盖用户的固定默认值或权限边界；不确定当前支持的字段时先看本机 `--help`，必要时再核对官方文档。

```bash
rg -n "^### submit|^### export|SidecarMemoryRatio|AccessType" references/full-cli-doc.md
```

`ml_model`、`ml_service` 只在用户明确询问时查阅。只有另行授权使用代码上传工作流时，才查 `ml_task upload`、`--links`、`--copy-links` 的细节。
