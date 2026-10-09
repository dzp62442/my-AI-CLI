"""任务配置的离线测试，不访问火山或 GitHub。"""

import copy
import importlib.util
from pathlib import Path
import unittest

import yaml

SKILL = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validator", SKILL / "scripts/validate_task_config.py"
)
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


class TaskConfigTests(unittest.TestCase):
    def setUp(self):
        self.template = validator.read_yaml(SKILL / "references/ml-task-template.yaml")
        self.config = copy.deepcopy(self.template)
        self.config["TaskName"] = "dzp_svocc_sem_test"
        self.config["Entrypoint"] = (
            "cd /vepfs-mlp2/c20250502/haoce/dzp/SV-Occ-sem\n"
            ". /root/miniconda3/bin/activate\n"
            "source haoce_activate.sh\n"
            "bash cloud_sync.sh dev_semantic\n"
            "PYTHONPATH=. MODE=cloud bash scripts/test.sh\n"
        )

    def check_config(self, allowed=(), *, worktree="sem", experiment=None,
                     work_dir="work_dirs/test"):
        return validator.validate(
            self.config, self.template, "svocc", work_dir, allowed,
            worktree=worktree, experiment=experiment,
        )[0]

    def test_default_passes(self):
        self.assertEqual(self.check_config(), [])

    def test_svocc_sync_script_must_be_at_project_root(self):
        self.config["Entrypoint"] = self.config["Entrypoint"].replace(
            "bash cloud_sync.sh", "bash scripts/cloud_sync.sh"
        )
        self.assertTrue(self.check_config())

    def test_other_project_uses_its_own_sync_script(self):
        self.config["TaskName"] = "dzp_other_sem_test"
        self.config["Entrypoint"] = self.config["Entrypoint"].replace(
            "bash cloud_sync.sh", "bash scripts/project_sync.sh"
        )
        errors, _ = validator.validate(
            self.config, self.template, "other", "work_dirs/test", worktree="sem"
        )
        self.assertEqual(errors, [])

    def test_template_matches_user_confirmed_defaults(self):
        expected = {
            "ResourceQueueName": "c20250502",
            "ResourceQueueID": "q-20251224110115-844wd",
            "Priority": 9,
            "Preemptible": True,
            "Description": "",
            "Tags": [],
            "Framework": "PyTorchDDP",
        }
        for field, value in expected.items():
            self.assertEqual(self.template[field], value)
        self.assertEqual(self.template["TaskRoleSpecs"], [{
            "RoleName": "worker", "RoleReplicas": 1, "Flavor": "ml.pni2.14xlarge"
        }])
        self.assertEqual(self.template["RetryOptions"], {
            "EnableRetry": True, "MaxRetryTimes": 10, "IntervalSeconds": 120,
            "PolicySets": ["InstanceReclaimed", "Failed", "MachineFailure"],
            "EnableReserveResourceOnRetry": False,
        })
        self.assertEqual([item["MountPath"] for item in self.template["Storages"]], [
            "/c20250502", "/vepfs-mlp2/c20250502/haoce", "/vepfs-mlp2/mlp-public/haoce"
        ])
        self.assertTrue(all(item["ReadOnly"] is False for item in self.template["Storages"]))

    def test_reject_protected_changes(self):
        edits = [
            ("Priority", 6), ("Preemptible", False),
            ("ResourceQueueName", "another-queue"),
            ("ResourceQueueID", "q-another"), ("ImageUrl", "another-image"),
            ("UserCodePath", "/project"), ("CacheType", "another-cache"),
        ]
        for field, value in edits:
            with self.subTest(field=field):
                self.config[field] = value
                self.assertTrue(self.check_config())
                self.config[field] = self.template[field]

    def test_reject_gpu_storage_and_retry_changes(self):
        cases = [
            ("TaskRoleSpecs", lambda value: value[0].update(Flavor="ml.pni2.3xlarge")),
            ("Storages", lambda value: value[0].update(ReadOnly=True)),
            ("RetryOptions", lambda value: value.update(MaxRetryTimes=5)),
            ("RetryOptions", lambda value: value.update(IntervalSeconds=60)),
        ]
        for field, edit in cases:
            with self.subTest(field=field):
                edit(self.config[field])
                self.assertTrue(self.check_config())
                self.config[field] = copy.deepcopy(self.template[field])

    def test_description_tags_cannot_be_exempted(self):
        for field, value in [("Description", "commit abc"), ("Tags", ["abc"])]:
            with self.subTest(field=field):
                self.config[field] = value
                self.assertTrue(self.check_config([field]))
                self.config[field] = copy.deepcopy(self.template[field])

    def test_exact_authorized_difference(self):
        self.config["TaskRoleSpecs"][0]["Flavor"] = "ml.pni2.3xlarge"
        self.assertEqual(self.check_config(["TaskRoleSpecs[0].Flavor"]), [])
        self.assertTrue(self.check_config(["TaskRoleSpecs"]))

    def test_unknown_field_and_type_changes(self):
        self.config["ImageCredential"] = {}
        self.assertTrue(self.check_config())
        self.config.pop("ImageCredential")
        self.config["Priority"] = "9"
        self.assertTrue(self.check_config())

    def test_name_and_entrypoint_validation(self):
        self.config["TaskName"] = "dzp_svocc_wrong"
        self.assertTrue(self.check_config())
        self.config["TaskName"] = "dzp_svocc_sem_test"
        self.config["Entrypoint"] = "cd /project\nbash scripts/test.sh"
        self.assertTrue(self.check_config())

    def test_entrypoint_uses_plain_newlines_not_chaining(self):
        entry = self.config["Entrypoint"]
        self.assertEqual(self.check_config(), [])
        for index in range(4):
            with self.subTest(line=index + 1):
                lines = entry.splitlines()
                lines[index] += " &&"
                self.config["Entrypoint"] = "\n".join(lines) + "\n"
                self.assertTrue(self.check_config())

    def test_duplicate_yaml_keys_rejected(self):
        with self.assertRaises(ValueError):
            yaml.load("Priority: 9\nPriority: 6\n", Loader=validator.UniqueKeyLoader)

    def test_name_length_boundary(self):
        experiment = "gauss_suppress_v1"
        self.config["TaskName"] = f"dzp_svocc_sem_{experiment}"
        self.assertEqual(len(self.config["TaskName"]), 31)
        self.assertEqual(self.check_config(experiment=experiment), [])
        self.config["TaskName"] += "x"
        self.assertTrue(self.check_config(experiment=experiment + "x"))

    def test_forbidden_word_is_case_insensitive(self):
        for experiment in ("smoke", "SMOKE", "env_SmOkE"):
            with self.subTest(experiment=experiment):
                self.config["TaskName"] = f"dzp_svocc_sem_{experiment}"
                self.assertTrue(self.check_config(experiment=experiment))

    def test_date_suffixes_rejected(self):
        for suffix in ("20261009", "261009", "2026_10_09", "2026-10-09", "261009_153513"):
            with self.subTest(suffix=suffix):
                experiment = f"test_{suffix}"
                self.config["TaskName"] = f"dzp_svocc_sem_{experiment}"
                self.assertTrue(self.check_config(experiment=experiment))

    def test_existing_names_and_versions_pass(self):
        for experiment in ("env_check", "carve_v2_fast", "iter13_audit", "B"):
            with self.subTest(experiment=experiment):
                self.config["TaskName"] = f"dzp_svocc_sem_{experiment}"
                self.assertEqual(self.check_config(experiment=experiment), [])

    def test_worktree_required_and_branch_abbreviated(self):
        self.config["TaskName"] = "dzp_svocc_test"
        self.assertTrue(self.check_config())
        for worktree in ("", "dev_semantic", "semantic", "asy"):
            with self.subTest(worktree=worktree):
                self.config["TaskName"] = f"dzp_svocc_{worktree}_test"
                self.assertTrue(self.check_config(worktree=worktree))
        self.config["Entrypoint"] = self.config["Entrypoint"].replace("dev_semantic", "dev_asy")
        self.config["TaskName"] = "dzp_svocc_asy_test"
        self.assertEqual(self.check_config(worktree="asy"), [])

    def test_directory_prefix_is_not_duplicated(self):
        self.assertEqual(self.check_config(work_dir="work_dirs/sem_test"), [])

    def test_explicit_alias_preserves_real_output_directory(self):
        work_dir = "work_dirs/semantic_carve_v2_fast_20261009"
        self.config["TaskName"] = "dzp_svocc_sem_carve_v2_fast"
        self.assertEqual(self.check_config(experiment="carve_v2_fast", work_dir=work_dir), [])
        self.assertTrue(self.check_config(work_dir=work_dir))

    def test_invalid_name_parts_and_empty_experiment_rejected(self):
        for experiment in ("", "test__v1", "test/check", "测试"):
            with self.subTest(experiment=experiment):
                self.config["TaskName"] = f"dzp_svocc_sem_{experiment}"
                self.assertTrue(self.check_config(experiment=experiment))
        self.config["TaskName"] = None
        self.assertTrue(self.check_config())


if __name__ == "__main__":
    unittest.main()
