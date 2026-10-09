#!/usr/bin/env python3
"""离线核验任务 YAML；不联网、不执行入口、不提交任务。"""

import argparse
from pathlib import Path, PurePosixPath
import re
import shlex
import sys

import yaml


MAX_TASK_NAME_LENGTH = 31
# 常见 YYYYMMDD / YYMMDD / YYYY_MM_DD / YYYY-MM-DD，可跟时间。
DATE_SUFFIX = re.compile(
    r"(?:^|_)(?:(?:19|20)?\d{2})[-_]?(?:0[1-9]|1[0-2])"
    r"[-_]?(?:0[1-9]|[12]\d|3[01])(?:[_-]?\d{4,6})?$"
)
SVOCC_WORKTREES = {"dev_semantic": "sem", "dev_asy": "asy"}


class UniqueKeyLoader(yaml.SafeLoader):
    """拒绝重复键，避免人工摘要与最终解析结果不一致。"""


def unique_mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in mapping:
            raise ValueError("YAML 含非字符串键或重复键")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping
)


def read_yaml(path):
    value = yaml.load(Path(path).read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
    if not isinstance(value, dict):
        raise ValueError("YAML 顶层必须是映射")
    return value


def differences(expected, actual, path=""):
    """只返回字段路径，不把可能敏感的字段值打印出来。"""
    if type(expected) is not type(actual):
        return [path]
    if isinstance(expected, dict):
        result = []
        for key in sorted(expected.keys() | actual.keys()):
            child = f"{path}.{key}" if path else key
            if key not in expected or key not in actual:
                result.append(child)
            else:
                result.extend(differences(expected[key], actual[key], child))
        return result
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return [path]
        result = []
        for index, (left, right) in enumerate(zip(expected, actual)):
            result.extend(differences(left, right, f"{path}[{index}]"))
        return result
    return [] if expected == actual else [path]


def validate(config, template, project, work_dir, allowed=(), *, worktree, experiment=None):
    errors = []
    if experiment is None:
        experiment = PurePosixPath(work_dir).name.removeprefix(f"{worktree}_")
    expected_name = f"dzp_{project}_{worktree}_{experiment}"
    if not project or not PurePosixPath(work_dir).name:
        errors.append("项目简称或输出根目录为空")
    for label, value in (("项目", project), ("工作树", worktree)):
        if not re.fullmatch(r"[a-z][a-z0-9]*", value):
            errors.append(f"{label}简称须为单个简短小写字母数字字段，不使用完整分支名")
    if not re.fullmatch(r"[A-Za-z0-9]+(?:_[A-Za-z0-9]+)*", experiment):
        errors.append("实验简称须为非空字母数字字段，可用下划线分隔")
    name = config.get("TaskName")
    if not isinstance(name, str):
        errors.append("TaskName 必须为字符串")
    else:
        if len(name) > MAX_TASK_NAME_LENGTH:
            errors.append("TaskName 最多 31 个字符（含下划线），请使用有意义的简称")
        if "smoke" in name.lower():
            errors.append("TaskName 禁止使用 smoke，不可豁免")
        if DATE_SUFFIX.search(name):
            errors.append("TaskName 不得带日期后缀")
    if config.get("TaskName") != expected_name:
        errors.append("TaskName 须匹配 dzp_<项目简称>_<工作树简称>_<实验简称>")
    if config.get("TaskName") == template["TaskName"]:
        errors.append("TaskName 仍为模板占位值")
    if config.get("Description") != "":
        errors.append("Description 必须为空字符串，不可豁免")
    if config.get("Tags") != []:
        errors.append("Tags 必须为空数组，不可豁免")

    entry = config.get("Entrypoint", "")
    lines = [line.strip() for line in entry.splitlines()] if isinstance(entry, str) else []
    if len(lines) != 5 or not all(lines):
        errors.append("Entrypoint 必须采用五行结构")
    else:
        if any(line.endswith("&&") for line in lines):
            errors.append("入口各行使用普通换行，不添加 &&")
        try:
            directory = shlex.split(lines[0])
            if len(directory) != 2 or directory[0] != "cd" or not directory[1].startswith("/"):
                errors.append("入口第一行必须 cd 到云端绝对路径")
            if lines[1] != ". /root/miniconda3/bin/activate":
                errors.append("入口第二行必须激活平台 conda")
            if lines[2] != "source haoce_activate.sh":
                errors.append("入口第三行必须加载项目环境")
            sync = shlex.split(lines[3])
            if (len(sync) != 3 or sync[0] != "bash"
                    or PurePosixPath(sync[1]).is_absolute()
                    or ".." in PurePosixPath(sync[1]).parts
                    or not sync[1].endswith(".sh")):
                errors.append("入口第四行应调用项目内相对路径的 Git 同步脚本并传入预期分支")
            elif (project == "svocc" or project.startswith("svocc_")) and sync[1] not in (
                    "cloud_sync.sh", "./cloud_sync.sh"):
                errors.append("SV-Occ 必须调用根目录 cloud_sync.sh，与 haoce_activate.sh 并列")
            if project == "svocc" and len(sync) == 3:
                expected_worktree = SVOCC_WORKTREES.get(sync[2])
                if expected_worktree and worktree != expected_worktree:
                    errors.append(f"当前分支的工作树简称须为 {expected_worktree}")
            shlex.split(lines[4])
        except ValueError:
            errors.append("入口命令的引号不匹配")
        if "replace_" in entry:
            errors.append("Entrypoint 仍有模板占位值")

    excluded = {"TaskName", "Entrypoint"}
    changed = differences(
        {key: value for key, value in template.items() if key not in excluded},
        {key: value for key, value in config.items() if key not in excluded},
    )
    allowed = set(allowed)
    for field in changed:
        if field not in allowed:
            errors.append(f"未经精确豁免的默认值变化：{field}")
    for field in allowed:
        if field not in changed:
            errors.append(f"豁免字段没有对应差异，请核对：{field}")
    return errors, changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config")
    parser.add_argument("--project", required=True)
    parser.add_argument("--worktree", required=True, help="工作树简称，例如 dev_semantic 使用 sem")
    parser.add_argument("--experiment", help="实验简称；默认取输出目录末级并去除已有工作树前缀")
    parser.add_argument("--work-dir", required=True)
    parser.add_argument(
        "--allow-change", action="append", default=[],
        help="仅用于用户明确要求的精确字段差异；不代表用户授权，描述和标签不可豁免",
    )
    args = parser.parse_args()
    template_path = Path(__file__).resolve().parents[1] / "references/ml-task-template.yaml"
    try:
        config = read_yaml(args.config)
        template = read_yaml(template_path)
        errors, changed = validate(
            config, template, args.project, args.work_dir, args.allow_change,
            worktree=args.worktree, experiment=args.experiment,
        )
    except (OSError, ValueError, yaml.YAMLError) as exc:
        # 不输出 YAML 原始异常上下文，避免意外泄露写入其中的敏感内容。
        print(f"配置读取或解析失败：{type(exc).__name__}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("本地配置校验通过；未联网、未执行入口、未提交任务。")
    if changed:
        print("仍须人工核对用户授权的差异：" + "、".join(changed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
